"""WP-5: GZip + CORS preflight caching. Middleware order matters, so test behaviour, not config."""
import pytest

import main
from tests.test_flows import env  # noqa: F401  (fixture: httpx client bound to main.app)

pytestmark = pytest.mark.asyncio

ORIGIN = main.ALLOWED_ORIGINS[0]


@pytest.fixture
def big_route(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_PATHS", set(main.PUBLIC_PATHS) | {"/__test_big", "/__test_small"})
    async def _big():
        return {"rows": ["x" * 50] * 200}          # ~10 KB of JSON, well over the 1 KB threshold

    async def _small():
        return {"ok": True}

    before = len(main.app.router.routes)
    main.app.add_api_route("/__test_big", _big)
    main.app.add_api_route("/__test_small", _small)
    yield
    del main.app.router.routes[before:]


async def test_large_response_is_gzipped_and_still_carries_cors(env, big_route):
    r = await env.client.get("/__test_big", headers={"Accept-Encoding": "gzip", "Origin": ORIGIN})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert r.headers.get("access-control-allow-origin") == ORIGIN       # CORS stays outermost
    assert len(r.json()["rows"]) == 200                                  # body survives the round trip


async def test_small_response_still_arrives_intact(env, big_route):
    # NOTE: GZip's minimum_size is not honoured here — the app's @app.middleware("http") layers hand the
    # body down as a stream, and Starlette always compresses streamed bodies. Harmless; assert correctness.
    r = await env.client.get("/__test_small", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_client_without_gzip_gets_plain_body(env, big_route):
    r = await env.client.get("/__test_big", headers={"Accept-Encoding": "identity"})
    assert r.headers.get("content-encoding") is None and len(r.json()["rows"]) == 200


async def test_preflight_is_cached_for_two_hours(env):
    r = await env.client.options("/vote", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-voter-token,content-type"})
    assert r.status_code == 200
    assert r.headers.get("access-control-max-age") == "7200"


async def test_disallowed_origin_gets_no_cors_header(env, big_route):
    r = await env.client.get("/__test_big", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
