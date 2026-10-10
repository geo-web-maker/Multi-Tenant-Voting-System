"""PERF-M1/M2/M3/M7: collector, listener, middleware, attribution, alert rules."""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient

import perf_metrics as pm
import perf_tiers as pt


class Ev(SimpleNamespace):
    pass


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("PERF_ENABLED", raising=False)
    pm.reset_for_tests()
    pm.set_clock(lambda: 1_000_000.0)
    yield
    pm.set_clock(None)
    pm.reset_for_tests()


def cmd(name, coll, rid=1, **extra):
    return Ev(command_name=name, command={name: coll, **extra}, request_id=rid)


def run(name, coll, rid=1, ms=3, **extra):
    L = pm.COMMAND_LISTENER
    L.started(cmd(name, coll, rid, **extra))
    L.succeeded(Ev(request_id=rid, duration_micros=ms * 1000))


def ops_now():
    """Total weighted operations in the last minute."""
    return pm._window_sum("ops", 60, 1_000_000.0 + 1)[0]


def test_weighting_counts_documents_in_a_batch():
    run("insert", "votes", documents=[{}] * 5)
    run("update", "voters", rid=2, updates=[{}] * 3)
    run("delete", "otps", rid=3, deletes=[{}] * 2)
    run("find", "voters", rid=4)
    assert ops_now() == 11  # 5 + 3 + 2 + 1


def test_housekeeping_and_self_collection_are_ignored():
    for i, n in enumerate(("hello", "ping", "isMaster", "saslStart", "endSessions")):
        run(n, 1, rid=i)
    run("insert", "perf_minutes", rid=9, documents=[{}])
    assert ops_now() == 0


def test_getmore_uses_collection_field_and_is_typed_separately():
    pm.COMMAND_LISTENER.started(Ev(command_name="getMore", command={"getMore": 7, "collection": "voters"}, request_id=1))
    pm.COMMAND_LISTENER.succeeded(Ev(request_id=1, duration_micros=1000))
    rows = {r["name"]: r["ops"] for r in pm.breakdown("collection")["rows"]}
    assert rows["voters"] == 1
    assert {r["name"] for r in pm.breakdown("op")["rows"]} == {"getMore"}


def test_listener_never_raises_on_garbage():
    pm.COMMAND_LISTENER.started(object())
    pm.COMMAND_LISTENER.succeeded(object())
    pm.COMMAND_LISTENER.failed(None)


def test_inflight_dict_is_capped():
    for i in range(pm._INFLIGHT_CAP + 50):
        pm.COMMAND_LISTENER.started(cmd("find", "voters", rid=i))
    assert len(pm._inflight_cmds) <= pm._INFLIGHT_CAP


def test_stale_slots_are_not_read_as_current():
    run("find", "voters")
    pm.set_clock(lambda: 1_000_000.0 + pm.SECONDS.N)      # one full lap later
    assert pm.SECONDS.value(int(1_000_000.0 + pm.SECONDS.N), "ops") in (0, None)


def test_threads_hammering_the_listener_lose_nothing():
    def work(base):
        for i in range(250):
            run("find", "voters", rid=base * 1000 + i)
    ts = [threading.Thread(target=work, args=(k,)) for k in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert ops_now() == 2000


def test_slow_commands_are_listed_without_filters():
    run("find", "voters", ms=400, filter={"student_id": "S123"})
    slow = pm.slow_commands()
    assert slow and slow[0]["collection"] == "voters"
    assert "S123" not in repr(slow)


def test_disabled_means_client_options_are_the_historical_ones(monkeypatch):
    monkeypatch.setenv("PERF_ENABLED", "false")
    assert pm.motor_kwargs() == {"maxPoolSize": 20, "minPoolSize": 1, "waitQueueTimeoutMS": 2500}
    monkeypatch.setenv("PERF_ENABLED", "true")
    assert "event_listeners" in pm.motor_kwargs()


async def _call(mw, path="/vote-bulk", status=200, boom=False):
    req = SimpleNamespace(url=SimpleNamespace(path=path), scope={"path": path}, state=SimpleNamespace(),
                          method="POST", headers={})

    async def nxt(_):
        if boom:
            raise RuntimeError("x")
        return SimpleNamespace(status_code=status)
    return await mw(req, nxt)


async def test_middleware_records_status_and_balances_inflight():
    await _call(pm.perf_middleware, status=429)
    with pytest.raises(RuntimeError):
        await _call(pm.perf_middleware, boom=True)
    assert pm._inflight == 0
    s = pm.summary()
    assert s["http"]["s429_1m"] >= 0 and s["http"]["in_flight"] == 0


async def test_lag_probe_sees_blocking_work():
    async def blocker():
        await asyncio.sleep(0.01)
        time.sleep(0.2)
    pm.set_clock(None)
    t = asyncio.create_task(blocker())
    lag = await pm.measure_lag_once(0.05)
    await t
    assert lag >= 100


async def test_attribution_inside_a_request_not_outside():
    from tenant_db import scoped_db_for
    db = AsyncMongoMockClient()["t"]
    tdb = scoped_db_for(db, "org1")
    await tdb.voters.find_one({})                     # outside a request: no holder
    holder = pm.begin_request()
    await tdb.voters.find_one({})
    await tdb.voters.insert_many([{"a": 1}, {"a": 2}])
    assert (holder.ops, holder.by_coll["voters"]) == (3, 3)
    pm.end_request(holder, route="/vote-bulk", status=200, ms=5, org="t1")
    rows = {r["name"]: r for r in pm.breakdown("route")["rows"]}
    assert rows["/vote-bulk"]["ops_per_request"] == 3


async def test_metrics_do_not_change_db_call_count():
    from tenant_db import scoped_db_for
    from tests.opcount import CountingDB

    async def burst():
        cdb = CountingDB(AsyncMongoMockClient()["t"])
        tdb = scoped_db_for(cdb, "o")
        h = pm.begin_request()
        await tdb.voters.find_one({})
        await tdb.voters.update_one({"a": 1}, {"$set": {"b": 1}}, upsert=True)
        pm.end_request(h, route="/x", status=200, ms=1, org=None)
        return cdb.total()
    on = await burst()
    pt.swap_saved({"paused": True})
    off = await burst()
    assert on == off == 2


def test_pause_makes_hooks_inert():
    pt.swap_saved({"paused": True})
    run("find", "voters")
    assert pm.begin_request() is None and ops_now() == 0


# ---- alert rules (pure) ---------------------------------------------------------------------
BASE = dict(capped=True, cap=100, warn_pct=70, crit_pct=90, ops_s=10, secs_above_warn=0, secs_above_crit=0,
            throttle_suspect=False, pool_waiting_secs=0, pool_timeouts=0, loop_lag_p95=5, http_p95=100,
            http_requests_1m=100, uptime_s=9999, election_open=False)


@pytest.mark.parametrize("over,kind", [
    ({"secs_above_warn": 10}, "ops_warn"),
    ({"secs_above_crit": 5}, "ops_critical"),
    ({"throttle_suspect": True}, "throttle_suspect"),
    ({"pool_waiting_secs": 10}, "pool_pressure"),
    ({"pool_timeouts": 1}, "pool_pressure"),
    ({"loop_lag_p95": 150}, "loop_lag"),
    ({"http_p95": 2000}, "latency"),
    ({"election_open": True, "uptime_s": 60}, "cold_start"),
])
def test_each_alert_rule_fires(over, kind):
    assert kind in {a["kind"] for a in pm.evaluate_perf_alerts({**BASE, **over})}


def test_alert_rules_do_not_fire_below_threshold():
    assert pm.evaluate_perf_alerts({**BASE, "secs_above_warn": 9, "secs_above_crit": 4, "http_p95": 2000,
                                    "http_requests_1m": 10}) == []


def test_uncapped_tier_has_no_percentage_alerts():
    kinds = {a["kind"] for a in pm.evaluate_perf_alerts(
        {**BASE, "capped": False, "cap": None, "secs_above_warn": 99, "secs_above_crit": 99,
         "throttle_suspect": True, "loop_lag_p95": 500})}
    assert kinds == {"loop_lag"}


def test_cooldown_and_cold_start_once_per_start():
    a = [{"kind": "ops_warn", "level": "warning", "message": "m"}]
    fired, last = pm.apply_cooldown(a, {}, 1000.0, "s1")
    assert fired
    assert not pm.apply_cooldown(a, last, 1000.0 + 60, "s1")[0]
    assert pm.apply_cooldown(a, last, 1000.0 + 601, "s1")[0]
    cs = [{"kind": "cold_start", "level": "warning", "message": "m"}]
    f1, l1 = pm.apply_cooldown(cs, {}, 1.0, "s1")
    assert f1 and not pm.apply_cooldown(cs, l1, 99999.0, "s1")[0]


@pytest.mark.parametrize("pct,expect", [(10, "ok"), (70, "busy"), (90, "critical")])
def test_gauge_status_follows_the_cap(pct, expect):
    assert pm.gauge_status({"cap_pct": pct}, {"ops_cap": 100, "warn_pct": 70, "crit_pct": 90}) == expect


def test_throttling_status_and_uncapped_status():
    assert pm.gauge_status({"cap_pct": 96, "throttle_suspect": True}, {"ops_cap": 100}) == "throttling"
    assert pm.gauge_status({"latency_ms": {"p95": 900}}, {"ops_cap": None}) == "critical"
