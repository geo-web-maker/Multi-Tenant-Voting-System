"""Candidate payments are cleared by the Financial Controller, never by a commissioner.

Reuses the `env` fixture from test_flows (mongomock + fake clock).
"""
import pytest

from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


# ── helpers ──────────────────────────────────────────────────────────────────

async def _fc(e, sid="fc1", **flags):
    """A Financial Controller voter plus its session headers."""
    await e.voter(sid, "Fin Controller", ("256700000009",), is_financial_controller=True, **flags)
    return e.tok(sid, "financial_controller")


async def _application(e, sid="v1", name="Ayebale Elizabeth", fee=50000):
    pos = await e.client.post("/positions", headers=e.sa, json={"title": "Speaker", "order": 1, "application_fee": fee})
    assert pos.status_code == 200, pos.text
    await e.db.settings.delete_many({"name": "election_phases"})            # applications unscheduled = open
    r = await e.client.post("/apply", json={
        "student_id": sid, "full_name": name, "position_id": pos.json()["id"], "manifesto": "m",
        "payment_method": "Cash Receipt", "payment_proof_url": "https://x/receipt.png"})
    assert r.status_code == 200, r.text
    return await e.db.applications.find_one({"student_id": sid})


def _clear(e, app, hdr, who, **body):
    return e.client.post(f"/admin/applications/{app['_id']}/finance-clear", headers=hdr,
                         json={"financial_controller_id": who, **body})


def _reject(e, app, hdr, who, reason="Receipt short by UGX 20,000"):
    return e.client.post(f"/admin/applications/{app['_id']}/finance-reject", headers=hdr,
                         json={"financial_controller_id": who, "reason": reason})


async def _reload(e, app):
    return await e.db.applications.find_one({"_id": app["_id"]})


# ── the Financial Controller clears / rejects ────────────────────────────────

async def test_financial_controller_clears_and_commissioners_can_then_vote(env):
    await env.seed_panel()
    fc = await _fc(env)
    app = await _application(env)
    aid = str(app["_id"])

    # before clearance nobody can vote, and the message names the right person
    r = await env.client.post(f"/admin/applications/{aid}/vote", headers=env.pan1,
                              json={"commissioner_id": "com1", "vote": "approve"})
    assert r.status_code == 400 and "Financial Controller" in r.json()["detail"]

    r = await _clear(env, app, fc, "fc1", reason="Receipt matches the fee")
    assert r.status_code == 200 and r.json() == {"status": "finance_cleared"}
    doc = await _reload(env, app)
    assert doc["finance_cleared"] is True and doc["finance_cleared_by"] == "fc1"
    assert doc["finance_clear_note"] == "Receipt matches the fee"

    # the audit entry carries the receipt details, so the log alone shows what the decision rested on
    entry = await env.db.audit_log.find_one({"action": "application_finance_cleared"})
    assert entry["actor"] == "fc1"
    assert entry["details"]["payment_proof_url"] == "https://x/receipt.png"
    assert entry["details"]["fee_required"] == 50000 and entry["details"]["reason"] == "Receipt matches the fee"

    for who, hdr in (("com1", env.pan1), ("com2", env.pan2)):
        r = await env.client.post(f"/admin/applications/{aid}/vote", headers=hdr,
                                  json={"commissioner_id": who, "vote": "approve"})
        assert r.status_code == 200, r.text
    assert (await _reload(env, app))["status"] == "approved"


async def test_reject_needs_a_reason_and_is_logged_with_the_receipt(env):
    fc = await _fc(env)
    app = await _application(env)
    r = await env.client.post(f"/admin/applications/{app['_id']}/finance-reject", headers=fc,
                              json={"financial_controller_id": "fc1", "reason": "   "})
    assert r.status_code == 400
    assert (await _reload(env, app))["status"] == "pending"

    r = await _reject(env, app, fc, "fc1")
    assert r.status_code == 200 and r.json() == {"status": "denied"}
    doc = await _reload(env, app)
    assert doc["status"] == "denied" and doc["finance_rejected_by"] == "fc1"
    entry = await env.db.audit_log.find_one({"action": "application_finance_rejected"})
    assert entry["actor"] == "fc1" and entry["details"]["reason"] == "Receipt short by UGX 20,000"
    assert entry["details"]["payment_proof_url"] == "https://x/receipt.png"


async def test_a_decided_payment_cannot_be_decided_again(env):
    fc = await _fc(env)
    app = await _application(env)
    assert (await _clear(env, app, fc, "fc1")).status_code == 200
    assert (await _clear(env, app, fc, "fc1")).status_code == 400
    assert (await _reject(env, app, fc, "fc1")).status_code == 400
    assert (await _reload(env, app))["finance_cleared"] is True


# ── nobody else can ──────────────────────────────────────────────────────────

async def test_commissioners_can_no_longer_clear_or_reject_even_with_the_old_flag(env):
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_finance_commissioner": True}})
    app = await _application(env)
    for call in (_clear(env, app, env.com1, "com1"), _reject(env, app, env.com1, "com1")):
        r = await call
        assert r.status_code == 403, r.text
    doc = await _reload(env, app)
    assert doc["status"] == "pending" and not doc.get("finance_cleared")


async def test_it_admin_overseer_and_superadmin_are_refused_superadmin_keeps_force_clear(env):
    app = await _application(env)
    await env.voter("ov1", "Over Seer", ("256700000010",), is_overseer=True)
    for hdr, who in ((env.it, "it1"), (env.over, "ov1"), (env.sa, "root")):
        assert (await _clear(env, app, hdr, who)).status_code == 403
        assert (await _reject(env, app, hdr, who)).status_code == 403
    assert not (await _reload(env, app)).get("finance_cleared")

    r = await env.client.post(f"/superadmin/applications/{app['_id']}/force-finance-clear", headers=env.sa)
    assert r.status_code == 200
    doc = await _reload(env, app)
    assert doc["finance_cleared"] is True and doc["finance_cleared_by"] == "superadmin_override"
    assert await env.db.audit_log.find_one({"action": "application_force_finance_cleared"})


async def test_a_controller_cannot_act_in_someone_elses_name(env):
    fc = await _fc(env)
    await _fc(env, "fc2")
    app = await _application(env)
    assert (await _clear(env, app, fc, "fc2")).status_code == 403
    assert not (await _reload(env, app)).get("finance_cleared")


async def test_someone_holding_both_roles_uses_the_role_of_the_session(env):
    await env.seed_panel()
    fin = await _fc(env, "fcx", is_commissioner=True)              # one person, both roles
    comm = env.tok("fcx", "commission")
    a1 = await _application(env)

    # the Commission session cannot clear payments; the Financial Controller session can
    assert (await _clear(env, a1, comm, "fcx")).status_code == 403
    assert (await _clear(env, a1, fin, "fcx")).status_code == 200
    entry = await env.db.audit_log.find_one({"action": "application_finance_cleared"})
    assert entry["actor"] == "fcx" and entry["details"]["decider_also_commissioner"] is True

    # a commissioner cannot vote from the Commission session (guide 8.1); the same person votes from the panel hat
    r = await env.client.post(f"/admin/applications/{a1['_id']}/vote", headers=comm,
                              json={"commissioner_id": "fcx", "vote": "approve"})
    assert r.status_code == 403
    await env.db.panel_members.insert_one({"org_id": env.org_id, "panel_member_id": "PM-FCX", "student_id": "fcx",
                                           "is_member": True, "full_name": "Fin Comm", "email": "fcx@p.org",
                                           "phone_numbers": ["256700000000"], "active": True,
                                           "appointment_reason": "test", "password_hash": "x",
                                           "must_change_password": False})
    r = await env.client.post(f"/admin/applications/{a1['_id']}/vote", headers=env.tok("PM-FCX", "vetting"),
                              json={"commissioner_id": "fcx", "vote": "approve"})
    assert r.status_code == 200, r.text

    # rejecting works the same way
    await env.voter("v9", "Nine Person", ("256700999999",))
    a2 = await _application(env, "v9", "Nine Person")
    assert (await _reject(env, a2, fin, "fcx")).status_code == 200
    e2 = await env.db.audit_log.find_one({"action": "application_finance_rejected"})
    assert e2["details"]["decider_also_commissioner"] is True


async def test_revoked_controller_is_refused(env):
    fc = await _fc(env)
    app = await _application(env)
    await env.db.voters.update_one({"student_id": "fc1"}, {"$set": {"is_financial_controller": False}})
    assert (await _clear(env, app, fc, "fc1")).status_code in (401, 403)


# ── keeping the two roles apart at grant time ────────────────────────────────

async def test_both_roles_can_be_granted_to_the_same_person(env):
    r = await env.client.post("/superadmin/financial-controllers/com1/toggle", headers=env.sa)
    assert r.status_code == 200 and r.json()["is_financial_controller"] is True
    v = await env.db.voters.find_one({"student_id": "com1"})
    assert v["is_financial_controller"] and v["is_commissioner"]

    await _fc(env)
    r = await env.client.post("/superadmin/commissioners/fc1/toggle", headers=env.sa)
    assert r.status_code == 200 and r.json()["is_commissioner"] is True


async def test_setting_a_finance_commissioner_is_retired(env):
    r = await env.client.post("/superadmin/commissioners/com1/set-finance-commissioner", headers=env.sa)
    assert r.status_code == 410
    assert not (await env.db.voters.find_one({"student_id": "com1"})).get("is_finance_commissioner")


# ── visibility ───────────────────────────────────────────────────────────────

async def test_controller_sees_receipts_but_not_how_commissioners_voted(env):
    await env.seed_panel()
    fc = await _fc(env)
    app = await _application(env)
    await _clear(env, app, fc, "fc1")
    await env.client.post(f"/admin/applications/{app['_id']}/vote", headers=env.pan1,
                          json={"commissioner_id": "com1", "vote": "approve"})

    seen_by_fc = (await env.client.get("/admin/applications", headers=fc)).json()[0]
    assert seen_by_fc["payment_proof_url"] == "https://x/receipt.png" and seen_by_fc["fee_required"] == 50000
    assert "votes" not in seen_by_fc and "removal_votes" not in seen_by_fc

    # commissioners see no pending applications at all; panelists see progress and their own vote only
    assert (await env.client.get("/admin/applications", headers=env.com2)).json() == []
    seen_by_panel = (await env.client.get("/admin/applications", headers=env.pan2)).json()[0]
    assert seen_by_panel["my_vote"] is None and seen_by_panel["progress"] == {"cast": 1, "panel_count": 2}
    assert "votes" not in seen_by_panel and "final_split" not in seen_by_panel


# ── voter-register decisions follow the same rule ────────────────────────────

async def test_denying_a_student_change_needs_a_reason(env):
    fc = await _fc(env)
    ch = await env.db.student_changes.insert_one({
        "org_id": env.org_id, "change_type": "add", "student_id": "n1", "full_name": "New One",
        "status": "pending", "requested_by": "it1", "phones": ["256700123456"]})
    url = f"/admin/student-changes/{ch.inserted_id}/decide"

    r = await env.client.post(url, headers=fc, json={"financial_controller_id": "fc1", "decision": "deny"})
    assert r.status_code == 400
    assert (await env.db.student_changes.find_one({"_id": ch.inserted_id}))["status"] == "pending"

    r = await env.client.post(url, headers=fc, json={"financial_controller_id": "fc1", "decision": "deny",
                                                     "reason": "No proof of payment"})
    assert r.status_code == 200
    doc = await env.db.student_changes.find_one({"_id": ch.inserted_id})
    assert doc["status"] == "denied" and doc["decision_reason"] == "No proof of payment"


# ── reversing and reinstating (Finance corrects its own decisions) ───────────

def _reverse(e, app, hdr, who, reason="Receipt is forged"):
    return e.client.post(f"/admin/applications/{app['_id']}/finance-reverse", headers=hdr,
                         json={"financial_controller_id": who, "reason": reason})


def _reinstate(e, app, hdr, who, target, reason="Balance paid, receipt 4411 checked"):
    return e.client.post(f"/admin/applications/{app['_id']}/finance-reinstate", headers=hdr,
                         json={"financial_controller_id": who, "target": target, "reason": reason})


async def test_clearance_can_be_reversed_while_pending_and_blocks_voting(env):
    await env.seed_panel()
    fc = await _fc(env)
    app = await _application(env)
    aid = str(app["_id"])
    assert (await _clear(env, app, fc, "fc1")).status_code == 200
    r = await env.client.post(f"/admin/applications/{aid}/vote", headers=env.pan1,
                              json={"commissioner_id": "com1", "vote": "approve"})
    assert r.status_code == 200

    assert (await _reverse(env, app, fc, "fc1", "  ")).status_code == 400          # reason required
    r = await _reverse(env, app, fc, "fc1")
    assert r.status_code == 200 and r.json()["votes_set_aside"] == 1
    doc = await _reload(env, app)
    assert doc["status"] == "pending" and doc["finance_cleared"] is False
    assert doc["votes"] == {} and "finance_cleared_by" not in doc
    assert doc["finance_history"][-1]["action"] == "clearance_reversed"
    assert doc["revert_history"][-1]["prior_votes"]                                # kept for the superadmin
    entry = await env.db.audit_log.find_one({"action": "application_finance_reversed"})
    assert entry["details"]["reason"] == "Receipt is forged"

    # voting is closed again until Finance re-clears
    r = await env.client.post(f"/admin/applications/{aid}/vote", headers=env.pan2,
                              json={"commissioner_id": "com2", "vote": "approve"})
    assert r.status_code == 400 and "Financial Controller" in r.json()["detail"]
    assert (await _reverse(env, app, fc, "fc1")).status_code == 400                # nothing left to reverse


async def test_clearance_cannot_be_reversed_after_the_panel_decided(env):
    await env.seed_panel()
    fc = await _fc(env)
    app = await _application(env)
    assert (await _clear(env, app, fc, "fc1")).status_code == 200
    for who, hdr in (("com1", env.pan1), ("com2", env.pan2)):
        await env.client.post(f"/admin/applications/{app['_id']}/vote", headers=hdr,
                              json={"commissioner_id": who, "vote": "approve"})
    assert (await _reload(env, app))["status"] == "approved"
    r = await _reverse(env, app, fc, "fc1")
    assert r.status_code == 409
    assert (await _reload(env, app))["finance_cleared"] is True


async def test_rejection_reason_reaches_the_candidate_status_page_snapshot(env):
    fc = await _fc(env)
    app = await _application(env)
    assert (await _reject(env, app, fc, "fc1", "Receipt short by UGX 20,000")).status_code == 200
    snap = (await _reload(env, app))["denial_snapshot"]
    assert snap["reason"] == "Receipt short by UGX 20,000" and snap["denied_by"] == "Financial Controller"


async def test_rejected_application_can_be_reinstated_to_pending_or_cleared(env):
    fc = await _fc(env)
    a1 = await _application(env)
    assert (await _reject(env, a1, fc, "fc1")).status_code == 200
    assert (await _reinstate(env, a1, fc, "fc1", "bogus")).status_code == 400
    assert (await _reinstate(env, a1, fc, "fc1", "pending", "  ")).status_code == 400

    r = await _reinstate(env, a1, fc, "fc1", "pending")
    assert r.status_code == 200 and r.json() == {"status": "pending", "finance_cleared": False}
    doc = await _reload(env, a1)
    assert doc["status"] == "pending" and doc["finance_cleared"] is False
    assert not doc.get("finance_rejected") and doc["denial_snapshot"] is None
    assert "finance_rejection_reason" not in doc
    assert doc["finance_history"][-1]["previous_rejection_reason"] == "Receipt short by UGX 20,000"

    # and a second applicant goes straight to cleared
    await env.voter("v2", "Second Person", ("256700000222",))
    a2 = await _application(env, "v2", "Second Person")
    assert (await _reject(env, a2, fc, "fc1")).status_code == 200
    r = await _reinstate(env, a2, fc, "fc1", "cleared")
    assert r.status_code == 200 and r.json()["finance_cleared"] is True
    doc = await _reload(env, a2)
    assert doc["status"] == "pending" and doc["finance_cleared"] is True and doc["finance_cleared_by"] == "fc1"
    assert (await env.db.audit_log.find_one({"action": "application_finance_reinstated"})) is not None
    # not rejected any more, so it cannot be reinstated twice
    assert (await _reinstate(env, a2, fc, "fc1", "pending")).status_code == 400


async def test_commission_or_override_denials_cannot_be_reinstated_by_finance(env):
    fc = await _fc(env)
    app = await _application(env)
    await env.db.applications.update_one({"_id": app["_id"]}, {"$set": {"status": "denied"}})
    assert (await _reinstate(env, app, fc, "fc1", "pending")).status_code == 400     # not a finance rejection
    await env.db.applications.update_one({"_id": app["_id"]},
                                         {"$set": {"finance_rejected": True, "superadmin_override": True}})
    assert (await _reinstate(env, app, fc, "fc1", "pending")).status_code == 400     # override


async def test_only_the_financial_controller_can_reverse_or_reinstate(env):
    await env.seed_panel()
    fc = await _fc(env)
    app = await _application(env)
    assert (await _clear(env, app, fc, "fc1")).status_code == 200
    assert (await _reverse(env, app, env.pan1, "com1")).status_code in (401, 403)
    assert (await _reverse(env, app, fc, "someone-else")).status_code == 403        # bind_identity
    assert (await _reload(env, app))["finance_cleared"] is True
