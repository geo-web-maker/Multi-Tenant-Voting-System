"""Regression tests for the security audit that followed Vetting Panel phases 5 and 6.

Each test pins one finding (see SECURITY_AUDIT_VETTING_PANEL.md). Reuses the `env` fixture and the
helpers from test_flows / test_vetting_panel_p1 / test_vetting_panel_p2.
NOTE: written in a sandbox without FastAPI/mongomock, so these have not been executed there; run
`pytest tests/test_vetting_panel_security_audit.py` before deploying.
"""
from datetime import timedelta

import pytest
from bson import ObjectId

import main
from tests.test_flows import env, START  # noqa: F401
from tests.test_vetting_panel_p1 import _panelist, _login, _install_revocation_hook, PW, _now  # noqa: F401
from tests.test_vetting_panel_p2 import _ready_application, _vote, _set_policy  # noqa: F401

pytestmark = pytest.mark.asyncio


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"}


# SEC-01: a MEMBER panelist (panel record carries a student_id) must get a usable token.
async def test_member_panelist_direct_login_token_works(env):
    await _panelist(env, "PM-MEM001", "mem@x.org", is_member=True, student_id="com1")
    r = await _login(env, "mem@x.org")
    assert r.status_code == 200, r.text
    me = await env.client.get("/admin/vetting-me", headers=_h(r.json()["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["panel_member_id"] == "PM-MEM001"


# SEC-02: neither the Chair's identity nor the tie-break marker reaches a commissioner via the audit log.
async def test_audit_log_hides_tie_break_marker_and_chair_identity(env):
    await env.seed_panel(extra=2)
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    await _set_policy(env, "majority_total")
    aid = await _ready_application(env)
    ext = [env.tok("PM-EXT0", "vetting"), env.tok("PM-EXT1", "vetting")]
    await _vote(env, aid, env.pan1, "approve", "com1")
    await _vote(env, aid, env.pan2, "deny", "com2")
    await _vote(env, aid, ext[0], "approve")
    await _vote(env, aid, ext[1], "deny")
    r = await env.client.post(f"/admin/applications/{aid}/tie-break", headers=env.pan1, json={"decision": "approve"})
    assert r.status_code == 200, r.text
    entries = (await env.client.get("/admin/audit-log", headers=env.com1)).json()["entries"]
    approved = [e for e in entries if e["action"] == "application_approved"][0]
    assert approved["actor"] == "vetting" and "tie_break" not in approved["details"]
    assert not [e for e in entries if e["action"] == "application_tie_broken"]


# SEC-03: the actor filter must not reveal which panelist voted on an application.
async def test_actor_filter_cannot_probe_who_voted(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    await _vote(env, aid, env.pan1, "approve", "com1")
    body = (await env.client.get("/admin/audit-log?actor=PM-COM1", headers=env.com1)).json()
    assert body["total"] == 0 or all(e["action"] != "application_vote_cast" for e in body["entries"])
    sa = (await env.client.get("/superadmin/audit-log?action=application_vote_cast", headers=env.sa)).json()
    assert any(e["action"] == "application_vote_cast" for e in (sa["entries"] if isinstance(sa, dict) else sa))


# SEC-04: unauthenticated hits must not write an audit row each time.
async def test_unauthenticated_hits_do_not_flood_the_audit_log(env):
    main._GUARD_401_LAST.clear()
    for _ in range(5):
        assert (await env.client.get("/admin/audit-log")).status_code == 401
    assert await env.db.audit_log.count_documents({"action": "admin_guard_401"}) <= 1


# SEC-06/07: public /apply bounds and https-only proof links.
async def test_apply_rejects_non_https_and_oversized_fields(env):
    from tests.test_flows import _mk_position
    pid = await _mk_position(env)
    await env.db.settings.delete_many({"name": "election_phases"})
    base = {"student_id": "v1", "full_name": "Ayebale Elizabeth", "position_id": pid, "manifesto": "m"}
    r = await env.client.post("/apply", json={**base, "payment_proof_url": "javascript:alert(1)"})
    assert r.status_code == 400
    r = await env.client.post("/apply", json={**base, "image_url": "http://insecure/x.png"})
    assert r.status_code == 400
    r = await env.client.post("/apply", json={**base, "payment_method": "x" * 500})
    assert r.status_code == 422


# SEC-07: panel vote reason is bounded (it is written to the audit log).
async def test_vote_reason_is_length_bounded(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    r = await env.client.post(f"/admin/applications/{aid}/vote", headers=env.pan1,
                              json={"vote": "approve", "reason": "x" * 501})
    assert r.status_code == 422


# SEC-08: an external whose phase has no end date cannot be created or log in (fail closed).
async def test_external_with_phase_that_has_no_end_is_refused(env):
    await env.db.settings.delete_many({"name": "election_phases"})
    body = {"full_name": "Ext One", "email": "e1@x.org", "phone": "256700000009", "is_member": False,
            "appointment_reason": "auditor", "expires_with_phase": "vetting"}
    r = await env.client.post("/superadmin/vetting-panel", headers=env.sa, json=body)
    assert r.status_code == 400
    await _panelist(env, "PM-EXTNOEND", "noend@x.org", is_member=False, expires=None)
    assert (await _login(env, "noend@x.org")).status_code == 401


# SEC-10: a panel email may not equal another role's login email (branch order would hijack that login).
async def test_panel_email_cannot_collide_with_a_commissioner_email(env):
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"commissioner_email": "boss@x.org"}})
    body = {"full_name": "Ext One", "email": "BOSS@x.org", "phone": "256700000009", "is_member": False,
            "appointment_reason": "auditor",
            "access_expires_at": (_now() + timedelta(days=10)).isoformat()}
    assert (await env.client.post("/superadmin/vetting-panel", headers=env.sa, json=body)).status_code == 409


# SEC-11: tokens lacking exp/iat/jti are refused.
async def test_token_without_required_claims_is_rejected(env):
    import jwt as _jwt
    from auth import JWT_SECRET, JWT_ALGORITHM
    tok = _jwt.encode({"sub": "root", "role": "superadmin", "org_id": env.org_id}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    assert (await env.client.get("/admin/audit-log", headers=_h(tok))).status_code == 401
