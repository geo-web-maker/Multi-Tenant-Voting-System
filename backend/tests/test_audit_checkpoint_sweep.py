"""Automatic audit checkpoints: the sweep folds sealed ballots in and Chain Verify then matches."""
from datetime import datetime, timedelta
import pytest
from bson import ObjectId

import main
from tests.test_flows import env, Clock  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def _ballots(e, n, age_s):
    when = Clock.now - timedelta(seconds=age_s)
    for _ in range(n):
        _id, at = main._new_vote_event_stamp(when)
        await e.db.vote_events.insert_one({"_id": _id, "org_id": e.org_id, "candidate_id": ObjectId(),
                                           "cast_at": at, "round_id": "round-1", "chain_version": 2})


async def test_sweep_checkpoints_old_ballots_and_chain_verifies(env):
    await _ballots(env, 3, age_s=3600)
    assert await main._sweep_audit_checkpoints() == 1
    r = await env.client.get("/admin/audit/verify", headers=env.sa)
    body = r.json()
    assert body["valid"] is True and body["checkpoints_verified"] == 1
    assert body["uncheckpointed_events"] == 0 and body["roster_ledger"]["valid"] is True
    log = await env.db.audit_log.find_one({"action": "audit_checkpoint_created"})
    assert log["actor"] == "system"


async def test_recent_ballots_wait_until_sealed_and_second_sweep_is_noop(env):
    await _ballots(env, 2, age_s=0)
    assert await main._sweep_audit_checkpoints() == 0
    r = await env.client.get("/admin/audit/checkpoints", headers=env.sa)
    assert r.json()["uncheckpointed_events"] == 2
    await _ballots(env, 2, age_s=3600)
    assert await main._sweep_audit_checkpoints() == 1
    assert await main._sweep_audit_checkpoints() == 0


async def test_public_integrity_summary_is_cached_and_never_verifies_on_request(env):
    r = await env.client.get("/integrity-summary")
    assert r.status_code == 200 and r.json() == {"available": False}

    await _ballots(env, 3, age_s=3600)
    await main._sweep_audit_checkpoints()          # creates the checkpoint and caches the verdict
    await _ballots(env, 1, age_s=0)                # a fresh ballot, not yet sealed
    body = (await env.client.get("/integrity-summary")).json()   # no auth header
    assert body["available"] and body["chain_valid"] is True and body["ledger_valid"] is True
    assert body["checkpoints"] == 1 and body["events_covered"] == 3 and body["uncheckpointed_events"] == 1
    assert len(body["head_hash"]) == 64 and "first_mismatch_checkpoint_id" not in body


async def test_manual_verify_refreshes_the_cached_summary(env):
    await _ballots(env, 2, age_s=3600)
    await main._sweep_audit_checkpoints()
    await env.db.vote_events.update_many({}, {"$set": {"round_id": "round-9"}})   # tamper after checkpointing
    assert (await env.client.get("/admin/audit/verify", headers=env.sa)).json()["valid"] is False
    body = (await env.client.get("/integrity-summary")).json()
    assert body["chain_valid"] is False and body["head_hash"] is None
