import asyncio

from hwmon.sampler import Hub, Sampler
from tests.fakes import FakeClock


class StubCollector:
    def __init__(self, name, metrics, interval=None):
        self.name, self.metrics, self.interval = name, metrics, interval
        self.calls = 0
        self.fail = False

    def static_info(self):
        return {}

    def sample(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return dict(self.metrics)


class RecordingStore:
    def __init__(self):
        self.writes = []

    def write(self, ts, metrics):
        self.writes.append((ts, metrics))


def make(collectors, **kw):
    clock = FakeClock(1000.0)
    s = Sampler(collectors, unavailable={"sensors": "no provider"}, clock=clock, **kw)
    return s, clock


def test_tick_merges_collectors_and_reports_status():
    a, b = StubCollector("a", {"a.x": 1.0}), StubCollector("b", {"b.y": 2.0})
    s, _ = make([a, b])
    snap = s.tick()
    assert snap["ts"] == 1000.0
    assert snap["metrics"] == {"a.x": 1.0, "b.y": 2.0}
    assert snap["status"] == {"a": "ok", "b": "ok", "sensors": "unavailable: no provider"}
    assert s.latest is snap


def test_failing_collector_is_isolated_and_backs_off():
    a, b = StubCollector("a", {"a.x": 1.0}), StubCollector("b", {"b.y": 2.0})
    s, clock = make([a, b])
    s.tick()
    b.fail = True
    clock.advance(1)
    snap = s.tick()
    assert snap["metrics"] == {"a.x": 1.0}  # stale b values are dropped
    assert snap["status"]["b"] == "error: boom"
    assert b.calls == 2

    clock.advance(0.5)  # within the 1s backoff: not retried
    s.tick()
    assert b.calls == 2
    clock.advance(1)
    s.tick()  # retried, fails again -> backoff doubles to 2s
    assert b.calls == 3
    clock.advance(1.5)
    s.tick()
    assert b.calls == 3

    b.fail = False
    clock.advance(1)
    snap = s.tick()
    assert b.calls == 4
    assert snap["status"]["b"] == "ok"
    assert snap["metrics"]["b.y"] == 2.0


def test_backoff_is_capped():
    a = StubCollector("a", {})
    a.fail = True
    s, clock = make([a])
    for _ in range(20):
        s.tick()
        clock.advance(Sampler.MAX_BACKOFF_S)
    assert a.calls == 20


def test_slow_collector_values_are_carried_between_polls():
    fast, slow = StubCollector("fast", {"f": 1.0}), StubCollector("slow", {"s": 2.0}, interval=2.0)
    s, clock = make([fast, slow])
    s.tick()
    clock.advance(1)
    snap = s.tick()
    assert slow.calls == 1
    assert snap["metrics"]["s"] == 2.0
    clock.advance(1)
    s.tick()
    assert slow.calls == 2


def test_persists_at_persist_interval():
    store = RecordingStore()
    s, clock = make([StubCollector("a", {"a.x": 1.0})], store=store, persist_interval=5.0)
    for _ in range(11):
        s.tick()
        clock.advance(1)
    assert [ts for ts, _ in store.writes] == [1000.0, 1005.0, 1010.0]


class DetailCollector(StubCollector):
    def __init__(self):
        super().__init__("procs", {"proc.count": 2.0})

    def sample(self):
        m = super().sample()
        self.details = [{"name": "a"}, {"name": "b"}]
        return m


def test_details_are_included_in_snapshot_but_not_persisted():
    store = RecordingStore()
    d = DetailCollector()
    s, _ = make([d, StubCollector("a", {"a.x": 1.0})], store=store)
    snap = s.tick()
    assert snap["details"] == {"procs": [{"name": "a"}, {"name": "b"}]}
    assert store.writes == [(1000.0, {"proc.count": 2.0, "a.x": 1.0})]


def test_details_are_dropped_when_collector_fails():
    d = DetailCollector()
    s, clock = make([d])
    s.tick()
    d.fail = True
    clock.advance(1)
    assert s.tick()["details"] == {}


def test_run_samples_on_one_dedicated_thread():
    """psutil.cpu_percent keeps per-thread state, so ticks must not hop between pool threads."""
    import threading
    import time as _time

    class ThreadRecorder(StubCollector):
        def __init__(self):
            super().__init__("rec", {})
            self.threads = set()

        def sample(self):
            self.calls += 1
            self.threads.add(threading.get_ident())
            return {}

    rec = ThreadRecorder()
    s = Sampler([rec], interval=0.01)

    async def scenario():
        task = asyncio.create_task(s.run())
        # Keep the default executor busy so a to_thread-based loop would land on other threads.
        await asyncio.gather(*(asyncio.to_thread(_time.sleep, 0.05) for _ in range(16)))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert rec.calls >= 5
    assert len(rec.threads) == 1
    assert threading.get_ident() not in rec.threads


def test_hub_keeps_only_latest_for_slow_subscribers():
    async def scenario():
        hub = Hub()
        q = hub.subscribe()
        hub.publish({"n": 1})
        hub.publish({"n": 2})
        assert q.qsize() == 1
        assert (await q.get()) == {"n": 2}
        hub.unsubscribe(q)
        hub.publish({"n": 3})
        assert q.empty()

    asyncio.run(scenario())
