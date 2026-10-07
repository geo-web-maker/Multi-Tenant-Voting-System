"""tenant_db: every operation on a scoped handle is confined to one tenant, and a missing tenant fails closed."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient
from pymongo import DeleteMany, InsertOne, UpdateOne

import tenant_db
from tenant_db import TenantScopeError, scoped_db, scoped_db_for

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db():
    d = AsyncMongoMockClient()["t"]
    await d.voters.insert_many([
        {"student_id": "a1", "org_id": "A", "n": 1},
        {"student_id": "a2", "org_id": "A", "n": 2},
        {"student_id": "b1", "org_id": "B", "n": 3},
    ])
    return d


def _req(org_id):
    return SimpleNamespace(state=SimpleNamespace(org_id=org_id))


# ---- creating a handle ------------------------------------------------------------------------
@pytest.mark.parametrize("missing", [None, ""])
async def test_handle_refuses_without_a_tenant(db, missing):
    with pytest.raises(HTTPException) as e:
        scoped_db(db, _req(missing))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        scoped_db_for(db, missing)


async def test_handle_refuses_request_without_org_attribute(db):
    with pytest.raises(HTTPException):
        scoped_db(db, SimpleNamespace(state=SimpleNamespace()))


async def test_non_tenant_collections_are_not_exposed(db):
    tdb = scoped_db_for(db, "A")
    for name in ("organizations", "revoked_tokens", "ip_rate_limits"):
        with pytest.raises(AttributeError):
            getattr(tdb, name)


async def test_ddl_is_not_exposed_on_a_tenant_collection(db):
    with pytest.raises(AttributeError):
        scoped_db_for(db, "A").voters.create_index("x")
    with pytest.raises(AttributeError):
        scoped_db_for(db, "A").voters.drop()


# ---- reads ------------------------------------------------------------------------------------
async def test_reads_only_see_own_tenant(db):
    a = scoped_db_for(db, "A")
    assert await a.voters.count_documents({}) == 2
    assert await a.voters.find_one({"student_id": "b1"}) is None
    assert {d["student_id"] async for d in a.voters.find({})} == {"a1", "a2"}
    assert await a.voters.find_one({"student_id": "a1"}, {"_id": 0, "n": 1}) == {"n": 1}
    assert sorted(await a.voters.distinct("student_id")) == ["a1", "a2"]


async def test_find_supports_chained_cursor_methods(db):
    a = scoped_db_for(db, "A")
    rows = await a.voters.find({}).sort("n", -1).limit(1).to_list(5)
    assert [r["student_id"] for r in rows] == ["a2"]


async def test_explicit_foreign_org_id_in_filter_is_refused_not_overridden(db):
    with pytest.raises(TenantScopeError):
        await scoped_db_for(db, "A").voters.find_one({"org_id": "B"})
    # naming your own tenant is fine
    assert await scoped_db_for(db, "A").voters.count_documents({"org_id": "A"}) == 2


async def test_aggregate_is_prefixed_with_tenant_match(db):
    a = scoped_db_for(db, "A")
    rows = [r async for r in a.voters.aggregate([{"$group": {"_id": None, "t": {"$sum": "$n"}}}])]
    assert rows == [{"_id": None, "t": 3}]


@pytest.mark.parametrize("stage", [{"$lookup": {}}, {"$unionWith": "x"}, {"$graphLookup": {}}, {"$out": "x"}, {"$merge": "x"}])
async def test_aggregate_refuses_cross_document_stages(db, stage):
    with pytest.raises(TenantScopeError):
        scoped_db_for(db, "A").voters.aggregate([stage])


# ---- writes -----------------------------------------------------------------------------------
async def test_insert_is_stamped_and_foreign_stamp_refused(db):
    a = scoped_db_for(db, "A")
    r = await a.voters.insert_one({"student_id": "a3"})
    assert (await db.voters.find_one({"_id": r.inserted_id}))["org_id"] == "A"
    with pytest.raises(TenantScopeError):
        await a.voters.insert_one({"student_id": "x", "org_id": "B"})
    await a.voters.insert_many([{"student_id": "a4"}, {"student_id": "a5"}])
    assert await db.voters.count_documents({"org_id": "A"}) == 5
    with pytest.raises(TenantScopeError):
        await a.voters.insert_many([{"student_id": "ok"}, {"student_id": "bad", "org_id": "B"}])


async def test_update_and_delete_cannot_touch_another_tenant(db):
    a = scoped_db_for(db, "A")
    r = await a.voters.update_one({"student_id": "b1"}, {"$set": {"n": 99}})
    assert r.matched_count == 0
    assert (await db.voters.find_one({"student_id": "b1"}))["n"] == 3
    r = await a.voters.update_many({}, {"$set": {"flag": True}})
    assert r.modified_count == 2
    assert await db.voters.count_documents({"flag": True, "org_id": "B"}) == 0
    assert (await a.voters.delete_one({"student_id": "b1"})).deleted_count == 0
    assert (await a.voters.delete_many({})).deleted_count == 2          # "{}" means "all of MY tenant"
    assert await db.voters.count_documents({"org_id": "B"}) == 1


async def test_update_cannot_move_a_document_to_another_tenant(db):
    a = scoped_db_for(db, "A")
    with pytest.raises(TenantScopeError):
        await a.voters.update_one({"student_id": "a1"}, {"$set": {"org_id": "B"}})
    with pytest.raises(TenantScopeError):
        await a.voters.update_one({"student_id": "a1"}, {"$unset": {"org_id": ""}})
    with pytest.raises(TenantScopeError):
        await a.voters.update_one({"student_id": "a1"}, [{"$set": {"org_id": "B"}}])


async def test_upsert_creates_in_own_tenant(db):
    a = scoped_db_for(db, "A")
    await a.voters.update_one({"student_id": "new"}, {"$set": {"n": 7}}, upsert=True)
    assert (await db.voters.find_one({"student_id": "new"}))["org_id"] == "A"


async def test_replace_and_find_one_and_x(db):
    a = scoped_db_for(db, "A")
    await a.voters.replace_one({"student_id": "a1"}, {"student_id": "a1", "n": 10})
    assert (await db.voters.find_one({"student_id": "a1"}))["org_id"] == "A"
    assert await a.voters.find_one_and_update({"student_id": "b1"}, {"$set": {"n": 0}}) is None
    assert await a.voters.find_one_and_delete({"student_id": "b1"}) is None
    assert (await db.voters.find_one({"student_id": "b1"}))["n"] == 3
    got = await a.voters.find_one_and_update({"student_id": "a2"}, {"$inc": {"n": 1}})
    assert got["student_id"] == "a2"


async def test_bulk_write_is_confined(db):
    a = scoped_db_for(db, "A")
    await a.voters.bulk_write([
        UpdateOne({"student_id": "b1"}, {"$set": {"n": 0}}),         # other tenant: matches nothing
        UpdateOne({"student_id": "a1"}, {"$set": {"n": 11}}),
        InsertOne({"student_id": "a9"}),
        DeleteMany({"student_id": "b1"}),
    ], ordered=False)
    assert (await db.voters.find_one({"student_id": "b1"}))["n"] == 3
    assert (await db.voters.find_one({"student_id": "a1"}))["n"] == 11
    assert (await db.voters.find_one({"student_id": "a9"}))["org_id"] == "A"
    with pytest.raises(TenantScopeError):
        await a.voters.bulk_write([InsertOne({"student_id": "z", "org_id": "B"})])


async def test_two_handles_do_not_interfere(db):
    a, b = scoped_db_for(db, "A"), scoped_db_for(db, "B")
    assert await a.voters.count_documents({}) == 2
    assert await b.voters.count_documents({}) == 1


async def test_cross_tenant_is_the_raw_db(db):
    assert tenant_db.cross_tenant(db) is db


# ---- end-to-end: the migrated routes really are confined -------------------------------------
from tests.test_flows import env  # noqa: E402,F401  (fixture)


async def test_admin_voter_list_never_shows_another_tenants_voters(env):
    other = await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    await env.db.voters.insert_many([
        {"student_id": "mine1", "full_name": "Mine One", "org_id": env.org_id, "phone_numbers": ["256700000001"]},
        {"student_id": "theirs1", "full_name": "Theirs One", "org_id": str(other.inserted_id), "phone_numbers": ["256700000002"]},
    ])
    r = await env.client.get("/admin/voters", headers=env.it)
    assert r.status_code == 200, r.text
    assert "theirs1" not in r.text and "Theirs One" not in r.text
    assert "mine1" in r.text


async def test_token_for_one_tenant_is_useless_on_another(env):
    other = await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    r = await env.client.get("/admin/voters", headers={**env.it, "X-Org-Slug": "t2"})
    assert r.status_code == 403
    # and a tenant-less request never reaches data at all
    r = await env.client.get("/admin/voters", headers={**env.it, "X-Org-Slug": ""})
    assert r.status_code in (400, 403)
