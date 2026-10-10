"""Slow synchronous work (bcrypt, Cloudinary, spreadsheet rendering) must run in a worker thread, not on the
event loop where it would freeze every other request, voters included."""
import base64
import struct
import threading
import zlib

import pytest
from fastapi import HTTPException

import main
from tests.test_flows import env  # noqa: F401
from tests.test_voter_export import seed, set_mode, export

pytestmark = pytest.mark.asyncio


def _png() -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


async def test_password_hashing_runs_off_the_event_loop(monkeypatch):
    loop_thread, seen = threading.get_ident(), []
    real = main.hash_password
    monkeypatch.setattr(main, "hash_password", lambda p: (seen.append(threading.get_ident()), real(p))[1])
    h = await main.hash_password_async("S3cret-pass")
    assert seen and seen[0] != loop_thread
    assert main.verify_password("S3cret-pass", h)


async def test_async_hash_still_refuses_passwords_over_72_bytes():
    with pytest.raises(HTTPException) as e:
        await main.hash_password_async("x" * 73)
    assert e.value.status_code == 400


async def test_no_handler_calls_the_blocking_hash_directly():
    import re
    src = open(main.__file__).read()
    assert not re.findall(r"(?<![\w.])hash_password\((?!plain_password)", src)


async def test_cloudinary_image_upload_runs_off_the_event_loop(env, monkeypatch):
    loop_thread, seen = threading.get_ident(), []

    def fake_upload(content, **kw):
        seen.append(threading.get_ident())
        return {"secure_url": "https://res.cloudinary.com/x/y.png"}
    monkeypatch.setattr(main.cloudinary.uploader, "upload", fake_upload)
    r = await env.client.post("/admin/upload-image", headers=env.sa, files={"file": ("a.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    assert seen and seen[0] != loop_thread


async def test_voter_export_renders_off_the_event_loop_and_is_unchanged(env, monkeypatch):
    loop_thread, seen = threading.get_ident(), []
    real = main._render_voter_export
    monkeypatch.setattr(main, "_render_voter_export", lambda *a: (seen.append(threading.get_ident()), real(*a))[1])
    await seed(env)
    await set_mode(env, "full")
    expected = str(await env.db.voters.count_documents({"org_id": env.org_id}))
    for fmt in ("csv", "xlsx"):
        r = await export(env, fmt=fmt)
        assert r.status_code == 200 and r.headers["X-Export-Rows"] == expected, r.text
    assert seen and all(t != loop_thread for t in seen)
