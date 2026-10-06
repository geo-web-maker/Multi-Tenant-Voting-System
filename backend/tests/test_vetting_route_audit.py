"""Regression tests for the vetting-route audit.

NOT executed when written (no FastAPI/Mongo in the audit sandbox): run `pytest tests/test_vetting_route_audit.py`
before deploying. Reuses the `env` fixture and helpers from the existing vetting test modules.
"""
from datetime import timedelta

import pytest
from bson import ObjectId

from tests.test_flows import env, Clock  # noqa: F401
from tests.test_vetting_panel_p1 import _panelist, _add, _install_revocation_hook  # noqa: F401
from tests.test_vetting_panel_p2 import _ready_application, _vote

pytestmark = pytest.mark.asyncio


# 4. A panel vote is final and is stored exactly once.
async def test_second_vote_by_same_panelist_is_refused_and_first_vote_stands(env):
    await env.seed_panel(extra=1)                       # panel of 3, so one vote cannot resolve it
    aid = await _ready_application(env)
    assert (await _vote(env, aid, env.pan1, "approve", "com1")).status_code == 200
    r = await _vote(env, aid, env.pan1, "deny", "com1")
    assert r.status_code == 409, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["votes"]["com1"] == "approve"
    # only the stored vote is audited
    assert await env.db.audit_log.count_documents({"action": "application_vote_cast"}) == 1


# 3. The same member cannot be put on the panel twice (would inflate the denominator).
async def test_member_cannot_be_added_twice(env):
    first = await _add(env, is_member=True, student_id="com1", email="m1@x.org", access_expires_at=None)
    assert first.status_code == 200, first.text
    second = await _add(env, is_member=True, student_id="com1", email="m1b@x.org", access_expires_at=None)
    assert second.status_code == 409, second.text
    assert await env.db.panel_members.count_documents({"student_id": "com1"}) == 1


# 1. A "Z"-suffixed (aware) date during the vetting freeze must not crash with a 500.
async def test_patch_extend_access_with_utc_z_date_during_freeze(env):
    await env.db.settings.update_one(
        {"name": "election_phases", "org_id": env.org_id},
        {"$set": {"name": "election_phases", "org_id": env.org_id, "round_id": "round-1",
                  "phases": {"vetting": {"start": Clock.now - timedelta(days=1),
                                         "end": Clock.now + timedelta(days=10), "enforced": True}}}},
        upsert=True)
    await _panelist(env, "PM-EXT001", "ext@x.org", is_member=False, expires=Clock.now + timedelta(days=5))
    later = (Clock.now + timedelta(days=8)).isoformat() + "Z"
    r = await env.client.patch("/superadmin/vetting-panel/PM-EXT001", headers=env.sa,
                               json={"access_expires_at": later})
    assert r.status_code == 200, r.text
    doc = await env.db.panel_members.find_one({"panel_member_id": "PM-EXT001"})
    assert doc["access_expires_at"].tzinfo is None            # stored naive UTC


# 2. A phase with no end date cannot be the only end for an external.
async def test_patch_external_to_phase_without_end_is_refused(env):
    await _panelist(env, "PM-EXT002", "ext2@x.org", is_member=False, expires=Clock.now + timedelta(days=5))
    r = await env.client.patch("/superadmin/vetting-panel/PM-EXT002", headers=env.sa,
                               json={"expires_with_phase": "vetting"})
    assert r.status_code == 400, r.text
    doc = await env.db.panel_members.find_one({"panel_member_id": "PM-EXT002"})
    assert doc["expires_with_phase"] is None and doc["access_expires_at"] is not None


# 6. Re-activating clears the stale removal stamp.
async def test_reactivation_clears_removed_at(env):
    await _panelist(env, "PM-OFF002", "off2@x.org", is_member=False, active=False,
                    expires=Clock.now + timedelta(days=5))
    await env.db.panel_members.update_one({"panel_member_id": "PM-OFF002"},
                                           {"$set": {"removed_at": Clock.now}})
    r = await env.client.post("/superadmin/vetting-panel/PM-OFF002/active?active=true", headers=env.sa)
    assert r.status_code == 200, r.text
    doc = await env.db.panel_members.find_one({"panel_member_id": "PM-OFF002"})
    assert doc["active"] is True and doc["removed_at"] is None


# 5. Candidate creation survives an application that only has the snapshot name.
async def test_candidate_created_from_snapshot_name_when_full_name_missing(env):
    import main
    app_doc = {"_id": ObjectId(), "application_snapshot": {"full_name": "Snap Name"}, "position_id": ""}
    await main._create_candidate_from_application(app_doc, env.org_id)
    cand = await env.db.candidates.find_one({"application_id": str(app_doc["_id"])})
    assert cand["name"] == "Snap Name"
