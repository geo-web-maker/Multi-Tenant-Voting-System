"""Guide 4.8 #2: /vote-status lets a voter confirm their ballot after a lost response."""
import pytest

import main
from tests.test_flows import env  # noqa: F401
from tests.test_security_regressions import _candidate, _authenticate, _FakeClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def txn(monkeypatch):
    monkeypatch.setattr(main, "client", _FakeClient())


async def _vote(env, tok, cid):
    return await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]},
                                 headers={"X-Voter-Token": tok})


async def test_status_false_before_and_true_after_with_the_same_token(env, txn, monkeypatch):
    cid = await _candidate(env)
    tok = (await _authenticate(env)).json()["voter_token"]
    h = {"X-Voter-Token": tok}
    r = await env.client.get("/vote-status", params={"student_id": "v1"}, headers=h)
    assert r.status_code == 200 and r.json() == {"has_voted": False}
    assert r.headers["cache-control"] == "no-store"
    assert (await _vote(env, tok, cid)).status_code == 200
    # the vote cleared vote_jti, yet the same token must still be able to ask
    r = await env.client.get("/vote-status", params={"student_id": "v1"}, headers=h)
    assert r.status_code == 200 and r.json() == {"has_voted": True}


async def test_status_requires_a_token(env):
    await env.voter("v1x", "Someone")
    r = await env.client.get("/vote-status", params={"student_id": "v1x"})
    assert r.status_code == 401


async def test_one_voters_token_cannot_read_another_voters_status(env):
    await env.voter("v2", "Bosco Kato", ("256700333444",))
    tok_a = (await _authenticate(env, "v1")).json()["voter_token"]
    r = await env.client.get("/vote-status", params={"student_id": "v2"}, headers={"X-Voter-Token": tok_a})
    assert r.status_code == 403
