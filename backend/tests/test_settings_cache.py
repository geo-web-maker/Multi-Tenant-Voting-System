"""Guide 3.4: short-TTL settings cache. Must be fast, must be invalidated on writes, and must NEVER leak
one tenant's settings to another."""
import pytest

import main
from tests.test_flows import env  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cache_on(monkeypatch):
    monkeypatch.setattr(main, "_SETTINGS_TTL", 5.0)
    main.invalidate_settings()
    yield
    main.invalidate_settings()


async def test_second_read_is_served_from_cache(env, cache_on):
    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_open": True})
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is True
    await env.db.settings.update_one({"name": "election_config", "org_id": env.org_id}, {"$set": {"is_open": False}})
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is True      # still cached
    main.invalidate_settings(env.org_id)
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is False     # refreshed


async def test_ttl_expiry_refreshes(env, cache_on, monkeypatch):
    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_open": True})
    t = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: t[0])
    await main.cached_setting(env.org_id, "election_config")
    await env.db.settings.update_one({"name": "election_config", "org_id": env.org_id}, {"$set": {"is_open": False}})
    t[0] += 4.9
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is True
    t[0] += 0.2
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is False


async def test_missing_doc_is_cached_too_and_returns_none(env, cache_on):
    assert await main.cached_setting(env.org_id, "election_config") is None
    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_open": False})
    assert await main.cached_setting(env.org_id, "election_config") is None                   # negative result cached briefly
    main.invalidate_settings(env.org_id)
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is False


async def test_tenants_never_share_cache_entries(env, cache_on):
    await env.db.settings.insert_one({"name": "election_config", "org_id": "orgA", "is_open": True})
    await env.db.settings.insert_one({"name": "election_config", "org_id": "orgB", "is_open": False})
    assert (await main.cached_setting("orgA", "election_config"))["is_open"] is True
    assert (await main.cached_setting("orgB", "election_config"))["is_open"] is False
    main.invalidate_settings("orgA")                                                          # only A is dropped
    await env.db.settings.update_one({"org_id": "orgB", "name": "election_config"}, {"$set": {"is_open": True}})
    assert (await main.cached_setting("orgB", "election_config"))["is_open"] is False         # B untouched


async def test_callers_cannot_poison_the_cache(env, cache_on):
    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_open": True})
    d = await main.cached_setting(env.org_id, "election_config")
    d["is_open"] = "tampered"
    assert (await main.cached_setting(env.org_id, "election_config"))["is_open"] is True


async def test_admin_toggle_is_visible_immediately_despite_cache(env, cache_on):
    r = await env.client.get("/election-status")
    assert r.json()["is_open"] is True                                                        # primes the cache
    t = await env.client.post("/admin/toggle-election", json={}, headers=env.sa)
    assert t.status_code == 200, t.text
    assert (await env.client.get("/election-status")).json()["is_open"] is False              # write invalidated it


async def test_security_settings_write_invalidates(env, cache_on):
    class _Req:                       # the minimum _save_security needs: request.state.org_id
        state = type("S", (), {"org_id": env.org_id})()
    default = (await main.security_settings_for(env.org_id))["turnstile_mode"]   # primes the cache
    await main._save_security(_Req(), {"turnstile_mode": "on"})
    assert default != "on"
    assert (await main.security_settings_for(env.org_id))["turnstile_mode"] == "on"   # visible at once


async def test_positions_cache_headers(env):
    pub = await env.client.get("/positions")
    assert "max-age=15" in pub.headers["cache-control"]
    assert "x-org-slug" in pub.headers["vary"].lower()                                        # tenant-safe caching
    adm = await env.client.get("/positions", headers=env.it)
    assert adm.headers["cache-control"] == "no-store"                                         # admins see their edits at once
