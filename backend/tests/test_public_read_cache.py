"""Guide 04: server-side cache for the public reads (branding, /payment-info, /election-roadmap, /positions).
conftest turns every cache off, so each test opts in. A hit must cost no database call, every write path must
invalidate, and one tenant must never see another's cached data."""
import pytest

import main
from tests.opcount import CountingDB, FakeClient
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def caches_on(monkeypatch):
    monkeypatch.setattr(main, "_SETTINGS_TTL", 5.0)
    monkeypatch.setattr(main, "_POSITIONS_TTL", 5.0)
    main.invalidate_settings()
    yield
    main.invalidate_settings()


@pytest.fixture
def counted(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    monkeypatch.setattr(main, "client", FakeClient())
    return cdb


def _reads(cdb, snap, coll):
    return sum(n for (c, _m), n in cdb.since(snap).items() if c == coll)


async def _second_call_is_free(env, counted, path, coll, headers=None):
    first = await env.client.get(path, headers=headers or {})
    assert first.status_code == 200, first.text
    snap = counted.snapshot()
    second = await env.client.get(path, headers=headers or {})
    assert second.json() == first.json()
    assert _reads(counted, snap, coll) == 0, counted.since(snap)


# ---- a hit costs no query ------------------------------------------------------------------------
async def test_branding_hit_costs_no_settings_read(env, counted, caches_on):
    await _second_call_is_free(env, counted, "/superadmin/branding", "settings")


async def test_payment_info_hit_costs_no_settings_read(env, counted, caches_on):
    await _second_call_is_free(env, counted, "/payment-info", "settings")


async def test_roadmap_hit_costs_no_settings_read(env, counted, caches_on):
    await _second_call_is_free(env, counted, "/election-roadmap", "settings")


async def test_positions_hit_costs_no_positions_read(env, counted, caches_on):
    await env.db.positions.insert_one({"title": "President", "org_id": env.org_id, "order": 1})
    await _second_call_is_free(env, counted, "/positions", "positions")


async def test_bootstrap_hit_costs_no_settings_or_positions_read(env, counted, caches_on):
    await env.client.get("/public/bootstrap")
    snap = counted.snapshot()
    assert (await env.client.get("/public/bootstrap")).status_code == 200
    assert _reads(counted, snap, "settings") == 0 and _reads(counted, snap, "positions") == 0, counted.since(snap)


# ---- every write shows at once -------------------------------------------------------------------
async def test_position_writes_show_at_once(env, caches_on):
    assert (await env.client.get("/positions")).json() == []                       # primes the (empty) cache
    r = await env.client.post("/positions", headers=env.sa, json={"title": "Chair", "order": 1})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert [p["title"] for p in (await env.client.get("/positions")).json()] == ["Chair"]
    r = await env.client.patch(f"/positions/{pid}", headers=env.sa, json={"title": "Chairperson"})
    assert r.status_code == 200, r.text
    assert [p["title"] for p in (await env.client.get("/positions")).json()] == ["Chairperson"]
    assert (await env.client.delete(f"/positions/{pid}", headers=env.sa)).status_code == 200
    assert (await env.client.get("/positions")).json() == []


async def test_payment_put_shows_at_once(env, caches_on):
    assert (await env.client.get("/payment-info")).json()["mobile_money_number"] == ""     # primes the cache
    r = await env.client.put("/superadmin/payment-info", headers=env.sa, json={
        "reason": "initial setup", "mobile_money_number": "0772123456", "mobile_money_name": "Guild"})
    assert r.status_code == 200, r.text
    assert (await env.client.get("/payment-info")).json()["mobile_money_number"] == "256772123456"


async def test_payment_put_with_a_stale_cache_still_saves_and_audits_the_true_old_value(env, caches_on):
    """Audit S-04: the PUT must compare against the database, not the cache."""
    await env.db.settings.insert_one({"name": "payment_info", "org_id": env.org_id,
                                      "mobile_money_number": "256772000000", "mobile_money_name": "Old"})
    assert (await env.client.get("/payment-info")).json()["mobile_money_name"] == "Old"   # cache now holds Old
    # Changed behind the cache's back (another instance, a script): the cache is stale.
    await env.db.settings.update_one({"name": "payment_info", "org_id": env.org_id},
                                     {"$set": {"mobile_money_number": "256772111111", "mobile_money_name": "Real"}})
    r = await env.client.put("/superadmin/payment-info", headers=env.sa, json={
        "reason": "set back to old", "mobile_money_number": "256772000000", "mobile_money_name": "Old"})
    assert r.status_code == 200, r.text                           # not rejected as "Nothing to change"
    stored = await env.db.settings.find_one({"name": "payment_info", "org_id": env.org_id})
    assert stored["mobile_money_name"] == "Old"
    log = await env.db.audit_log.find_one({"action": "payment_info_changed"})
    assert log["details"]["old"]["mobile_money_name"] == "Real"


async def test_roadmap_post_shows_at_once(env, caches_on):
    assert (await env.client.get("/election-roadmap")).json()["milestones"] == []          # primes the cache
    r = await env.client.post("/admin/roadmap", headers=env.sa, json={
        "milestones": [{"start_date": "2026-10-01", "activities": ["Nominations open"]}], "week_start_day": 1})
    assert r.status_code == 200, r.text
    got = (await env.client.get("/election-roadmap")).json()
    assert [m["activities"] for m in got["milestones"]] == [["Nominations open"]]


async def test_branding_save_shows_at_once(env, caches_on):
    assert (await env.client.get("/superadmin/branding")).json()["org_name"] != "Cached Name Test"
    full = (await env.client.get("/superadmin/branding-full", headers=env.sa)).json()
    full["org_name"] = "Cached Name Test"
    r = await env.client.post("/superadmin/branding", headers=env.sa, json=full)
    assert r.status_code == 200, r.text
    assert (await env.client.get("/superadmin/branding")).json()["org_name"] == "Cached Name Test"


# ---- safety --------------------------------------------------------------------------------------
async def test_tenants_never_share_cached_public_reads(env, caches_on):
    org = await env.db.organizations.insert_one({"slug": "t2", "name": "Other"})
    oid = str(org.inserted_id)
    await env.db.positions.insert_one({"title": "MINE", "org_id": env.org_id, "order": 1})
    await env.db.positions.insert_one({"title": "THEIRS", "org_id": oid, "order": 1})
    await env.db.settings.insert_one({"name": "payment_info", "org_id": oid,
                                      "mobile_money_number": "256700999999", "mobile_money_name": "Theirs"})
    for _ in range(2):                                              # second round is served from the cache
        mine = await env.client.get("/positions")
        theirs = await env.client.get("/positions", headers={"X-Org-Slug": "t2"})
        assert [p["title"] for p in mine.json()] == ["MINE"]
        assert [p["title"] for p in theirs.json()] == ["THEIRS"]
        assert (await env.client.get("/payment-info")).json()["mobile_money_number"] == ""
        assert (await env.client.get("/payment-info", headers={"X-Org-Slug": "t2"})).json()["mobile_money_number"] == "256700999999"


async def test_callers_cannot_poison_the_positions_cache(env, caches_on):
    await env.db.positions.insert_one({"title": "President", "org_id": env.org_id, "order": 1})
    await main.get_positions(_FakeReq(env.org_id), _FakeResp())
    got = await main.get_positions(_FakeReq(env.org_id), _FakeResp())
    got[0]["title"] = "tampered"
    again = await main.get_positions(_FakeReq(env.org_id), _FakeResp())
    assert again[0]["title"] == "President"


async def test_a_fake_authorization_header_does_not_skip_the_cache(env, counted, caches_on):
    """The header is not verified on this public route, so honouring it would hand a flood a way round the cache."""
    await env.db.positions.insert_one({"title": "President", "org_id": env.org_id, "order": 1})
    h = {"Authorization": "Bearer not-a-real-token"}
    await env.client.get("/positions", headers=h)
    snap = counted.snapshot()
    await env.client.get("/positions", headers=h)
    assert _reads(counted, snap, "positions") == 0


async def test_broad_invalidation_clears_positions_too(env, caches_on):
    await env.db.positions.insert_one({"title": "A", "org_id": env.org_id, "order": 1})
    assert len((await env.client.get("/positions")).json()) == 1
    await env.db.positions.insert_one({"title": "B", "org_id": env.org_id, "order": 2})   # behind the cache's back
    assert len((await env.client.get("/positions")).json()) == 1
    main.invalidate_settings(env.org_id)                                                   # e.g. demo reset
    assert len((await env.client.get("/positions")).json()) == 2


async def test_ttl_zero_turns_the_positions_cache_off(env, monkeypatch):
    monkeypatch.setattr(main, "_POSITIONS_TTL", 0.0)
    await env.db.positions.insert_one({"title": "A", "org_id": env.org_id, "order": 1})
    assert len((await env.client.get("/positions")).json()) == 1
    await env.db.positions.insert_one({"title": "B", "org_id": env.org_id, "order": 2})
    assert len((await env.client.get("/positions")).json()) == 2


class _FakeReq:
    def __init__(self, org_id):
        self.state = type("S", (), {"org_id": org_id})()
        self.headers = {}

    async def _db(self):  # pragma: no cover
        raise AssertionError("not used")


class _FakeResp:
    def __init__(self):
        self.headers = {}
