"""Phase 0: 60-second in-memory organisation lookup cache in main.py (behavioural tests)."""
import pytest

import main


class FakeOrgs:
    def __init__(self, docs):
        self.docs, self.calls = docs, 0

    async def find_one(self, query, projection=None):
        self.calls += 1
        oid = self.docs.get(query["slug"])
        return {"_id": oid} if oid else None


class FakeDb:
    def __init__(self, docs):
        self.organizations = FakeOrgs(docs)


@pytest.fixture
def fake(monkeypatch):
    db = FakeDb({"alpha": "id-a", "beta": "id-b"})
    monkeypatch.setattr(main, "db", db)
    main._ORG_CACHE.clear()
    yield db
    main._ORG_CACHE.clear()


async def test_repeat_lookup_hits_cache(fake):
    assert await main._resolve_org_id("alpha") == "id-a"
    assert await main._resolve_org_id("alpha") == "id-a"
    assert fake.organizations.calls == 1


async def test_unknown_slug_is_never_cached(fake):
    assert await main._resolve_org_id("nope") is None
    assert await main._resolve_org_id("nope") is None
    assert fake.organizations.calls == 2
    assert "nope" not in main._ORG_CACHE


async def test_expiry_requeries(fake, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    await main._resolve_org_id("alpha")
    clock[0] += main.ORG_CACHE_TTL_S - 1
    await main._resolve_org_id("alpha")
    assert fake.organizations.calls == 1
    clock[0] += 2
    await main._resolve_org_id("alpha")
    assert fake.organizations.calls == 2


async def test_cache_is_bounded_to_200(fake):
    fake.organizations.docs.update({f"o{i}": f"id{i}" for i in range(260)})
    for i in range(260):
        await main._resolve_org_id(f"o{i}")
    assert len(main._ORG_CACHE) <= 200


async def test_invalidation_and_reverse_lookup(fake):
    await main._resolve_org_id("alpha")
    await main._resolve_org_id("beta")
    assert main._org_slug_for_id("id-a") == "alpha"
    main._invalidate_org_cache("alpha")
    assert main._org_slug_for_id("id-a") is None
    assert main._org_slug_for_id("id-b") == "beta"
    main._invalidate_org_cache()
    assert main._ORG_CACHE == {}
