"""Cutover readiness: baseline is ready; each blocking condition flips exactly its own check."""
from datetime import datetime, timedelta
import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

import backup
import backup_admin_routes as bar
import write_freeze

pytestmark = pytest.mark.asyncio


async def _baseline(monkeypatch, **o):
    db = AsyncMongoMockClient()["live"]
    now = datetime.utcnow()
    org = ObjectId(); oid = str(org)
    await db.organizations.insert_one({"_id": org, "slug": "acme"})
    await db.settings.insert_one({"name": "election_config", "org_id": oid, "is_open": o.get("open", False)})
    await db.backup_state.insert_one({"_id": oid, "last_full_at": now - o.get("full_age", timedelta(hours=2))})
    write_freeze.lift()
    if not o.get("no_freeze"):
        write_freeze.start(20)
    fz = datetime.utcnow()
    jobs = [
        {"kind": "b2_verify", "status": "passed", "started_at": now, "finished_at": now},
        {"kind": "restore_test", "status": o.get("restore", "passed"), "started_at": now, "finished_at": now},
        {"kind": "migration_final", "status": "passed", "started_at": fz + timedelta(seconds=1), "finished_at": fz + timedelta(seconds=5)},
        {"kind": "migration_verify", "status": "passed",
         "started_at": fz + timedelta(seconds=(1 if o.get("verify_early") else 10)), "finished_at": fz + timedelta(seconds=20)},
    ]
    await db.backup_jobs.insert_many(jobs)
    async def cov(d): return ["stray"] if o.get("uncovered") else []
    async def own(d): return {"safe": not o.get("ownerless"), "counts": {}}
    monkeypatch.setattr(backup, "coverage_audit", cov)
    monkeypatch.setattr(backup, "ownerless_preflight", own)
    status = o.get("live_status", "ok")
    conns = {"connections": [{"id": i, "status": (status if i == "live_mongo" else "ok")}
                             for i in ("live_mongo", "migration_target", "b2_backup_bucket", "postgres_history")]}
    mirror = {"enabled": True, "last_ok_at": now, "last_error": "x" if o.get("mirror_error") else None, "counts": []}
    return await bar._migration_state(db, conns, {}, mirror, {})


def _failed(res):
    return [c["name"] for c in res["checklist"] if not c["ok"]]


async def test_baseline_is_ready(monkeypatch):
    res = await _baseline(monkeypatch)
    assert res["ready"] is True and _failed(res) == []


@pytest.mark.parametrize("opts,fragment", [
    ({"open": True}, "No election open"),
    ({"live_status": "down"}, "probes healthy"),
    ({"full_age": timedelta(days=30)}, "Recent full backups"),
    ({"mirror_error": True}, "Mirror synced"),
    ({"restore": "failed"}, "Restore test passed"),
    ({"no_freeze": True}, "write freeze"),
    ({"verify_early": True}, "after final pass"),
    ({"uncovered": True}, "uncovered"),
    ({"ownerless": True}, "ownerless"),
])
async def test_each_condition_flips_the_pill(monkeypatch, opts, fragment):
    res = await _baseline(monkeypatch, **opts)
    failed = _failed(res)
    assert res["ready"] is False
    assert any(fragment.lower() in n.lower() for n in failed), failed
    write_freeze.lift()
