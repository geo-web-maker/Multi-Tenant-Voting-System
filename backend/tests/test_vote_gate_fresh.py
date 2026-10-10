"""Guide 05 / audit S-01: a ballot must be refused as soon as election_config says closed or certified, even
when this process's settings cache still holds the old open copy (another instance, or a deploy overlap)."""
import pytest

import main
from tests.test_flows import env, ident, code_from  # noqa: F401  (fixture + helpers)
from tests.test_security_regressions import _FakeClient  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _tx(monkeypatch):
    monkeypatch.setattr(main, "client", _FakeClient())


@pytest.fixture
def cache_on(monkeypatch):
    monkeypatch.setattr(main, "_SETTINGS_TTL", 60.0)       # long, so only a fresh read can see the change
    main.invalidate_settings()
    yield
    main.invalidate_settings()


async def _token_and_candidate(e):
    cand = str((await e.db.candidates.insert_one(
        {"org_id": e.org_id, "name": "A", "position": "President", "order": 1})).inserted_id)
    await ident(e)
    r = await e.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(e)})
    assert r.status_code == 200, r.text
    await main.cached_setting(e.org_id, "election_config")   # warm the cache while the election is open
    return r.json()["voter_token"], cand


async def _vote(e, tok, cand):
    return await e.client.post("/vote-bulk", headers={"X-Voter-Token": tok},
                               json={"student_id": "v1", "candidate_ids": [cand]})


async def test_closed_behind_the_cache_still_refuses_the_ballot(env, cache_on):
    tok, cand = await _token_and_candidate(env)
    await env.db.settings.update_one({"name": "election_config", "org_id": env.org_id},
                                     {"$set": {"is_open": False}}, upsert=True)      # no invalidate: "another instance"
    assert (await main.cached_setting(env.org_id, "election_config")) is None or \
        (await main.cached_setting(env.org_id, "election_config")).get("is_open", True) is True   # cache is stale
    r = await _vote(env, tok, cand)
    assert r.status_code == 403 and "closed" in r.text.lower(), r.text


async def test_certified_behind_the_cache_still_refuses_the_ballot(env, cache_on):
    tok, cand = await _token_and_candidate(env)
    await env.db.settings.update_one({"name": "election_config", "org_id": env.org_id},
                                     {"$set": {"is_certified": True}}, upsert=True)
    r = await _vote(env, tok, cand)
    assert r.status_code == 403 and "certified" in r.text.lower(), r.text


async def test_open_election_still_accepts_the_ballot(env, cache_on):
    tok, cand = await _token_and_candidate(env)
    r = await _vote(env, tok, cand)
    assert r.status_code == 200, r.text
