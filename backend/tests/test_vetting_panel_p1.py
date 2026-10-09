"""Phase One of the Vetting Panel change (guide section 9, P1).

Done when: a panelist can log in and a linked commissioner can switch; nothing else changes.
Reuses the `env` fixture from test_flows (in-memory Mongo, org, token helper).
"""
from datetime import datetime, timedelta

import pytest

import main
from auth import create_access_token
from main import hash_password
from tests.test_flows import env, START, Clock  # noqa: F401  (fixture + helpers)


def _now():
    """The server reads the fake clock (test_flows.Clock), so expiries must be built from it."""
    return Clock.now

pytestmark = pytest.mark.asyncio

PW = "Tempw0rd!XZ"


@pytest.fixture(autouse=True)
def _install_revocation_hook(monkeypatch):
    """Production wires the revocation check in the app lifespan (main.py ~line 205). The test
    ASGI client does not run lifespan, so without this the revoked-token path is never exercised
    and a logged-out / switched-away token would still work in tests. Install it explicitly so
    revocation is tested for real."""
    import auth
    monkeypatch.setattr(auth, "_revocation_check", main._is_token_revoked)
    yield


async def _panelist(e, pmid="PM-AAA111", email="pan@x.org", *, is_member=True,
                    student_id=None, active=True, must_change=False, expires=None, sessions_after=None):
    doc = {
        "org_id": e.org_id, "panel_member_id": pmid, "full_name": "Panel One",
        "email": email, "phone_numbers": ["256700000001"], "is_member": is_member,
        "student_id": student_id, "active": active,
        "password_hash": hash_password(PW), "must_change_password": must_change,
        "access_expires_at": expires, "appointment_reason": "test",
    }
    if sessions_after:
        doc["sessions_valid_after"] = sessions_after
    await e.db.panel_members.insert_one(doc)
    return doc


def _login(e, email, pw=PW):
    return e.client.post("/verify-admin", json={"email": email, "password": pw})


# ---- Login ----------------------------------------------------------------------------------
async def test_panelist_can_log_in_with_role_vetting(env):
    await _panelist(env)
    r = await _login(env, "pan@x.org")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "vetting"
    assert body["panel_member_id"] == "PM-AAA111"
    assert body["is_member"] is True


async def test_external_panelist_logs_in_with_no_voter_row(env):
    await _panelist(env, "PM-EXT001", "ext@x.org", is_member=False,
                    expires=_now() + timedelta(days=30))
    assert await env.db.voters.count_documents({"email": "ext@x.org"}) == 0
    r = await _login(env, "ext@x.org")
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "vetting"
    assert r.json()["is_member"] is False


async def test_wrong_password_is_rejected_for_panelist(env):
    await _panelist(env)
    assert (await _login(env, "pan@x.org", "nope-nope")).status_code == 401


async def test_inactive_panelist_cannot_log_in(env):
    await _panelist(env, active=False)
    assert (await _login(env, "pan@x.org")).status_code == 401


async def test_expired_external_cannot_log_in(env):
    await _panelist(env, "PM-EXP001", "old@x.org", is_member=False,
                    expires=_now() - timedelta(minutes=1))
    assert (await _login(env, "old@x.org")).status_code == 401


# ---- Guard: a panel token is only good while the account is live ----------------------------
async def test_panel_token_stops_working_when_deactivated(env):
    await _panelist(env)
    tok = (await _login(env, "pan@x.org")).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"}
    # /admin/applications is on the panel's allow-list; /admin/commissioners is not and would 403 either way.
    assert (await env.client.get("/admin/applications", headers=h)).status_code == 200  # live before deactivation
    await env.db.panel_members.update_one({"panel_member_id": "PM-AAA111"}, {"$set": {"active": False}})
    r = await env.client.get("/admin/applications", headers=h)
    assert r.status_code == 401


# ---- Password change: self only -------------------------------------------------------------
async def test_panelist_cannot_change_another_panelists_password(env):
    await _panelist(env, "PM-AAA111", "pan@x.org")
    await _panelist(env, "PM-BBB222", "other@x.org")
    tok = (await _login(env, "pan@x.org")).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"}
    r = await env.client.post("/admin/set-password", headers=h, json={
        "email": "other@x.org", "old_password": PW, "new_password": "Brand-new-pass9"})
    assert r.status_code == 403
    # The target account's password must be untouched.
    assert await _login(env, "other@x.org") and (await _login(env, "other@x.org", PW)).status_code == 200


async def test_panelist_can_change_own_password_and_clears_temp_flag(env):
    await _panelist(env, must_change=True)
    tok = (await _login(env, "pan@x.org")).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"}
    r = await env.client.post("/admin/set-password", headers=h, json={
        "email": "pan@x.org", "old_password": PW, "new_password": "Brand-new-pass9"})
    assert r.status_code == 200, r.text
    doc = await env.db.panel_members.find_one({"panel_member_id": "PM-AAA111"})
    assert doc["must_change_password"] is False


# ---- Superadmin: add panelists --------------------------------------------------------------
def _add(e, **over):
    body = {"full_name": "New Panelist", "email": "new@x.org", "phone": "256700000009",
            "is_member": False, "appointment_reason": "External auditor, vetting only",
            "affiliation": "Alumni association",
            "access_expires_at": (_now() + timedelta(days=20)).isoformat()}
    body.update(over)
    return e.client.post("/superadmin/vetting-panel", headers=e.sa, json=body)


async def test_superadmin_adds_external_with_reason_and_expiry(env):
    r = await _add(env)
    assert r.status_code == 200, r.text
    doc = await env.db.panel_members.find_one({"email": "new@x.org"})
    assert doc["is_member"] is False
    assert doc["appointment_reason"]
    assert doc["panel_member_id"].startswith("PM-")
    assert doc["access_expires_at"] is not None
    assert doc["active"] is True and doc["must_change_password"] is True
    assert await env.db.voters.count_documents({"email": "new@x.org"}) == 0


async def test_add_requires_reason(env):
    assert (await _add(env, appointment_reason="   ")).status_code == 400


async def test_external_requires_access_end(env):
    assert (await _add(env, access_expires_at=None, expires_with_phase=None)).status_code == 400


async def test_member_requires_linked_student(env):
    assert (await _add(env, is_member=True, student_id=None)).status_code == 400


async def test_member_must_exist_on_voter_roll(env):
    assert (await _add(env, is_member=True, student_id="NOPE")).status_code == 404


async def test_no_duplicate_email(env):
    await _add(env)
    assert (await _add(env)).status_code == 409


async def test_only_superadmin_can_add(env):
    r = await env.client.post("/superadmin/vetting-panel", headers=env.com1, json={})
    assert r.status_code in (401, 403)


async def test_panel_is_frozen_while_vetting_is_open(env, monkeypatch):
    monkeypatch.setattr(main, "_panel_open_guard", main._panel_open_guard)

    async def open_now(request):
        raise main.HTTPException(409, "frozen")
    monkeypatch.setattr(main, "_panel_open_guard", open_now)
    assert (await _add(env)).status_code == 409


# ---- Superadmin: minimum of 3 active panelists ----------------------------------------------
async def test_cannot_drop_below_three_active_panelists(env):
    for i in range(3):
        await _panelist(env, f"PM-{i:03d}", f"p{i}@x.org")
    r = await env.client.post("/superadmin/vetting-panel/PM-000/active?active=false", headers=env.sa)
    assert r.status_code == 409
    assert (await env.db.panel_members.find_one({"panel_member_id": "PM-000"}))["active"] is True


async def test_can_deactivate_when_four_remain_active(env):
    for i in range(4):
        await _panelist(env, f"PM-{i:03d}", f"p{i}@x.org")
    r = await env.client.post("/superadmin/vetting-panel/PM-000/active?active=false", headers=env.sa)
    assert r.status_code == 200
    assert (await env.db.panel_members.find_one({"panel_member_id": "PM-000"}))["active"] is False


# ---- Hat switch ------------------------------------------------------------------------------
async def _linked_commissioner(e, sid="com1", linked=True, voter_active=True):
    await e.voter(sid, "Commish One", ("256700111222",), is_commissioner=True,
                  commissioner_email="com1@x.org")
    if linked:
        await _panelist(e, "PM-LNK001", "com1@x.org", student_id=sid)
    return sid


def _tok(e, sub, role, jti=None):
    return {"Authorization": "Bearer " + create_access_token(subject=sub, role=role, org_id=e.org_id),
            "X-Org-Slug": "t1"}


async def test_linked_commissioner_switches_to_vetting_and_gets_new_token(env):
    await _linked_commissioner(env)
    h = _tok(env, "com1", "commission")
    r = await env.client.post("/admin/switch-hat", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "vetting"
    assert r.json()["access_token"]


async def test_switch_revokes_the_old_commission_token(env):
    await _linked_commissioner(env)
    h = _tok(env, "com1", "commission")
    new = (await env.client.post("/admin/switch-hat", headers=h)).json()["access_token"]
    # The old commission token is now revoked: using it fails.
    r = await env.client.get("/admin/commissioners", headers=h)
    assert r.status_code == 401
    # The new vetting token works.
    r = await env.client.get("/admin/commissioners",
                             headers={"Authorization": f"Bearer {new}", "X-Org-Slug": "t1"})
    assert r.status_code != 401


async def test_commissioner_not_on_panel_cannot_switch(env):
    await _linked_commissioner(env, linked=False)
    r = await env.client.post("/admin/switch-hat", headers=_tok(env, "com1", "commission"))
    assert r.status_code == 403


async def test_inactive_panel_record_blocks_switch(env):
    await _linked_commissioner(env)
    await env.db.panel_members.update_one({"panel_member_id": "PM-LNK001"}, {"$set": {"active": False}})
    r = await env.client.post("/admin/switch-hat", headers=_tok(env, "com1", "commission"))
    assert r.status_code == 403


async def test_switch_back_returns_to_commissioner_view(env):
    await _linked_commissioner(env)
    to_panel = (await env.client.post("/admin/switch-hat",
                headers=_tok(env, "com1", "commission"))).json()["access_token"]
    h = {"Authorization": f"Bearer {to_panel}", "X-Org-Slug": "t1"}
    r = await env.client.post("/admin/switch-hat", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "commission"


async def test_superadmin_cannot_switch_and_unlinked_admin_cannot(env):
    assert (await env.client.post("/admin/switch-hat", headers=env.sa)).status_code == 403
    assert (await env.client.post("/admin/switch-hat", headers=env.it)).status_code == 403   # not on the panel


# ---- Migration script ------------------------------------------------------------------------
async def test_migration_makes_each_commissioner_an_inactive_linked_member(env):
    await env.voter("c1", "Comm A", is_commissioner=True)
    await env.voter("c2", "Comm B", is_commissioner=True)
    from migrate_create_vetting_panel import main as mig
    await mig(apply=True, only_org=None, db=env.db)
    rows = [p async for p in env.db.panel_members.find({"org_id": env.org_id})]
    # The fixture seeds com1/com2 as commissioners too, so all four are expected.
    assert {r["student_id"] for r in rows} == {"c1", "c2", "com1", "com2"}
    assert all(r["is_member"] and not r["active"] for r in rows)


async def test_migration_is_idempotent(env):
    await env.voter("c1", "Comm A", is_commissioner=True)
    from migrate_create_vetting_panel import main as mig
    await mig(apply=True, only_org=None, db=env.db)
    await mig(apply=True, only_org=None, db=env.db)
    # Four commissioners (c1 plus the fixture's com1/com2 and the seeded one) -> exactly four records, not eight.
    total = await env.db.panel_members.count_documents({"org_id": env.org_id})
    assert total == await env.db.voters.count_documents({"org_id": env.org_id, "is_commissioner": True})


async def test_migration_dry_run_changes_nothing(env):
    await env.voter("c1", "Comm A", is_commissioner=True)
    from migrate_create_vetting_panel import main as mig
    await mig(apply=False, only_org=None, db=env.db)
    assert await env.db.panel_members.count_documents({}) == 0


# ---- Link a commissioner to the panel with no separate login ---------------------------------
async def test_linking_a_commissioner_needs_no_credentials_and_hat_switch_works(env):
    await _linked_commissioner(env, linked=False)
    r = await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa,
                              json={"student_id": "com1", "appointment_reason": "Serving commissioner"})
    assert r.status_code == 200, r.text
    assert r.json()["sms_notified"] is False
    rec = await env.db.panel_members.find_one({"student_id": "com1"})
    assert rec["active"] is True and rec["is_member"] is True
    assert rec["password_hash"] == "" and rec["email"] == ""          # nothing to log in with
    # ...and the commissioner reaches the panel through their own screen.
    sw = await env.client.post("/admin/switch-hat", headers=_tok(env, "com1", "commission"))
    assert sw.status_code == 200 and sw.json()["role"] == "vetting"


async def test_link_commissioner_requires_a_reason_and_logs_it(env):
    await _linked_commissioner(env, linked=False)
    body = {"student_id": "com1", "appointment_reason": "   "}
    assert (await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa, json=body)).status_code == 400
    assert await env.db.panel_members.count_documents({}) == 0
    body["appointment_reason"] = "Chairs the exercise"
    assert (await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa, json=body)).status_code == 200
    row = await env.db.audit_log.find_one({"action": "vetting_panel_member_added"})
    assert row["details"]["reason"] == "Chairs the exercise" and row["details"]["linked_commissioner"] is True


async def test_link_commissioner_rejects_non_commissioners_and_duplicates(env):
    await env.voter("plain1", "Plain Voter", ("256700999000",))
    body = {"student_id": "plain1", "appointment_reason": "x"}
    assert (await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa, json=body)).status_code == 404
    await _linked_commissioner(env, linked=False)
    ok = {"student_id": "com1", "appointment_reason": "x"}
    assert (await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa, json=ok)).status_code == 200
    assert (await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa, json=ok)).status_code == 409


async def test_a_linked_commissioner_cannot_log_in_directly(env):
    await _linked_commissioner(env, linked=False)
    await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa,
                          json={"student_id": "com1", "appointment_reason": "x"})
    for pw in ("", "anything"):
        assert (await _login(env, "", pw)).status_code in (401, 404, 422)
