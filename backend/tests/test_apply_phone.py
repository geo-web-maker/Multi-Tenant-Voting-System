"""Applicant phone number (nomination-form setting `collect_phone`): off by default; when on, the number is saved to the
voter record (only if it has none), the application continues, and nobody can change a record that already has a phone."""
import pytest

import main  # noqa: F401
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_nomination_form import put
from tests.test_nomination_upload import apply, position

pytestmark = pytest.mark.asyncio


async def phone_of(e, sid):
    return (await e.db.voters.find_one({"student_id": sid}))["phone_numbers"]


async def test_off_by_default_and_public_payload_unchanged(env):
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}
    pos = await position(env)
    await env.voter("np1", "No Phone", ())
    r = await apply(env, pos, sid="np1", name="No Phone", phone="0772123456")      # ignored while the toggle is off
    assert r.status_code == 200
    assert await phone_of(env, "np1") == []


async def test_toggle_is_public_even_with_nomination_section_off(env):
    assert (await put(env, collect_phone=True)).status_code == 200
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False, "collect_phone": True}


async def test_phone_is_saved_to_the_voter_and_application_continues(env):
    await put(env, collect_phone=True)
    pos = await position(env)
    await env.voter("np1", "No Phone", ())
    r = await apply(env, pos, sid="np1", name="No Phone", phone="0772 123 456")
    assert r.status_code == 200, r.text
    assert await phone_of(env, "np1") == ["256772123456"]
    app = await env.db.applications.find_one({"student_id": "np1"})
    assert app and "phone" not in app                                  # lives on the voter record only
    assert await env.db.audit_log.count_documents({"action": "applicant_phone_registered"}) in (0, 1)


async def test_missing_or_bad_phone_is_refused_before_anything_is_stored(env):
    await put(env, collect_phone=True)
    pos = await position(env)
    await env.voter("np1", "No Phone", ())
    assert (await apply(env, pos, sid="np1", name="No Phone")).status_code == 400
    assert (await apply(env, pos, sid="np1", name="No Phone", phone="12")).status_code == 400
    assert await env.db.applications.count_documents({}) == 0 and await phone_of(env, "np1") == []
    r = await env.client.post("/apply/check-eligibility", json={"student_id": "np1", "full_name": "No Phone"})
    assert r.status_code == 400                                         # caught at the early eligibility step too


async def test_existing_phone_is_never_overwritten(env):
    await put(env, collect_phone=True)
    pos = await position(env)
    r = await apply(env, pos, sid="v1", phone="0772999999")           # v1 already has 256700111222
    assert r.status_code == 200
    assert await phone_of(env, "v1") == ["256700111222"]


async def test_number_already_on_another_voter_is_refused(env):
    await put(env, collect_phone=True)
    pos = await position(env)
    await env.voter("np1", "No Phone", ())
    r = await apply(env, pos, sid="np1", name="No Phone", phone="256700111222")   # belongs to v1
    assert r.status_code == 400 and "already registered" in r.json()["detail"]
    assert await phone_of(env, "np1") == []


async def test_toggle_needs_superadmin_and_a_reason(env):
    r = await env.client.put("/superadmin/nomination-form", headers=env.sa, json={"collect_phone": True})
    assert r.status_code in (400, 422)


async def test_apply_errors_use_the_orgs_own_name_for_the_id(env):
    """One branding change (id_label) must reach the apply errors too, exactly like the voter login."""
    await env.db.settings.insert_one({"name": "branding", "org_id": env.org_id, "id_label": "Student Number"})
    main.invalidate_settings(env.org_id, "branding")
    pos = await position(env)
    r = await apply(env, pos, sid="nobody", name="Nobody")
    assert r.status_code == 404 and "student number" in r.json()["detail"].lower()
    assert "Student ID" not in r.json()["detail"]
    r = await apply(env, pos, sid="v1", name="Totally Different")
    assert r.status_code == 400 and "this student number" in r.json()["detail"]
