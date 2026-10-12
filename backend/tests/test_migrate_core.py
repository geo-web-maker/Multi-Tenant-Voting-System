"""migrate_core: copy+verify, idempotence, final-pass deletes, security skip, wrong-direction refusal."""
import pytest
from mongomock_motor import AsyncMongoMockClient

import migrate_core

pytestmark = pytest.mark.asyncio
REAL_PROBE = migrate_core.assert_different_clusters   # captured before the autouse fixture replaces it


@pytest.fixture(autouse=True)
def _no_cluster_probe(monkeypatch):
    async def ok(*a, **k):
        return None
    monkeypatch.setattr(migrate_core, "assert_different_clusters", ok)
    monkeypatch.setattr(migrate_core, "PAUSE_S", 0)


async def _pair():
    c = AsyncMongoMockClient()
    src, dst = c["live_src"], c["live_dst"]
    await src.voters.insert_many([{"_id": i, "org_id": "o", "v": i} for i in range(5)])
    await src.otps.insert_one({"_id": "s", "code": "123"})
    return src, dst


async def test_plan_writes_nothing():
    src, dst = await _pair()
    r = await migrate_core.migrate_database(src, dst, mode="plan")
    assert r["status"] == "planned" and await dst.list_collection_names() == []


async def test_copy_verifies_skips_security_and_is_rerunnable():
    src, dst = await _pair()
    events = []
    r = await migrate_core.migrate_database(src, dst, mode="copy", progress=lambda p: events.append(p))
    assert r["status"] == "passed" and await dst.voters.count_documents({}) == 5
    assert await dst.otps.count_documents({}) == 0
    assert any(e.get("phase") == "verified" for e in events)
    assert (await migrate_core.migrate_database(src, dst, mode="copy"))["status"] == "passed"


async def test_include_security_copies_security_collections():
    src, dst = await _pair()
    await migrate_core.migrate_database(src, dst, mode="copy", include_security=True)
    assert await dst.otps.count_documents({}) == 1


async def test_verify_detects_a_changed_document():
    src, dst = await _pair()
    await migrate_core.migrate_database(src, dst, mode="copy")
    await dst.voters.update_one({"_id": 1}, {"$set": {"v": 999}})
    r = await migrate_core.migrate_database(src, dst, mode="verify")
    assert r["status"] == "failed" and r["mismatches"] == ["voters"]


async def test_final_removes_rows_deleted_at_source_but_copy_does_not():
    src, dst = await _pair()
    await migrate_core.migrate_database(src, dst, mode="copy")
    await src.voters.delete_one({"_id": 0})
    with pytest.raises(migrate_core.MigrationRefused):   # plain copy never deletes: target now has MORE rows
        await migrate_core.migrate_database(src, dst, mode="copy")
    r = await migrate_core.migrate_database(src, dst, mode="final")
    assert r["status"] == "passed" and await dst.voters.count_documents({"_id": 0}) == 0


async def test_wrong_direction_is_refused_without_force():
    src, dst = await _pair()
    await dst.voters.insert_many([{"_id": 100 + i} for i in range(10)])
    with pytest.raises(migrate_core.MigrationRefused, match="MORE documents"):
        await migrate_core.migrate_database(src, dst, mode="copy")
    assert await dst.voters.count_documents({}) == 10


async def test_same_cluster_probe_refuses_shared_nodes(monkeypatch):
    from tests._fakes import FakeDb
    real = REAL_PROBE
    c = AsyncMongoMockClient()
    a, b = FakeDb(c["a"], {("h1", 27017)}), FakeDb(c["b"], {("h1", 27017)})
    with pytest.raises(migrate_core.MigrationRefused, match="share"):
        await real(a, b)
    ok = FakeDb(c["b"], {("h2", 27017)})
    await real(a, ok)
