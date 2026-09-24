from types import SimpleNamespace as NS

import pytest

from hwmon.collectors.cpu import CpuCollector
from hwmon.collectors.memory import MemoryCollector
from hwmon.collectors.network import NetworkCollector
from hwmon.collectors.sensors import NullSensors
from hwmon.collectors.base import CollectorUnavailable, metric_key
from hwmon.collectors.storage import StorageCollector
from tests.fakes import FakeClock, FakePsutil


def test_metric_key_sanitizes_parts():
    assert metric_key("net", "vEthernet (WSL.1)", "rx_bps") == "net.vEthernet (WSL_1).rx_bps"
    assert metric_key("disk", "C:\\", "used") == "disk.C.used"


class TestCpu:
    def test_sample_reports_total_per_core_and_frequency(self):
        ps = FakePsutil()
        c = CpuCollector(ps=ps, freq_fn=lambda: 3100.0, name_fn=lambda: "Test CPU")
        m = c.sample()
        assert m["cpu.total"] == 40.0
        assert [m[f"cpu.core.{i}"] for i in range(4)] == [10.0, 30.0, 50.0, 70.0]
        assert m["cpu.freq_mhz"] == 3100.0

    def test_frequency_omitted_when_unknown(self):
        c = CpuCollector(ps=FakePsutil(), freq_fn=lambda: None, name_fn=lambda: "x")
        assert "cpu.freq_mhz" not in c.sample()

    def test_static_info(self):
        c = CpuCollector(ps=FakePsutil(), freq_fn=lambda: None, name_fn=lambda: "Test CPU")
        assert c.static_info() == {
            "cpu": {"name": "Test CPU", "cores": 2, "threads": 4, "base_mhz": 2300.0}
        }


def test_memory_sample():
    m = MemoryCollector(ps=FakePsutil()).sample()
    assert m["mem.used"] == 10 * 2**30
    assert m["mem.available"] == 6 * 2**30
    assert m["mem.percent"] == 62.5
    assert m["swap.used"] == 2**30
    assert m["swap.percent"] == 25.0


def test_memory_static_info():
    assert MemoryCollector(ps=FakePsutil()).static_info() == {
        "memory": {"total": 16 * 2**30, "swap_total": 4 * 2**30}
    }


class TestStorage:
    def test_volume_usage_skips_unready_and_non_fixed_drives(self):
        m = StorageCollector(ps=FakePsutil(), clock=FakeClock()).sample()
        assert m["disk.C.used"] == 400
        assert m["disk.C.total"] == 1000
        assert m["disk.C.percent"] == 40.0
        assert not any(k.startswith("disk.E.") for k in m)

    def test_io_rates_need_two_samples(self):
        ps, clock = FakePsutil(), FakeClock()
        c = StorageCollector(ps=ps, clock=clock)
        assert "disk.io.read_bps" not in c.sample()
        ps.io = NS(read_bytes=2000, write_bytes=500)
        clock.advance(2.0)
        m = c.sample()
        assert m["disk.io.read_bps"] == 1000.0
        assert m["disk.io.write_bps"] == 250.0

    def test_counter_reset_is_skipped(self):
        ps, clock = FakePsutil(), FakeClock()
        ps.io = NS(read_bytes=5000, write_bytes=5000)
        c = StorageCollector(ps=ps, clock=clock)
        c.sample()
        ps.io = NS(read_bytes=10, write_bytes=10)
        clock.advance(1.0)
        assert "disk.io.read_bps" not in c.sample()

    def test_static_info_lists_volumes(self):
        info = StorageCollector(ps=FakePsutil(), clock=FakeClock()).static_info()
        assert info == {"disks": [{"id": "C", "mountpoint": "C:\\", "fstype": "NTFS", "total": 1000}]}


class TestNetwork:
    def test_rates_per_interface_excluding_loopback(self):
        ps, clock = FakePsutil(), FakeClock()
        c = NetworkCollector(ps=ps, clock=clock)
        first = c.sample()
        assert first["net.Wi-Fi.up"] == 1.0
        assert first["net.Bluetooth.up"] == 0.0
        assert "net.Wi-Fi.rx_bps" not in first
        assert not any("Loopback" in k for k in first)

        ps.nic_io["Wi-Fi"] = NS(bytes_recv=4000, bytes_sent=1000)
        clock.advance(4.0)
        m = c.sample()
        assert m["net.Wi-Fi.rx_bps"] == 1000.0
        assert m["net.Wi-Fi.tx_bps"] == 250.0

    def test_static_info(self):
        info = NetworkCollector(ps=FakePsutil(), clock=FakeClock()).static_info()
        wifi = next(n for n in info["network"] if n["name"] == "Wi-Fi")
        assert wifi == {"name": "Wi-Fi", "speed_mbps": 866, "addresses": ["192.168.1.20"]}
        assert not any("Loopback" in n["name"] for n in info["network"])


def test_null_sensors_is_unavailable():
    with pytest.raises(CollectorUnavailable):
        NullSensors()
