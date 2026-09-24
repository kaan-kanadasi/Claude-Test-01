"""NVIDIA GPUs via NVML. Query-only: uses nvmlDeviceGet* functions exclusively."""

from __future__ import annotations

from typing import Any, Callable


def _load_nvml():
    import pynvml

    return pynvml


class NvidiaGpuCollector:
    name = "gpu_nvidia"
    # A metric NVML reports as unsupported is skipped for this many samples before
    # retrying (a sleeping laptop dGPU can report NotSupported transiently).
    UNSUPPORTED_RETRY_SAMPLES = 60

    def __init__(self, nvml: Any = None, interval: float | None = 2.0):
        from .base import CollectorUnavailable

        self.interval = interval
        try:
            self._nv = nvml if nvml is not None else _load_nvml()
            self._nv.nvmlInit()
            count = self._nv.nvmlDeviceGetCount()
        except Exception as e:  # ImportError, NVMLError (no driver), OSError (no DLL)
            raise CollectorUnavailable(f"NVML unavailable: {e}") from e
        if count == 0:
            raise CollectorUnavailable("NVML found no NVIDIA GPUs")
        self._handles = [self._nv.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        # (device index, metric) -> sample number at which to retry an unsupported metric.
        self._unsupported: dict[tuple[int, str], int] = {}
        self._samples = 0

    def _readers(self, h) -> dict[str, Callable[[], float]]:
        nv = self._nv
        return {
            "util": lambda: nv.nvmlDeviceGetUtilizationRates(h).gpu,
            "mem_util": lambda: nv.nvmlDeviceGetUtilizationRates(h).memory,
            "vram_used": lambda: nv.nvmlDeviceGetMemoryInfo(h).used,
            "vram_total": lambda: nv.nvmlDeviceGetMemoryInfo(h).total,
            "temp_c": lambda: nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU),
            "power_w": lambda: nv.nvmlDeviceGetPowerUsage(h) / 1000.0,
            "clock_gfx_mhz": lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS),
            "clock_mem_mhz": lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_MEM),
            "fan_pct": lambda: nv.nvmlDeviceGetFanSpeed(h),
        }

    def static_info(self) -> dict:
        try:
            driver = self._nv.nvmlSystemGetDriverVersion()
        except self._nv.NVMLError:
            driver = None
        gpus = []
        for i, h in enumerate(self._handles):
            gpus.append({
                "id": f"nvidia{i}",
                "name": self._nv.nvmlDeviceGetName(h),
                "vendor": "NVIDIA",
                "vram_total": self._nv.nvmlDeviceGetMemoryInfo(h).total,
                "driver": driver,
                "source": "nvml",
            })
        return {"gpus": gpus}

    def sample(self) -> dict[str, float]:
        m: dict[str, float] = {}
        not_supported = getattr(self._nv, "NVMLError_NotSupported", ())
        self._samples += 1
        for i, h in enumerate(self._handles):
            for metric, read in self._readers(h).items():
                if self._unsupported.get((i, metric), 0) > self._samples:
                    continue
                try:
                    m[f"gpu.nvidia{i}.{metric}"] = float(read())
                except not_supported:
                    self._unsupported[(i, metric)] = self._samples + self.UNSUPPORTED_RETRY_SAMPLES
                except self._nv.NVMLError:
                    # Transient (e.g. GPU asleep/lost); try again next sample.
                    pass
        return m

    def close(self) -> None:
        try:
            self._nv.nvmlShutdown()
        except Exception:
            pass
