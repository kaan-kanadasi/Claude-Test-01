from types import SimpleNamespace as NS

import pytest

from hwmon.collectors.base import CollectorUnavailable
from hwmon.collectors.gpu_nvidia import NvidiaGpuCollector
from hwmon.collectors.gpu_windows import Adapter, WindowsGpuCollector


# ---------------------------------------------------------------- NVIDIA ----

def nvml_sample(ts, value):
    return NS(timeStamp=ts, sampleValue=NS(uiVal=value))


class FakeNvml:
    NVML_TEMPERATURE_GPU = 0
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 2
    NVML_GPU_UTILIZATION_SAMPLES = 1
    NVML_MEMORY_UTILIZATION_SAMPLES = 2
    NVML_VALUE_TYPE_UNSIGNED_INT = 1

    class NVMLError(Exception):
        pass

    class NVMLError_NotSupported(NVMLError):
        pass

    def __init__(self, count=1, init_fails=False):
        self.count, self.init_fails = count, init_fails
        self.fan_calls = 0
        self.util = 37
        self.rates_fail = False
        # Driver sample buffers per sample type: list of (timestamp_us, percent).
        self.buffers = {1: [(100, 30), (200, 44)], 2: [(100, 10), (200, 14)]}
        self.samples_fail = False

    def nvmlDeviceGetSamples(self, h, sample_type, last_seen):
        if self.samples_fail:
            raise self.NVMLError("Unknown Error")
        return 1, [nvml_sample(t, v) for t, v in self.buffers[sample_type] if t > last_seen]

    def nvmlInit(self):
        if self.init_fails:
            raise self.NVMLError("driver not loaded")

    def nvmlShutdown(self):
        pass

    def nvmlSystemGetDriverVersion(self):
        return "566.26"

    def nvmlDeviceGetCount(self):
        return self.count

    def nvmlDeviceGetHandleByIndex(self, i):
        return f"h{i}"

    def nvmlDeviceGetName(self, h):
        return "NVIDIA GeForce RTX 4050 Laptop GPU"

    def nvmlDeviceGetUtilizationRates(self, h):
        if self.rates_fail:
            raise self.NVMLError("Unknown Error")
        return NS(gpu=self.util, memory=12)

    def nvmlDeviceGetMemoryInfo(self, h):
        return NS(total=6 * 2**30, used=2**30, free=5 * 2**30)

    def nvmlDeviceGetTemperature(self, h, sensor):
        return 48

    def nvmlDeviceGetPowerUsage(self, h):
        return 13136  # milliwatts

    def nvmlDeviceGetClockInfo(self, h, clock):
        return 2100 if clock == self.NVML_CLOCK_GRAPHICS else 8000

    def nvmlDeviceGetFanSpeed(self, h):
        self.fan_calls += 1
        raise self.NVMLError_NotSupported("Not Supported")


def test_nvidia_unavailable_when_init_fails():
    with pytest.raises(CollectorUnavailable):
        NvidiaGpuCollector(nvml=FakeNvml(init_fails=True))


def test_nvidia_unavailable_with_no_devices():
    with pytest.raises(CollectorUnavailable):
        NvidiaGpuCollector(nvml=FakeNvml(count=0))


def test_nvidia_sample():
    m = NvidiaGpuCollector(nvml=FakeNvml()).sample()
    assert m == {
        "gpu.nvidia0.util": 37.0,
        "gpu.nvidia0.mem_util": 12.0,
        "gpu.nvidia0.vram_used": float(2**30),
        "gpu.nvidia0.vram_total": float(6 * 2**30),
        "gpu.nvidia0.temp_c": 48.0,
        "gpu.nvidia0.power_w": pytest.approx(13.136),
        "gpu.nvidia0.clock_gfx_mhz": 2100.0,
        "gpu.nvidia0.clock_mem_mhz": 8000.0,
    }


def test_nvidia_util_averages_new_driver_samples_since_last_poll():
    nv = FakeNvml()
    nv.rates_fail = True  # GetUtilizationRates is flaky on Optimus laptops; samples are not
    c = NvidiaGpuCollector(nvml=nv)
    assert c.sample()["gpu.nvidia0.util"] == 37.0
    nv.buffers[1].append((300, 90))
    nv.buffers[2].append((300, 50))
    m = c.sample()
    assert m["gpu.nvidia0.util"] == 90.0  # only samples newer than the last poll
    assert m["gpu.nvidia0.mem_util"] == 50.0


def test_nvidia_util_falls_back_to_rates_when_no_new_samples():
    nv = FakeNvml()
    c = NvidiaGpuCollector(nvml=nv)
    c.sample()
    nv.util = 5
    assert c.sample()["gpu.nvidia0.util"] == 5.0


def test_nvidia_util_omitted_when_both_sources_fail():
    nv = FakeNvml()
    nv.samples_fail = nv.rates_fail = True
    m = NvidiaGpuCollector(nvml=nv).sample()
    assert "gpu.nvidia0.util" not in m
    assert m["gpu.nvidia0.temp_c"] == 48.0


def test_nvidia_unsupported_metric_is_retried_only_after_cooldown():
    nv = FakeNvml()
    c = NvidiaGpuCollector(nvml=nv)
    for _ in range(NvidiaGpuCollector.UNSUPPORTED_RETRY_SAMPLES):
        c.sample()
    assert nv.fan_calls == 1
    c.sample()
    assert nv.fan_calls == 2


def test_nvidia_static_info():
    info = NvidiaGpuCollector(nvml=FakeNvml()).static_info()
    assert info == {
        "gpus": [{
            "id": "nvidia0", "name": "NVIDIA GeForce RTX 4050 Laptop GPU", "vendor": "NVIDIA",
            "vram_total": 6 * 2**30, "driver": "566.26", "source": "nvml",
        }]
    }


def test_nvidia_never_calls_setters():
    """Read-only guarantee: the collector module references no NVML Set* functions."""
    import inspect
    import hwmon.collectors.gpu_nvidia as mod
    assert "nvmlDeviceSet" not in inspect.getsource(mod)


# --------------------------------------------------------------- Windows ----

INTEL = "0x00000000_0x000144D0"
NVIDIA = "0x00000000_0x00014AF4"
BASIC = "0x00000000_0x000149E2"

ADAPTERS = [
    Adapter(luid=INTEL, name="Intel(R) Arc(TM) Graphics", vendor_id=0x8086,
            dedicated_bytes=128 * 2**20, software=False),
    Adapter(luid=NVIDIA, name="NVIDIA GeForce RTX 4050 Laptop GPU", vendor_id=0x10DE,
            dedicated_bytes=6 * 2**30, software=False),
    Adapter(luid=BASIC, name="Microsoft Basic Render Driver", vendor_id=0x1414,
            dedicated_bytes=0, software=True),
]


class FakePdh:
    def __init__(self, arrays):
        self.arrays = arrays

    def add(self, path):
        return path

    def collect(self):
        pass

    def array(self, counter):
        return self.arrays.get(counter, {})


UTIL = r"\GPU Engine(*)\Utilization Percentage"
DED = r"\GPU Adapter Memory(*)\Dedicated Usage"
SHR = r"\GPU Adapter Memory(*)\Shared Usage"


def eng(pid, luid, e, t):
    return f"pid_{pid}_luid_{luid}_phys_0_eng_{e}_engtype_{t}"


def make_pdh():
    return FakePdh({
        UTIL: {
            # two processes on the Intel 3D engine sum to 30; video decode engine at 20
            eng(1, INTEL, 0, "3D"): 10.0,
            eng(2, INTEL, 0, "3D"): 20.0,
            eng(2, INTEL, 5, "VideoDecode"): 20.0,
            eng(3, INTEL, 1, ""): 99.0,  # unnamed engine type: counts toward util, not broken out
            eng(1, NVIDIA, 0, "3D"): 50.0,
            eng(1, BASIC, 0, "3D"): 5.0,
        },
        DED: {f"luid_{INTEL}_phys_0": 0.0, f"luid_{NVIDIA}_phys_0": 1.0},
        SHR: {f"luid_{INTEL}_phys_0": 3.0e9, f"luid_{NVIDIA}_phys_0": 2.0},
    })


def test_windows_gpu_excludes_software_and_excluded_vendors():
    c = WindowsGpuCollector(adapters_fn=lambda: ADAPTERS, pdh=make_pdh(), exclude_vendors={0x10DE})
    assert c.static_info() == {
        "gpus": [{
            "id": "intel0", "name": "Intel(R) Arc(TM) Graphics", "vendor": "Intel",
            "vram_total": 128 * 2**20, "driver": None, "source": "pdh",
        }]
    }
    m = c.sample()
    assert not any(k.startswith("gpu.nvidia") for k in m)


def test_windows_gpu_utilization_is_busiest_engine_summed_over_processes():
    c = WindowsGpuCollector(adapters_fn=lambda: ADAPTERS, pdh=make_pdh(), exclude_vendors={0x10DE})
    m = c.sample()
    assert m["gpu.intel0.util"] == 99.0
    assert m["gpu.intel0.engine.3D"] == 30.0
    assert m["gpu.intel0.engine.VideoDecode"] == 20.0
    assert m["gpu.intel0.shared_used"] == 3.0e9
    assert m["gpu.intel0.dedicated_used"] == 0.0


def test_windows_gpu_util_capped_at_100():
    pdh = make_pdh()
    pdh.arrays[UTIL] = {eng(1, INTEL, 0, "3D"): 80.0, eng(2, INTEL, 0, "3D"): 70.0}
    c = WindowsGpuCollector(adapters_fn=lambda: ADAPTERS, pdh=pdh, exclude_vendors={0x10DE})
    assert c.sample()["gpu.intel0.util"] == 100.0


def test_windows_gpu_idle_adapter_reports_zero():
    pdh = make_pdh()
    pdh.arrays[UTIL] = {}
    c = WindowsGpuCollector(adapters_fn=lambda: ADAPTERS, pdh=pdh, exclude_vendors={0x10DE})
    assert c.sample()["gpu.intel0.util"] == 0.0


def test_windows_gpu_includes_nvidia_when_not_excluded():
    c = WindowsGpuCollector(adapters_fn=lambda: ADAPTERS, pdh=make_pdh(), exclude_vendors=set())
    assert [g["id"] for g in c.static_info()["gpus"]] == ["intel0", "nvidia0"]
    assert c.sample()["gpu.nvidia0.util"] == 50.0


def test_windows_gpu_unavailable_without_hardware_adapters():
    with pytest.raises(CollectorUnavailable):
        WindowsGpuCollector(adapters_fn=lambda: ADAPTERS[2:], pdh=make_pdh())
