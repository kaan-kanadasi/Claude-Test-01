import pytest

from hwmon.store import MetricStore


@pytest.fixture
def store(tmp_path):
    s = MetricStore(tmp_path / "m.db")
    yield s
    s.close()


def test_raw_history_round_trip(store):
    store.write(1000.0, {"cpu.total": 10.0, "mem.used": 5.0})
    store.write(1005.0, {"cpu.total": 20.0})
    h = store.history(["cpu.total", "mem.used", "nope"], 990, 1010)
    assert h["source"] == "raw"
    assert h["series"]["cpu.total"] == [[1000, 10.0], [1005, 20.0]]
    assert h["series"]["mem.used"] == [[1000, 5.0]]
    assert h["series"]["nope"] == []


def test_history_respects_range(store):
    for t in (100, 200, 300):
        store.write(t, {"k": float(t)})
    assert store.history(["k"], 150, 250)["series"]["k"] == [[200, 200.0]]


def test_persists_across_reopen(tmp_path):
    s = MetricStore(tmp_path / "m.db")
    s.write(1000, {"k": 1.0})
    s.close()
    s = MetricStore(tmp_path / "m.db")
    assert s.history(["k"], 0, 2000)["series"]["k"] == [[1000, 1.0]]
    s.close()


def test_raw_history_is_downsampled_to_max_points(store):
    for t in range(0, 3600, 5):
        store.write(t, {"k": float(t % 2)})
    h = store.history(["k"], 0, 3600, max_points=100)
    assert h["step"] == 36
    assert len(h["series"]["k"]) <= 100


def test_rollup_only_complete_minutes(store):
    for t in range(0, 125, 5):  # minutes 0, 1 complete; minute 2 partial
        store.write(t, {"k": float(t)})
    store.rollup(now=125)
    rows = store._rollup_rows("k")
    assert rows == [(0, 27.5, 0.0, 55.0), (60, 87.5, 60.0, 115.0)]
    # Running again later picks up minute 2 without duplicating earlier ones.
    store.rollup(now=200)
    assert [r[0] for r in store._rollup_rows("k")] == [0, 60, 120]


def test_long_ranges_use_rollups(store):
    for t in range(0, 7200, 5):
        store.write(t, {"k": 1.0})
    store.rollup(now=7200)
    h = store.history(["k"], 0, 7200)
    assert h["source"] == "1m"
    assert h["step"] == 60
    assert len(h["series"]["k"]) == 120
    assert all(v == 1.0 for _, v in h["series"]["k"])


def test_prune_applies_retention(store):
    for t in range(0, 600, 5):
        store.write(t, {"k": 1.0})
    store.rollup(now=600)
    store.prune(now=600, raw_retention_s=120, rollup_retention_s=300)
    assert store.history(["k"], 0, 600)["series"]["k"][0][0] >= 480
    assert [r[0] for r in store._rollup_rows("k")] == [300, 360, 420, 480, 540]
