"""Performance audit changes (see PERFORMANCE_AUDIT.md): indexes, per-request database-call budgets, the
public results cache, the shared SMS client and bcrypt off the event loop. Every cache here is switched OFF
for the rest of the suite by conftest; the tests below turn the one under test back on."""
import asyncio
import threading

import httpx
import pytest
from bson import ObjectId

import main
from tests.opcount import CountingDB, FakeClient
from tests.test_flows import env, ident, code_from, tick  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def prod_caches(monkeypatch):
    """Production cache settings (conftest turns them off so other tests see writes immediately)."""
    monkeypatch.setattr(main, "_SETTINGS_TTL", 5.0)
    monkeypatch.setattr(main, "_RESULTS_TTL", 5.0)
    main.invalidate_settings()
    yield
    main.invalidate_settings()


@pytest.fixture
def counted(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    monkeypatch.setattr(main, "client", FakeClient())      # mongomock has no transactions
    return cdb


async def _candidate(e):
    return str((await e.db.candidates.insert_one(
        {"org_id": e.org_id, "name": "A", "position": "President", "order": 1})).inserted_id)


def _reads(d, coll):
    return sum(n for (c, m), n in d.items() if c == coll)


# ---- Indexes ------------------------------------------------------------------------------------
async def test_hot_path_indexes_are_created(env):
    await main._ensure_perf_indexes()
    for coll, keys in main.PERF_INDEXES:
        info = await env.db[coll].index_information()
        assert any([tuple(k) for k in v["key"]] == [tuple(k) for k in keys] for v in info.values()), (coll, keys)
    # The lookups that matter most: every voter request (otps) and every admin request (revoked_tokens).
    assert any(v["key"][0][0] == "student_id" for v in (await env.db.otps.index_information()).values())
    assert any(v["key"] == [("jti", 1)] for v in (await env.db.revoked_tokens.index_information()).values())


async def test_one_failing_index_does_not_stop_the_others(env, monkeypatch):
    real = env.db["otps"]
    calls = []

    class Flaky:
        def __getitem__(self, name):
            coll = env.db[name]
            if name == "otps":
                async def boom(*a, **k):
                    calls.append(name)
                    raise RuntimeError("index conflict")
                return type("C", (), {"create_index": staticmethod(boom)})()
            return coll
    monkeypatch.setattr(main, "db", Flaky())
    await main._ensure_perf_indexes()                       # must not raise
    assert calls == ["otps"]
    assert await env.db.revoked_tokens.index_information() and \
        any(v["key"] == [("jti", 1)] for v in (await env.db.revoked_tokens.index_information()).values())


# ---- Database-call budgets (warm settings cache) -------------------------------------------------
async def test_voter_path_call_budget(env, counted, prod_caches):
    cand = await _candidate(env)
    await env.voter("v2", "Bako Daniel", ("256700111333",))
    await ident(env, "v2", "Bako Daniel")                   # warms the settings cache
    s = counted.snapshot()
    assert (await ident(env)).status_code == 200
    d = counted.since(s)
    assert _reads(d, "settings") == 0, d                    # election_config / branding come from the cache
    assert sum(d.values()) <= 10, d                         # was 13, then 11

    s = counted.snapshot()
    r = await env.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(env)})
    assert r.status_code == 200, r.text
    assert sum(counted.since(s).values()) <= 10
    tok = r.json()["voter_token"]

    s = counted.snapshot()
    r = await env.client.post("/vote-bulk", headers={"X-Voter-Token": tok},
                              json={"student_id": "v1", "candidate_ids": [cand]})
    assert r.status_code == 200, r.text
    d = counted.since(s)
    assert _reads(d, "settings") == 0, d                    # the cast-time election_config re-check is cached
    assert sum(d.values()) <= 5, d                          # was 6


# ---- Cached election state must still react at once -------------------------------------------
async def test_closing_the_election_blocks_voters_immediately(env, prod_caches):
    assert (await ident(env)).status_code == 200            # warms election_config into the cache
    r = await env.client.post("/admin/toggle-election", headers=env.sa, json={"reason": "stop for test"})
    assert r.status_code == 200, r.text
    r = await ident(env, "v1")
    assert r.status_code in (403, 429) and "closed" in r.text.lower(), r.text


async def test_cast_time_recheck_sees_a_close_without_waiting_for_the_ttl(env, counted, prod_caches):
    cand = await _candidate(env)
    await ident(env)
    r = await env.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(env)})
    tok = r.json()["voter_token"]
    assert (await env.client.post("/admin/toggle-election", headers=env.sa, json={"reason": "stop"})).status_code == 200
    r = await env.client.post("/vote-bulk", headers={"X-Voter-Token": tok},
                              json={"student_id": "v1", "candidate_ids": [cand]})
    assert r.status_code == 403 and "closed" in r.text.lower(), r.text


async def test_saving_branding_refreshes_the_cached_sms_name(env, prod_caches):
    await ident(env)                                        # caches branding ("T1")
    assert "T1" in env.sent[-1][1]
    body = {"logo_url": "", "primary_color": "#000", "accent_color": "#111", "org_name": "Renamed Guild"}
    assert (await env.client.post("/superadmin/branding", headers=env.sa, json=body)).status_code == 200
    tick(minutes=2)                                         # past the resend cooldown
    await ident(env)
    assert "Renamed Guild" in env.sent[-1][1]


# ---- Public results cache -----------------------------------------------------------------------
async def test_results_are_cached_per_org_and_cost_nothing_on_a_hit(env, counted, prod_caches):
    cand = await _candidate(env)
    first = (await env.client.get("/election-results")).json()
    s = counted.snapshot()
    again = await env.client.get("/election-results")
    assert again.json() == first
    assert sum(counted.since(s).values()) == 0              # a hit touches no collection
    # A vote inside the window is not shown yet (5 s by design) ...
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": ObjectId(cand), "cast_at": main.datetime.utcnow()})
    assert (await env.client.get("/election-results")).json() == first
    # ... and appears as soon as the window is dropped.
    main.invalidate_settings(env.org_id)
    fresh = (await env.client.get("/election-results")).json()
    assert fresh["results"][0]["votes"] == 1


async def test_results_cache_never_leaks_a_released_payload_to_a_gated_visitor(env, prod_caches):
    cand = await _candidate(env)
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": ObjectId(cand), "cast_at": main.datetime.utcnow()})
    await env.db.settings.update_one({"name": "security_settings", "org_id": env.org_id},
                                     {"$set": {"public_results_mode": "closed"}}, upsert=True)
    main.invalidate_settings(env.org_id)
    admin_view = (await env.client.get("/election-results", headers=env.sa)).json()
    assert admin_view["results_released"] is True and admin_view["results"][0]["votes"] == 1
    public_view = (await env.client.get("/election-results")).json()   # election still open: gated
    assert public_view["results_released"] is False and public_view["results"] == []
    # And the reverse: the gated payload does not hide results from the admin afterwards.
    assert (await env.client.get("/election-results", headers=env.sa)).json()["results"][0]["votes"] == 1


async def test_certifying_or_closing_drops_the_cached_results(env, prod_caches):
    cand = await _candidate(env)
    await env.client.get("/election-results")                          # caches zero votes
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": ObjectId(cand), "cast_at": main.datetime.utcnow()})
    r = await env.client.post("/admin/toggle-election", headers=env.sa, json={"reason": "stop"})
    assert r.status_code == 200, r.text
    assert (await env.client.get("/election-results", headers=env.sa)).json()["results"][0]["votes"] == 1


# ---- Shared SMS client --------------------------------------------------------------------------
async def test_sms_client_is_shared_and_rebuilt_when_closed():
    await main._close_sms_http()
    a = main._sms_http()
    assert main._sms_http() is a                                        # reused: keep-alive, no new handshake
    assert a.timeout.connect == 5.0 and a.timeout.read == 15.0          # fast connect failure, same read window
    await main._close_sms_http()
    assert main._sms_http() is not a
    await main._close_sms_http()


async def test_sms_client_is_rebuilt_for_a_new_event_loop():
    await main._close_sms_http()
    a = main._sms_http()
    main._SMS_HTTP_LOOP = object()                                      # as if the loop had changed
    assert main._sms_http() is not a
    await main._close_sms_http()


async def test_egosms_and_mambosms_go_through_the_shared_client(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.url.host)
        if "egosms" in request.url.host:
            return httpx.Response(200, text="OK")
        return httpx.Response(200, json={"success": True})
    await main._close_sms_http()
    shared = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=main._SMS_TIMEOUT)
    monkeypatch.setattr(main, "_SMS_HTTP", shared)
    monkeypatch.setattr(main, "_SMS_HTTP_LOOP", asyncio.get_running_loop())
    assert await main.send_sms_via_egosms("256700000000", "hi") == "ok"
    assert await main.send_sms_via_mambosms("256700000000", "hi") is True
    assert seen == ["comms.egosms.co", "api-mongolia.mambosms.com"]
    assert not shared.is_closed                                         # not closed per call any more
    await shared.aclose()


async def test_egosms_connect_failure_is_a_definite_failure_not_ambiguous(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("no route", request=request)
    shared = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=main._SMS_TIMEOUT)
    monkeypatch.setattr(main, "_SMS_HTTP", shared)
    monkeypatch.setattr(main, "_SMS_HTTP_LOOP", asyncio.get_running_loop())
    assert await main.send_sms_via_egosms("256700000000", "hi") == "failed"   # nothing was sent: safe to fall back
    await shared.aclose()


# ---- bcrypt off the event loop ------------------------------------------------------------------
async def test_password_check_runs_off_the_event_loop_thread(monkeypatch):
    main_thread = threading.get_ident()
    ran_on = []
    real = main.verify_password

    def spy(plain, hashed):
        ran_on.append(threading.get_ident())
        return real(plain, hashed)
    monkeypatch.setattr(main, "verify_password", spy)
    h = main.hash_password("Correct-horse-9")
    assert await main.verify_password_async("Correct-horse-9", h) is True
    assert await main.verify_password_async("wrong", h) is False
    assert await main.verify_password_async("x", "") is False
    assert ran_on and all(t != main_thread for t in ran_on)
