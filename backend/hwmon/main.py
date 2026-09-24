"""App factory and entry point: ``uv run hwmon`` or ``uvicorn hwmon.main:app``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .collectors.base import Collector, CollectorUnavailable
from .config import Config
from .sampler import Hub, Sampler
from .store import MetricStore

log = logging.getLogger("hwmon")

CollectorsFactory = Callable[[Config], tuple[list[Collector], dict[str, str]]]


def build_collectors(cfg: Config) -> tuple[list[Collector], dict[str, str]]:
    """Instantiate every collector that works on this machine; record why others don't."""
    from .collectors.battery import BatteryCollector
    from .collectors.cpu import CpuCollector
    from .collectors.memory import MemoryCollector
    from .collectors.network import NetworkCollector
    from .collectors.sensors import NullSensors
    from .collectors.storage import StorageCollector

    collectors: list[Collector] = []
    unavailable: dict[str, str] = {}

    def attempt(name: str, factory: Callable[[], Collector]) -> Collector | None:
        try:
            c = factory()
        except CollectorUnavailable as e:
            unavailable[name] = str(e)
            return None
        except Exception as e:
            log.exception("collector %s failed to start", name)
            unavailable[name] = f"failed to start: {e}"
            return None
        collectors.append(c)
        return c

    attempt("cpu", CpuCollector)
    attempt("memory", MemoryCollector)
    attempt("storage", StorageCollector)
    attempt("network", NetworkCollector)

    nvidia = None
    if cfg.nvidia_interval > 0:
        from .collectors.gpu_nvidia import NvidiaGpuCollector

        from .collectors.battery import on_battery

        # On battery, let an idle NVIDIA laptop GPU sleep: check its load via Windows
        # counters (which don't wake it) and skip NVML while it's idle.
        activity = None
        if sys.platform == "win32":
            try:
                from .collectors.gpu_windows import AdapterActivity

                activity = AdapterActivity(0x10DE)
            except Exception as e:
                log.info("NVIDIA battery saving unavailable: %s", e)
        nvidia = attempt("gpu_nvidia", lambda: NvidiaGpuCollector(
            interval=cfg.nvidia_interval, on_battery_fn=on_battery, activity_fn=activity))
    else:
        unavailable["gpu_nvidia"] = "disabled by HWMON_NVIDIA_INTERVAL=0"

    if sys.platform == "win32":
        from .collectors.gpu_windows import WindowsGpuCollector

        # NVML gives richer NVIDIA data; use Windows counters only for the other GPUs.
        exclude = {0x10DE} if nvidia is not None else set()
        attempt("gpu_windows", lambda: WindowsGpuCollector(exclude_vendors=exclude))

        from .collectors.processes import ProcessCollector

        attempt("processes", ProcessCollector)

    attempt("battery", BatteryCollector)

    attempt("sensors", NullSensors)
    return collectors, unavailable


def _merge_static_info(collectors: list[Collector]) -> dict:
    info: dict = {"gpus": []}
    for c in collectors:
        try:
            part = c.static_info()
        except Exception as e:
            log.warning("static_info failed for %s: %s", c.name, e)
            continue
        for k, v in part.items():
            if k == "gpus":
                info["gpus"].extend(v)
            else:
                info[k] = v
    return info


async def _maintenance(store: MetricStore, cfg: Config) -> None:
    while True:
        try:
            now = time.time()
            await asyncio.to_thread(store.rollup, now)
            await asyncio.to_thread(store.prune, now, cfg.raw_retention_s, cfg.rollup_retention_s)
        except Exception:
            log.exception("maintenance job failed")
        await asyncio.sleep(cfg.maintenance_interval)


def create_app(cfg: Config | None = None, collectors_factory: CollectorsFactory = build_collectors) -> FastAPI:
    cfg = cfg or Config.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        collectors, unavailable = await asyncio.to_thread(collectors_factory, cfg)
        store = MetricStore(cfg.db_path)
        hub = Hub()
        sampler = Sampler(collectors, unavailable, store=store, hub=hub,
                          interval=cfg.sample_interval, persist_interval=cfg.persist_interval)
        app.state.store, app.state.hub, app.state.sampler = store, hub, sampler
        app.state.static_info = {
            **_merge_static_info(collectors),
            "unavailable": unavailable,
            "config": cfg.public(),
        }
        for name, reason in unavailable.items():
            log.info("collector %s unavailable: %s", name, reason)

        tasks = [asyncio.create_task(sampler.run()), asyncio.create_task(_maintenance(store, cfg))]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for c in collectors:
                close = getattr(c, "close", None)
                if close:
                    close()
            store.close()

    app = FastAPI(title="Hardware Monitor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
    )
    app.include_router(router)
    if cfg.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=cfg.frontend_dist, html=True), name="frontend")
    return app


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    run()
