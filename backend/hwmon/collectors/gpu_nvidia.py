"""NVIDIA GPUs via NVML. Query-only: uses nvmlDeviceGet* functions exclusively."""

from __future__ import annotations

from typing import Any, Callable


def _load_nvml():
    import pynvml

    return pynvml


class NvidiaGpuCollector:
    name = "gpu_nvidia"
    # NVML calls can block ~0.5 s while a sleeping laptop dGPU wakes, so the sampler
    # polls this collector on its own thread instead of in the main tick.
    background = True
    # A metric NVML reports as unsupported is skipped for this many samples before
    # retrying (a sleeping laptop dGPU can report NotSupported transiently).
    UNSUPPORTED_RETRY_SAMPLES = 60
    # On battery, below this load (from activity_fn) the GPU is treated as idle and NVML
    # is not queried, so the dGPU can stay asleep.
    ACTIVE_THRESHOLD_PCT = 1.0

    def __init__(self, nvml: Any = None, interval: float | None = 2.0,
                 on_battery_fn: Callable[[], bool] | None = None,
                 activity_fn: Callable[[], float | None] | None = None):
        """``on_battery_fn`` and ``activity_fn`` (GPU load read without waking it) enable
        battery saving; without them NVML is always queried."""
        from .base import CollectorUnavailable

        self.interval = interval
        self._on_battery_fn = on_battery_fn
        self._activity_fn = activity_fn
        try:
            self._nv = nvml if nvml is not None else _load_nvml()
            self._nv.nvmlInit()
            count = self._nv.nvmlDeviceGetCount()
        except Exception as e:  # ImportError, NVMLError (no driver), OSError (no DLL)
            raise CollectorUnavailable(f"NVML unavailable: {e}") from e
        if count == 0:
            raise CollectorUnavailable("NVML found no NVIDIA GPUs")
        self._handles = [self._nv.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        self._power_limits_w = [self._power_limit_w(h) for h in self._handles]
        # (device index, metric) -> sample number at which to retry an unsupported metric.
        self._unsupported: dict[tuple[int, str], int] = {}
        self._samples = 0
        # (device index, sample type) -> newest driver sample timestamp already consumed.
        self._last_sample_ts: dict[tuple[int, int], int] = {}

    def _utilization(self, i: int, h, sample_type: int, rates_field: str) -> float:
        """Mean of the driver's utilization samples since the last poll.

        nvmlDeviceGetUtilizationRates fails intermittently with "Unknown Error" on
        Optimus laptops while the sample buffer stays readable, so prefer the buffer
        and fall back to the instantaneous rate when there are no new samples.
        """
        nv = self._nv
        try:
            _, samples = nv.nvmlDeviceGetSamples(h, sample_type, self._last_sample_ts.get((i, sample_type), 0))
        except nv.NVMLError:
            samples = []
        if samples:
            self._last_sample_ts[(i, sample_type)] = samples[-1].timeStamp
            return sum(s.sampleValue.uiVal for s in samples) / len(samples)
        return getattr(nv.nvmlDeviceGetUtilizationRates(h), rates_field)

    def _readers(self, i: int, h) -> dict[str, Callable[[], float]]:
        nv = self._nv
        return {
            "util": lambda: self._utilization(i, h, nv.NVML_GPU_UTILIZATION_SAMPLES, "gpu"),
            "mem_util": lambda: self._utilization(i, h, nv.NVML_MEMORY_UTILIZATION_SAMPLES, "memory"),
            "vram_used": lambda: nv.nvmlDeviceGetMemoryInfo(h).used,
            "vram_total": lambda: nv.nvmlDeviceGetMemoryInfo(h).total,
            "temp_c": lambda: nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU),
            "power_w": lambda: self._plausible_power(i, nv.nvmlDeviceGetPowerUsage(h) / 1000.0),
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

    def _power_limit_w(self, h) -> float | None:
        try:
            return self._nv.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0
        except Exception:  # NVMLError, or missing from older bindings
            return None

    def _plausible_power(self, i: int, watts: float) -> float | None:
        """Drop readings far above the card's power limit (seen right after a dGPU wakes)."""
        limit = self._power_limits_w[i]
        return None if limit and watts > 2 * limit else watts

    def _idle_on_battery(self) -> float | None:
        """The GPU's load if we're on battery and it's idle (so NVML should be skipped)."""
        if self._on_battery_fn is None or self._activity_fn is None or not self._on_battery_fn():
            return None
        load = self._activity_fn()
        return load if load is not None and load < self.ACTIVE_THRESHOLD_PCT else None

    def sample(self) -> dict[str, float]:
        idle_load = self._idle_on_battery()
        if idle_load is not None:
            # Any NVML query would wake the sleeping dGPU; report its idle load only.
            m = {}
            for i in range(len(self._handles)):
                m[f"gpu.nvidia{i}.util"] = idle_load
                m[f"gpu.nvidia{i}.paused"] = 1.0
            return m

        m: dict[str, float] = {}
        not_supported = getattr(self._nv, "NVMLError_NotSupported", ())
        self._samples += 1
        for i, h in enumerate(self._handles):
            for metric, read in self._readers(i, h).items():
                if self._unsupported.get((i, metric), 0) > self._samples:
                    continue
                try:
                    value = read()
                    if value is not None:
                        m[f"gpu.nvidia{i}.{metric}"] = float(value)
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
