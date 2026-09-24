"""Runtime settings. Every field can be overridden with an HWMON_<FIELD> environment variable."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = field(default_factory=lambda: BACKEND_DIR / "data" / "metrics.db")
    frontend_dist: Path = field(default_factory=lambda: BACKEND_DIR.parent / "frontend" / "dist")
    sample_interval: float = 1.0  # seconds between live snapshots
    persist_interval: float = 5.0  # seconds between samples written to SQLite
    nvidia_interval: float = 2.0  # seconds between NVML polls; 0 disables NVML
    raw_retention_s: int = 24 * 3600
    rollup_retention_s: int = 30 * 24 * 3600
    maintenance_interval: float = 60.0  # rollup + retention job

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls()
        for f in fields(cls):
            raw = os.environ.get(f"HWMON_{f.name.upper()}")
            if raw is None:
                continue
            current = getattr(cfg, f.name)
            setattr(cfg, f.name, type(current)(raw))
        return cfg

    def public(self) -> dict:
        """Settings safe to show in the UI."""
        d = asdict(self)
        return {k: v for k, v in d.items() if not isinstance(v, Path)}
