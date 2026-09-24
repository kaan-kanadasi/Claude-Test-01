"""Top processes by CPU, memory and GPU, grouped by executable name.

Uses the Windows "Process V2" performance counters (all processes in one query,
~20 ms) rather than psutil, whose per-process reads take seconds on Windows because
protected processes force a full system rescan each.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Callable

from .base import CollectorUnavailable
from .gpu_windows import Adapter, enumerate_dxgi_adapters, parse_engine_instance

CPU_PATH = r"\Process V2(*)\% Processor Time"
MEM_PATH = r"\Process V2(*)\Working Set - Private"
GPU_PATH = r"\GPU Engine(*)\Utilization Percentage"

_SKIP = {"Idle", "_Total"}


def _split(instance: str) -> tuple[str, int] | None:
    """'chrome:1234' -> ('chrome', 1234); None for aggregate or unparseable instances."""
    name, sep, pid = instance.rpartition(":")
    if not sep or not pid.isdigit() or name in _SKIP:
        return None
    return name, int(pid)


def _default_pdh():
    from ._pdh import PdhQuery

    return PdhQuery()


class ProcessCollector:
    name = "processes"

    def __init__(self, pdh: Any = None, adapters_fn: Callable[[], list[Adapter]] = enumerate_dxgi_adapters,
                 cpu_count: int | None = None, interval: float | None = 2.0, top_n: int = 30):
        self.interval = interval
        self._top_n = top_n
        self._cpus = cpu_count or os.cpu_count() or 1
        try:
            self._adapter_names = {a.luid.upper(): a.name for a in adapters_fn() if not a.software}
        except Exception:
            self._adapter_names = {}  # per-process GPU then just lacks adapter names
        try:
            self._pdh = pdh if pdh is not None else _default_pdh()
            self._cpu = self._pdh.add(CPU_PATH)
            self._mem = self._pdh.add(MEM_PATH)
            self._gpu = self._pdh.add(GPU_PATH)
            self._pdh.collect()  # CPU time is a rate counter: needs a baseline
        except Exception as e:
            raise CollectorUnavailable(f"Process performance counters unavailable: {e}") from e
        self.details: list[dict[str, Any]] = []

    def static_info(self) -> dict:
        return {}

    def sample(self) -> dict[str, float]:
        self._pdh.collect()
        cpu = self._pdh.array(self._cpu, nocap=True)
        mem = self._pdh.array(self._mem)

        groups: dict[str, dict[str, Any]] = {}
        group_of_pid: dict[int, str] = {}
        for inst, raw_cpu in cpu.items():
            parsed = _split(inst)
            if parsed is None:
                continue
            name, pid = parsed
            g = groups.setdefault(name, {"name": name, "count": 0, "cpu": 0.0, "memory": 0,
                                         "gpu": 0.0, "gpu_adapter": None})
            g["count"] += 1
            g["cpu"] += raw_cpu / self._cpus
            g["memory"] += int(mem.get(inst, 0))
            group_of_pid[pid] = name

        # Per engine, sum the group's processes; the group's GPU load is its busiest engine.
        engines: dict[tuple[str, str, str, str], float] = defaultdict(float)
        for inst, value in self._pdh.array(self._gpu).items():
            parsed = parse_engine_instance(inst)
            if parsed is None:
                continue
            luid, phys, eng, _etype, pid = parsed
            name = group_of_pid.get(pid)
            if name is not None:
                engines[(name, luid, phys, eng)] += value
        for (name, luid, _, _), load in engines.items():
            g = groups[name]
            load = min(load, 100.0)
            if load > g["gpu"]:
                g["gpu"] = load
                g["gpu_adapter"] = self._adapter_names.get(luid)

        rows = list(groups.values())
        for r in rows:
            r["cpu"] = round(r["cpu"], 2)
            r["gpu"] = round(r["gpu"], 2)
        keep: dict[str, dict[str, Any]] = {}
        for key in ("cpu", "memory", "gpu"):
            for r in sorted(rows, key=lambda r: r[key], reverse=True)[: self._top_n]:
                keep[r["name"]] = r
        self.details = sorted(keep.values(), key=lambda r: r["cpu"], reverse=True)
        return {"proc.count": float(len(group_of_pid))}
