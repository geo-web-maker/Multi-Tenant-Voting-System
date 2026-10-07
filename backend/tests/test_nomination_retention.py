"""Regression: submitted nomination forms must stay readable indefinitely; only stale *pending* uploads are swept,
and sweeping removes the private file too. (A TTL index on created_at used to delete attached records after 24h.)"""
from datetime import datetime, timedelta

import pytest

import main
import nomination_storage
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_nomination_upload import apply, enable, position, store, upload  # noqa: F401
from tests.test_nomination_readback import signer, submitted, url  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def deleted(monkeypatch):
    keys = []
    monkeypatch.setattr(nomination_storage, "delete_object", lambda key: keys.append(key))
    return keys


async def test_no_ttl_index_on_nomination_uploads_is_created_by_code():
    import inspect
    src = inspect.getsource(main.lifespan)
    assert 'nomination_uploads.create_index("created_at", expireAfterSeconds' not in src


async def test_attached_upload_survives_the_sweep_and_stays_readable(env, store, signer, deleted):
    await env.seed_panel()
    app_id, key = await submitted(env, store)
    old = datetime.utcnow() - timedelta(days=30)
    await env.db.nomination_uploads.update_many({}, {"$set": {"created_at": old, "uploaded_at": old}})
    assert await main._sweep_stale_nomination_uploads(main.tdb_for(env.org_id)) == 0
    assert deleted == []
    r = await env.client.get(url(app_id), headers=env.pan1)
    assert r.status_code == 200, r.text


async def test_stale_pending_upload_is_swept_with_its_file(env, store, deleted):
    await enable(env)
    await position(env)
    up = (await upload(env)).json()
    old = datetime.utcnow() - timedelta(hours=25)
    await env.db.nomination_uploads.update_one({"upload_id": up["upload_id"]}, {"$set": {"created_at": old}})
    assert await main._sweep_stale_nomination_uploads(main.tdb_for(env.org_id)) == 1
    assert deleted == [f"nomination-forms/{env.org_id}/{up['upload_id']}.pdf"]
    assert await env.db.nomination_uploads.count_documents({}) == 0


async def test_fresh_pending_upload_is_kept(env, store, deleted):
    await enable(env)
    await position(env)
    await upload(env)
    assert await main._sweep_stale_nomination_uploads(main.tdb_for(env.org_id)) == 0
    assert await env.db.nomination_uploads.count_documents({}) == 1


async def test_demo_reset_deletes_private_files_of_demo_uploads(env, store, deleted):
    await env.db.nomination_uploads.insert_one({"org_id": env.org_id, "upload_id": "u1", "key": "nomination-forms/x/u1.pdf",
                                                "is_demo": True, "status": "attached"})
    await main._demo_fenced_reset(env.org_id, {})
    assert deleted == ["nomination-forms/x/u1.pdf"]
