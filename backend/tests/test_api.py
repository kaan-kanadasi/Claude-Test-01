import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from hwmon.config import Config
from hwmon.main import create_app


class InfoCollector:
    name = "cpu"
    interval = None

    def static_info(self):
        return {"cpu": {"name": "Test CPU", "cores": 2, "threads": 4, "base_mhz": 2300.0}}

    def sample(self):
        self.details = [{"name": "python", "cpu": 4.5}]
        return {"cpu.total": 42.0}


class GpuA:
    name = "gpu_nvidia"
    interval = None

    def static_info(self):
        return {"gpus": [{"id": "nvidia0", "name": "A"}]}

    def sample(self):
        return {"gpu.nvidia0.util": 5.0}


class GpuB(GpuA):
    name = "gpu_windows"

    def static_info(self):
        return {"gpus": [{"id": "intel0", "name": "B"}]}

    def sample(self):
        return {"gpu.intel0.util": 7.0}


@pytest.fixture
def client(tmp_path):
    cfg = Config(db_path=tmp_path / "m.db", sample_interval=0.02, persist_interval=0.0)
    app = create_app(cfg, collectors_factory=lambda cfg: (
        [InfoCollector(), GpuA(), GpuB()], {"sensors": "no provider"}))
    with TestClient(app) as c:
        yield c


def wait_for(fn, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_info_merges_static_info_and_lists_gpus_from_all_collectors(client):
    info = client.get("/api/info").json()
    assert info["cpu"]["name"] == "Test CPU"
    assert [g["id"] for g in info["gpus"]] == ["nvidia0", "intel0"]
    assert info["unavailable"] == {"sensors": "no provider"}
    assert info["config"]["sample_interval"] == 0.02


def test_snapshot(client):
    snap = wait_for(lambda: (r := client.get("/api/snapshot")).status_code == 200 and r.json())
    assert snap["metrics"] == {"cpu.total": 42.0, "gpu.nvidia0.util": 5.0, "gpu.intel0.util": 7.0}
    assert snap["status"]["sensors"] == "unavailable: no provider"
    assert snap["details"] == {"cpu": [{"name": "python", "cpu": 4.5}]}


def test_websocket_streams_snapshots(client):
    with client.websocket_connect("/ws/live") as ws:
        first = ws.receive_json()
        second = ws.receive_json()
    assert first["metrics"]["cpu.total"] == 42.0
    assert second["ts"] > first["ts"]


def test_history_returns_persisted_samples(client):
    def fetch():
        now = time.time()
        r = client.get("/api/history", params={"keys": "cpu.total,missing", "start": now - 60, "end": now + 1})
        body = r.json()
        return body if body["series"]["cpu.total"] else None

    body = wait_for(fetch)
    assert body["source"] == "raw"
    assert body["series"]["missing"] == []
    assert all(v == 42.0 for _, v in body["series"]["cpu.total"])


def test_history_defaults_to_last_hour(client):
    body = client.get("/api/history", params={"keys": "cpu.total"}).json()
    assert body["source"] == "raw"


def test_history_rejects_bad_range(client):
    assert client.get("/api/history", params={"keys": "k", "start": 10, "end": 5}).status_code == 400
    assert client.get("/api/history", params={"keys": ""}).status_code == 400


def test_api_is_read_only(client):
    """v1 guarantee: no route accepts anything but GET/HEAD."""
    for route in client.app.routes:
        if isinstance(route, APIRoute):
            assert route.methods <= {"GET", "HEAD"}, route.path
    assert client.post("/api/info").status_code == 405
