"""Mirror: disabled without env, refuses unsafe targets, incr/full/prune, fingerprint reset, 3-failure alert."""
import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

import backup_mirror
from tests._fakes import FakeDb, FakeClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://u:p@live.example/")
    monkeypatch.setenv("SECOND_MONGO_URL", "mongodb+srv://u:p@second.example/")
    monkeypatch.setenv("MIRROR_DB_NAME", "mirror")
    monkeypatch.setenv("MIRROR_ENABLED", "true")
    monkeypatch.setattr(backup_mirror, "PAUSE_S", 0)
    alerts = []
    async def crit(s, b): alerts.append(("crit", s, b))
    async def warn(s, b): alerts.append(("warn", s, b))
    monkeypatch.setattr(backup_mirror, "alert_critical", crit)
    monkeypatch.setattr(backup_mirror, "alert_warning", warn)
    return alerts


def _setup(monkeypatch, second_nodes=("h2",)):
    mongo = AsyncMongoMockClient()
    live = FakeDb(mongo["live"], {("h1", 1)})
    second = FakeClient(AsyncMongoMockClient(), {(n, 1) for n in second_nodes})
    monkeypatch.setattr(backup_mirror, "second_client", lambda: second)
    return live, second


async def test_disabled_without_second_url(monkeypatch, env):
    monkeypatch.delenv("SECOND_MONGO_URL")
    live, _ = _setup(monkeypatch)
    assert (await backup_mirror.sync_mirror(live, "full"))["status"] == "disabled"


async def test_refuses_same_host_and_never_raises(monkeypatch, env):
    monkeypatch.setenv("SECOND_MONGO_URL", "mongodb+srv://u:p@live.example/")
    live, second = _setup(monkeypatch)
    res = await backup_mirror.sync_mirror(live, "full")
    assert res["status"] == "failed" and "live cluster" in res["error"]
    assert await second["mirror"].list_collection_names() == []


async def test_refuses_shared_replica_nodes(monkeypatch, env):
    live, second = _setup(monkeypatch, second_nodes=("h1",))
    assert (await backup_mirror.sync_mirror(live, "full"))["status"] == "failed"
    assert await second["mirror"].list_collection_names() == []


async def test_bad_mirror_name_refused(monkeypatch, env):
    monkeypatch.setenv("MIRROR_DB_NAME", "restore_test")
    live, _ = _setup(monkeypatch)
    assert (await backup_mirror.sync_mirror(live, "full"))["status"] == "failed"


async def test_full_copy_then_prune_and_security_collections_never_copied(monkeypatch, env):
    live, second = _setup(monkeypatch)
    await live.voters.insert_many([{"_id": i, "org_id": "o"} for i in range(3)])
    await live.otps.insert_one({"_id": "x"})
    assert (await backup_mirror.sync_mirror(live, "full"))["status"] == "ok"
    m = second["mirror"]
    assert await m.voters.count_documents({}) == 3 and "otps" not in await m.list_collection_names()
    await live.voters.delete_one({"_id": 0})
    await backup_mirror.sync_mirror(live, "full")
    assert await m.voters.count_documents({}) == 2


async def test_incr_skips_unchanged_digest_and_picks_up_changes(monkeypatch, env):
    live, second = _setup(monkeypatch)
    await live.voters.insert_one({"_id": 1, "v": 1})
    await backup_mirror.sync_mirror(live, "full")
    await live.voters.update_one({"_id": 1}, {"$set": {"v": 2}})
    await backup_mirror.sync_mirror(live, "incr")
    assert (await second["mirror"].voters.find_one({"_id": 1}))["v"] == 2


async def test_append_only_incremental_uses_watermark(monkeypatch, env):
    live, second = _setup(monkeypatch)
    first = ObjectId()
    await live.vote_events.insert_one({"_id": first, "org_id": "o"})
    await backup_mirror.sync_mirror(live, "full")
    nxt = ObjectId()
    await live.vote_events.insert_one({"_id": nxt, "org_id": "o"})
    await backup_mirror.sync_mirror(live, "incr")
    assert await second["mirror"].vote_events.count_documents({}) == 2


async def test_changed_second_host_resets_digests_and_forces_full(monkeypatch, env):
    live, second = _setup(monkeypatch)
    await live.voters.insert_one({"_id": 1})
    await backup_mirror.sync_mirror(live, "full")
    state = await live.backup_meta.find_one({"_id": "mirror_state"})
    assert state["digests"] and state["second_host_fp"]
    monkeypatch.setenv("SECOND_MONGO_URL", "mongodb+srv://u:p@capetown.example/")
    res = await backup_mirror.sync_mirror(live, "incr")
    assert res["mode"] == "full"


async def test_three_consecutive_failures_alert_and_error_is_redacted(monkeypatch, env):
    alerts = env
    live, second = _setup(monkeypatch)
    def boom(): raise RuntimeError("cannot reach mongodb+srv://user:secret@second.example/ password=hunter2")
    monkeypatch.setattr(backup_mirror, "second_client", boom)
    for _ in range(3):
        res = await backup_mirror.sync_mirror(live, "incr")
    assert res["status"] == "failed" and "secret" not in res["error"] and "hunter2" not in res["error"]
    assert [a for a in alerts if a[0] == "crit"] and len([a for a in alerts if a[0] == "crit"]) == 1
