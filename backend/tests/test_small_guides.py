"""Guides 07 (analytics flush interval), 10 (revoked-token cache) and 11 step 3 (boot index marker)."""
import pytest

import auth
import main
import analytics as a
from tests.opcount import CountingDB
from tests.test_analytics import FakeDb, ingest, pv
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


# ======================= guide 10: revoked-token cache =======================
@pytest.fixture
def revocation_on(monkeypatch):
    monkeypatch.setattr(auth, "_revocation_check", main._is_token_revoked)
    monkeypatch.setattr(main, "_REVOKED_TTL", 30.0)
    main._clear_revocation_cache()


def _lookups(cdb, snap):
    return sum(n for (c, _m), n in cdb.since(snap).items() if c == "revoked_tokens")


async def test_second_check_of_the_same_token_makes_no_query(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    assert await main._is_token_revoked("j1") is False
    s = cdb.snapshot()
    assert await main._is_token_revoked("j1") is False
    assert _lookups(cdb, s) == 0


async def test_logout_is_effective_at_once_even_after_a_cached_fine_answer(env, revocation_on):
    assert (await env.client.get("/admin/voters/stats", headers=env.sa)).status_code == 200     # caches "fine"
    assert (await env.client.post("/admin/logout", headers=env.sa)).status_code == 200
    assert (await env.client.get("/admin/voters/stats", headers=env.sa)).status_code == 401      # no 30 s wait


async def test_revoked_answer_needs_no_query_and_other_tokens_are_independent(env, monkeypatch):
    await main._revoke_jti("bad")
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    s = cdb.snapshot()
    assert await main._is_token_revoked("bad") is True
    assert _lookups(cdb, s) == 0
    assert await main._is_token_revoked("good") is False


async def test_fine_answer_expires_and_the_database_is_asked_again(env, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(main, "_REVOKED_TTL", 30.0)
    assert await main._is_token_revoked("j2") is False
    await env.db.revoked_tokens.insert_one({"jti": "j2"})                       # revoked elsewhere
    t[0] += 29
    assert await main._is_token_revoked("j2") is False                           # still inside the TTL
    t[0] += 2
    assert await main._is_token_revoked("j2") is True                            # re-checked


async def test_a_failed_lookup_is_never_cached_as_fine(env, monkeypatch):
    class Boom:
        async def find_one(self, *a, **k):
            raise RuntimeError("db down")
    class Db:
        revoked_tokens = Boom()
    monkeypatch.setattr(main, "db", Db())
    with pytest.raises(RuntimeError):
        await main._is_token_revoked("j3")
    assert "j3" not in main._NOT_REVOKED_UNTIL


async def test_a_failed_revoke_insert_remembers_nothing(env, monkeypatch):
    class Boom:
        async def insert_one(self, *a, **k):
            raise RuntimeError("db down")
    class Db:
        revoked_tokens = Boom()
    monkeypatch.setattr(main, "db", Db())
    with pytest.raises(RuntimeError):
        await main._revoke_jti("j4")
    assert "j4" not in main._REVOKED_LOCAL


async def test_cache_size_is_bounded(env, monkeypatch):
    monkeypatch.setattr(main, "_REVOKED_MAX_TRACKED", 50)
    for i in range(500):
        await main._is_token_revoked(f"x{i}")
    assert len(main._NOT_REVOKED_UNTIL) <= 50


async def test_ttl_zero_turns_off_the_fine_cache(env, monkeypatch):
    monkeypatch.setattr(main, "_REVOKED_TTL", 0.0)
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    await main._is_token_revoked("j5")
    s = cdb.snapshot()
    await main._is_token_revoked("j5")
    assert _lookups(cdb, s) == 1


# ======================= guide 07: analytics flush interval =======================
async def test_counters_wait_for_the_flush_interval_but_alerts_still_run(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    calls = {"alerts": 0, "trim": 0}

    async def fake_alerts():
        calls["alerts"] += 1
    monkeypatch.setattr(a, "_send_alerts", fake_alerts)
    monkeypatch.setattr(a, "_trim_minutes", lambda m: calls.__setitem__("trim", calls["trim"] + 1))
    t = [5000.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(a, "_FLUSH_S", 150.0)
    monkeypatch.setattr(a, "_last_db_flush", t[0])             # a flush just happened
    db = FakeDb(); a._db = db
    try:
        ingest([pv(first=False, ns=False)] * 5)
        for _ in range(4):                                      # four 30 s ticks: not due yet
            t[0] += 30
            await a._flush_once()
        assert not db.analytics_counters.ops
        assert calls == {"alerts": 4, "trim": 4}                # alert evaluation kept its 30 s cadence
        t[0] += 30                                              # 150 s since the last flush: due
        await a._flush_once()
        assert len(db.analytics_counters.ops) == 1
        assert not a._deltas
    finally:
        a._db = None


async def test_default_interval_flushes_on_every_tick(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    t = [9000.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(a, "_FLUSH_S", 30.0)
    monkeypatch.setattr(a, "_last_db_flush", t[0])
    db = FakeDb(); a._db = db
    try:
        for _ in range(3):
            ingest([pv(first=False, ns=False)] * 2)
            t[0] += 29.9                                        # a slightly early tick must still flush
            await a._flush_once()
        assert len(db.analytics_counters.ops) == 3
    finally:
        a._db = None


async def test_stop_flushes_even_when_the_interval_has_not_passed(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    monkeypatch.setattr(a, "_FLUSH_S", 3600.0)
    monkeypatch.setattr(a, "_last_db_flush", a.time.monotonic())
    db = FakeDb(); a._db = db
    try:
        ingest([pv(first=False, ns=False)] * 3)
        await a.stop()
        assert len(db.analytics_counters.ops) == 1
    finally:
        a._db = None


# ======================= guide 11 step 3: boot index marker =======================
async def test_marker_is_written_and_a_second_start_skips_index_creation(env, monkeypatch):
    assert await main._indexes_up_to_date() is False
    await main._mark_indexes_current()
    assert await main._indexes_up_to_date() is True
    doc = await env.db.app_meta.find_one({"_id": "index_schema"})
    assert doc["signature"] == main._index_signature()


async def test_a_changed_index_set_or_force_flag_recreates(env, monkeypatch):
    await main._mark_indexes_current()
    v = main.INDEX_SCHEMA_VERSION
    monkeypatch.setattr(main, "INDEX_SCHEMA_VERSION", v + 1)
    assert await main._indexes_up_to_date() is False                 # version bumped
    monkeypatch.setattr(main, "INDEX_SCHEMA_VERSION", v)
    assert await main._indexes_up_to_date() is True
    monkeypatch.setenv("FORCE_INDEX_SYNC", "1")
    assert await main._indexes_up_to_date() is False


async def test_perf_index_list_change_is_picked_up_automatically(env, monkeypatch):
    await main._mark_indexes_current()
    monkeypatch.setattr(main, "PERF_INDEXES", main.PERF_INDEXES + [("voters", [("x", 1)])])
    assert await main._indexes_up_to_date() is False


async def test_marker_is_not_tenant_data(env):
    await main._mark_indexes_current()
    assert await env.db.settings.count_documents({"name": "index_schema"}) == 0
    assert await env.db.app_meta.count_documents({"org_id": None}) in (0, 1)   # not in any legacy-checked collection
    assert "app_meta" not in main.LEGACY_TENANT_COLLECTIONS


async def test_index_creation_still_works_and_is_one_function(env):
    await main._create_startup_indexes()                             # mongomock accepts every index definition
    info = await env.db.otps.index_information()
    assert any(v["key"][0][0] == "created_at" for v in info.values())


async def test_analytics_start_can_skip_index_creation(monkeypatch):
    made = []

    class C:
        async def create_index(self, *a, **k):
            made.append(a)

    class Db:
        analytics_counters = C()
        analytics_heat = C()
    async def noop(db):
        return None
    monkeypatch.setattr(a, "_warm_caps", noop)
    monkeypatch.setattr(a, "_task", object())          # so no flusher task is started
    await a.start(Db(), create_indexes=False)
    assert made == []
    await a.start(Db())
    assert len(made) == 3
