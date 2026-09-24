"""SQLite persistence for metric history.

Raw samples (every few seconds) are kept for a short window; complete minutes are
rolled up into avg/min/max rows that are kept much longer. Queries downsample to a
bounded number of points so charts stay fast for any range.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from pathlib import Path

RAW_MAX_RANGE_S = 3600  # ranges up to this use raw samples; longer ones use rollups

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_keys (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS samples (
    key_id INTEGER NOT NULL, ts INTEGER NOT NULL, value REAL NOT NULL,
    PRIMARY KEY (key_id, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS samples_1m (
    key_id INTEGER NOT NULL, ts INTEGER NOT NULL, avg REAL NOT NULL, min REAL NOT NULL, max REAL NOT NULL,
    PRIMARY KEY (key_id, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


class MetricStore:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self._key_ids: dict[str, int] = dict(
            (k, i) for i, k in self._db.execute("SELECT id, key FROM metric_keys")
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _key_id(self, key: str) -> int:
        kid = self._key_ids.get(key)
        if kid is None:
            self._db.execute("INSERT OR IGNORE INTO metric_keys (key) VALUES (?)", (key,))
            kid = self._db.execute("SELECT id FROM metric_keys WHERE key = ?", (key,)).fetchone()[0]
            self._key_ids[key] = kid
        return kid

    def write(self, ts: float, metrics: dict[str, float]) -> None:
        t = int(round(ts))
        with self._lock, self._db:
            rows = [(self._key_id(k), t, v) for k, v in metrics.items()]
            self._db.executemany(
                "INSERT OR REPLACE INTO samples (key_id, ts, value) VALUES (?, ?, ?)", rows)

    def rollup(self, now: float) -> None:
        """Aggregate every complete minute not yet rolled up."""
        until = int(now) // 60 * 60
        with self._lock, self._db:
            row = self._db.execute("SELECT value FROM meta WHERE name = 'rollup_until'").fetchone()
            if row is not None:
                since = row[0]
            else:
                first = self._db.execute("SELECT MIN(ts) FROM samples").fetchone()[0]
                if first is None:
                    return
                since = first // 60 * 60
            if since >= until:
                return
            self._db.execute(
                """INSERT OR REPLACE INTO samples_1m (key_id, ts, avg, min, max)
                   SELECT key_id, ts / 60 * 60, AVG(value), MIN(value), MAX(value)
                   FROM samples WHERE ts >= ? AND ts < ? GROUP BY key_id, ts / 60""",
                (since, until))
            self._db.execute(
                "INSERT OR REPLACE INTO meta (name, value) VALUES ('rollup_until', ?)", (until,))

    def prune(self, now: float, raw_retention_s: int, rollup_retention_s: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM samples WHERE ts < ?", (int(now) - raw_retention_s,))
            self._db.execute("DELETE FROM samples_1m WHERE ts < ?", (int(now) - rollup_retention_s,))

    def history(self, keys: list[str], start: float, end: float, max_points: int = 1000) -> dict:
        start_i, end_i = int(start), int(end)
        span = max(end_i - start_i, 1)
        if span <= RAW_MAX_RANGE_S:
            source, table, col, base = "raw", "samples", "value", 1
        else:
            source, table, col, base = "1m", "samples_1m", "avg", 60
        step = max(base, math.ceil(span / max_points / base) * base)

        series: dict[str, list[list[float]]] = {}
        with self._lock:
            for key in keys:
                kid = self._key_ids.get(key)
                if kid is None:
                    series[key] = []
                    continue
                rows = self._db.execute(
                    f"""SELECT ts / ? * ? AS bucket, AVG({col}) FROM {table}
                        WHERE key_id = ? AND ts >= ? AND ts <= ?
                        GROUP BY bucket ORDER BY bucket""",
                    (step, step, kid, start_i, end_i)).fetchall()
                series[key] = [[b, v] for b, v in rows]
        return {"source": source, "step": step, "series": series}

    def _rollup_rows(self, key: str) -> list[tuple]:
        """Test helper: raw rollup rows for one key."""
        kid = self._key_ids.get(key)
        with self._lock:
            return self._db.execute(
                "SELECT ts, avg, min, max FROM samples_1m WHERE key_id = ? ORDER BY ts", (kid,)
            ).fetchall()
