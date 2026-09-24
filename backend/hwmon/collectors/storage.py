from __future__ import annotations

import time
from typing import Callable

import psutil

from .base import RateTracker, metric_key


class StorageCollector:
    name = "storage"
    interval = None

    def __init__(self, ps=psutil, clock: Callable[[], float] = time.monotonic):
        self._ps = ps
        self._rates = RateTracker(clock)

    def _volumes(self):
        """Yield (id, partition, usage) for fixed, ready volumes."""
        for p in self._ps.disk_partitions(all=False):
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                usage = self._ps.disk_usage(p.mountpoint)
            except OSError:
                continue
            yield metric_key(p.mountpoint) or p.mountpoint, p, usage

    def static_info(self) -> dict:
        return {
            "disks": [
                {"id": vid, "mountpoint": p.mountpoint, "fstype": p.fstype, "total": u.total}
                for vid, p, u in self._volumes()
            ]
        }

    def sample(self) -> dict[str, float]:
        m: dict[str, float] = {}
        for vid, _, u in self._volumes():
            m[f"disk.{vid}.used"] = float(u.used)
            m[f"disk.{vid}.total"] = float(u.total)
            m[f"disk.{vid}.percent"] = float(u.percent)
        io = self._ps.disk_io_counters()
        if io is not None:
            for field, key in (("read_bytes", "disk.io.read_bps"), ("write_bytes", "disk.io.write_bps")):
                r = self._rates.rate(key, getattr(io, field))
                if r is not None:
                    m[key] = r
        return m
