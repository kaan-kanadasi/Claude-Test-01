import pytest

from hwmon.collectors.gpu_windows import Adapter, parse_engine_instance
from hwmon.collectors.processes import CPU_PATH, GPU_PATH, MEM_PATH, ProcessCollector

INTEL = "0x00000000_0x000144D0"
NVIDIA = "0x00000000_0x00014AF4"

ADAPTERS = [
    Adapter(luid=INTEL, name="Intel(R) Arc(TM) Graphics", vendor_id=0x8086, dedicated_bytes=0, software=False),
    Adapter(luid=NVIDIA, name="NVIDIA GeForce RTX 4050 Laptop GPU", vendor_id=0x10DE, dedicated_bytes=0, software=False),
    Adapter(luid="0x00000000_0x000149E2", name="Microsoft Basic Render Driver", vendor_id=0x1414,
            dedicated_bytes=0, software=True),
]


class FakePdh:
    def __init__(self, arrays):
        self.arrays = arrays
        self.nocap_requests = set()

    def add(self, path):
        return path

    def collect(self):
        pass

    def array(self, counter, nocap=False):
        if nocap:
            self.nocap_requests.add(counter)
        return self.arrays.get(counter, {})


def eng(pid, luid, e, t):
    return f"pid_{pid}_luid_{luid}_phys_0_eng_{e}_engtype_{t}"


def make_pdh():
    return FakePdh({
        # Raw "% Processor Time" is per logical CPU (0..100*ncpu); 4 CPUs here.
        CPU_PATH: {
            "_Total": 400.0, "Idle:0": 300.0,
            "chrome:1": 20.0, "chrome:2": 20.0,
            "python:3": 100.0,
            "svchost:4": 0.0,
        },
        MEM_PATH: {
            "_Total": 9e9, "Idle:0": 8192.0,
            "chrome:1": 300.0, "chrome:2": 200.0,
            "python:3": 100.0,
            "svchost:4": 1000.0,
        },
        GPU_PATH: {
            eng(1, INTEL, 0, "3D"): 10.0,
            eng(2, INTEL, 0, "3D"): 20.0,         # same engine as pid 1 -> 30 for chrome
            eng(2, INTEL, 5, "VideoDecode"): 25.0,
            eng(3, NVIDIA, 0, "Compute"): 50.0,
            eng(99, NVIDIA, 0, "3D"): 70.0,       # process that already exited: ignored
        },
    })


def make(pdh=None, **kw):
    return ProcessCollector(pdh=pdh or make_pdh(), adapters_fn=lambda: ADAPTERS, cpu_count=4, **kw)


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_parse_engine_instance():
    assert parse_engine_instance(eng(12, INTEL, 5, "VideoDecode")) == (INTEL.upper(), "0", "5", "VideoDecode", 12)
    assert parse_engine_instance("garbage") is None


def test_groups_processes_by_name_with_normalized_cpu():
    c = make()
    m = c.sample()
    rows = by_name(c.details)
    assert m == {"proc.count": 4.0}
    assert set(rows) == {"chrome", "python", "svchost"}  # Idle and _Total excluded
    assert rows["chrome"]["count"] == 2
    assert rows["chrome"]["cpu"] == pytest.approx(10.0)   # (20+20)/4
    assert rows["python"]["cpu"] == pytest.approx(25.0)   # 100/4
    assert rows["chrome"]["memory"] == 500
    assert rows["svchost"]["memory"] == 1000


def test_cpu_counter_is_read_uncapped():
    pdh = make_pdh()
    make(pdh).sample()
    assert CPU_PATH in pdh.nocap_requests


def test_gpu_is_busiest_engine_summed_over_the_groups_processes():
    c = make()
    c.sample()
    rows = by_name(c.details)
    assert rows["chrome"]["gpu"] == 30.0
    assert rows["chrome"]["gpu_adapter"] == "Intel(R) Arc(TM) Graphics"
    assert rows["python"]["gpu"] == 50.0
    assert rows["python"]["gpu_adapter"] == "NVIDIA GeForce RTX 4050 Laptop GPU"
    assert rows["svchost"]["gpu"] == 0.0
    assert rows["svchost"]["gpu_adapter"] is None


def test_details_sorted_by_cpu():
    c = make()
    c.sample()
    assert [r["name"] for r in c.details] == ["python", "chrome", "svchost"]


def test_details_keep_top_n_by_each_measure():
    c = make(top_n=1)
    c.sample()
    # top CPU = python, top memory = svchost, top GPU = python
    assert {r["name"] for r in c.details} == {"python", "svchost"}
