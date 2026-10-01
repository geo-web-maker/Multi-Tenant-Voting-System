"""Route-level check that the real endpoints tag outcomes with the right funnel reason codes."""
from datetime import timedelta

import pytest

import analytics as a
import main  # noqa: F401
from tests.test_flows import env, ident, code_from, set_voting, START, Clock  # noqa: F401  (fixture + helpers)
from tests.test_security_regressions import _candidate, _FakeClient  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    def wipe():
        a._deltas.clear(); a._heat.clear(); a._minutes.clear()
    wipe()
    monkeypatch.setattr(main, "client", _FakeClient())
    yield
    wipe()


def outcomes():
    out = {}
    for k, f in a._deltas.items():
        if k[2] == "fout":
            out[(k[3], k[4])] = f["n"]
    return out


async def open_voting(e):
    await set_voting(e, START - timedelta(hours=1), START + timedelta(days=1))


async def test_identity_and_otp_reasons_are_recorded(env):
    await open_voting(env)
    assert (await ident(env, "nobody")).status_code == 404
    assert (await ident(env, "v1", "Totally Wrong")).status_code == 400
    assert (await ident(env, "v1")).status_code == 200
    bad = await env.client.post("/verify-otp", json={"student_id": "v1", "code": "000000"})
    assert bad.status_code == 400
    good = await env.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(env)})
    assert good.status_code == 200
    o = outcomes()
    assert o[("/verify-identity", "not_on_roll")] == 1
    assert o[("/verify-identity", "name_mismatch")] == 1
    assert o[("/verify-identity", "ok")] == 1
    assert o[("/verify-otp", "wrong_code")] == 1
    assert o[("/verify-otp", "ok")] == 1


async def test_phase_closed_and_vote_reasons(env):
    # Voting window has not opened yet.
    await set_voting(env, START + timedelta(days=1), START + timedelta(days=2))
    assert (await ident(env, "v1")).status_code == 403
    assert outcomes()[("/verify-identity", "phase_not_open")] == 1

    await open_voting(env)
    cid = await _candidate(env)
    assert (await ident(env, "v1")).status_code == 200
    tok = (await env.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(env)})).json()["voter_token"]
    h = {"X-Voter-Token": tok}
    assert (await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]}, headers=h)).status_code == 200
    assert (await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]}, headers=h)).status_code == 400
    o = outcomes()
    assert o[("/vote-bulk", "ok")] == 1
    assert o[("/vote-bulk", "already_voted")] == 1

    s = a.build_summary([{"org_id": k[0], "day": k[1], "kind": k[2], "k1": k[3], "k2": k[4], "device": k[5], "seg": k[6],
                          **{kk: vv for kk, vv in f.items() if "." not in kk}} for k, f in a._deltas.items()],
                        1, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    assert s["funnels"]["voting"]["vote"]["ok"] == 1
    assert {"label": "already_voted", "value": 1} in s["funnels"]["voting"]["vote"]["reasons"]


async def test_api_outcomes_are_tagged_public_or_staff_by_the_request(env):
    a._deltas.clear(); a._seen_routes.clear()
    assert (await env.client.get("/positions")).status_code == 200                 # no Authorization: a voter/applicant
    assert (await env.client.get("/positions", headers=env.sa)).status_code == 200  # admin session
    segs = sorted(k[6] for k in a._deltas if k[2] == "api" and k[3] == "/positions")
    assert segs == ["public", "staff"]
