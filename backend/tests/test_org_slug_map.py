"""Audit S-10 / guide 02: unknown X-Org-Slug values must not cost a database op each."""
import asyncio

import pytest

import main
from tests.test_org_cache import FakeDb


@pytest.fixture
def fake(monkeypatch):
    db = FakeDb({"alpha": "id-a"})
    monkeypatch.setattr(main, "db", db)
    main._invalidate_org_cache()
    main._ORG_CACHE.clear()
    yield db
    main._invalidate_org_cache()
    main._ORG_CACHE.clear()


async def test_random_unknown_slugs_cost_one_query_in_total(fake):
    for i in range(200):
        assert await main._resolve_org_id(f"x{i}") is None
    assert fake.organizations.calls == 1


async def test_new_org_visible_right_after_invalidation(fake):
    assert await main._resolve_org_id("beta") is None
    fake.organizations.docs["beta"] = "id-b"
    main._invalidate_org_cache("beta")
    assert await main._resolve_org_id("beta") == "id-b"


async def test_concurrent_cold_requests_share_one_load(fake):
    res = await asyncio.gather(*[main._resolve_org_id("nope") for _ in range(30)])
    assert res == [None] * 30
    assert fake.organizations.calls == 1


async def test_truncated_map_falls_back_to_the_database(fake, monkeypatch):
    monkeypatch.setattr(main, "_ORG_SLUG_MAP_LIMIT", 1)
    fake.organizations.docs.update({"b": "id-b", "c": "id-c"})
    assert await main._resolve_org_id("c") == "id-c"  # not in the 1-entry map, found by find_one
    assert await main._resolve_org_id("zzz") is None
