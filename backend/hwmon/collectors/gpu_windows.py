"""Any GPU via Windows GPU performance counters (the data behind Task Manager).

Adapters are enumerated with DXGI to map PDH's LUID-keyed instances to names.
Utilization per adapter = busiest engine, where an engine's load is summed over
processes -- the same definition Task Manager uses.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .base import CollectorUnavailable, metric_key

VENDORS = {0x8086: "Intel", 0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD"}
# Engine types broken out as separate metrics (others still count toward overall util).
ENGINE_TYPES = {"3D", "Compute", "Copy", "VideoDecode", "VideoEncode", "VideoProcessing"}

UTIL_PATH = r"\GPU Engine(*)\Utilization Percentage"
DEDICATED_PATH = r"\GPU Adapter Memory(*)\Dedicated Usage"
SHARED_PATH = r"\GPU Adapter Memory(*)\Shared Usage"

_ENGINE_RE = re.compile(r"pid_(\d+)_luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$")
_MEMORY_RE = re.compile(r"luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_\d+$")


def parse_engine_instance(inst: str) -> tuple[str, str, str, str, int] | None:
    """Split a GPU Engine instance name into (LUID upper-cased, phys, engine, engine type, pid)."""
    mt = _ENGINE_RE.search(inst)
    if not mt:
        return None
    return mt[2].upper(), mt[3], mt[4], mt[5], int(mt[1])


@dataclass(frozen=True)
class Adapter:
    luid: str  # "0xHIGH_0xLOW", as it appears in PDH instance names
    name: str
    vendor_id: int
    dedicated_bytes: int
    software: bool


def enumerate_dxgi_adapters() -> list[Adapter]:
    """List display adapters via DXGI (ctypes COM calls; read-only)."""
    import ctypes
    import uuid
    from ctypes import wintypes as wt

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]

    class DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", wt.WCHAR * 128), ("VendorId", wt.UINT), ("DeviceId", wt.UINT),
            ("SubSysId", wt.UINT), ("Revision", wt.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID), ("Flags", wt.UINT),
        ]

    DXGI_ADAPTER_FLAG_SOFTWARE = 2
    DXGI_ERROR_NOT_FOUND = 0x887A0002 - 2**32

    def vcall(obj, index, *argtypes):
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])

    iid = (ctypes.c_byte * 16).from_buffer_copy(
        uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le  # IDXGIFactory1
    )
    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
        return []
    adapters = []
    try:
        i = 0
        while True:
            adapter = ctypes.c_void_p()
            # IDXGIFactory1::EnumAdapters1 is vtable slot 12
            hr = vcall(factory, 12, wt.UINT, ctypes.POINTER(ctypes.c_void_p))(
                factory, i, ctypes.byref(adapter))
            if hr == DXGI_ERROR_NOT_FOUND or hr != 0:
                break
            try:
                desc = DXGI_ADAPTER_DESC1()
                # IDXGIAdapter1::GetDesc1 is vtable slot 10
                if vcall(adapter, 10, ctypes.POINTER(DXGI_ADAPTER_DESC1))(adapter, ctypes.byref(desc)) == 0:
                    luid = f"0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08X}_0x{desc.AdapterLuid.LowPart:08X}"
                    adapters.append(Adapter(
                        luid=luid, name=desc.Description, vendor_id=desc.VendorId,
                        dedicated_bytes=desc.DedicatedVideoMemory,
                        software=bool(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE),
                    ))
            finally:
                vcall(adapter, 2)(adapter)  # Release
            i += 1
    finally:
        vcall(factory, 2)(factory)  # Release
    return adapters


def _default_pdh():
    from ._pdh import PdhQuery

    return PdhQuery()


class AdapterActivity:
    """Current load of one vendor's GPUs, read from Windows counters.

    These counters come from the OS GPU scheduler, so reading them does not wake a
    sleeping laptop dGPU (verified: NVML still paid the ~1.5 s wake-up afterwards).
    Returns None when no adapter of that vendor exists.
    """

    def __init__(self, vendor_id: int, adapters_fn: Callable[[], list[Adapter]] = enumerate_dxgi_adapters,
                 pdh: Any = None):
        self._luids = {a.luid.upper() for a in adapters_fn() if a.vendor_id == vendor_id and not a.software}
        self._pdh = pdh if pdh is not None else _default_pdh()
        self._util = self._pdh.add(UTIL_PATH)
        self._pdh.collect()  # rate counter: needs a baseline

    def __call__(self) -> float | None:
        if not self._luids:
            return None
        self._pdh.collect()
        engines: dict[tuple[str, str, str], float] = defaultdict(float)
        for inst, value in self._pdh.array(self._util).items():
            parsed = parse_engine_instance(inst)
            if parsed is not None and parsed[0] in self._luids:
                engines[parsed[:3]] += value
        return min(max(engines.values(), default=0.0), 100.0)


class WindowsGpuCollector:
    name = "gpu_windows"
    interval = None

    def __init__(self, adapters_fn: Callable[[], list[Adapter]] = enumerate_dxgi_adapters,
                 pdh: Any = None, exclude_vendors: Iterable[int] = ()):
        excluded = set(exclude_vendors)
        try:
            adapters = [a for a in adapters_fn() if not a.software and a.vendor_id not in excluded]
        except Exception as e:
            raise CollectorUnavailable(f"Could not enumerate GPUs: {e}") from e
        if not adapters:
            raise CollectorUnavailable("No hardware GPUs to monitor via Windows counters")

        self._adapters: dict[str, tuple[str, Adapter]] = {}  # luid (upper) -> (id, adapter)
        per_prefix: dict[str, int] = defaultdict(int)
        for a in adapters:
            prefix = VENDORS.get(a.vendor_id, "gpu").lower()
            gid = f"{prefix}{per_prefix[prefix]}"
            per_prefix[prefix] += 1
            self._adapters[a.luid.upper()] = (gid, a)

        try:
            self._pdh = pdh if pdh is not None else _default_pdh()
            self._util = self._pdh.add(UTIL_PATH)
            self._ded = self._pdh.add(DEDICATED_PATH)
            self._shr = self._pdh.add(SHARED_PATH)
            self._pdh.collect()  # utilization is a rate counter: needs a baseline
        except Exception as e:
            raise CollectorUnavailable(f"GPU performance counters unavailable: {e}") from e

    def static_info(self) -> dict:
        return {
            "gpus": [
                {"id": gid, "name": a.name, "vendor": VENDORS.get(a.vendor_id, "Unknown"),
                 "vram_total": a.dedicated_bytes, "driver": None, "source": "pdh"}
                for gid, a in self._adapters.values()
            ]
        }

    def sample(self) -> dict[str, float]:
        self._pdh.collect()

        # Sum each physical engine's load over processes.
        engines: dict[tuple[str, str, str], float] = defaultdict(float)
        engine_type: dict[tuple[str, str, str], str] = {}
        for inst, value in self._pdh.array(self._util).items():
            parsed = parse_engine_instance(inst)
            if parsed is None:
                continue
            luid, phys, eng, etype, _pid = parsed
            key = (luid, phys, eng)
            engines[key] += value
            engine_type[key] = etype

        m: dict[str, float] = {}
        for luid, (gid, _) in self._adapters.items():
            m[f"gpu.{gid}.util"] = 0.0
        for key, load in engines.items():
            entry = self._adapters.get(key[0])
            if entry is None:
                continue
            gid = entry[0]
            load = min(load, 100.0)
            util_key = f"gpu.{gid}.util"
            m[util_key] = max(m[util_key], load)
            etype = engine_type[key]
            if etype in ENGINE_TYPES:
                ekey = metric_key("gpu", gid, "engine", etype)
                m[ekey] = max(m.get(ekey, 0.0), load)

        for counter, suffix in ((self._ded, "dedicated_used"), (self._shr, "shared_used")):
            totals: dict[str, float] = defaultdict(float)
            for inst, value in self._pdh.array(counter).items():
                mt = _MEMORY_RE.search(inst)
                if mt:
                    totals[mt[1].upper()] += value
            for luid, (gid, _) in self._adapters.items():
                if luid in totals:
                    m[f"gpu.{gid}.{suffix}"] = totals[luid]
        return m
