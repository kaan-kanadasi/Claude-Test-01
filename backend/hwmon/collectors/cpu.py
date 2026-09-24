from __future__ import annotations

import platform
import sys
from typing import Callable

import psutil

from .base import metric_key


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "Unknown CPU"


class _WindowsCpuFreq:
    """Current clock = base clock x '% Processor Performance' (what Task Manager shows).

    psutil on Windows only reports the fixed base clock.
    """

    def __init__(self, base_mhz: float):
        from ._pdh import PdhQuery

        self._base = base_mhz
        self._q = PdhQuery()
        self._c = self._q.add(r"\Processor Information(_Total)\% Processor Performance")
        self._q.collect()

    def __call__(self) -> float | None:
        self._q.collect()
        perf = self._q.value(self._c)
        return None if perf is None else self._base * perf / 100.0


def _default_freq_fn(ps) -> Callable[[], float | None]:
    freq = ps.cpu_freq()
    base = (freq.max or freq.current) if freq else 0.0
    if sys.platform == "win32" and base:
        try:
            return _WindowsCpuFreq(base)
        except Exception:
            pass
    return lambda: (ps.cpu_freq().current or None) if ps.cpu_freq() else None


class CpuCollector:
    name = "cpu"
    interval = None

    def __init__(self, ps=psutil, freq_fn: Callable[[], float | None] | None = None,
                 name_fn: Callable[[], str] = _cpu_name):
        self._ps = ps
        self._freq_fn = freq_fn if freq_fn is not None else _default_freq_fn(ps)
        self._name = name_fn()
        # Prime psutil's internal counters so the first real sample is meaningful.
        ps.cpu_percent(percpu=True)
        ps.cpu_percent()

    def static_info(self) -> dict:
        f = self._ps.cpu_freq()
        return {
            "cpu": {
                "name": self._name,
                "cores": self._ps.cpu_count(logical=False),
                "threads": self._ps.cpu_count(logical=True),
                "base_mhz": (f.max or f.current) if f else None,
            }
        }

    def sample(self) -> dict[str, float]:
        m: dict[str, float] = {"cpu.total": float(self._ps.cpu_percent())}
        for i, pct in enumerate(self._ps.cpu_percent(percpu=True)):
            m[metric_key("cpu", "core", i)] = float(pct)
        freq = self._freq_fn()
        if freq:
            m["cpu.freq_mhz"] = float(freq)
        return m
