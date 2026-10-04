"""Revert-to-pending and application reg-no edit (superadmin overrides), with mandatory audited reasons."""
import pytest

from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_security_regressions import _FakeClient  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _app(e, sid="v1", name="Ayebale Elizabeth", position_id="p1", **kw):
    r = await e.db.applications.insert_one({
        "org_id": e.org_id, "student_id": sid, "full_name": name, "position_id": position_id,
        "status": "pending", "votes": {}, "removal_votes": {}, "round_id": "round-1",
        "application_snapshot": {"student_id": sid}, **kw})
    return str(r.inserted_id)


async def _audit(e, action):
    return [d async for d in e.db.audit_log.find({"action": action})]


async def test_revert_force_approved_removes_candidate_and_revokes_certificate(env):
    aid = await _app(env)
    await env.db.certificates.insert_one({"certificate_id": "CERT-1", "org_id": env.org_id, "revoked": False})
    await env.db.applications.update_one({"_id": __import__("bson").ObjectId(aid)}, {"$set": {
        "status": "approved", "superadmin_override": True, "certificate_id": "CERT-1", "votes": {"com1": "deny"}}})
    await env.db.candidates.insert_one({"org_id": env.org_id, "application_id": aid, "name": "X"})

    r = await env.client.post(f"/superadmin/applications/{aid}/revert-to-pending", headers=env.sa,
                              json={"reason": "Approved by mistake"})
    assert r.status_code == 200 and r.json()["from_status"] == "approved"
    doc = await env.db.applications.find_one({"student_id": "v1"})
    assert doc["status"] == "pending" and doc["votes"] == {} and "superadmin_override" not in doc
    assert doc["revert_history"][0]["prior_votes"] == {"com1": "deny"}
    assert await env.db.candidates.count_documents({}) == 0
    assert (await env.db.certificates.find_one({"certificate_id": "CERT-1"}))["revoked"] is True
    log = (await _audit(env, "application_reverted_to_pending"))[0]
    assert log["details"]["reason"] == "Approved by mistake" and log["actor"] == "root"


async def test_revert_force_denied_back_to_pending(env):
    aid = await _app(env, status="denied", superadmin_override=True)
    r = await env.client.post(f"/superadmin/applications/{aid}/revert-to-pending", headers=env.sa,
                              json={"reason": "Wrongly denied"})
    assert r.status_code == 200
    assert (await env.db.applications.find_one({"student_id": "v1"}))["status"] == "pending"


async def test_revert_requires_reason_and_force_decision_and_no_votes(env):
    aid = await _app(env, status="denied", superadmin_override=True)
    assert (await env.client.post(f"/superadmin/applications/{aid}/revert-to-pending", headers=env.sa,
                                  json={"reason": " "})).status_code == 400
    by_vote = await _app(env, sid="v2", status="denied")                     # commission decision
    assert (await env.client.post(f"/superadmin/applications/{by_vote}/revert-to-pending", headers=env.sa,
                                  json={"reason": "nope nope"})).status_code == 400
    pend = await _app(env, sid="v3")
    assert (await env.client.post(f"/superadmin/applications/{pend}/revert-to-pending", headers=env.sa,
                                  json={"reason": "nope nope"})).status_code == 400
    approved = await _app(env, sid="v4", status="approved", superadmin_override=True)
    cand = await env.db.candidates.insert_one({"org_id": env.org_id, "application_id": approved, "name": "Y"})
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": cand.inserted_id})
    r = await env.client.post(f"/superadmin/applications/{approved}/revert-to-pending", headers=env.sa,
                              json={"reason": "has votes"})
    assert r.status_code == 409 and await env.db.candidates.count_documents({}) == 1


async def test_revert_is_superadmin_only(env):
    aid = await _app(env, status="denied", superadmin_override=True)
    r = await env.client.post(f"/superadmin/applications/{aid}/revert-to-pending", headers=env.com1,
                              json={"reason": "sneaky"})
    assert r.status_code in (401, 403)


async def test_edit_application_reg_no_logs_reason_and_revokes_links(env):
    await env.voter("v9", "Ayebale Elizabeth")
    aid = await _app(env, sid="wrong1")
    await env.db.candidate_tokens.insert_one({"org_id": env.org_id, "student_id": "wrong1", "token": "t", "round_id": "round-1"})
    r = await env.client.post(f"/superadmin/applications/{aid}/edit", headers=env.sa,
                              json={"student_id": " V9 ", "reason": "Typed the wrong number"})
    assert r.status_code == 200 and r.json()["fields"] == ["student_id"]
    doc = await env.db.applications.find_one({"full_name": "Ayebale Elizabeth"})
    assert doc["student_id"] == "v9"
    h = doc["edit_history"][0]
    assert h["changes"]["student_id"] == {"old": "wrong1", "new": "v9"} and h["after"]["student_id"] == "v9"
    assert doc["application_snapshot"]["student_id"] == "wrong1"            # original submission untouched
    tok = await env.db.candidate_tokens.find_one({"token": "t"})
    assert tok["student_id"] == "v9" and tok["revoked"] is True
    log = (await _audit(env, "application_edited"))[0]
    assert log["details"]["changes"]["student_id"] == {"old": "wrong1", "new": "v9"}
    assert log["details"]["reason"] == "Typed the wrong number"


async def test_edit_any_field_records_each_change_and_updates_ballot_entry(env):
    pos = await env.db.positions.insert_one({"org_id": env.org_id, "title": "Treasurer", "order": 3})
    aid = await _app(env, status="approved", superadmin_override=True, manifesto="old text", image_url="https://x/a.png",
                     application_snapshot={"student_id": "v1", "full_name": "Ayebale Elizabeth", "manifesto": "old text",
                                           "image_url": "https://x/a.png", "position_title": "President"})
    await env.db.candidates.insert_one({"org_id": env.org_id, "application_id": aid, "name": "Ayebale Elizabeth",
                                        "position": "President", "image_url": "https://x/a.png"})
    r = await env.client.post(f"/superadmin/applications/{aid}/edit", headers=env.sa, json={
        "manifesto": "new text", "image_url": "https://x/b.png", "position_id": str(pos.inserted_id),
        "payment_method": "MTN", "reason": "applicant asked"})
    assert r.status_code == 200, r.text
    assert r.json()["fields"] == ["image_url", "manifesto", "payment_method", "position_id"] and r.json()["ballot_updated"]
    doc = await env.db.applications.find_one({"student_id": "v1"})
    assert doc["manifesto"] == "new text" and doc["payment_method"] == "MTN"
    assert doc["edit_history"][0]["after"]["position_title"] == "Treasurer"
    assert doc["edit_history"][0]["after"]["manifesto"] == "new text"
    assert doc["application_snapshot"]["manifesto"] == "old text"
    cand = await env.db.candidates.find_one({"application_id": aid})
    assert cand["image_url"] == "https://x/b.png" and cand["position"] == "Treasurer" and cand["order"] == 3


async def test_second_edit_chains_from_the_first(env):
    aid = await _app(env, manifesto="m0", application_snapshot={"student_id": "v1", "full_name": "Ayebale Elizabeth",
                                                                "manifesto": "m0", "position_title": "P"})
    for text in ("m1", "m2"):
        assert (await env.client.post(f"/superadmin/applications/{aid}/edit", headers=env.sa,
                                      json={"manifesto": text, "reason": "tweak"})).status_code == 200
    h = (await env.db.applications.find_one({"student_id": "v1"}))["edit_history"]
    assert [e["after"]["manifesto"] for e in h] == ["m1", "m2"]
    assert h[1]["changes"]["manifesto"]["old"] == "m1"


async def test_edit_application_validation(env):
    await env.voter("v9", "Someone Else")
    aid = await _app(env, sid="wrong1")
    ok = {"reason": "fixing it"}
    post = lambda body: env.client.post(f"/superadmin/applications/{aid}/edit", headers=env.sa, json=body)
    assert (await post({"student_id": "v9", "reason": "x"})).status_code == 400                      # reason too short
    assert (await post({"student_id": "ghost", **ok})).status_code == 404                            # not on roll
    assert (await post({"student_id": "v9", **ok})).status_code == 400                               # name mismatch
    assert (await post({"image_url": "http://insecure/x.png", **ok})).status_code == 400
    assert (await post({"position_id": "not-a-position", **ok})).status_code == 400
    assert (await post({**ok})).status_code == 400                                                   # nothing to change
    await _app(env, sid="v1")                                                                       # v1 already applied to p1
    assert (await post({"student_id": "v1", **ok})).status_code == 409


async def test_status_portal_marks_edited_and_keeps_original_snapshot(env):
    await env.voter("v9", "Ayebale Elizabeth")
    aid = await _app(env, sid="wrong1", application_snapshot={"student_id": "wrong1", "full_name": "Ayebale Elizabeth"})
    r = await env.client.post(f"/superadmin/applications/{aid}/edit", headers=env.sa,
                              json={"student_id": "v9", "reason": "Typed the wrong number"})
    assert r.status_code == 200
    from datetime import timedelta
    await env.db.candidate_tokens.insert_one({"org_id": env.org_id, "student_id": "v9", "token": "t2", "round_id": "round-1",
                                              "revoked": False, "expires_at": main_now() + timedelta(days=5)})
    c = (await env.client.get("/candidates/status/t2")).json()["candidacies"][0]
    assert c["application_snapshot"]["student_id"] == "wrong1"                 # original page
    e = c["edits"][-1]
    assert e["snapshot"]["student_id"] == "v9" and set(e) == {"at", "snapshot"}   # no who / why leaked


async def test_voter_reg_no_edit_moves_status_links(env):
    await _app(env, sid="v1")
    await env.db.candidate_tokens.insert_one({"org_id": env.org_id, "student_id": "v1", "token": "t", "round_id": "round-1"})
    r = await env.client.post("/admin/students/edit", headers=env.sa,
                              json={"student_id": "v1", "new_student_id": "v1b", "reason": "typo fix"})
    assert r.status_code == 200, r.text
    assert (await env.db.applications.find_one({"full_name": "Ayebale Elizabeth"}))["student_id"] == "v1b"
    assert (await env.db.candidate_tokens.find_one({"token": "t"}))["student_id"] == "v1b"


def main_now():
    from tests.test_flows import Clock
    return Clock.now
