"""Performance tab: switch Site Usage storage between MongoDB and PostgreSQL, then migrate history."""
from __future__ import annotations

import pytest
import mongomock_motor

import analytics as a
import analytics_migration as mig
import analytics_store as ast
import main
from tests.test_analytics_store import FakeCon, FakePool
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_security_regressions import _FakeClient

pytestmark = pytest.mark.asyncio
URL = "postgres://user:s3cret@host.example/db?sslmode=require"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ANALYTICS_STORE", raising=False)
    monkeypatch.delenv("ANALYTICS_POSTGRES_URL", raising=False)
    monkeypatch.setattr(main, "client", _FakeClient())
    a._mode_override, a._switch_info, a._store = None, {}, None
    mig._state, mig._task = {"status": "idle"}, None
    yield
    a._mode_override, a._switch_info, a._store = None, {}, None
    mig._state, mig._task = {"status": "idle"}, None


def _pg(monkeypatch, fail=False):
    monkeypatch.setenv("ANALYTICS_POSTGRES_URL", URL)

    async def factory(url, **kw):
        if fail:
            raise RuntimeError(f"cannot connect to {url}")
        return FakePool(FakeCon())

    monkeypatch.setattr(a, "make_postgres_store_from_env", lambda: ast.PostgresAnalyticsStore(URL, pool_factory=factory))


async def test_cannot_switch_to_postgres_without_a_url():
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    with pytest.raises(ValueError, match="ANALYTICS_POSTGRES_URL is not set"):
        await a.switch_storage(db, "postgres", "root")
    assert a.storage_mode() == "mongo" and await db.platform_settings.find_one({"name": "analytics_storage"}) is None


async def test_unreachable_postgres_changes_nothing_and_never_leaks_the_password(monkeypatch):
    _pg(monkeypatch, fail=True)
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    with pytest.raises(ValueError) as e:
        await a.switch_storage(db, "postgres", "root")
    assert "s3cret" not in str(e.value) and "not ready" in str(e.value)
    assert a.storage_mode() == "mongo" and a._store is None


async def test_switch_saves_the_choice_and_routes_writes_to_postgres(monkeypatch):
    _pg(monkeypatch)
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    a._db = db
    status = await a.switch_storage(db, "postgres", "root")
    assert status["mode"] == "postgres" and status["chosen_in_app"] and status["switched_by"] == "root"
    assert "s3cret" not in str(status) and status["switch_day"]
    assert isinstance(a._analytics_store(db), ast.PostgresAnalyticsStore)
    saved = await db.platform_settings.find_one({"name": "analytics_storage"})
    assert saved["mode"] == "postgres"
    # After a restart the saved choice wins over the environment default.
    a._mode_override, a._switch_info, a._store = None, {}, None
    await a.load_storage_choice(db)
    assert a.storage_mode() == "postgres"


async def test_switch_back_to_mongo_and_same_mode_is_a_no_op(monkeypatch):
    _pg(monkeypatch)
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    a._db = db
    await a.switch_storage(db, "postgres", "root")
    await a.switch_storage(db, "mongo", "root")
    assert a.storage_mode() == "mongo" and a._store is None
    before = dict(a._switch_info)
    await a.switch_storage(db, "mongo", "root")
    assert a._switch_info == before
    with pytest.raises(ValueError):
        await a.switch_storage(db, "sqlite", "root")


class _Store(ast.PostgresAnalyticsStore):
    async def copy_history_batch(self, c, h):
        return {"counter_rows": 0, "heat_rows": 0, "skipped_documents": 0}

    async def counter_totals(self, *_a):
        return []

    async def heat_totals(self):
        return {}


async def test_migrate_needs_postgres_first():
    with pytest.raises(ValueError, match="Switch to PostgreSQL first"):
        mig.start_migration(mongomock_motor.AsyncMongoMockClient()["t"])


async def test_migration_runs_in_the_background_and_reports_the_result(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    a._mode_override, a._store = "postgres", _Store(URL)
    a._switch_info = {"switch_day": "2026-10-10"}
    mig.start_migration(db, pause=0)
    with pytest.raises(ValueError, match="already running"):
        mig.start_migration(db, pause=0)
    await mig._task
    st = mig.migration_state()
    assert st["status"] == "done" and st["cutoff"] == "2026-10-10" and st["counts"]["verify"] == "passed"
    assert (await db.platform_settings.find_one({"name": "analytics_migration"}))["result"]["status"] == "done"


async def test_failed_check_is_reported_as_failed(monkeypatch):
    class Bad(_Store):
        async def counter_totals(self, *_a):
            return [{"org_id": "o", "kind": "pv", "field": "n", "total": 5}]
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    a._mode_override, a._store = "postgres", Bad(URL)
    mig.start_migration(db, pause=0)
    await mig._task
    assert mig.migration_state()["status"] == "failed" and "differ" in mig.migration_state()["message"]


def url(tail=""):
    return f"/superadmin/performance/storage{tail}"


async def test_routes_are_superadmin_only_and_validate(env):
    for call in (lambda h: env.client.get(url(), headers=h), lambda h: env.client.put(url(), json={"mode": "mongo"}, headers=h),
                 lambda h: env.client.post(url("/migrate"), headers=h)):
        assert (await call({})).status_code in (401, 403)
        for role in (env.it, env.com1, env.over):
            assert (await call(role)).status_code in (401, 403)
    r = await env.client.get(url(), headers=env.sa)
    assert r.status_code == 200 and r.json()["mode"] == "mongo" and r.json()["migration"]["status"] == "idle"
    assert (await env.client.put(url(), json={"mode": "oracle"}, headers=env.sa)).status_code == 400
    bad = await env.client.put(url(), json={"mode": "postgres"}, headers=env.sa)
    assert bad.status_code == 400 and "ANALYTICS_POSTGRES_URL" in bad.json()["detail"]
    assert (await env.client.post(url("/migrate"), headers=env.sa)).status_code == 409


async def test_route_switch_then_migrate_end_to_end(env, monkeypatch):
    _pg(monkeypatch)
    monkeypatch.setattr(a, "_flush_once", lambda force=False: _noop())
    r = await env.client.put(url(), json={"mode": "postgres"}, headers=env.sa)
    assert r.status_code == 200 and r.json()["mode"] == "postgres"
    a._store = _Store(URL)
    monkeypatch.setattr(mig, "copy_history", _fast_copy)
    r = await env.client.post(url("/migrate"), headers=env.sa)
    assert r.status_code == 200 and r.json()["migration"]["status"] == "running"
    await mig._task
    assert (await env.client.get(url(), headers=env.sa)).json()["migration"]["status"] == "done"


async def _noop():
    return None


async def _fast_copy(db, store, cutoff, **kw):
    return 0, {"counter_docs": 1, "counter_rows": 4, "heat_docs": 0, "heat_rows": 0, "already_imported": 0, "verify": "passed", "mismatches": 0}
