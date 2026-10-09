"""Backend half of the Vetting Panel frontend-audit fixes: panel-link, view-as for panelists,
editing a panelist, and the Chairperson / frozen info on the panel list."""
from datetime import timedelta

import pytest

from auth import create_access_token
from tests.test_flows import env, Clock  # noqa: F401
from tests.test_vetting_panel_p1 import _panelist, _linked_commissioner, _tok, _install_revocation_hook  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_panel_link_false_for_commissioner_not_on_panel(env):
    await _linked_commissioner(env, linked=False)
    r = await env.client.get("/admin/panel-link", headers=_tok(env, "com1", "commission"))
    assert r.status_code == 200 and r.json()["panel_linked"] is False


async def test_panel_link_true_for_linked_commissioner_and_no_tie_for_non_chair(env):
    await _linked_commissioner(env)
    await env.db.applications.insert_one({"org_id": env.org_id, "status": "pending", "tied_pending_chief": True})
    r = await env.client.get("/admin/panel-link", headers=_tok(env, "com1", "commission"))
    assert r.json() == {"panel_linked": True, "tie_waiting": 0, "overseer_paused": False}


async def test_chairperson_is_told_how_many_ties_wait(env):
    await _linked_commissioner(env)
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    await env.db.applications.insert_many([
        {"org_id": env.org_id, "status": "pending", "tied_pending_chief": True},
        {"org_id": env.org_id, "status": "approved", "tied_pending_chief": True},   # resolved: not counted
    ])
    r = await env.client.get("/admin/panel-link", headers=_tok(env, "com1", "commission"))
    assert r.json()["tie_waiting"] == 1


async def test_panel_link_is_for_admin_roles_not_panel_tokens(env):
    # Any admin role may ask (the answer is only about the caller); a panel token may not.
    r = await env.client.get("/admin/panel-link", headers=env.it)
    assert r.status_code == 200 and r.json()["panel_linked"] is False
    await _panelist(env)
    tok = create_access_token(subject="PM-AAA111", role="vetting", org_id=env.org_id)
    r = await env.client.get("/admin/panel-link", headers={"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"})
    assert r.status_code == 403


async def test_superadmin_view_as_panelist_is_read_only_and_skips_confidentiality_gate(env):
    await _panelist(env, "PM-EXT001", "ext@x.org", is_member=False, expires=Clock.now + timedelta(days=30))
    r = await env.client.post("/superadmin/view-as", headers=env.sa,
                              json={"student_id": "PM-EXT001", "role": "vetting"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "vetting"
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Org-Slug": "t1"}
    # The external never accepted the notice, but a read-only diagnostic view is not gated by it.
    me = await env.client.get("/admin/vetting-me", headers=h)
    assert me.status_code == 200 and me.json()["confidentiality_required"] is False
    assert (await env.client.get("/admin/applications", headers=h)).status_code == 200
    # Strictly read-only.
    w = await env.client.post("/admin/vetting-confidentiality/accept", headers=h)
    assert w.status_code == 403


async def test_view_as_rejects_inactive_or_unknown_panelist(env):
    await _panelist(env, "PM-OFF001", "off@x.org", active=False)
    for pid in ("PM-OFF001", "PM-NOPE"):
        r = await env.client.post("/superadmin/view-as", headers=env.sa, json={"student_id": pid, "role": "vetting"})
        assert r.status_code == 404


async def test_patch_panelist_updates_details_and_keeps_an_end_for_externals(env):
    await _panelist(env, "PM-EXT001", "ext@x.org", is_member=False, expires=Clock.now + timedelta(days=30))
    r = await env.client.patch("/superadmin/vetting-panel/PM-EXT001", headers=env.sa,
                               json={"affiliation": "Alumni", "phone": "256700999888"})
    assert r.status_code == 200, r.text
    doc = await env.db.panel_members.find_one({"panel_member_id": "PM-EXT001"})
    assert doc["affiliation"] == "Alumni" and doc["phone_numbers"] == ["256700999888"]
    # An external may not have the end removed.
    r = await env.client.patch("/superadmin/vetting-panel/PM-EXT001", headers=env.sa, json={"clear_access_end": True})
    assert r.status_code == 400
    # Extending the date works and replaces any phase-based end.
    new_end = (Clock.now + timedelta(days=60)).isoformat()
    r = await env.client.patch("/superadmin/vetting-panel/PM-EXT001", headers=env.sa, json={"access_expires_at": new_end})
    assert r.status_code == 200
    assert (await env.db.panel_members.find_one({"panel_member_id": "PM-EXT001"}))["expires_with_phase"] is None


async def test_patch_panelist_404_and_nothing_to_change(env):
    await _panelist(env)
    assert (await env.client.patch("/superadmin/vetting-panel/PM-NOPE", headers=env.sa, json={"affiliation": "x"})).status_code == 404
    assert (await env.client.patch("/superadmin/vetting-panel/PM-AAA111", headers=env.sa, json={})).status_code == 400


async def test_panel_list_marks_chairperson_and_reports_rules(env):
    await _linked_commissioner(env)
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    r = await env.client.get("/superadmin/vetting-panel", headers=env.sa)
    body = r.json()
    assert body["min_panel"] == 3 and body["frozen"] is False
    assert [p["is_chair"] for p in body["panel"]] == [True]
