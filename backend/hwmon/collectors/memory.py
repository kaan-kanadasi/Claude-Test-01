from __future__ import annotations

import psutil


class MemoryCollector:
    name = "memory"
    interval = None

    def __init__(self, ps=psutil):
        self._ps = ps

    def static_info(self) -> dict:
        return {
            "memory": {
                "total": self._ps.virtual_memory().total,
                "swap_total": self._ps.swap_memory().total,
            }
        }

    def sample(self) -> dict[str, float]:
        vm = self._ps.virtual_memory()
        sw = self._ps.swap_memory()
        return {
            "mem.used": float(vm.used),
            "mem.available": float(vm.available),
            "mem.total": float(vm.total),
            "mem.percent": float(vm.percent),
            "swap.used": float(sw.used),
            "swap.total": float(sw.total),
            "swap.percent": float(sw.percent),
        }
