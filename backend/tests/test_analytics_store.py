"""Guide 12 tests for the analytics Postgres store and safe rollback behavior."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os

import pytest
import mongomock_motor

import analytics as a
import analytics_store as ast
from tests.test_flows import env  # noqa: F401  (fixture)


class FakeCon:
    def __init__(self):
        self.calls = []
        self.imports = set()
        self.rows = []
        self.scalar = None
        self.fail_in_transaction = False

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        if self.fail_in_transaction and sql.startswith("DELETE FROM analytics_counter"):
            raise RuntimeError("simulated transaction failure")
        return "OK"

    async def executemany(self, sql, args):
        args = list(args)
        self.calls.append(("executemany", sql, args))
        if self.fail_in_transaction:
            raise RuntimeError("simulated transaction failure")

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.rows

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        if sql == ast.IMPORT_MARK:
            key = (args[0], args[1])
            if key in self.imports:
                return None
            self.imports.add(key)
            return args[1]
        return self.scalar

    @asynccontextmanager
    async def transaction(self):
        self.calls.append(("transaction_begin", "", ()))
        old_imports = set(self.imports)
        try:
            yield
            self.calls.append(("transaction_commit", "", ()))
        except Exception:
            self.imports = old_imports
            self.calls.append(("transaction_rollback", "", ()))
            raise


class FakePool:
    def __init__(self, con):
        self.con = con
        self.closed = False

    def acquire(self):
        pool = self

        class Acquire:
            async def __aenter__(self):
                return pool.con

            async def __aexit__(self, *args):
                return False

        return Acquire()

    async def close(self):
        self.closed = True


def pg_store(con=None, pooled=False):
    con = con or FakeCon()
    pool = FakePool(con)
    seen = {}

    async def factory(url, **kwargs):
        seen.update(kwargs)
        return pool

    store = ast.PostgresAnalyticsStore("postgresql://app:secret@example.test/analytics", pooled=pooled,
                                       pool_factory=factory)
    return store, con, pool, seen


def test_counter_rows_round_trip_to_the_same_mongo_document_shape():
    source = [{
        "org_id": "org-a", "day": "2026-10-10", "kind": "perf", "k1": "results", "k2": "",
        "device": "mobile", "seg": "public", "n": 3, "cold": 1, "l": {"2": 1, "3": 2},
        "c": {"1": 3}, "day_dt": datetime(2026, 10, 10, tzinfo=timezone.utc), "_id": "ignored",
    }]
    flat = [row for doc in source for row in ast.flatten_counter_document(doc)]
    rows = [dict(zip(ast.COUNTER_COLUMNS, row)) for row in flat]
    rebuilt = ast.counter_documents_from_rows(rows)
    assert len(rebuilt) == 1
    for key in ("org_id", "day", "kind", "k1", "k2", "device", "seg", "n", "cold", "l", "c"):
        assert rebuilt[0][key] == source[0][key]
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    assert a.build_summary(source, 7, now) == a.build_summary(rebuilt, 7, now)


def test_postgres_write_is_atomic_and_uses_add_for_counters_max_for_concurrency():
    async def scenario():
        store, con, _, _ = pg_store()
        await store.ensure_schema(create=True)
        deltas = {
            ("org-a", "2026-10-10", "pv", "results", "Chrome|Android", "mobile", "public"):
                {"n": 3, "l.2": 1},
            ("org-a", "2026-10-10", "conc", "", "", "all", "all"): {"m.4": 7},
        }
        heat = {("org-a", "results", "mobile", "public", "click", 3, 4): 2}
        await store.write(deltas, heat)
        operations = [call for call in con.calls if call[0] == "executemany"]
        assert any(call[1] == ast.COUNTER_ADD for call in operations)
        assert any(call[1] == ast.COUNTER_MAX for call in operations)
        assert any(call[1] == ast.HEAT_ADD for call in operations)
        assert any(call[0] == "transaction_begin" for call in con.calls)
        assert any(call[0] == "transaction_commit" for call in con.calls)
        add_rows = next(call[2] for call in operations if call[1] == ast.COUNTER_ADD)
        max_rows = next(call[2] for call in operations if call[1] == ast.COUNTER_MAX)
        assert any(row[-2:] == ("n", 3) for row in add_rows)
        assert any(row[-2:] == ("m.4", 7) for row in max_rows)
    import asyncio
    asyncio.run(scenario())


def test_pooled_neon_disables_statement_cache_and_pool_size_is_small():
    async def scenario():
        store, _, _, seen = pg_store(pooled=True)
        await store.ensure_schema(create=True)
        await store.write({("org-a", "2026-10-10", "pv", "results", "", "mobile", "public"): {"n": 1}}, {})
        assert seen["min_size"] == 1 and seen["max_size"] == 2
        assert seen["timeout"] == 5 and seen["command_timeout"] == 5
        assert seen["statement_cache_size"] == 0
    import asyncio
    asyncio.run(scenario())


def test_all_postgres_reads_are_org_scoped_and_reconstruct_dot_fields():
    async def scenario():
        con = FakeCon()
        con.rows = [{"org_id": "org-a", "day": "2026-10-10", "kind": "perf", "k1": "results",
                     "k2": "", "device": "mobile", "seg": "public", "field": "l.3", "n": 4}]
        store, _, _, _ = pg_store(con)
        await store.ensure_schema(create=True)
        docs = await store.fetch_counters(["org-a"], 7, "public", "mobile", datetime(2026, 10, 11, tzinfo=timezone.utc))
        sql, args = next((c[1], c[2]) for c in con.calls if c[0] == "fetch")
        assert "org_id = ANY($1::text[])" in sql and args[0] == ["org-a"]
        assert docs[0]["l"] == {"3": 4}
        await store.fetch_heat("org-a", "results", "mobile", "click", "public")
        heat_call = [c for c in con.calls if c[0] == "fetch"][-1]
        assert "org_id = $1" in heat_call[1] and heat_call[2][0] == "org-a"
        await store.first_day("org-a")
        since_call = [c for c in con.calls if c[0] == "fetchval"][-1]
        assert "WHERE org_id = $1" in since_call[1] and since_call[2] == ("org-a",)
    import asyncio
    asyncio.run(scenario())


def test_history_heat_import_ledger_prevents_double_add_on_retry():
    async def scenario():
        store, con, _, _ = pg_store()
        await store.ensure_schema(create=True)
        heat_doc = {"_id": "heat-1", "org_id": "org-a", "page": "results", "device": "mobile",
                    "seg": "public", "kind": "click", "gx": 2, "gy": 3, "n": 8}
        await store.copy_history_batch([], [heat_doc])
        await store.copy_history_batch([], [heat_doc])
        heat_upserts = [c for c in con.calls if c[0] == "execute" and c[1] == ast.HEAT_ADD]
        assert len(heat_upserts) == 1
    import asyncio
    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_analytics_flush_restores_whole_snapshot_and_caps_keys_when_store_is_down(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    monkeypatch.setenv("ANALYTICS_MAX_BUFFER_KEYS", "2")
    monkeypatch.setattr(a, "_deltas", {})
    monkeypatch.setattr(a, "_heat", __import__("collections").defaultdict(int))
    monkeypatch.setattr(a, "_flush_pending_keys", set())
    monkeypatch.setattr(a, "_last_db_flush", 0.0)
    a._db = object()
    monkeypatch.setattr(a, "_FLUSH_S", 1)

    class AlwaysDown:
        name = "postgres"
        async def write(self, deltas, heat):
            # A concurrent collect during the in-flight snapshot must not overrun the cap.
            a._inc(("org-a", "2026-10-11", "click", "new-page", "label", "mobile", "public"), {"n": 1})
            raise RuntimeError("connection failed")
        def safe_error(self, exc): return "connection failed"

    monkeypatch.setattr(a, "_analytics_store", lambda _db=None: AlwaysDown())
    a._inc(("org-a", "2026-10-11", "pv", "results", "", "mobile", "public"), {"n": 2})
    a._inc(("org-a", "2026-10-11", "click", "results", "menu", "mobile", "public"), {"n": 1})
    await a._flush_once(force=True)
    assert len(a._deltas) <= 2
    assert a._flush_pending_keys == set()
    assert any(v.get("n") == 2 for k, v in a._deltas.items() if k[2] == "pv")
    a._db = None


def test_environment_defaults_to_mongo_and_pool_import_is_lazy(monkeypatch):
    monkeypatch.delenv("ANALYTICS_STORE", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["analytics_test"]
    store = a._analytics_store(db)
    assert store.name == "mongo"
    assert isinstance(store, ast.MongoAnalyticsStore)


def test_mongo_store_purge_filters_both_collections_by_org():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["analytics_test"]
        store = ast.MongoAnalyticsStore(db, a._build_ops)
        await db.analytics_counters.insert_many([
            {"org_id": "org-a", "day": "2026-10-10", "kind": "pv"},
            {"org_id": "org-b", "day": "2026-10-10", "kind": "pv"},
        ])
        await db.analytics_heat.insert_many([
            {"org_id": "org-a", "page": "results", "kind": "click"},
            {"org_id": "org-b", "page": "results", "kind": "click"},
        ])
        await store.purge("org-a")
        assert await db.analytics_counters.count_documents({"org_id": "org-a"}) == 0
        assert await db.analytics_counters.count_documents({"org_id": "org-b"}) == 1
        assert await db.analytics_heat.count_documents({"org_id": "org-a"}) == 0
        assert await db.analytics_heat.count_documents({"org_id": "org-b"}) == 1
    import asyncio
    asyncio.run(scenario())


def test_retention_runs_on_first_empty_flush_and_only_once_per_utc_day():
    async def scenario():
        store, con, _, _ = pg_store()
        await store.ensure_schema(create=True)
        await store.write({}, {})
        deletes = [c for c in con.calls if c[0] == "execute" and c[1] == ast.RETENTION_DELETE]
        assert len(deletes) == 1
        await store.write({}, {})
        deletes = [c for c in con.calls if c[0] == "execute" and c[1] == ast.RETENTION_DELETE]
        assert len(deletes) == 1
    import asyncio
    asyncio.run(scenario())


# ---- Review fixes (2026-10-11) -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mongo_flush_has_no_timeout_so_a_slow_write_is_never_cancelled(monkeypatch):
    """A cancelled Mongo bulk_write can already have applied part of its $inc ops; only Postgres (one
    transaction) gets the 5 s timeout."""
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    monkeypatch.setenv("ANALYTICS_STORE", "mongo")
    monkeypatch.setattr(a, "_deltas", {})
    monkeypatch.setattr(a, "_heat", __import__("collections").defaultdict(int))
    monkeypatch.setattr(a, "_flush_pending_keys", set())
    monkeypatch.setattr(a, "_last_db_flush", 0.0)
    monkeypatch.setattr(a, "_FLUSH_S", 1)
    seen = []

    class SlowMongo:
        name = "mongo"
        async def write(self, deltas, heat):
            seen.append(len(deltas))

    async def forbidden(*args, **kwargs):
        raise AssertionError("asyncio.wait_for must not wrap a Mongo write")

    monkeypatch.setattr(a, "_analytics_store", lambda db=None: SlowMongo())
    monkeypatch.setattr(a.asyncio, "wait_for", forbidden)
    a._db = object()
    try:
        a._inc(("org-a", "2026-10-11", "click", "p", "l", "mobile", "public"), {"n": 1})
        await a._flush_once()
        assert seen == [1] and not a._deltas
    finally:
        a._db = None


def test_history_copy_adds_on_the_cutover_day_and_keeps_max_for_conc():
    async def scenario():
        store, con, _, _ = pg_store()
        await store.ensure_schema(create=True)
        docs = [
            {"_id": "c1", "org_id": "o", "day": "2026-10-20", "kind": "pv", "k1": "p", "k2": "x",
             "device": "all", "seg": "all", "n": 7},
            {"_id": "c2", "org_id": "o", "day": "2026-10-20", "kind": "conc", "k1": "x", "k2": "x",
             "device": "all", "seg": "all", "m": {"3": 9}},
        ]
        await store.copy_history_batch(docs, [])
        sqls = [c[1] for c in con.calls if c[0] == "executemany"]
        assert ast.COUNTER_ADD in sqls and ast.COUNTER_MAX in sqls and ast.COUNTER_COPY not in sqls
        # a retry applies nothing: the ledger already holds both documents
        before = len([c for c in con.calls if c[0] == "executemany"])
        await store.copy_history_batch(docs, [])
        assert len([c for c in con.calls if c[0] == "executemany"]) == before
    import asyncio
    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_postgres_read_failure_is_a_503_not_an_empty_dashboard(env, monkeypatch):
    class Down:
        name = "postgres"
        async def fetch_counters(self, *args, **kwargs):
            raise RuntimeError("neon is suspended")
        async def fetch_heat(self, *args, **kwargs):
            raise RuntimeError("neon is suspended")
        async def first_day(self, org_id):
            raise RuntimeError("neon is suspended")
        def safe_error(self, exc):
            return "neon is suspended"

    monkeypatch.setattr(a, "_analytics_store", lambda db=None: Down())
    for path in ("/superadmin/analytics/summary", "/superadmin/analytics/heatmap?page=results",
                 "/superadmin/analytics/compare?orgs=t1"):
        r = await env.client.get(path, headers=env.sa)
        assert r.status_code == 503, (path, r.status_code, r.text)
        assert "temporarily unavailable" in r.text
