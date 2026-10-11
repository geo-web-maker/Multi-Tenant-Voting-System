"""Voter-path call budgets after the single-write ballot claim, insert-first OTP state and lazy voter read, plus
proof that every /vote-bulk rejection keeps its status, message and precedence, and that analytics flushing is
chunked, coalesced and loses nothing on failure."""
import pytest

import analytics
import main
from tests.opcount import CountingDB, FakeClient
from tests.test_flows import env, ident, code_from, tick  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fake_sessions(monkeypatch):
    monkeypatch.setattr(main, "client", FakeClient())          # mongomock has no transactions


@pytest.fixture
def counted(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    monkeypatch.setattr(main, "client", FakeClient())
    monkeypatch.setattr(main, "_SETTINGS_TTL", 5.0)
    main.invalidate_settings()
    yield cdb
    main.invalidate_settings()


async def cand(e, name="A", position="President", order=1):
    return str((await e.db.candidates.insert_one(
        {"org_id": e.org_id, "name": name, "position": position, "order": order})).inserted_id)


async def login(e, sid="v1", name="Ayebale Elizabeth"):
    assert (await ident(e, sid, name)).status_code == 200
    r = await e.client.post("/verify-otp", json={"student_id": sid, "code": code_from(e)})
    assert r.status_code == 200, r.text
    return r.json()["voter_token"]


async def bulk(e, tok, ids, sid="v1"):
    return await e.client.post("/vote-bulk", headers={"X-Voter-Token": tok}, json={"student_id": sid, "candidate_ids": ids})


async def test_budgets_per_step(env, counted):
    c1, c2 = await cand(env), await cand(env, "B", "Secretary", 2)
    await env.voter("w", "Warm Up", ("256700111999",)); await login(env, "w", "Warm Up")      # warm caches
    s = counted.snapshot()
    assert (await ident(env)).status_code == 200
    assert sum(counted.since(s).values()) <= 9
    s = counted.snapshot()
    r = await env.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(env)})
    assert r.status_code == 200
    assert sum(counted.since(s).values()) <= 8, counted.since(s)                      # was 10
    s = counted.snapshot()
    assert (await bulk(env, r.json()["voter_token"], [c1, c2])).status_code == 200
    d = counted.since(s)
    assert d.get(("voters", "find_one"), 0) == 0 and d.get(("voters", "find_one_and_update")) == 1, d
    assert sum(d.values()) <= 2 + 1 + 2 + 1, d                                        # was 4 + positions


async def test_vote_is_recorded_once_and_replay_is_refused(env):
    c1 = await cand(env)
    tok = await login(env)
    assert (await bulk(env, tok, [c1])).status_code == 200
    assert await env.db.vote_events.count_documents({}) == 1
    voter = await env.db.voters.find_one({"student_id": "v1"})
    assert voter["has_voted"] is True and voter["last_status"] == "completed" and "vote_jti" not in voter
    r = await bulk(env, tok, [c1])                                                    # same valid token again
    assert r.status_code == 400 and "already cast" in r.text
    assert await env.db.vote_events.count_documents({}) == 1


async def test_rejections_keep_status_message_and_precedence(env):
    c1 = await cand(env)
    c1b = await cand(env, "A2", "President", 2)
    ghost = "5" * 24
    tok = await login(env)
    assert (await bulk(env, "garbage", [c1])).status_code == 401                      # bad token
    assert (await bulk(env, tok, [ghost])).status_code == 404 and "candidates" in (await bulk(env, tok, [ghost])).text
    r = await bulk(env, tok, [c1, c1b])
    assert r.status_code == 400 and "per position" in r.text
    voter = await env.db.voters.find_one({"student_id": "v1"})
    assert voter["has_voted"] is False and voter.get("vote_jti")                      # rejected ballot cost nothing
    assert (await bulk(env, tok, [c1], sid="nobody")).status_code in (403, 404)
    # a newer login invalidates the older token even though it is validly signed
    tick(minutes=30)                                                                  # past the resend cooldown
    tok2 = await login(env)
    r = await bulk(env, tok, [c1])
    assert r.status_code == 401 and "expired" in r.text
    assert (await bulk(env, tok2, [c1])).status_code == 200
    # ineligible voter with a bad candidate gets the VOTER error first, as before
    r = await bulk(env, tok2, [ghost])
    assert r.status_code == 400 and "already cast" in r.text


async def test_voting_without_otp_is_forbidden(env):
    c1 = await cand(env)
    await env.voter("n1", "No Otp", ("256700111555",))
    r = await bulk(env, "x", [c1], sid="n1")
    assert r.status_code == 403                                                        # OTP check precedes the token check
    import auth
    tok, _ = auth.create_voter_token(student_id="n1", org_id=env.org_id)
    r = await bulk(env, tok, [c1], sid="n1")
    assert r.status_code == 403 and "OTP" in r.text


async def test_cooldown_and_guess_bucket_still_enforced_with_insert_first(env, counted):
    await env.voter("g1", "Gee One", ("256700111888",))
    s = counted.snapshot()
    assert (await ident(env, "g1", "Gee One")).status_code == 200
    d = counted.since(s)
    assert d.get(("otp_send_state", "insert_one")) == 1 and d.get(("otp_send_state", "find_one"), 0) == 0, d
    r = await ident(env, "g1", "Gee One")                                             # resend inside the cooldown
    assert r.status_code == 429 and "wait" in r.text.lower()
    # wrong guesses are charged against the bucket, and a right one still works afterwards
    for _ in range(2):
        assert (await env.client.post("/verify-otp", json={"student_id": "g1", "code": "000000"})).status_code == 400
    bucket = await env.db.otp_guess_state.find_one({})
    assert bucket["tokens"] == pytest.approx(main.ol.FREE_GUESSES - 2, abs=0.01)
    r = await env.client.post("/verify-otp", json={"student_id": "g1", "code": code_from(env)})
    assert r.status_code == 200


async def test_verify_otp_unknown_voter_and_no_code_messages_unchanged(env):
    r = await env.client.post("/verify-otp", json={"student_id": "ghost", "code": "123456"})
    assert r.status_code == 404 and "not found" in r.text.lower()
    r = await env.client.post("/verify-otp", json={"student_id": "v1", "code": "123456"})
    assert r.status_code == 400 and "request a new code" in r.text.lower()


# ---- analytics flush ---------------------------------------------------------------------------------------------
class FakeColl:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    async def bulk_write(self, ops, ordered=False):
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise RuntimeError("db down")
        self.calls.append(len(ops))


class FakeDB:
    def __init__(self, fail_on=None):
        self.analytics_counters, self.analytics_heat = FakeColl(fail_on), FakeColl()


def _seed(n_counters, n_heat):
    analytics._deltas.clear(); analytics._heat.clear()
    for i in range(n_counters):
        analytics._deltas[("o", "2026-10-10", "pv", f"/p{i}", "", "d", "s")] = {"n": 1}
    for i in range(n_heat):
        analytics._heat[("o", "/p", "d", "s", "click", i, 0)] = 2


async def test_flush_is_chunked_and_heat_waits_for_its_own_cadence(monkeypatch):
    monkeypatch.setenv("ANALYTICS_FLUSH_CHUNK", "25"); monkeypatch.setenv("ANALYTICS_FLUSH_PACE_S", "0")
    fdb = FakeDB(); monkeypatch.setattr(analytics, "_db", fdb)
    _seed(60, 40)
    await analytics._flush_once(include_heat=False)
    assert fdb.analytics_counters.calls == [25, 25, 10] and fdb.analytics_heat.calls == []
    assert len(analytics._heat) == 40                                                 # kept for the next heat flush
    await analytics._flush_once(include_heat=True)
    assert fdb.analytics_heat.calls == [25, 15] and len(analytics._heat) == 0


async def test_failed_chunk_restores_only_what_was_not_written(monkeypatch):
    monkeypatch.setenv("ANALYTICS_FLUSH_CHUNK", "25"); monkeypatch.setenv("ANALYTICS_FLUSH_PACE_S", "0")
    fdb = FakeDB(fail_on=1); monkeypatch.setattr(analytics, "_db", fdb)               # 2nd counter chunk fails
    _seed(60, 10)
    await analytics._flush_once()
    assert fdb.analytics_counters.calls == [25]
    assert len(analytics._deltas) == 35 and len(analytics._heat) == 10                # nothing double-counted or lost
