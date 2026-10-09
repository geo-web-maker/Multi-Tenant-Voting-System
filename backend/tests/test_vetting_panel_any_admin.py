"""Any admin role (not just commissioners) can be linked to the Vetting Panel and switch to it and back.
Overseer: access is paused while serving. Financial controller: deliberately no extra rule."""
import pytest

from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_vetting_panel_p1 import (  # noqa: F401
    _install_revocation_hook, _panelist, _tok)

pytestmark = pytest.mark.asyncio

ROLES = [("it_admin", "is_it_admin"), ("financial_controller", "is_financial_controller"),
         ("overseer", "is_overseer"), ("commission", "is_commissioner")]


async def _admin(env, role, flag, sid="adm1"):
    await env.voter(sid, "Admin One", ("256700555111",), **{flag: True})
    return sid


async def _link(env, sid):
    return await env.client.post("/superadmin/vetting-panel/link-commissioner", headers=env.sa,
                                 json={"student_id": sid, "appointment_reason": "Serving"})


@pytest.mark.parametrize("role,flag", ROLES)
async def test_every_admin_role_can_be_linked_and_has_no_login(env, role, flag):
    sid = await _admin(env, role, flag)
    r = await _link(env, sid)
    assert r.status_code == 200, r.text
    rec = await env.db.panel_members.find_one({"student_id": sid})
    assert rec["password_hash"] == "" and rec["email"] == "" and rec["active"] is True
    audit = await env.db.audit_log.find_one({"action": "vetting_panel_member_added"})
    assert audit["details"]["linked_roles"] == [role]


async def test_link_refuses_someone_with_no_admin_role(env):
    await env.voter("plain1", "Plain", ("256700999000",))
    assert (await _link(env, "plain1")).status_code == 404


@pytest.mark.parametrize("role,flag", [r for r in ROLES if r[0] != "overseer"])
async def test_admin_switches_to_panel_and_back_to_their_own_role(env, role, flag):
    sid = await _admin(env, role, flag)
    await _link(env, sid)
    r = await env.client.post("/admin/switch-hat", headers=_tok(env, sid, role))
    assert r.status_code == 200 and r.json()["role"] == "vetting" and r.json()["back_to"] == role
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Org-Slug": "t1"}
    back = await env.client.post("/admin/switch-hat", headers=h)
    assert back.status_code == 200 and back.json()["role"] == role


async def test_unlinked_admin_cannot_switch(env):
    sid = await _admin(env, "it_admin", "is_it_admin")
    assert (await env.client.post("/admin/switch-hat", headers=_tok(env, sid, "it_admin"))).status_code == 403


async def test_cannot_switch_back_to_a_role_no_longer_held(env):
    sid = await _admin(env, "financial_controller", "is_financial_controller")
    await _link(env, sid)
    to_panel = (await env.client.post("/admin/switch-hat", headers=_tok(env, sid, "financial_controller"))).json()["access_token"]
    await env.db.voters.update_one({"student_id": sid}, {"$set": {"is_financial_controller": False}})
    r = await env.client.post("/admin/switch-hat", headers={"Authorization": f"Bearer {to_panel}", "X-Org-Slug": "t1"})
    assert r.status_code == 403


async def test_financial_controller_gets_no_extra_rule(env):
    """Decision: allowed with no restriction; discouraged by people, not blocked by the system."""
    sid = await _admin(env, "financial_controller", "is_financial_controller")
    await _link(env, sid)
    r = await env.client.get("/admin/panel-link", headers=_tok(env, sid, "financial_controller"))
    assert r.json()["panel_linked"] is True and r.json()["overseer_paused"] is False


# ---- Overseer: paused while serving --------------------------------------------------------
async def test_overseer_access_is_paused_while_on_the_panel(env):
    sid = await _admin(env, "overseer", "is_overseer")
    h = _tok(env, sid, "overseer")
    assert (await env.client.get("/overseer/dashboard", headers=h)).status_code == 200   # before linking
    await _link(env, sid)
    r = await env.client.get("/overseer/dashboard", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "overseer_paused"
    # The few allowed paths still work, and say why the dashboard is closed.
    pl = await env.client.get("/admin/panel-link", headers=h)
    assert pl.status_code == 200 and pl.json()["overseer_paused"] is True


async def test_overseer_can_reach_the_panel_but_not_return_while_serving(env):
    sid = await _admin(env, "overseer", "is_overseer")
    await _link(env, sid)
    r = await env.client.post("/admin/switch-hat", headers=_tok(env, sid, "overseer"))
    assert r.status_code == 200 and r.json()["role"] == "vetting" and r.json()["back_label"] == "Overseer"
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Org-Slug": "t1"}
    assert (await env.client.post("/admin/switch-hat", headers=h)).status_code == 403


async def test_overseer_access_returns_when_service_ends(env):
    sid = await _admin(env, "overseer", "is_overseer")
    await _link(env, sid)
    await env.db.panel_members.update_one({"student_id": sid}, {"$set": {"active": False}})
    assert (await env.client.get("/overseer/dashboard", headers=_tok(env, sid, "overseer"))).status_code == 200


async def test_other_roles_are_not_paused_by_panel_service(env):
    sid = await _admin(env, "it_admin", "is_it_admin")
    await _link(env, sid)
    assert (await env.client.get("/it-admin/applications", headers=_tok(env, sid, "it_admin"))).status_code == 200


# ---- Picker data -----------------------------------------------------------------------------
async def test_panel_eligible_admins_lists_every_admin_role_with_labels(env):
    await env.voter("a1", "Alpha", ("256700000011",), is_it_admin=True, is_commissioner=True)
    await env.voter("b1", "Bravo", ("256700000012",), is_overseer=True)
    await env.voter("c1", "Plain", ("256700000013",))
    r = await env.client.get("/superadmin/panel-eligible-admins", headers=env.sa)
    assert r.status_code == 200
    by = {x["student_id"]: x["roles"] for x in r.json()}
    assert by["a1"] == ["Commissioner", "IT Admin"] and by["b1"] == ["Overseer"] and "c1" not in by
    assert (await env.client.get("/superadmin/panel-eligible-admins", headers=env.it)).status_code == 403
