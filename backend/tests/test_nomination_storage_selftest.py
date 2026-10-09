"""'Test storage' (superadmin): proves the private bucket settings work without submitting an application."""
import io
import urllib.request

import pytest

import main  # noqa: F401
import nomination_storage as ns
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

SETTINGS = {"NOMINATION_B2_ENDPOINT": "https://s3.example.com", "NOMINATION_B2_KEY_ID": "id",
            "NOMINATION_B2_APPLICATION_KEY": "secret", "NOMINATION_B2_BUCKET_NAME": "bkt"}


class ClientError(Exception):
    def __init__(self, code, msg=""):
        self.response = {"Error": {"Code": code, "Message": msg}}
        super().__init__(code)


class FakeS3:
    """In-memory bucket. `deny` names an operation that fails with AccessDenied; `keep` ignores deletes (Object Lock)."""
    def __init__(self, deny=None, keep=False):
        self.files, self.deny, self.keep = {}, deny, keep

    def _check(self, op):
        if self.deny == op:
            raise ClientError("AccessDenied", f"not allowed to {op}")

    def put_object(self, Bucket, Key, Body, ContentType):
        self._check("put"); self.files[Key] = Body

    def get_object(self, Bucket, Key):
        self._check("get"); return {"Body": io.BytesIO(self.files[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.files:
            raise ClientError("404")
        return {}

    def delete_object(self, Bucket, Key):
        self._check("delete")
        if not self.keep:
            self.files.pop(Key, None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.example.com/{Params['Key']}?sig=x"


@pytest.fixture
def bucket(monkeypatch):
    for k, v in SETTINGS.items():
        monkeypatch.setenv(k, v)
    b = FakeS3()
    monkeypatch.setattr(ns, "_client", b)

    class Resp(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: Resp(b.files[url.split("/", 3)[3].split("?")[0]]))
    return b


def names(r, ok):
    return [s["name"] for s in r["steps"] if s["ok"] is ok]


def test_all_steps_pass_and_nothing_is_left_behind(bucket):
    r = ns.self_test("nomination-forms/o/_selftest/a.pdf")
    assert r["ok"] is True and not names(r, False)
    assert names(r, True) == ["Settings present", "Storage client", "Write file", "Read file back", "Staff download link", "Delete file"]
    assert bucket.files == {}


def test_missing_settings_are_named_and_nothing_is_attempted(monkeypatch):
    for k in SETTINGS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ns, "_client", None)
    r = ns.self_test("k")
    assert r["ok"] is False and len(r["steps"]) == 1
    assert "NOMINATION_B2_BUCKET_NAME" in r["steps"][0]["detail"]


def test_a_key_that_cannot_write_stops_there(bucket):
    bucket.deny = "put"
    r = ns.self_test("k")
    assert r["ok"] is False and names(r, False) == ["Write file"] and "AccessDenied" in r["steps"][-1]["detail"]
    assert len(r["steps"]) == 3                                  # settings, client, write: no read/delete attempted


def test_a_key_that_cannot_delete_is_reported_after_a_good_write(bucket):
    bucket.deny = "delete"
    r = ns.self_test("k")
    assert r["ok"] is False and names(r, False) == ["Delete file"]


def test_object_lock_style_undeletable_files_are_caught(bucket):
    bucket.keep = True
    r = ns.self_test("k")
    assert r["ok"] is False and "Object Lock" in [s for s in r["steps"] if s["name"] == "Delete file"][0]["detail"]


def test_no_secret_ever_appears_in_the_result(bucket):
    bucket.deny = "get"
    assert "secret" not in str(ns.self_test("k"))


async def test_route_is_superadmin_only_and_audited(env, bucket):
    assert (await env.client.post("/superadmin/nomination-form/test-storage", headers=env.it)).status_code == 403
    r = await env.client.post("/superadmin/nomination-form/test-storage", headers=env.sa)
    assert r.status_code == 200 and r.json()["ok"] is True
    log = await env.db.audit_log.find_one({"action": "nomination_storage_tested"})
    assert log is not None
    assert bucket.files == {}
