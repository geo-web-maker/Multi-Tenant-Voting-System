"""Nomination form phase N3: staff read-back through an audited, short-lived signed link; role shaping never
exposes the upload id or storage key."""
import json

import pytest

import main
import nomination_storage
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_nomination_upload import apply, enable, position, store, upload  # noqa: F401  (fixtures/helpers)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def signer(monkeypatch):
    calls = []

    def fake_presign(key, filename, expires=300):
        calls.append((key, filename))
        return f"https://signed.example/{key}?X-Expires=300"
    monkeypatch.setattr(nomination_storage, "presigned_get_url", fake_presign)
    return calls


async def submitted(e, store, required=True, **kw):
    """One pending application that carries a signed form. Returns (application id, storage key)."""
    await enable(e, required=required, **kw)
    pos = await position(e)
    up = (await upload(e)).json()
    r = await apply(e, pos, nomination_upload_id=up["upload_id"])
    assert r.status_code in (200, 201), r.text
    doc = await e.db.applications.find_one({"student_id": "v1"})
    return str(doc["_id"]), f"nomination-forms/{e.org_id}/{up['upload_id']}.pdf"


def url(app_id):
    return f"/admin/applications/{app_id}/nomination-form"


# ------------------------------------------------------------------ read-back
async def test_vetting_panelist_gets_a_signed_link_and_every_view_is_audited(env, store, signer):
    await env.seed_panel()
    app_id, key = await submitted(env, store)
    r = await env.client.get(url(app_id), headers=env.pan1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == f"https://signed.example/{key}?X-Expires=300"
    assert body["filename"] == "signed.pdf" and body["kind"] == "pdf" and body["expires_in"] == 300
    assert r.headers["cache-control"] == "no-store"
    assert signer == [(key, "signed.pdf")]
    await env.client.get(url(app_id), headers=env.pan2)
    logs = [l async for l in env.db.audit_log.find({"action": "nomination_form_viewed"})]
    assert [l["actor"] for l in logs] == ["PM-COM1", "PM-COM2"]
    assert all(l["details"]["application_id"] == app_id for l in logs)
    assert key not in json.dumps([l["details"] for l in logs], default=str)


@pytest.mark.parametrize("who", ["sa", "over"])
async def test_superadmin_and_overseer_get_a_signed_link(env, store, signer, who):
    app_id, _ = await submitted(env, store)
    r = await env.client.get(url(app_id), headers=getattr(env, who))
    assert r.status_code == 200 and r.json()["url"].startswith("https://signed.example/")


async def test_commissioner_is_denied_while_pending_and_allowed_once_resolved(env, store, signer):
    app_id, _ = await submitted(env, store)
    assert (await env.client.get(url(app_id), headers=env.com1)).status_code == 403
    assert not signer and not [l async for l in env.db.audit_log.find({"action": "nomination_form_viewed"})]
    await env.db.applications.update_one({"student_id": "v1"}, {"$set": {"status": "approved"}})
    assert (await env.client.get(url(app_id), headers=env.com1)).status_code == 200


async def test_other_roles_and_anonymous_callers_are_refused(env, store, signer):
    app_id, _ = await submitted(env, store)
    assert (await env.client.get(url(app_id), headers=env.it)).status_code == 403
    assert (await env.client.get(url(app_id), headers=env.tok("fc1", "financial_controller"))).status_code == 403
    assert (await env.client.get(url(app_id))).status_code in (401, 403)
    assert not signer


async def test_view_only_superadmin_session_is_recorded_with_the_viewer(env, store, signer):
    await env.seed_panel()
    app_id, _ = await submitted(env, store)
    tok = main.create_access_token(subject="PM-COM1", role="vetting", org_id=env.org_id,
                                   extra_claims={"view_only": True, "viewer": "root"})
    r = await env.client.get(url(app_id), headers={"Authorization": "Bearer " + tok, "X-Org-Slug": "t1"})
    assert r.status_code == 200
    log = await env.db.audit_log.find_one({"action": "nomination_form_viewed"})
    assert log["details"]["viewed_by_superadmin"] == "root"


async def test_application_without_a_form_unknown_and_malformed_ids(env, store, signer):
    await enable(env, required=False)
    pos = await position(env)
    await apply(env, pos)                                         # optional form skipped
    app_id = str((await env.db.applications.find_one({"student_id": "v1"}))["_id"])
    assert (await env.client.get(url(app_id), headers=env.sa)).status_code == 404
    assert (await env.client.get(url("64b64b64b64b64b64b64b64b"), headers=env.sa)).status_code == 404
    assert (await env.client.get(url("not-an-id"), headers=env.sa)).status_code in (400, 404, 422)
    assert not signer


async def test_form_from_another_org_is_never_reachable(env, store, signer):
    app_id, _ = await submitted(env, store)
    other = await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    tok = main.create_access_token(subject="root", role="superadmin", org_id=str(other.inserted_id))
    r = await env.client.get(url(app_id), headers={"Authorization": "Bearer " + tok, "X-Org-Slug": "t2"})
    assert r.status_code == 404 and not signer


async def test_storage_not_configured_is_503_and_failure_is_502_with_no_audit_row(env, store, signer, monkeypatch):
    app_id, _ = await submitted(env, store)
    store.configured = False
    assert (await env.client.get(url(app_id), headers=env.sa)).status_code == 503
    store.configured = True

    def boom(*a, **k):
        raise RuntimeError("bucket down")
    monkeypatch.setattr(nomination_storage, "presigned_get_url", boom)
    assert (await env.client.get(url(app_id), headers=env.sa)).status_code == 502
    assert not [l async for l in env.db.audit_log.find({"action": "nomination_form_viewed"})]


# ------------------------------------------------------------------ role shaping
async def test_no_role_ever_receives_the_upload_id_or_storage_key(env, store, signer):
    await env.seed_panel()
    app_id, key = await submitted(env, store)
    upload_id = (await env.db.applications.find_one({"student_id": "v1"}))["nomination_form"]["upload_id"]
    await env.db.applications.update_one({"student_id": "v1"}, {"$set": {"status": "approved"}})   # commission can list it
    for who in ("sa", "over", "pan1", "com1", "it", "fc"):
        h = env.tok("fc1", "financial_controller") if who == "fc" else getattr(env, who)
        r = await env.client.get("/admin/applications", headers=h)
        if r.status_code != 200:
            continue
        assert upload_id not in r.text and key not in r.text and "nomination-forms" not in r.text, who
        row = r.json()[0]
        assert "nomination_form" not in row
        assert row["has_nomination_form"] is True and row["nomination_form_filename"] == "signed.pdf"
        assert row["nomination_form_required"] is True


async def test_required_flag_is_a_snapshot_and_old_applications_default_to_not_required(env, store, signer):
    app_id, _ = await submitted(env, store, required=True)
    await enable(env, required=False)                             # setting changes after submission
    rows = (await env.client.get("/admin/applications", headers=env.sa)).json()
    assert rows[0]["nomination_form_required"] is True            # history is not rewritten
    await env.db.applications.update_one({"student_id": "v1"}, {"$unset": {"nomination_form_required": "", "nomination_form": ""}})
    row = (await env.client.get("/admin/applications", headers=env.sa)).json()[0]
    assert row["has_nomination_form"] is False and row["nomination_form_filename"] is None
    assert row["nomination_form_required"] is False


async def test_optional_form_skipped_is_stored_as_not_required(env, store, signer):
    await enable(env, required=False)
    pos = await position(env)
    await apply(env, pos)
    doc = await env.db.applications.find_one({"student_id": "v1"})
    assert doc["nomination_form_required"] is False and doc["nomination_form"] is None


async def test_candidate_status_page_and_snapshot_do_not_carry_the_form(env, store, signer):
    app_id, key = await submitted(env, store)
    doc = await env.db.applications.find_one({"student_id": "v1"})
    assert "nomination" not in json.dumps(doc["application_snapshot"], default=str)
    assert key not in json.dumps(doc["application_snapshot"], default=str)
