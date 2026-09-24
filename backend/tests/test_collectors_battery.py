from types import SimpleNamespace as NS

import pytest

from hwmon.collectors.base import CollectorUnavailable
from hwmon.collectors.battery import BatteryCollector

POWER_TIME_UNLIMITED, POWER_TIME_UNKNOWN = -2, -1


class FakePs:
    def __init__(self, battery):
        self.battery = battery

    def sensors_battery(self):
        return self.battery


def battery(percent=80.0, secsleft=POWER_TIME_UNLIMITED, plugged=True):
    return NS(percent=percent, secsleft=secsleft, power_plugged=plugged)


class FakeWmi:
    def __init__(self):
        self.fail = set()
        self.tables = {
            "BatteryStatus": [{"ChargeRate": 25_000, "DischargeRate": 0, "RemainingCapacity": 63_504,
                               "Voltage": 17_662, "Charging": True}],
            "BatteryFullChargedCapacity": [{"FullChargedCapacity": 79_380}],
            "BatteryCycleCount": [{"CycleCount": 468}],
        }

    def __call__(self, cls, fields):
        if cls in self.fail:
            raise OSError("WMI error")
        return [{f: row[f] for f in fields} for row in self.tables[cls]]


def test_unavailable_without_battery():
    with pytest.raises(CollectorUnavailable):
        BatteryCollector(ps=FakePs(None), wmi_query=FakeWmi())


def test_psutil_fields_and_unlimited_time_omitted():
    m = BatteryCollector(ps=FakePs(battery()), wmi_query=FakeWmi()).sample()
    assert m["battery.percent"] == 80.0
    assert m["battery.plugged"] == 1.0
    assert "battery.secs_left" not in m


def test_time_left_on_battery():
    m = BatteryCollector(ps=FakePs(battery(secsleft=12_000, plugged=False)), wmi_query=FakeWmi()).sample()
    assert m["battery.secs_left"] == 12_000.0
    assert m["battery.plugged"] == 0.0


def test_unknown_time_omitted():
    m = BatteryCollector(ps=FakePs(battery(secsleft=POWER_TIME_UNKNOWN, plugged=False)),
                         wmi_query=FakeWmi()).sample()
    assert "battery.secs_left" not in m


def test_wmi_power_and_capacity_in_watts_and_watt_hours():
    m = BatteryCollector(ps=FakePs(battery()), wmi_query=FakeWmi()).sample()
    assert m["battery.charging"] == 1.0
    assert m["battery.charge_w"] == 25.0
    assert m["battery.discharge_w"] == 0.0
    assert m["battery.remaining_wh"] == pytest.approx(63.504)
    assert m["battery.voltage_v"] == pytest.approx(17.662)
    assert m["battery.full_wh"] == pytest.approx(79.38)
    assert m["battery.cycles"] == 468.0


def test_implausible_rates_are_dropped():
    wmi = FakeWmi()
    wmi.tables["BatteryStatus"][0]["DischargeRate"] = -2147483648  # driver's "unknown"
    m = BatteryCollector(ps=FakePs(battery()), wmi_query=wmi).sample()
    assert "battery.discharge_w" not in m
    assert m["battery.charge_w"] == 25.0


def test_wmi_failure_keeps_psutil_fields_and_other_tables():
    wmi = FakeWmi()
    wmi.fail = {"BatteryStatus"}
    c = BatteryCollector(ps=FakePs(battery()), wmi_query=wmi)
    m = c.sample()
    assert m["battery.percent"] == 80.0
    assert "battery.charge_w" not in m
    assert m["battery.cycles"] == 468.0
    wmi.fail = set()
    assert c.sample()["battery.charge_w"] == 25.0  # recovers on the next sample


def test_static_info_marks_battery_present():
    assert BatteryCollector(ps=FakePs(battery()), wmi_query=FakeWmi()).static_info() == {"battery": {"present": True}}


def test_on_battery_helper():
    from hwmon.collectors.battery import on_battery

    assert on_battery(FakePs(battery(plugged=False))) is True
    assert on_battery(FakePs(battery(plugged=True))) is False
    assert on_battery(FakePs(None)) is False  # desktops never count as on battery
