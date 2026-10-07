"""Nomination form phase N2: signed forms go to a private bucket via /apply/upload-document and are attached
to the application through /apply. Read-back (presigned links for staff) is N3 and gets its tests there."""
from datetime import timedelta

import pytest

import main
import nomination_storage
from tests.test_flows import env, Clock  # noqa: F401  (fixture)
from tests.test_nomination_form import PDF, make_docx, put

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(monkeypatch):
    """Fake private bucket: records puts and can be told to fail or to be unconfigured."""
    s = type("S", (), {})()
    s.puts, s.configured, s.fail = {}, True, False
    monkeypatch.setattr(nomination_storage, "is_configured", lambda: s.configured)
    monkeypatch.setattr(nomination_storage, "missing_settings", lambda: ["NOMINATION_B2_BUCKET_NAME"])

    def fake_put(key, content, content_type):
        if s.fail:
            raise RuntimeError("bucket down")
        s.puts[key] = (content, content_type)
    monkeypatch.setattr(nomination_storage, "put_object", fake_put)
    return s


async def enable(e, **kw):
    r = await put(e, enabled=True, **kw)
    assert r.status_code == 200, r.text


async def upload(e, content=PDF, name="signed.pdf"):
    return await e.client.post("/apply/upload-document", files={"file": (name, content, "application/pdf")})


async def position(e):
    r = await e.client.post("/positions", headers=e.sa, json={"title": "Speaker", "order": 1})
    assert r.status_code == 200, r.text
    await e.db.settings.delete_many({"name": "election_phases"})        # applications unscheduled = open
    return r.json()["id"]


async def apply(e, pos, sid="v1", name="Ayebale Elizabeth", **extra):
    return await e.client.post("/apply", json={"student_id": sid, "full_name": name, "position_id": pos,
                                               "manifesto": "m", **extra})


# ---------------------------------------------------------------- upload route
async def test_upload_when_form_disabled_is_refused(env, store):
    await position(env)
    assert (await upload(env)).status_code == 404 and not store.puts


async def test_upload_stores_privately_and_returns_only_an_opaque_id(env, store):
    await enable(env)
    await position(env)
    r = await upload(env, name="../../My Form.pdf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"upload_id", "filename", "kind", "bytes"}
    assert body["filename"] == "My Form.pdf" and body["kind"] == "pdf" and body["bytes"] == len(PDF)
    (key, (content, ctype)), = store.puts.items()
    assert key == f"nomination-forms/{env.org_id}/{body['upload_id']}.pdf" and content == PDF and ctype == "application/pdf"
    doc = await env.db.nomination_uploads.find_one({"upload_id": body["upload_id"]})
    assert doc["org_id"] == env.org_id and doc["status"] == "pending" and doc["key"] == key and len(doc["sha256"]) == 64
    assert "http" not in r.text and "nomination-forms" not in r.text


async def test_upload_checks_real_bytes_and_accepted_types(env, store):
    await enable(env)                                                # PDF only by default
    await position(env)
    assert (await upload(env, b"not a pdf at all", "x.pdf")).status_code == 400
    assert (await upload(env, make_docx(), "x.docx")).status_code == 400    # DOCX not accepted yet
    await enable(env, accepted_types=["pdf", "docx"])
    r = await upload(env, make_docx(), "x.docx")
    assert r.status_code == 200 and r.json()["kind"] == "docx"
    assert list(store.puts.values())[0][1].endswith("wordprocessingml.document")
    assert await env.db.nomination_uploads.count_documents({}) == 1


async def test_upload_respects_the_configured_size_limit(env, store):
    await enable(env, max_mb=1)
    await position(env)
    big = PDF + b"0" * (1024 * 1024)
    assert (await upload(env, big)).status_code == 400 and not store.puts


async def test_upload_when_storage_is_not_configured_is_503_and_leaves_nothing(env, store):
    await enable(env)
    await position(env)
    store.configured = False
    assert (await upload(env)).status_code == 503
    assert await env.db.nomination_uploads.count_documents({}) == 0


async def test_upload_when_the_bucket_fails_is_502_and_stores_no_record(env, store):
    await enable(env)
    await position(env)
    store.fail = True
    assert (await upload(env)).status_code == 502
    assert await env.db.nomination_uploads.count_documents({}) == 0


async def test_upload_is_closed_outside_the_applications_phase(env, store):
    await enable(env)
    await env.db.settings.insert_one({"name": "election_phases", "org_id": env.org_id,
                                      "phases": {"applications": {"enforced": True, "start": Clock.now - timedelta(days=3),
                                                                  "end": Clock.now - timedelta(days=1)}}})
    r = await upload(env)
    assert r.status_code in (400, 403) and not store.puts


# ---------------------------------------------------------------- /apply binding
async def test_apply_requires_the_form_when_enabled_and_required(env, store):
    await enable(env)
    pos = await position(env)
    r = await apply(env, pos)
    assert r.status_code == 400 and "nomination form" in r.json()["detail"]
    assert await env.db.applications.count_documents({}) == 0


async def test_apply_attaches_the_upload_and_keeps_the_key_out_of_the_application(env, store):
    await enable(env)
    pos = await position(env)
    up = (await upload(env)).json()
    r = await apply(env, pos, nomination_upload_id=up["upload_id"])
    assert r.status_code == 200, r.text
    app = await env.db.applications.find_one({"student_id": "v1"})
    assert app["nomination_form"] == {"upload_id": up["upload_id"], "filename": "signed.pdf", "kind": "pdf", "bytes": len(PDF)}
    assert "nomination_upload_id" not in app and "nomination-forms" not in str(app)
    doc = await env.db.nomination_uploads.find_one({"upload_id": up["upload_id"]})
    assert doc["status"] == "attached" and doc["student_id"] == "v1" and doc["application_id"] == str(app["_id"])
    log = await env.db.audit_log.find_one({"action": "application_submitted"})
    assert log["details"]["nomination_form"] == "signed.pdf"


async def test_an_upload_serves_one_application_only(env, store):
    await enable(env)
    pos = await position(env)
    await env.voter("v2", "Second Student")
    up = (await upload(env)).json()["upload_id"]
    assert (await apply(env, pos, nomination_upload_id=up)).status_code == 200
    r = await apply(env, pos, sid="v2", name="Second Student", nomination_upload_id=up)
    assert r.status_code == 400 and await env.db.applications.count_documents({}) == 1


async def test_unknown_stale_and_foreign_uploads_are_refused(env, store):
    await enable(env)
    pos = await position(env)
    assert (await apply(env, pos, nomination_upload_id="f" * 32)).status_code == 400
    old = (await upload(env)).json()["upload_id"]
    Clock.now = Clock.now + timedelta(hours=main.NOMINATION_UPLOAD_TTL_HOURS + 1)
    assert (await apply(env, pos, nomination_upload_id=old)).status_code == 400
    await env.db.nomination_uploads.insert_one({"upload_id": "a" * 32, "org_id": "other-org", "status": "pending",
                                                "uploaded_at": Clock.now, "key": "k", "filename": "x.pdf", "kind": "pdf", "bytes": 1})
    assert (await apply(env, pos, nomination_upload_id="a" * 32)).status_code == 400
    assert await env.db.applications.count_documents({}) == 0


async def test_optional_form_may_be_skipped(env, store):
    await enable(env, required=False)
    pos = await position(env)
    assert (await apply(env, pos)).status_code == 200
    assert (await env.db.applications.find_one({"student_id": "v1"}))["nomination_form"] is None


async def test_when_the_form_is_off_an_id_is_ignored_and_not_consumed(env, store):
    pos = await position(env)
    await env.db.nomination_uploads.insert_one({"upload_id": "b" * 32, "org_id": env.org_id, "status": "pending",
                                                "uploaded_at": Clock.now, "key": "k", "filename": "x.pdf", "kind": "pdf", "bytes": 1})
    assert (await apply(env, pos, nomination_upload_id="b" * 32)).status_code == 200
    assert (await env.db.nomination_uploads.find_one({"upload_id": "b" * 32}))["status"] == "pending"


# ---------------------------------------------------------------- storage helper
def test_presigned_link_is_short_lived_and_forces_a_download(monkeypatch):
    monkeypatch.setattr(nomination_storage, "_client", None)
    for n, v in zip(nomination_storage.ENV_NAMES, ("https://s3.us-west-004.backblazeb2.com", "kid", "secret", "forms-bucket")):
        monkeypatch.setenv(n, v)
    url = nomination_storage.presigned_get_url("nomination-forms/o/u.pdf", 'a"b\r\n.pdf', expires=99999)
    assert "X-Amz-Expires=300" in url and "forms-bucket" in url
    assert "attachment" in url and "%0D" not in url and "%22b" not in url
    monkeypatch.setattr(nomination_storage, "_client", None)


def test_storage_is_unconfigured_without_its_own_settings(monkeypatch):
    for n in nomination_storage.ENV_NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("B2_BUCKET_NAME", "backup-bucket")          # the backup values must never be borrowed
    assert not nomination_storage.is_configured()
    assert nomination_storage.missing_settings() == list(nomination_storage.ENV_NAMES)
    with pytest.raises(nomination_storage.StorageUnavailable):
        nomination_storage.put_object("k", b"x", "application/pdf")
