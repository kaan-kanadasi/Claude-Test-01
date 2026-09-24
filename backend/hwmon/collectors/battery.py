"""Battery charge, power flow and capacity.

psutil gives charge, AC state and time left. On Windows the WMI ``root\\wmi`` battery
classes add charge/discharge power, capacity, voltage and cycle count (read-only
SELECT queries; no admin rights needed).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import psutil

from .base import CollectorUnavailable

log = logging.getLogger(__name__)

WmiQuery = Callable[[str, list[str]], list[dict[str, Any]]]

_MAX_PLAUSIBLE_MW = 500_000  # drivers report e.g. 0x80000000 for "unknown"


def _wmi_query(cls: str, fields: list[str]) -> list[dict[str, Any]]:
    """Run one SELECT against root\\wmi on the calling thread.

    Connects per call (~15 ms) so no COM object outlives its thread; a cached
    connection would be released from the wrong thread at shutdown.
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    svc = win32com.client.GetObject(r"winmgmts:root\wmi")
    rows = svc.ExecQuery(f"SELECT {', '.join(fields)} FROM {cls}")
    return [{f: getattr(r, f) for f in fields} for r in rows]


def _plausible_mw(v: Any) -> float | None:
    if v is None or not 0 <= v < _MAX_PLAUSIBLE_MW:
        return None
    return float(v)


class BatteryCollector:
    name = "battery"

    def __init__(self, ps=psutil, wmi_query: WmiQuery | None = None, interval: float | None = 5.0):
        self.interval = interval
        self._ps = ps
        if ps.sensors_battery() is None:
            raise CollectorUnavailable("No battery found")
        self._wmi = wmi_query if wmi_query is not None else _wmi_query

    def static_info(self) -> dict:
        return {"battery": {"present": True}}

    def _query(self, cls: str, fields: list[str]) -> dict[str, Any] | None:
        try:
            rows = self._wmi(cls, fields)
        except Exception as e:
            log.debug("WMI %s query failed: %s", cls, e)
            return None
        return rows[0] if rows else None

    def sample(self) -> dict[str, float]:
        b = self._ps.sensors_battery()
        if b is None:
            raise RuntimeError("battery no longer reported")
        m: dict[str, float] = {
            "battery.percent": float(b.percent),
            "battery.plugged": 1.0 if b.power_plugged else 0.0,
        }
        if b.secsleft is not None and b.secsleft >= 0:  # negative = unlimited / unknown
            m["battery.secs_left"] = float(b.secsleft)

        status = self._query("BatteryStatus",
                             ["ChargeRate", "DischargeRate", "RemainingCapacity", "Voltage", "Charging"])
        if status:
            m["battery.charging"] = 1.0 if status["Charging"] else 0.0
            for field, key in (("ChargeRate", "battery.charge_w"), ("DischargeRate", "battery.discharge_w")):
                mw = _plausible_mw(status[field])
                if mw is not None:
                    m[key] = mw / 1000.0
            if status["RemainingCapacity"]:
                m["battery.remaining_wh"] = status["RemainingCapacity"] / 1000.0
            if status["Voltage"]:
                m["battery.voltage_v"] = status["Voltage"] / 1000.0

        full = self._query("BatteryFullChargedCapacity", ["FullChargedCapacity"])
        if full and full["FullChargedCapacity"]:
            m["battery.full_wh"] = full["FullChargedCapacity"] / 1000.0
        cycles = self._query("BatteryCycleCount", ["CycleCount"])
        if cycles and cycles["CycleCount"]:
            m["battery.cycles"] = float(cycles["CycleCount"])
        return m
