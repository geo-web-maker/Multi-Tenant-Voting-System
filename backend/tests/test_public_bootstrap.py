"""E1: GET /public/bootstrap = branding + status + positions, same shapes as the individual endpoints, tenant-safe."""
import pytest

from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def add_org(e, slug, name, position):
    org = await e.db.organizations.insert_one({"slug": slug, "name": name})
    oid = str(org.inserted_id)
    await e.db.settings.insert_one({"name": "branding", "org_id": oid, "org_name": name, "cc_list": ["secret@x.org"]})
    await e.db.positions.insert_one({"title": position, "org_id": oid, "order": 1})
    return oid


async def test_same_data_as_the_old_endpoints(env):
    await env.db.positions.insert_one({"title": "Guild President", "org_id": env.org_id, "order": 1})
    b = (await env.client.get("/public/bootstrap")).json()
    assert set(b) == {"branding", "status", "positions"}
    assert b["branding"] == (await env.client.get("/superadmin/branding")).json()
    assert b["status"] == (await env.client.get("/election-status")).json()
    assert b["positions"] == (await env.client.get("/positions")).json()
    assert [p["title"] for p in b["positions"]] == ["Guild President"]


async def test_old_endpoints_still_work(env):
    for path in ("/superadmin/branding", "/election-status", "/positions"):
        assert (await env.client.get(path)).status_code == 200


async def test_cross_tenant_never_leaks(env):
    await add_org(env, "t2", "Other Org", "SECRET-OTHER-POSITION")
    await env.db.positions.insert_one({"title": "Mine", "org_id": env.org_id, "order": 1})
    mine = await env.client.get("/public/bootstrap")
    assert "SECRET-OTHER-POSITION" not in mine.text and "Other Org" not in mine.text
    theirs = await env.client.get("/public/bootstrap", headers={"X-Org-Slug": "t2"})
    assert "SECRET-OTHER-POSITION" in theirs.text and "Mine" not in theirs.text
    assert theirs.json()["branding"]["org_name"] == "Other Org"


async def test_only_public_fields(env):
    await env.db.settings.update_one({"name": "branding", "org_id": env.org_id}, {"$set": {"cc_list": ["secret@x.org"]}})
    r = await env.client.get("/public/bootstrap")
    assert "secret@x.org" not in r.text and "cc_list" not in r.json()["branding"]
    assert "256700000001" not in r.text and "Comm One" not in r.text      # no voter data


async def test_unknown_org_rejected_and_headers(env):
    assert (await env.client.get("/public/bootstrap", headers={"X-Org-Slug": "nope"})).status_code in (400, 404)
    r = await env.client.get("/public/bootstrap")
    assert "X-Org-Slug" in r.headers["vary"] and "max-age=15" in r.headers["cache-control"]
    a = await env.client.get("/public/bootstrap", headers=env.sa)
    assert a.headers["cache-control"] == "no-store"
