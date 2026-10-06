"""Regression: a Vetting Panel account whose access ends with a timeline phase (expires_with_phase)
crashed auth_guard_middleware with AttributeError: 'State' object has no attribute 'org_id' on EVERY
guarded request (/admin/set-password, /admin/vetting-me, /admin/applications, ...).

Cause: auth_guard_middleware runs BEFORE org_context_middleware, so request.state.org_id is not set
yet when the guard calls _panel_access_ended -> get_phase_schedule(request).
"""
from datetime import timedelta

import pytest

import main
from tests.test_flows import env, START, Clock  # noqa: F401
from tests.test_vetting_panel_p1 import (  # noqa: F401
    _panelist, _login, _install_revocation_hook, PW, _now,
)

pytestmark = pytest.mark.asyncio


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"}


async def _phase_panelist(env, *, phase_end, must_change=False, is_member=False, pmid="PM-PH0001",
                          email="ph@x.org"):
    await env.db.settings.update_one(
        {"name": "election_phases", "org_id": env.org_id},
        {"$set": {"name": "election_phases", "org_id": env.org_id, "round_id": "round-1",
                  "phases": {"vetting": {"start": _now() - timedelta(days=1), "end": phase_end,
                                         "enforced": True}}}}, upsert=True)
    p = await _panelist(env, pmid, email, is_member=is_member, must_change=must_change, expires=None)
    await env.db.panel_members.update_one({"panel_member_id": pmid}, {"$set": {
        "expires_with_phase": "vetting",
        "confidentiality_version": main.CONFIDENTIALITY_VERSION}})
    return p


async def test_phase_bound_panelist_can_use_panel_routes(env):
    await _phase_panelist(env, phase_end=_now() + timedelta(days=5))
    r = await _login(env, "ph@x.org")
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    for path in ("/admin/vetting-me", "/admin/applications"):
        resp = await env.client.get(path, headers=_h(tok))
        assert resp.status_code == 200, (path, resp.text)


async def test_phase_bound_panelist_can_set_new_password(env):
    await _phase_panelist(env, phase_end=_now() + timedelta(days=5), must_change=True)
    r = await _login(env, "ph@x.org")
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    tok = r.json()["access_token"]
    resp = await env.client.post("/admin/set-password", headers=_h(tok), json={
        "email": "ph@x.org", "old_password": PW, "new_password": "Brand-New-Pw1!x"})
    assert resp.status_code == 200, resp.text
    assert (await _login(env, "ph@x.org", "Brand-New-Pw1!x")).status_code == 200


async def test_phase_bound_panelist_is_cut_off_once_the_phase_ends(env):
    await _phase_panelist(env, phase_end=_now() + timedelta(days=5))
    tok = (await _login(env, "ph@x.org")).json()["access_token"]
    await env.db.settings.update_one(
        {"name": "election_phases", "org_id": env.org_id},
        {"$set": {"phases.vetting.end": _now() - timedelta(minutes=1)}})
    resp = await env.client.get("/admin/vetting-me", headers=_h(tok))
    assert resp.status_code == 401, resp.text


# Second deadlock on the same first-login path: an EXTERNAL on a temp password has a token limited to
# /admin/set-password (scope), but the confidentiality gate only lets vetting-me / accept / logout
# through, so set-password was refused with confidentiality_required and the notice could not be
# accepted either (scope refused it).
async def test_external_on_temp_password_can_set_password_before_accepting_notice(env):
    await _panelist(env, "PM-EXT777", "ext7@x.org", is_member=False, must_change=True,
                    expires=_now() + timedelta(days=10))
    r = await _login(env, "ext7@x.org")
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    resp = await env.client.post("/admin/set-password", headers=_h(tok), json={
        "email": "ext7@x.org", "old_password": PW, "new_password": "Brand-New-Pw1!x"})
    assert resp.status_code == 200, resp.text
    tok2 = (await _login(env, "ext7@x.org", "Brand-New-Pw1!x")).json()["access_token"]
    me = await env.client.get("/admin/vetting-me", headers=_h(tok2))
    assert me.status_code == 200, me.text
    assert me.json()["confidentiality_accepted"] is False       # the notice still has to be accepted
    blocked = await env.client.get("/admin/applications", headers=_h(tok2))
    assert blocked.status_code == 403 and blocked.json().get("code") == "confidentiality_required"


# Third bug on the same path: the frontend re-logs in straight after /admin/set-password. The new token's
# iat is whole seconds, sessions_valid_after has microseconds, so a re-login inside the same second was
# rejected as "session ended". Tokens from an EARLIER second must still be refused.
async def test_token_minted_in_same_second_as_password_change_is_accepted(env):
    from datetime import datetime
    from auth import create_access_token
    await _panelist(env, "PM-SAME01", "same@x.org", is_member=True,
                    sessions_after=datetime.utcnow().replace(microsecond=999000))
    tok = create_access_token(subject="PM-SAME01", role="vetting", org_id=env.org_id, scope="full")
    r = await env.client.get("/admin/vetting-me", headers=_h(tok))
    assert r.status_code == 200, r.text


async def test_token_from_an_earlier_second_is_still_refused_after_password_change(env):
    from datetime import datetime
    from auth import create_access_token
    tok = create_access_token(subject="PM-OLD001", role="vetting", org_id=env.org_id, scope="full")
    await _panelist(env, "PM-OLD001", "old1@x.org", is_member=True,
                    sessions_after=datetime.utcnow() + timedelta(seconds=5))
    r = await env.client.get("/admin/vetting-me", headers=_h(tok))
    assert r.status_code == 401, r.text
