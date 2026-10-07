"""Nomination form settings (phase N1): public read, superadmin write with reason + audit, blank-form upload.

Applicant upload (/apply/upload-document), /apply changes and read-back arrive in N2/N3 and get their tests there."""
import io
import zipfile

import pytest

import main  # noqa: F401
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def make_docx(extra=(), omit=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("[Content_Types].xml", "word/document.xml"):
            if name not in omit:
                z.writestr(name, "<x/>")
        for name in extra:
            z.writestr(name, "x")
    return buf.getvalue()


async def put(e, who=None, **body):
    return await e.client.put("/superadmin/nomination-form", headers=who or e.sa,
                              json={"reason": "initial setup", **body})


async def upload(e, content, name="form.pdf", who=None, reason="new blank form"):
    return await e.client.post("/superadmin/nomination-form/template", headers=who or e.sa,
                               files={"file": (name, content, "application/octet-stream")},
                               data={"reason": reason} if reason is not None else {})


@pytest.fixture
def cloud(monkeypatch):
    calls = []

    def fake_upload(content, **kw):
        calls.append({"size": len(content), **kw})
        return {"secure_url": f"https://res.example.com/raw/upload/{kw['public_id']}"}
    monkeypatch.setattr(main.cloudinary.uploader, "upload", fake_upload)
    return calls


# ---------------------------------------------------------------- public read
async def test_public_read_when_never_configured_is_a_bare_disabled_flag(env):
    r = await env.client.get("/nomination-form")          # no auth, like an applicant
    assert r.status_code == 200 and r.json() == {"enabled": False}


async def test_public_read_hides_everything_when_disabled(env):
    await put(env, enabled=True, instructions="Sign it.", title="Form")
    await put(env, enabled=False)
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}


async def test_public_read_returns_only_what_an_applicant_needs(env):
    await put(env, enabled=True, title="Nomination Form", instructions="Download, sign, upload.")
    body = (await env.client.get("/nomination-form")).json()
    assert set(body) == {"enabled", "required", "title", "instructions", "template_file", "accepted_types", "max_mb"}
    assert body["enabled"] is True and body["required"] is True
    assert body["accepted_types"] == ["pdf"] and body["max_mb"] == 5 and body["template_file"] is None


# ---------------------------------------------------------------- superadmin write
async def test_put_stores_audits_and_is_read_straight_back(env):
    r = await put(env, enabled=True, required=False, title="  Guild   Nomination ", instructions="Line one\r\nLine two",
                  accepted_types=["DOCX", "pdf"], max_mb=8)
    assert r.status_code == 200, r.text
    got = (await env.client.get("/nomination-form")).json()
    assert got["title"] == "Guild Nomination" and got["instructions"] == "Line one\nLine two"
    assert got["accepted_types"] == ["pdf", "docx"] and got["max_mb"] == 8 and got["required"] is False
    log = await env.db.audit_log.find_one({"action": "nomination_form_changed"})
    assert log["details"]["reason"] == "initial setup"
    assert log["details"]["old"]["enabled"] is False and log["details"]["new"]["enabled"] is True


async def test_partial_update_leaves_other_fields_alone(env):
    await put(env, enabled=True, title="Original", instructions="Keep me", max_mb=3)
    await put(env, max_mb=4)
    got = (await env.client.get("/nomination-form")).json()
    assert got["title"] == "Original" and got["instructions"] == "Keep me" and got["max_mb"] == 4


async def test_reason_is_required(env):
    for reason in ("", "  ", "ab"):
        r = await env.client.put("/superadmin/nomination-form", headers=env.sa, json={"reason": reason, "enabled": True})
        assert r.status_code == 400
    assert (await env.client.put("/superadmin/nomination-form", headers=env.sa, json={"enabled": True})).status_code == 422
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}


async def test_validation(env):
    assert (await put(env, title="x" * 81)).status_code == 400
    assert (await put(env, title="   ")).status_code == 400
    assert (await put(env, instructions="x" * 2001)).status_code == 400
    assert (await put(env, instructions="bad\x00text")).status_code == 400
    assert (await put(env, accepted_types=["exe"])).status_code == 400
    assert (await put(env, accepted_types=[])).status_code == 400
    assert (await put(env, accepted_types=["pdf", "zip"])).status_code == 400
    assert (await put(env, max_mb=0)).status_code == 400
    assert (await put(env, max_mb=11)).status_code == 400
    assert (await put(env, template_file={"url": "http://example.com/f.pdf"})).status_code == 400
    assert (await put(env, template_file={"url": "javascript:alert(1)"})).status_code == 400
    assert (await put(env, template_file={"url": "https://"})).status_code == 400
    assert (await put(env, template_file={"url": "https://x.example/f.pdf"}, clear_template_file=True)).status_code == 400
    assert await env.db.settings.find_one({"name": "nomination_form"}) is None       # nothing half-written


async def test_instructions_are_plain_text_not_html(env):
    """Stored as given (the UI renders newlines as paragraphs, never as HTML); the API must not interpret it."""
    await put(env, instructions="<script>alert(1)</script>\n\nSecond paragraph")
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}   # still disabled -> no leak
    await put(env, enabled=True)
    assert "<script>" in (await env.client.get("/nomination-form")).json()["instructions"]


async def test_nothing_to_change_is_400(env):
    await put(env, enabled=True)
    assert (await put(env, enabled=True)).status_code == 400
    assert (await put(env)).status_code == 400


async def test_https_template_url_accepted_and_filename_sanitised(env):
    r = await put(env, enabled=True, template_file={"url": "https://files.example.com/a.pdf",
                                                    "filename": "..\\..\\etc/pass<wd>.pdf"})
    assert r.status_code == 200, r.text
    tf = (await env.client.get("/nomination-form")).json()["template_file"]
    assert tf == {"url": "https://files.example.com/a.pdf", "filename": "passwd.pdf"}
    r = await put(env, clear_template_file=True)
    assert r.status_code == 200 and r.json()["template_file"] is None


async def test_only_superadmin_can_change_it(env):
    for who in (env.it, env.com1, env.over):
        assert (await put(env, who, enabled=True)).status_code == 403
    assert (await env.client.put("/superadmin/nomination-form",
                                 json={"reason": "x y z", "enabled": True})).status_code in (401, 403)
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}


async def test_settings_cache_is_invalidated_on_write(env, monkeypatch):
    monkeypatch.setattr(main, "_SETTINGS_TTL", 60.0)          # opt in to the cache for this test
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}   # primes the cache
    await put(env, enabled=True, title="Fresh")
    assert (await env.client.get("/nomination-form")).json()["title"] == "Fresh"


async def test_settings_are_per_organisation(env):
    other = await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    await put(env, enabled=True, title="Org one")
    r = await env.client.get("/nomination-form", headers={"X-Org-Slug": "t2"})
    assert r.status_code == 200 and r.json() == {"enabled": False}
    assert str(other.inserted_id) != env.org_id


# ---------------------------------------------------------------- blank-form upload
async def test_template_upload_pdf(env, cloud):
    r = await upload(env, PDF, "Guild Form.pdf")
    assert r.status_code == 200, r.text
    tf = r.json()["template_file"]
    assert tf["filename"] == "Guild Form.pdf" and tf["url"].startswith("https://")
    assert cloud[0]["resource_type"] == "raw" and cloud[0]["public_id"].endswith(".pdf")
    assert env.org_id in cloud[0]["folder"]
    await put(env, enabled=True)
    assert (await env.client.get("/nomination-form")).json()["template_file"] == tf
    log = await env.db.audit_log.find_one({"action": "nomination_form_template_uploaded"})
    assert log["details"]["reason"] == "new blank form" and log["details"]["type"] == "pdf"
    assert "url" not in log["details"]


async def test_template_upload_docx_and_filename_follows_real_type(env, cloud):
    r = await upload(env, make_docx(), "form.pdf")                 # lying filename: the bytes decide
    assert r.status_code == 200 and r.json()["template_file"]["filename"] == "form.docx"
    assert cloud[0]["public_id"].endswith(".docx")


async def test_template_upload_rejects_bad_files(env, cloud):
    assert (await upload(env, b"MZ\x90\x00 not a pdf", "form.pdf")).status_code == 400          # wrong magic bytes
    assert (await upload(env, b"<html>%PDF-</html>", "form.pdf")).status_code == 400
    assert (await upload(env, b"PK\x03\x04 garbage", "form.docx")).status_code == 400           # zip prefix only
    assert (await upload(env, make_docx(omit=("word/document.xml",)), "f.docx")).status_code == 400
    assert (await upload(env, make_docx(extra=("word/vbaProject.bin",)), "f.docx")).status_code == 400
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("hello.txt", "hi")
    assert (await upload(env, plain_zip.getvalue(), "f.docx")).status_code == 400
    assert (await upload(env, PDF + b"0" * (10 * 1024 * 1024), "big.pdf")).status_code == 400   # oversize
    assert cloud == []                                              # nothing reached storage
    assert (await env.client.get("/nomination-form")).json() == {"enabled": False}


async def test_template_upload_needs_reason_and_superadmin(env, cloud):
    assert (await upload(env, PDF, reason="")).status_code == 400
    assert (await upload(env, PDF, reason=None)).status_code == 400
    for who in (env.it, env.com1, env.over):
        assert (await upload(env, PDF, who=who)).status_code == 403
    assert cloud == []


async def test_template_upload_storage_failure_is_502_and_changes_nothing(env, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("cloudinary down")
    monkeypatch.setattr(main.cloudinary.uploader, "upload", boom)
    assert (await upload(env, PDF)).status_code == 502
    assert await env.db.settings.find_one({"name": "nomination_form"}) is None


async def test_replacing_the_template_is_logged_as_a_replacement(env, cloud):
    await upload(env, PDF)
    await upload(env, PDF)
    logs = [l async for l in env.db.audit_log.find({"action": "nomination_form_template_uploaded"})]
    assert [l["details"]["replaced"] for l in logs] == [False, True]


# ---------------------------------------------------------------- sniffing helper (reused by N2)
async def test_sniff_respects_accepted_types():
    assert main._sniff_document(PDF, ["pdf"]) == "pdf"
    assert main._sniff_document(make_docx(), ["pdf", "docx"]) == "docx"
    with pytest.raises(main.HTTPException) as exc:
        main._sniff_document(make_docx(), ["pdf"])                   # valid docx, but this org only takes PDF
    assert exc.value.status_code == 400
    with pytest.raises(main.HTTPException):
        main._sniff_document(PDF, ["docx"])


async def test_safe_filename():
    assert main._safe_filename("C:\\Users\\me\\form.pdf") == "form.pdf"
    assert main._safe_filename("../../x\x00y.pdf") == "xy.pdf"
    assert main._safe_filename("") == "document" and main._safe_filename("...") == "document"
    assert len(main._safe_filename("a" * 400 + ".pdf")) <= main.NOMINATION_FILENAME_MAX
    assert main._safe_filename("a" * 400 + ".pdf").endswith(".pdf")
