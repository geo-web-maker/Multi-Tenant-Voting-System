"""PERF-M5: sinks, retry queue, persistence rules."""
import asyncio
import sys

import pytest
from mongomock_motor import AsyncMongoMockClient

import perf_metrics as pm
import perf_sinks as ps
import perf_tiers as pt
from tests.opcount import CountingDB


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for k in ("PERF_SINK", "PERF_POSTGRES_URL", "PERF_POSTGRES_POOLED", "PERF_MONGO_URL", "PERF_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    pm.reset_for_tests()
    pm._manager = None
    pm.set_clock(lambda: 1_000_000.0)
    yield
    pm.set_clock(None)
    pm._manager = None
    pm.reset_for_tests()


def batch(epoch=999_900):
    return {"_id": epoch, "minute_dt": "x", "rows": [{"t": epoch, "ops": 5}]}


class FakeCon:
    def __init__(self, log, fail_delete=False):
        self.log, self.fail_delete = log, fail_delete

    async def execute(self, sql, *args):
        if sql.startswith("DELETE") and self.fail_delete:
            raise RuntimeError("boom")
        self.log.append((sql.split()[0], args))

    async def fetch(self, sql, *args):
        return [{"minute_epoch": 999_900, "rows": '[{"t": 999900, "ops": 5}]'}]


class FakePool:
    def __init__(self, log, fail_delete=False):
        self.log, self.fail_delete = log, fail_delete

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self_):
                return FakeCon(pool.log, pool.fail_delete)

            async def __aexit__(self_, *a):
                return False
        return Ctx()


def pg(log, **kw):
    seen = {}

    async def factory(url, **k):
        seen.update(k)
        return FakePool(log, kw.get("fail_delete", False))
    sink = ps.PostgresSink("postgresql://u:secret@h/db", pooled=kw.get("pooled", False), pool_factory=factory)
    return sink, seen


async def test_postgres_write_is_an_idempotent_upsert_then_retention_delete():
    log = []
    sink, _ = pg(log)
    await sink.write(batch())
    await sink.write(batch())
    verbs = [v for v, _ in log]
    # written every second now, so the retention DELETE runs on the first write and then at most every 10 minutes
    assert verbs.count("INSERT") == 2 and verbs.count("DELETE") == 1 and verbs[0] == "CREATE"
    assert "ON CONFLICT" in ps.PostgresSink.UPSERT


async def test_failing_retention_delete_does_not_fail_the_flush():
    sink, _ = pg([], fail_delete=True)
    await sink.write(batch())


async def test_pooled_url_turns_off_statement_cache():
    sink, seen = pg([], pooled=True)
    await sink.write(batch())
    assert seen["statement_cache_size"] == 0 and seen["max_size"] == 2
    sink2, seen2 = pg([])
    await sink2.write(batch())
    assert "statement_cache_size" not in seen2


async def test_postgres_read_returns_rows():
    sink, _ = pg([])
    got = await sink.read(999_000, 1_000_000)
    assert got[0]["rows"][0]["ops"] == 5


async def test_asyncpg_not_imported_unless_postgres_is_chosen(monkeypatch):
    monkeypatch.delitem(sys.modules, "asyncpg", raising=False)
    monkeypatch.setenv("PERF_SINK", "mongo")
    await pm.start(AsyncMongoMockClient()["t"])
    await pm.stop()
    assert "asyncpg" not in sys.modules


@pytest.mark.parametrize("kind,var", [("postgres", "PERF_POSTGRES_URL"), ("mongo_separate", "PERF_MONGO_URL")])
def test_missing_url_falls_back_to_none_and_says_so(monkeypatch, kind, var):
    monkeypatch.setenv("PERF_SINK", kind)
    s = ps.build_sink(lambda: None)
    assert s.name == "none" and var in s.detail()


def test_status_never_contains_the_url_or_password(monkeypatch):
    monkeypatch.setenv("PERF_SINK", "postgres")
    monkeypatch.setenv("PERF_POSTGRES_URL", "postgresql://u:secret@h/db")
    m = ps.SinkManager(ps.build_sink(lambda: None))
    m.add_secret("postgresql://u:secret@h/db")
    m.mark_err(RuntimeError("could not connect to postgresql://u:secret@h/db as secret"))
    assert "secret" not in repr(m.status())


def test_queue_is_bounded_at_twelve_and_counts_drops():
    m = ps.SinkManager(ps.NullSink())
    for i in range(15):
        m.enqueue(batch(i))
    assert len(m.queue) == 12 and m.dropped == 3 and m.queue[0]["_id"] == 3


class Boom(ps.Sink):
    name = "boom"

    async def write(self, b):
        raise TimeoutError("down")

    async def read(self, s, e):
        return []


async def test_a_failing_sink_queues_and_never_raises():
    pm.install_sink(Boom())
    pm.COMMAND_LISTENER.started(type("E", (), {"command_name": "find", "command": {"find": "voters"}, "request_id": 1})())
    pm.set_clock(lambda: 1_000_000.0 + 180)
    await pm.flush_once()
    st = pm.sink_status()
    assert st["ok"] is False and st["queued"] >= 1


async def test_mongo_sink_writes_one_document_and_is_idempotent():
    db = AsyncMongoMockClient()["t"]
    sink = ps.MongoSink(lambda: db)
    await sink.write(batch())
    await sink.write(batch())
    assert await db.perf_minutes.count_documents({}) == 1
    await sink.ensure_index(14)
    assert any("minute_dt" in k for k in (await db.perf_minutes.index_information()))


async def test_perf_minutes_writes_are_not_counted_as_ops():
    pm.COMMAND_LISTENER.started(type("E", (), {"command_name": "update", "command": {"update": "perf_minutes",
                                "updates": [{}]}, "request_id": 5})())
    assert pm._window_sum("ops", 60, 1_000_000.0 + 1)[0] == 0


async def test_mongo_sink_defers_while_hot_and_catches_up():
    db = AsyncMongoMockClient()["t"]
    pm.install_sink(ps.MongoSink(lambda: db))
    pm.set_clock(lambda: 1_000_000.0 + 180)
    for i in range(80):                      # 80 ops in one second: above the 70% warn line of a 100 ops/s cap
        pm.COMMAND_LISTENER.started(type("E", (), {"command_name": "find", "command": {"find": "voters"},
                                                   "request_id": i})())
    pm.set_clock(lambda: 1_000_000.0 + 181)
    assert pm._hot()
    await pm.flush_once()
    assert await db.perf_minutes.count_documents({}) == 0 and pm.sink_status()["queued"] == 1


async def test_separate_mongo_sink_uses_zero_main_cluster_operations():
    main_db = CountingDB(AsyncMongoMockClient()["main"])
    other = AsyncMongoMockClient()

    class Holder:
        def __call__(self, url, **kw):
            Holder.kw = kw
            return other
    sink = ps.SeparateMongoSink("mongodb://x", "perfdb", client_factory=Holder())
    await sink.write(batch())
    assert main_db.total() == 0
    assert "event_listeners" not in Holder.kw and Holder.kw.get("maxPoolSize") == 2
    assert await other["perfdb"].perf_batches.count_documents({}) == 1


def test_gap_is_null_not_zero():
    rows = ps.gap_fill([batch(999_900)], 999_840, 999_960)
    by_t = {r["t"]: r for r in rows}
    assert by_t[999_840].get("ops") is None and by_t[999_900]["ops"] == 5


class Recorder(ps.Sink):
    name = "postgres"

    def __init__(self, fail=False):
        self.writes, self.fail, self.stored = [], fail, []

    async def write(self, b):
        if self.fail:
            raise TimeoutError("down")
        self.writes.append(b)

    async def read(self, s, e):
        return self.stored


def _op(i=0):
    pm.COMMAND_LISTENER.started(type("E", (), {"command_name": "find", "command": {"find": "voters"}, "request_id": i})())


async def test_postgres_sink_writes_on_every_tick_including_the_minute_in_progress():
    sink = Recorder()
    pm.install_sink(sink)
    pm.set_clock(lambda: 1_000_000.0 + 5)
    pm._stamp_collecting()
    _op()
    await pm.flush_once()
    pm.set_clock(lambda: 1_000_000.0 + 6)
    await pm.flush_once()
    assert len(sink.writes) == 2                       # one write per tick, not one per five minutes
    live = sink.writes[-1]["rows"][-1]
    assert live["t"] == pm._minute(1_000_006.0) and live["ops"] == 1


async def test_postgres_idle_minute_is_zero_not_a_gap():
    sink = Recorder()
    pm.install_sink(sink)
    pm._stamp_collecting()
    pm.set_clock(lambda: 1_000_000.0 + 5)
    await pm.flush_once()
    pm.set_clock(lambda: 1_000_000.0 + 125)            # two minutes later, nothing happened
    await pm.flush_once()
    rows = sink.writes[-1]["rows"]
    assert len(rows) >= 2 and all(r["ops"] == 0 for r in rows)


async def test_postgres_failed_tick_retries_only_finished_minutes():
    sink = Recorder(fail=True)
    pm.install_sink(sink)
    pm._stamp_collecting()
    pm.set_clock(lambda: 1_000_000.0 + 5)
    await pm.flush_once()
    assert pm.sink_status()["queued"] == 0             # a lone in-progress snapshot is dropped; the next second replaces it
    pm.set_clock(lambda: 1_000_000.0 + 70)             # a minute has finished
    await pm.flush_once()
    assert pm.sink_status()["queued"] == 1


async def test_postgres_first_tick_never_overwrites_the_previous_process_minutes():
    sink = Recorder()
    pm.install_sink(sink)
    pm._stamp_collecting()
    pm.set_clock(lambda: 1_000_000.0 + 5)
    await pm.flush_once()
    rows = sink.writes[0]["rows"]
    assert len(rows) == 1 and rows[0]["t"] == pm._minute(1_000_005.0)


async def test_mongo_cadence_is_unchanged():
    pm.install_sink(Recorder())
    pm._manager.sink.name = "mongo"
    assert pm._flush_interval({"persist_s": 300}) == 300
    pm._manager.sink.name = "postgres"
    assert pm._flush_interval({"persist_s": 300}) == 10 and pm._flush_interval({"persist_s": 0}) == 0   # Render-free default


async def test_postgres_24h_chart_fills_gaps_from_the_database():
    sink = Recorder()
    sink.stored = [{"_id": 999_900, "rows": [{"t": 999_900, "ops": 120, "reqs": 7, "http_p95": 12.0}]}]
    pm.install_sink(sink)
    data = await pm.timeseries_filled("24h")
    by_t = {p["t"]: p for p in data["points"]}
    assert by_t[999_900]["ops"] == 2.0 and by_t[999_900]["reqs"] == 7
    assert by_t[999_840]["ops"] is None                # a minute nobody recorded stays a gap
