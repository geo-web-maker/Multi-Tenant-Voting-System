"""Audit S-02 / guide 03: in-memory per-IP limiter (token bucket, shadow and enforce modes)."""
import httpx
import pytest

import main


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    main._IP_LIMIT.clear()
    main._IP_LIMIT_STATS.update(allowed=0, limited=0, unknown_ip=0, next_summary=0.0)
    monkeypatch.setattr(main, "IP_LIMIT_RATE", 0.0001)  # effectively no refill inside a test
    monkeypatch.setattr(main, "IP_LIMIT_BURST", 3.0)
    yield
    main._IP_LIMIT.clear()


class Boom:
    def __getattr__(self, name):
        raise AssertionError("database touched by a request the limiter should have rejected")


async def _get(path, ip, method="GET"):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.request(method, path, headers={"x-forwarded-for": ip})


async def test_enforce_blocks_after_burst_with_retry_after_and_no_db(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MODE", "enforce")
    monkeypatch.setattr(main, "TRUSTED_PROXY_HOPS", 1)
    codes = [(await _get("/election-status", "1.1.1.1")).status_code for _ in range(3)]
    assert 429 not in codes
    monkeypatch.setattr(main, "db", Boom())
    r = await _get("/election-status", "1.1.1.1")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert "Too many" in r.json()["detail"]


async def test_other_ip_unaffected(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MODE", "enforce")
    monkeypatch.setattr(main, "TRUSTED_PROXY_HOPS", 1)
    for _ in range(5):
        await _get("/election-status", "1.1.1.1")
    assert (await _get("/election-status", "2.2.2.2")).status_code != 429


async def test_exempt_paths_and_options_are_never_limited(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MODE", "enforce")
    monkeypatch.setattr(main, "TRUSTED_PROXY_HOPS", 1)
    for _ in range(10):
        assert (await _get(main._KEEPWARM_PATH, "3.3.3.3")).status_code != 429
        assert (await _get("/election-status", "3.3.3.3", method="OPTIONS")).status_code != 429
    assert "3.3.3.3" not in main._IP_LIMIT


async def test_shadow_mode_counts_but_never_blocks(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MODE", "shadow")
    monkeypatch.setattr(main, "TRUSTED_PROXY_HOPS", 1)
    codes = [(await _get("/election-status", "4.4.4.4")).status_code for _ in range(8)]
    assert 429 not in codes
    assert main._IP_LIMIT["4.4.4.4"].blocked == 5 and main._IP_LIMIT["4.4.4.4"].peak >= 3


async def test_off_mode_tracks_nothing(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MODE", "off")
    await _get("/election-status", "5.5.5.5")
    assert main._IP_LIMIT == {}


def test_tracked_ip_table_is_bounded(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MAX_TRACKED", 50)
    for i in range(500):
        main._ip_limit_take(f"10.0.{i // 250}.{i % 250}", float(i) / 1000)
    assert len(main._IP_LIMIT) <= 50


def test_bucket_refills_over_time(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_RATE", 1.0)
    for _ in range(3):
        assert main._ip_limit_take("9.9.9.9", 100.0)[0]
    ok, retry = main._ip_limit_take("9.9.9.9", 100.0)
    assert not ok and retry == 1
    assert main._ip_limit_take("9.9.9.9", 102.5)[0]


async def test_429_carries_cors_headers_and_reaches_analytics(monkeypatch):
    monkeypatch.setattr(main, "IP_LIMIT_MODE", "enforce")
    monkeypatch.setattr(main, "TRUSTED_PROXY_HOPS", 1)
    seen = []

    async def fake_record(request, status, started):
        seen.append(status)

    monkeypatch.setattr(main.analytics, "_enabled", lambda: True)
    monkeypatch.setattr(main.analytics, "_record_outcome", fake_record)
    origin = main.ALLOWED_ORIGINS[0]
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        for _ in range(4):
            r = await c.get("/election-status", headers={"x-forwarded-for": "6.6.6.6", "origin": origin})
    assert r.status_code == 429
    assert r.headers.get("access-control-allow-origin") == origin
    assert seen[-1] == 429
