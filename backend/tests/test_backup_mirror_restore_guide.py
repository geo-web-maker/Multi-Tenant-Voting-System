"""BK guide regression tests: coverage, guard rails, migration safety and chain consistency."""
import hashlib
from datetime import datetime

import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

import backup
import migrate_core
import restore_check
import tenant_db
import write_freeze

pytestmark = pytest.mark.asyncio


async def test_every_tenant_collection_is_backed_up_or_explicitly_excluded():
    covered = set(backup.FULL_COLLECTIONS) | set(backup.APPEND_ONLY) | set(backup.EXCLUDED_BY_DESIGN)
    # sms_usage is a tenant-specific application collection and uses org_key as its owner key.
    covered.add("sms_usage")
    assert tenant_db.TENANT_COLLECTIONS <= covered
    assert backup.collection_filter("sms_usage", "org-1") == {"org_key": "org-1"}
    assert backup.collection_filter("sms_usage", None) == {"org_key": "default"}
    assert backup.coverage_audit_names(["known_custom", "voters", "system.indexes"]) == ["known_custom"]


async def test_ownerless_preflight_counts_without_mutating_data():
    db = AsyncMongoMockClient()["test"]
    await db.panel_members.insert_many([{"org_id": "org-1"}, {"name": "unowned"}, {"org_id": None}])
    await db.roster_ledger.insert_one({"org_id": "org-1"})
    await db.sms_usage.insert_one({"org_key": "org-1"})
    result = await backup.ownerless_preflight(db)
    assert result["counts"]["panel_members"] == 2
    assert result["counts"]["roster_ledger"] == 0
    assert result["safe"] is False
    assert await db.panel_members.count_documents({}) == 3


async def test_restore_scratch_guards_reject_wrong_name_same_host_and_missing_url():
    with pytest.raises(restore_check.ScratchRefused, match="exactly"):
        restore_check.assert_scratch_safe("mongodb+srv://live.example", "live", "mongodb+srv://second.example", "mirror")
    with pytest.raises(restore_check.ScratchRefused, match="equals the live"):
        restore_check.assert_scratch_safe("mongodb+srv://live.example", "live", "mongodb+srv://live.example", "restore_test")
    with pytest.raises(restore_check.ScratchRefused, match="not set"):
        restore_check.assert_scratch_safe("mongodb+srv://live.example", "live", None, "restore_test")
    restore_check.assert_scratch_safe("mongodb+srv://live.example", "live", "mongodb+srv://second.example", "restore_test")


async def test_migration_refuses_reserved_scratch_database_before_copy():
    client = AsyncMongoMockClient()
    live = client["electiondbaccounting"]
    scratch = client["restore_test"]
    with pytest.raises(migrate_core.MigrationRefused, match="reserved"):
        await migrate_core.migrate_database(live, scratch, mode="copy")


async def test_migration_refuses_same_cluster_urls_without_writing():
    client = AsyncMongoMockClient()
    with pytest.raises(migrate_core.MigrationRefused, match="same cluster"):
        await migrate_core.assert_different_clusters(client["source"], client["target"],
            "mongodb+srv://same.example/source", "mongodb+srv://same.example/target")
    assert await client["target"].list_collection_names() == []


async def test_chain_verify_accepts_valid_chain_and_detects_tampering():
    db = AsyncMongoMockClient()["chain"]
    org_id = "org-1"
    event_id = ObjectId()
    cast_at = datetime(2026, 10, 12, 10, 0)
    base = f"GENESIS|{event_id}|candidate-a|{cast_at.isoformat()}"
    chain_hash = hashlib.sha256(base.encode()).hexdigest()
    await db.vote_events.insert_one({"_id": event_id, "org_id": org_id, "candidate_id": "candidate-a", "cast_at": cast_at})
    await db.audit_checkpoints.insert_one({"_id": ObjectId(), "org_id": org_id, "from_id": None, "to_id": event_id, "chain_hash": chain_hash})
    import chain_verify
    valid = await chain_verify.chain_verify_db(db, org_id)
    assert valid["valid"] is True and valid["head_hash"] == chain_hash
    await db.vote_events.update_one({"_id": event_id}, {"$set": {"candidate_id": "candidate-b"}})
    invalid = await chain_verify.chain_verify_db(db, org_id)
    assert invalid["valid"] is False


async def test_write_freeze_has_bounded_lifetime_and_keeps_backup_paths_exempt(monkeypatch):
    write_freeze.lift()
    clock = {"now": 100.0}
    monkeypatch.setattr(write_freeze.time, "monotonic", lambda: clock["now"])
    state = write_freeze.start(1)
    assert state["active"] is True
    assert write_freeze.path_exempt("/superadmin/backups/migration/run")
    assert write_freeze.path_exempt("/internal/backup/probe")
    assert not write_freeze.path_exempt("/vote")
    clock["now"] = 161.0
    assert write_freeze.active() is False
    write_freeze.lift()
