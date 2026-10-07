"""Demo Mode D1-D3 integration coverage.

The shared ``env`` fixture supplies an isolated mongomock-motor tenant, authenticated
superadmin headers, and the project fake clock.  These tests focus on the safety
contract in the implementation guide rather than UI rendering.
"""
from datetime import timedelta

import pytest

import main
from tests.test_flows import env, Clock  # noqa: F401

pytestmark = pytest.mark.asyncio


async def enable(e, days=3, reason="client demo"):
    r = await e.client.post("/superadmin/demo/enable", headers=e.sa,
                            json={"reason": reason, "days": days})
    assert r.status_code == 200, r.text
    return r.json()


async def seed(e):
    r = await e.client.post("/superadmin/demo/seed", headers=e.sa)
    assert r.status_code == 200, r.text
    return r.json()


async def test_inbox_is_404_when_off_and_after_expiry(env):
    assert (await env.client.get("/demo/inbox")).status_code == 404
    await enable(env, days=1)
    assert (await env.client.get("/demo/inbox")).status_code == 200
    await env.db.settings.update_one({"name": "demo_mode"}, {"$set": {"expires_at": Clock.now - timedelta(seconds=1)}})
    main.invalidate_settings(env.org_id, main.DEMO_SETTING)
    assert (await env.client.get("/demo/inbox")).status_code == 404


async def test_capture_reserved_number_skips_provider_and_budget(env, monkeypatch):
    await enable(env)
    await seed(env)
    provider_called = {"value": False}

    async def fail_egosms(*args, **kwargs):
        provider_called["value"] = True
        raise AssertionError("Demo SMS must never call an SMS provider")

    async def fail_mambosms(*args, **kwargs):
        provider_called["value"] = True
        raise AssertionError("Demo SMS must never call an SMS provider")

    monkeypatch.setattr(main, "send_sms_via_egosms", fail_egosms)
    monkeypatch.setattr(main, "send_sms_via_mambosms", fail_mambosms)
    r = await env.client.post("/verify-identity", json={"student_id": "DEMO-005", "full_name": "Demo Voter 005"})
    assert r.status_code == 200, r.text
    assert not provider_called["value"]
    assert await env.db.sms_usage.count_documents({"org_key": env.org_id}) == 0
    messages = await env.db.demo_inbox.find({}).to_list(length=10)
    assert len(messages) == 1 and messages[0]["to"].startswith(main.DEMO_PHONE_PREFIX)
    otp = await env.db.otps.find_one({"student_id": "DEMO-005"})
    assert otp and otp.get("is_demo") is True
    code = otp["code"]
    assert (await env.client.post("/verify-otp", json={"student_id": "DEMO-005", "code": code})).status_code == 200


async def test_real_number_is_refused_and_never_stored(env):
    await enable(env)
    assert await main.send_sms_status(env.org_id, "256712345678", "Code is 123456.", kind="otp") == "failed"
    assert await env.db.demo_inbox.count_documents({}) == 0
    assert await env.db.audit_log.find_one({"action": "demo_sms_refused"})


async def test_enable_is_refused_after_applications_or_votes_exist(env):
    await env.db.applications.insert_one({"org_id": env.org_id, "student_id": "real-1"})
    r = await env.client.post("/superadmin/demo/enable", headers=env.sa,
                              json={"reason": "too late"})
    assert r.status_code == 409


async def test_seed_is_idempotent_and_returns_demo_credentials(env):
    await enable(env)
    first = await seed(env)
    second = await seed(env)
    assert first["status"] == second["status"] == "seeded"
    assert await env.db.voters.count_documents({"is_demo": True}) == 40
    assert await env.db.panel_members.count_documents({"is_demo": True}) == 3
    assert await env.db.applications.count_documents({"is_demo": True}) == 4
    assert first["credentials"]
    role = first["credentials"]["it admin"]
    assert role["password"]
    # The credentials are for actual demo accounts, not merely display text.
    login = await env.client.post("/verify-admin", headers={"X-Org-Slug": "t1"}, json={
        "email": role["email"], "password": role["password"]})
    assert login.status_code == 200
    assert login.json().get("role") == "it_admin"


async def test_phase_jumps_apply_real_gates_and_results_closes_voting(env):
    await enable(env)
    await seed(env)
    vet = await env.client.post("/superadmin/demo/phase", headers=env.sa, json={"phase": "vetting"})
    assert vet.status_code == 200, vet.text
    voting = await env.client.post("/superadmin/demo/phase", headers=env.sa, json={"phase": "voting"})
    assert voting.status_code == 200, voting.text
    config = await env.db.settings.find_one({"name": "election_config"})
    assert config["is_open"] is True
    assert await env.db.applications.count_documents({"is_demo": True, "status": "approved"}) >= 1
    assert await env.db.applications.count_documents({"is_demo": True, "finance_cleared": True}) >= 1
    assert await env.db.candidates.count_documents({"is_demo": True}) >= 1
    events = await env.client.post("/superadmin/demo/phase", headers=env.sa, json={"phase": "results"})
    assert events.status_code == 200, events.text
    config = await env.db.settings.find_one({"name": "election_config"})
    assert config["is_open"] is False


async def test_reset_deletes_only_demo_data_and_keeps_real_roster_and_branding(env):
    await env.voter("real-keep", "Real Keeper", ("256711111111",))
    await enable(env)
    await seed(env)
    r = await env.client.post("/superadmin/demo/reset", headers=env.sa, json={"reason": "reset for next walkthrough"})
    assert r.status_code == 200, r.text
    assert await env.db.voters.count_documents({"is_demo": True}) == 0
    assert await env.db.applications.count_documents({"is_demo": True}) == 0
    assert await env.db.panel_members.count_documents({"is_demo": True}) == 0
    assert await env.db.voters.find_one({"student_id": "real-keep"})
    assert await env.db.settings.find_one({"name": "branding", "org_name": "T1"})


async def test_disable_and_reset_refuse_when_demo_is_off(env):
    r = await env.client.post("/superadmin/demo/reset", headers=env.sa, json={"reason": "nope"})
    assert r.status_code == 409
    r = await env.client.post("/superadmin/demo/disable", headers=env.sa, json={"reason": "nope"})
    assert r.status_code == 409


async def test_inbox_is_capped(env):
    await enable(env)
    for i in range(main.DEMO_INBOX_MAX + 5):
        assert await main._demo_capture(env.org_id, "256700000101", f"Message {i}", "notice") == "ok"
    assert await env.db.demo_inbox.count_documents({}) == main.DEMO_INBOX_MAX


async def test_cache_invalidation_makes_enable_immediately_effective(env, monkeypatch):
    monkeypatch.setattr(main, "_SETTINGS_TTL", 60.0)
    assert await main._demo_active(env.org_id) is False
    await enable(env)
    assert await main._demo_active(env.org_id) is True


async def test_demo_seeded_voter_can_submit_nomination_and_panel_can_read_it(env, monkeypatch):
    import nomination_storage
    from auth import create_access_token
    from tests.test_nomination_form import PDF, put

    def fake_put(key, content, content_type):
        assert key.startswith(f"nomination-forms/{env.org_id}/")

    monkeypatch.setattr(nomination_storage, "is_configured", lambda: True)
    monkeypatch.setattr(nomination_storage, "put_object", fake_put)
    monkeypatch.setattr(nomination_storage, "presigned_get_url", lambda key, filename, expires=300: "https://files.example.test/signed")

    r = await put(env, enabled=True, required=True, title="Demo signed form")
    assert r.status_code == 200, r.text
    await enable(env)
    seeded = await seed(env)
    assert seeded["status"] == "seeded"

    position = await env.db.positions.find_one({"is_demo": True})
    assert position
    upload = await env.client.post("/apply/upload-document",
        files={"file": ("signed.pdf", PDF, "application/pdf")})
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["upload_id"]
    submit = await env.client.post("/apply", json={
        "student_id": "DEMO-020",
        "full_name": "Demo Voter 020",
        "position_id": str(position["_id"]),
        "manifesto": "A demo manifesto.",
        "payment_method": "Cash Receipt",
        "payment_proof_url": "",
        "nomination_upload_id": upload_id,
    })
    assert submit.status_code == 200, submit.text
    app = await env.db.applications.find_one({"student_id": "DEMO-020", "is_demo": True})
    assert app and app["nomination_form_required"] is True and app["nomination_form"]

    token = create_access_token(subject="DEMO-PANEL-1", role="vetting", org_id=env.org_id)
    view = await env.client.get(f"/admin/applications/{app['_id']}/nomination-form",
        headers={"Authorization": "Bearer " + token, "X-Org-Slug": "t1"})
    assert view.status_code == 200, view.text
    assert view.json()["url"] == "https://files.example.test/signed"
    audit = await env.db.audit_log.find_one({"action": "nomination_form_viewed", "application_id": str(app["_id"])})
    assert audit


async def test_reset_requires_a_reason(env):
    await env.client.post("/superadmin/demo/enable", headers=env.sa, json={"reason": "walkthrough prep", "days": 1})
    r = await env.client.post("/superadmin/demo/reset", headers=env.sa)
    assert r.status_code == 422
