from __future__ import annotations

import socket
import time
from typing import Callable

import psutil

from .base import RateTracker, metric_key


def _is_loopback(name: str) -> bool:
    n = name.lower()
    return n == "lo" or n.startswith("loopback")


class NetworkCollector:
    name = "network"
    interval = None

    def __init__(self, ps=psutil, clock: Callable[[], float] = time.monotonic):
        self._ps = ps
        self._rates = RateTracker(clock)

    def static_info(self) -> dict:
        addrs = self._ps.net_if_addrs()
        nics = []
        for name, st in self._ps.net_if_stats().items():
            if _is_loopback(name):
                continue
            ips = [a.address for a in addrs.get(name, [])
                   if a.family in (socket.AF_INET, socket.AF_INET6)]
            nics.append({"name": name, "speed_mbps": st.speed, "addresses": ips})
        return {"network": nics}

    def sample(self) -> dict[str, float]:
        m: dict[str, float] = {}
        stats = self._ps.net_if_stats()
        io = self._ps.net_io_counters(pernic=True)
        for name, st in stats.items():
            if _is_loopback(name):
                continue
            m[metric_key("net", name, "up")] = 1.0 if st.isup else 0.0
            counters = io.get(name)
            if counters is None:
                continue
            for field, suffix in (("bytes_recv", "rx_bps"), ("bytes_sent", "tx_bps")):
                key = metric_key("net", name, suffix)
                r = self._rates.rate(key, getattr(counters, field))
                if r is not None:
                    m[key] = r
        return m
