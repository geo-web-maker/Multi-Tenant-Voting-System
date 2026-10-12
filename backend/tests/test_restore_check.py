"""Full restore-test runs against a fake B2 and fake clusters (no network)."""
import hashlib
from datetime import datetime
import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

import backup
import restore_check
from tests._fakes import FakeDb, FakeClient, FakeS3, put_backup, CFG

pytestmark = pytest.mark.asyncio


class Rig:
    pass


async def _build(monkeypatch, *, keep=False, open_election=False, tamper=None, drop_from_live=False, bad_chain=False):
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://u:p@live.example/")
    monkeypatch.setenv("MONGO_DB_NAME", "live")
    monkeypatch.setenv("SECOND_MONGO_URL", "mongodb+srv://u:p@second.example/")
    monkeypatch.setenv("BACKUP_MAX_FULL_AGE_HOURS", "9999999")
    monkeypatch.setenv("RESTORE_TEST_KEEP_DATA", "true" if keep else "false")
    monkeypatch.delenv("RESTORE_TEST_DB_NAME", raising=False)
    live = FakeDb(AsyncMongoMockClient()["live"], {("h1", 1)})
    second = FakeClient(AsyncMongoMockClient(), {("h2", 1)})
    org = ObjectId(); tenant = str(org)
    await live.organizations.insert_one({"_id": org, "slug": "acme"})
    await live.settings.insert_one({"name": "election_config", "org_id": tenant, "is_open": open_election})
    # votes + checkpoint chain
    prev, events = "GENESIS", []
    for i in range(3):
        eid = ObjectId(); cast = datetime(2026, 10, 1, 9, 0, i)
        events.append({"_id": eid, "org_id": tenant, "candidate_id": "c", "cast_at": cast})
        prev = hashlib.sha256(f"{prev}|{eid}|c|{cast.isoformat()}".encode()).hexdigest()
    cp = {"_id": ObjectId(), "org_id": tenant, "from_id": None, "to_id": events[-1]["_id"],
          "chain_hash": "bad" if bad_chain else prev}
    live_events = events[:-1] if drop_from_live else events
    await live.vote_events.insert_many(live_events)
    s3 = FakeS3()
    put_backup(s3, f"routine/{tenant}/full-20261012T000000Z", tenant, tenant,
               {"vote_events": events, "audit_checkpoints": [cp], "voters": [{"_id": 1, "org_id": tenant}]},
               tamper=tamper)
    put_backup(s3, "routine/_global/full-20261012T000000Z", "_global", None, {"platform_settings": [{"_id": "g", "name": "x"}]})
    async def tenants(db): return [{"org_id": tenant, "slug": "acme"}]
    async def noalert(*a, **k): return None
    monkeypatch.setattr(backup, "list_tenants", tenants)
    monkeypatch.setattr(backup, "load_config", lambda: CFG)
    monkeypatch.setattr(backup, "make_client", lambda cfg: s3)
    async def no_cov(db): return []
    monkeypatch.setattr(backup, "coverage_audit", no_cov)
    monkeypatch.setattr(restore_check, "AsyncIOMotorClient", lambda *a, **k: second)
    monkeypatch.setattr(restore_check, "alert_critical", noalert)
    monkeypatch.setattr(restore_check, "alert_warning", noalert)
    r = Rig(); r.live, r.second, r.tenant = live, second, tenant
    return r


async def test_clean_run_passes_and_flushes_scratch_at_end(monkeypatch):
    r = await _build(monkeypatch)
    res = await restore_check.run_restore_test(r.live, "manual")
    assert res["status"] in {"passed", "warning"} and not res["failures"], res
    assert res["chain_verify"][0]["valid"] is True
    assert await r.second["restore_test"].list_collection_names() == []


async def test_keep_data_leaves_scratch_populated(monkeypatch):
    r = await _build(monkeypatch, keep=True)
    await restore_check.run_restore_test(r.live, "manual")
    assert await r.second["restore_test"].vote_events.count_documents({}) == 3


async def test_corrupted_backup_fails_the_run(monkeypatch):
    r = await _build(monkeypatch, tamper="checksum")
    res = await restore_check.run_restore_test(r.live, "manual")
    assert res["status"] == "failed"


async def test_vote_ids_missing_from_live_is_a_failure(monkeypatch):
    r = await _build(monkeypatch, drop_from_live=True)
    res = await restore_check.run_restore_test(r.live, "manual")
    assert res["status"] == "failed" and any("missing from live" in f["error"] for f in res["failures"])


async def test_invalid_chain_in_backup_is_a_failure(monkeypatch):
    r = await _build(monkeypatch, bad_chain=True)
    assert (await restore_check.run_restore_test(r.live, "manual"))["status"] == "failed"


async def test_scheduled_run_skips_while_election_open(monkeypatch):
    r = await _build(monkeypatch, open_election=True)
    res = await restore_check.run_restore_test(r.live, "schedule")
    assert res["status"] == "skipped"
    assert await r.second["restore_test"].list_collection_names() == []


async def test_manual_run_during_election_needs_confirmation(monkeypatch):
    r = await _build(monkeypatch, open_election=True)
    res = await restore_check.run_restore_test(r.live, "manual")
    assert res.get("requires_confirmation") is True


async def test_second_run_is_refused_while_one_is_running(monkeypatch):
    r = await _build(monkeypatch)
    async with restore_check._run_lock:
        res = await restore_check.run_restore_test(r.live, "manual")
    assert res["status"] == "warning" and "already running" in res["error"]


async def test_run_refused_when_scratch_cluster_is_live_cluster(monkeypatch):
    r = await _build(monkeypatch)
    monkeypatch.setenv("SECOND_MONGO_URL", "mongodb+srv://u:p@live.example/")
    with pytest.raises(restore_check.ScratchRefused):
        await restore_check.run_restore_test(r.live, "manual")


async def test_wrong_scratch_name_env_is_refused(monkeypatch):
    r = await _build(monkeypatch)
    monkeypatch.setenv("RESTORE_TEST_DB_NAME", "mirror")
    with pytest.raises(restore_check.ScratchRefused):
        await restore_check.run_restore_test(r.live, "manual")


async def test_live_id_lookup_is_chunked_and_owner_scoped(monkeypatch):
    monkeypatch.setattr(restore_check, "LIVE_ID_CHUNK", 3)
    db = AsyncMongoMockClient()["l"]
    await db.vote_events.insert_many([{"_id": i, "org_id": "o"} for i in range(10)] + [{"_id": 99, "org_id": "x"}])
    got = await restore_check._live_ids(db.vote_events, list(range(10)) + [99, 500], {"org_id": "o"})
    assert got == set(range(10))
