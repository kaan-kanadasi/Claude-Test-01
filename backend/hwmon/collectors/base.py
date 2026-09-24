"""Collector protocol and shared helpers.

A collector reads one hardware area and returns a flat ``{metric_key: float}``
dict from ``sample()``. Collectors are strictly read-only: they only query.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Protocol


class CollectorUnavailable(Exception):
    """Raised (usually from __init__) when a collector cannot run on this machine."""


class Collector(Protocol):
    name: str
    # Minimum seconds between samples; None means every sampler tick.
    interval: float | None

    def static_info(self) -> dict[str, Any]: ...

    def sample(self) -> dict[str, float]: ...


_UNSAFE = re.compile(r"[.:\\/]+")


def metric_key(*parts: object) -> str:
    """Join parts with dots, replacing characters that would break the dotted namespace."""
    cleaned = []
    for p in parts:
        s = _UNSAFE.sub("_", str(p)).strip("_")
        cleaned.append(s)
    return ".".join(cleaned)


class RateTracker:
    """Turns monotonically increasing byte counters into per-second rates.

    Returns None for the first observation of a key and after a counter reset.
    """

    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._last: dict[str, tuple[float, float]] = {}

    def rate(self, key: str, value: float) -> float | None:
        now = self._clock()
        prev = self._last.get(key)
        self._last[key] = (now, value)
        if prev is None:
            return None
        t0, v0 = prev
        dt = now - t0
        if dt <= 0 or value < v0:
            return None
        return (value - v0) / dt
