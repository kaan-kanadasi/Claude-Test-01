"""Minimal read-only wrapper over Windows Performance Data Helper (PDH) counters."""

from __future__ import annotations

import win32pdh


class PdhQuery:
    def __init__(self):
        self._q = win32pdh.OpenQuery()

    def add(self, path: str):
        """Add a counter by its English path; wildcards like ``(*)`` are allowed."""
        return win32pdh.AddEnglishCounter(self._q, path)

    def collect(self) -> None:
        win32pdh.CollectQueryData(self._q)

    def value(self, counter) -> float | None:
        try:
            _, v = win32pdh.GetFormattedCounterValue(counter, win32pdh.PDH_FMT_DOUBLE)
            return float(v)
        except win32pdh.error:
            return None

    def array(self, counter) -> dict[str, float]:
        """Per-instance values of a wildcard counter; empty if no data yet."""
        try:
            return win32pdh.GetFormattedCounterArray(counter, win32pdh.PDH_FMT_DOUBLE)
        except win32pdh.error:
            return {}

    def close(self) -> None:
        win32pdh.CloseQuery(self._q)
