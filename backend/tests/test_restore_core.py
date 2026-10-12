"""restore_core: verification failures raise, ownership is enforced, merge and apply behave."""
import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

import restore_core
from tests._fakes import FakeS3, put_backup, CFG

pytestmark = pytest.mark.asyncio
ORG = "org-1"
T = "org-1"


def _docs(n, org=ORG):
    return [{"_id": ObjectId(), "org_id": org, "n": i} for i in range(n)]


async def test_good_backup_plans_and_applies_with_matching_counts():
    s3, voters = FakeS3(), _docs(3)
    put_backup(s3, f"routine/{T}/full-20261012T000000Z", T, ORG, {"voters": voters})
    org_id, merged = restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-20261012T000000Z")
    assert org_id == ORG and len(merged["voters"]) == 3
    db = AsyncMongoMockClient()["restore_test"]
    counts = await restore_core.apply_restore(db, org_id, merged, replace=True, tenant=T)
    assert counts == {"voters": 3} and await db.voters.count_documents({}) == 3


async def test_checksum_mismatch_raises_not_exits():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(2)}, tamper="checksum")
    with pytest.raises(restore_core.RestoreVerifyError, match="CHECKSUM"):
        restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-1")


async def test_count_mismatch_raises():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(2)}, tamper="count")
    with pytest.raises(restore_core.RestoreVerifyError, match="COUNT"):
        restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-1")


async def test_foreign_org_id_is_refused():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(1) + _docs(1, org="someone-else")})
    with pytest.raises(restore_core.RestoreVerifyError, match="Refusing"):
        restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-1")


async def test_tenant_mismatch_in_manifest_is_refused():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", "other", ORG, {"voters": _docs(1)})
    with pytest.raises(restore_core.RestoreVerifyError, match="tenant"):
        restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-1")


async def test_later_incremental_overwrites_by_id_and_until_excludes_newer():
    s3, v = FakeS3(), _docs(2)
    put_backup(s3, f"routine/{T}/full-20261001", T, ORG, {"voters": v})
    changed = dict(v[0], n=99)
    put_backup(s3, f"routine/{T}/incr-20261002", T, ORG, {"voters": [changed]}, kind="incr")
    _, merged = restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-20261001")
    assert merged["voters"][v[0]["_id"]]["n"] == 99
    _, early = restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-20261001", until="20261001")
    assert early["voters"][v[0]["_id"]]["n"] == 0


async def test_platform_settings_only_from_global_backup():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"platform_settings": [{"_id": "x"}]})
    with pytest.raises(restore_core.RestoreVerifyError, match="_global"):
        restore_core.plan_restore(s3, CFG, T, f"routine/{T}/full-1")


async def test_replace_only_deletes_this_tenants_rows():
    db = AsyncMongoMockClient()["restore_test"]
    await db.voters.insert_many([{"_id": 1, "org_id": ORG}, {"_id": 2, "org_id": "other"}])
    await restore_core.apply_restore(db, ORG, {"voters": {3: {"_id": 3, "org_id": ORG}}}, replace=True, tenant=T)
    ids = sorted([d["_id"] async for d in db.voters.find({})])
    assert ids == [2, 3]
