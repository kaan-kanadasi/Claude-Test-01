"""The sampling loop: polls collectors, isolates failures, fans snapshots out."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .collectors.base import Collector

log = logging.getLogger(__name__)

# {"ts": float, "metrics": {key: float}, "status": {collector: str}, "details": {collector: Any}}
# "details" holds live-only structured data (e.g. process lists); it is never persisted.
Snapshot = dict[str, Any]


class Hub:
    """Broadcasts snapshots to subscribers; slow subscribers only ever get the latest one.

    Must be used from the event loop thread.
    """

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, snapshot: Snapshot) -> None:
        for q in self._queues:
            if q.full():
                q.get_nowait()
            q.put_nowait(snapshot)


class _State:
    def __init__(self):
        self.metrics: dict[str, float] = {}
        self.details: Any = None
        self.status = "ok"
        self.next_at = 0.0
        self.backoff = 0.0


class Sampler:
    MIN_BACKOFF_S = 1.0
    MAX_BACKOFF_S = 30.0

    def __init__(self, collectors: list[Collector], unavailable: dict[str, str] | None = None,
                 store: Any = None, hub: Hub | None = None, interval: float = 1.0,
                 persist_interval: float = 5.0, clock: Callable[[], float] = time.time):
        self.collectors = collectors
        self.unavailable = dict(unavailable or {})
        self.store = store
        self.hub = hub
        self.interval = interval
        self.persist_interval = persist_interval
        self._clock = clock
        self._state = {c.name: _State() for c in collectors}
        self._last_persist: float | None = None
        self.latest: Snapshot | None = None

    def tick(self) -> Snapshot:
        now = self._clock()
        metrics: dict[str, float] = {}
        status: dict[str, str] = {}
        details: dict[str, Any] = {}
        for c in self.collectors:
            st = self._state[c.name]
            if now >= st.next_at:
                try:
                    st.metrics = c.sample()
                    st.details = getattr(c, "details", None)
                    st.status = "ok"
                    st.backoff = 0.0
                    st.next_at = now + (c.interval or 0.0)
                except Exception as e:
                    if st.status == "ok":
                        log.warning("collector %s failed: %s", c.name, e)
                    st.metrics = {}
                    st.details = None
                    st.status = f"error: {e}"
                    st.backoff = min(max(st.backoff * 2, self.MIN_BACKOFF_S), self.MAX_BACKOFF_S)
                    st.next_at = now + st.backoff
            metrics.update(st.metrics)
            status[c.name] = st.status
            if st.details is not None:
                details[c.name] = st.details
        for name, reason in self.unavailable.items():
            status[name] = f"unavailable: {reason}"

        snapshot = {"ts": now, "metrics": metrics, "status": status, "details": details}
        self.latest = snapshot

        if self.store is not None and (
            self._last_persist is None or now - self._last_persist >= self.persist_interval
        ):
            try:
                self.store.write(now, metrics)
                self._last_persist = now
            except Exception:
                log.exception("failed to persist sample")
        return snapshot

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        # Always sample on the same thread: psutil.cpu_percent() keeps its baseline per
        # thread, so hopping between pool threads yields 0% or wrong-interval readings.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hwmon-sampler")
        next_tick = loop.time()
        try:
            while True:
                snapshot = await loop.run_in_executor(executor, self.tick)
                if self.hub is not None:
                    self.hub.publish(snapshot)
                next_tick += self.interval
                delay = next_tick - loop.time()
                if delay < 0:  # fell behind (e.g. system sleep): resync instead of bursting
                    next_tick = loop.time()
                    delay = 0
                await asyncio.sleep(delay)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
