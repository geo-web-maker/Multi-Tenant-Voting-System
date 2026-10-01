"""Regression tests for the security-audit findings. Reuses the `env` fixture from test_flows."""
import pytest
from bson import ObjectId

from auth import create_access_token, create_voter_token   # v3 API: returns (token, jti)
import main  # noqa: E402
from tests.test_flows import env, ident, code_from, tick, START, Clock  # noqa: F401  (fixture + helpers)

pytestmark = pytest.mark.asyncio


class _FakeSession:
    """mongomock has no transactions; run the callback directly (no session)."""
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def with_transaction(self, fn): return await fn(None)


class _FakeClient:
    async def start_session(self): return _FakeSession()


@pytest.fixture(autouse=True)
def _no_real_transactions(monkeypatch):
    import main
    monkeypatch.setattr(main, "client", _FakeClient())


async def _candidate(e, name="Cand A", position="President"):
    r = await e.db.candidates.insert_one({"name": name, "position": position, "org_id": e.org_id, "order": 1})
    return str(r.inserted_id)


async def _authenticate(e, sid="v1"):
    """Full OTP flow; returns the response of /verify-otp."""
    await ident(e, sid)
    return await e.client.post("/verify-otp", json={"student_id": sid, "code": code_from(e)})


# ---- C1: /vote must require the per-voter credential -----------------------------------------
async def test_vote_without_voter_token_is_rejected_even_when_authenticated(env):
    cid = await _candidate(env)
    assert (await _authenticate(env)).status_code == 200
    # An attacker who only knows the student_id (no token):
    r = await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]})
    assert r.status_code == 401
    r = await env.client.post("/vote", json={"student_id": "v1", "candidate_id": cid})
    assert r.status_code == 401
    assert (await env.db.voters.find_one({"student_id": "v1"}))["has_voted"] is False
    assert await env.db.vote_events.count_documents({}) == 0


async def test_vote_with_correct_token_succeeds_once_and_token_is_single_use(env):
    cid = await _candidate(env)
    tok = (await _authenticate(env)).json()["voter_token"]
    h = {"X-Voter-Token": tok}
    r = await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]}, headers=h)
    assert r.status_code == 200
    r = await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]}, headers=h)
    assert r.status_code == 400                      # already voted
    assert await env.db.vote_events.count_documents({}) == 1


async def test_token_for_voter_A_cannot_vote_as_voter_B(env):
    cid = await _candidate(env)
    await env.voter("v2", "Bosco Kato", ("256700333444",))
    tok_a = (await _authenticate(env, "v1")).json()["voter_token"]
    await _authenticate(env, "v2")                    # B is now sitting in the "authenticated" state
    r = await env.client.post("/vote-bulk", json={"student_id": "v2", "candidate_ids": [cid]},
                              headers={"X-Voter-Token": tok_a})
    assert r.status_code == 403
    assert (await env.db.voters.find_one({"student_id": "v2"}))["has_voted"] is False


async def test_forged_and_stale_tokens_rejected(env):
    cid = await _candidate(env)
    await _authenticate(env)
    forged, _ = create_voter_token(student_id="v1", org_id=env.org_id)     # valid signature, jti never stored
    r = await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]},
                              headers={"X-Voter-Token": forged})
    assert r.status_code == 401                        # stale/replaced session -> UI says "verify again"
    r = await env.client.post("/vote-bulk", json={"student_id": "v1", "candidate_ids": [cid]},
                              headers={"X-Voter-Token": create_access_token(subject="v1", role="superadmin", org_id=env.org_id)})
    assert r.status_code in (401, 403)                 # an admin token is not a voter token


# ---- H1: commissioner vote stuffing ------------------------------------------------------------
async def test_one_commissioner_cannot_vote_multiple_times_by_varying_the_id(env):
    for i in range(3):
        await env.voter(f"com{i+3}", f"Comm {i+3}", ("2567000000%02d" % (i + 10),), is_commissioner=True)   # 5 commissioners -> need 3
    app = await env.db.applications.insert_one({
        "org_id": env.org_id, "student_id": "v1", "full_name": "Ayebale Elizabeth", "position_id": "p",
        "status": "pending", "votes": {}, "removal_votes": {}, "finance_cleared": True})
    aid = str(app.inserted_id)
    for variant in ("com1", "COM1", "Com1 ", "c om1", '"com1"'):
        await env.client.post(f"/admin/applications/{aid}/vote", headers=env.com1,
                              json={"commissioner_id": variant, "vote": "approve"})
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "pending", "a single commissioner reached majority alone"
    assert len(doc["votes"]) == 1


# ---- C2: tenancy ------------------------------------------------------------------------------
async def test_token_from_org_a_is_rejected_on_org_b(env):
    await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    h = {**env.it, "X-Org-Slug": "t2"}                 # IT-admin token minted for t1, header swapped to t2
    r = await env.client.get("/admin/voters", headers=h)
    assert r.status_code == 403


async def test_unknown_org_slug_is_rejected_not_unscoped(env):
    r = await env.client.get("/candidates", headers={"X-Org-Slug": "does-not-exist"})
    assert r.status_code == 404


async def test_missing_org_header_is_rejected(env):
    r = await env.client.get("/candidates", headers={"X-Org-Slug": ""})
    assert r.status_code in (400, 404)


# ---- H2: live public results --------------------------------------------------------------------
async def test_public_results_hidden_until_certified(env, monkeypatch):
    import main
    # public_results_mode is per-org now (overrides the env-var default) — set it via
    # the same security_settings doc the superadmin PUT endpoint writes to.
    monkeypatch.setitem(main._SEC_DEFAULTS, "public_results_mode", "certified")
    await _candidate(env)
    # Gated: turnout still visible (participation transparency), breakdown withheld.
    r = await env.client.get("/election-results")
    assert r.status_code == 200
    body = r.json()
    assert body["results_released"] is False
    assert body["results"] == []
    assert "voter_turnout" in body                     # never hidden, regardless of mode

    r_admin = await env.client.get("/election-results", headers=env.sa)
    assert r_admin.status_code == 200 and r_admin.json()["results_released"] is True   # admins may look

    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_certified": True})
    r2 = await env.client.get("/election-results")
    assert r2.status_code == 200 and r2.json()["results_released"] is True


# ---- M: client IP spoofing -----------------------------------------------------------------------
async def test_spoofed_leftmost_x_forwarded_for_is_ignored(env):
    import main
    class R:                                           # minimal request stub
        def __init__(self, xff): self.headers = {"x-forwarded-for": xff}; self.client = None
    # attacker prepends a fake IP; the proxy appended the real peer on the right
    assert main.real_client_ip(R("6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    assert main.real_client_ip(R("1.1.1.1, 203.0.113.9")) == "203.0.113.9"


async def test_default_results_mode_preserves_live_page(env):
    import main
    assert main._SEC_DEFAULTS["public_results_mode"] == "live"
    await _candidate(env)
    assert (await env.client.get("/election-results")).status_code == 200


async def test_public_results_mode_is_per_org_not_process_wide(env):
    """One org can be 'live' while another is 'certified' on the same running app —
    public_results_mode must live in each org's security_settings doc, not a single
    global default shared by every tenant."""
    await _candidate(env)
    org2 = await env.db.organizations.insert_one({"slug": "org2", "name": "Org2"})
    org2_id = str(org2.inserted_id)
    await env.db.candidates.insert_one({"name": "Cand B", "position": "President",
                                        "org_id": org2_id, "order": 1})
    sa2 = {"Authorization": env.sa["Authorization"], "X-Org-Slug": "org2"}

    # org1 (env fixture's default org) opts into 'certified'; org2 is left on the
    # process-wide default ('live', per the fixture's DEBUG_MODE env).
    r = await env.client.put("/superadmin/security-settings",
                              json={"reason": "test", "public_results_mode": "certified"},
                              headers=env.sa)
    assert r.status_code == 200 and r.json()["settings"]["public_results_mode"] == "certified"

    r1 = await env.client.get("/election-results")
    r2 = await env.client.get("/election-results", headers={"X-Org-Slug": "org2"})
    assert r1.status_code == 200 and r1.json()["results_released"] is False    # org1: gated
    assert r2.status_code == 200 and r2.json()["results_released"] is True     # org2: unaffected


# ---- SMS provider fallback-on-timeout is per-org too, same bug shape as PUBLIC_RESULTS_MODE ------
async def test_sms_fallback_on_timeout_defaults_off_and_is_per_org(env, monkeypatch):
    import main
    mambo_calls = []

    async def fake_mambo(to, text):
        mambo_calls.append((to, text))
        return True
    monkeypatch.setattr(main, "send_sms_via_mambosms", fake_mambo)
    env.behaviour["result"] = "ambiguous"     # EgoSMS times out on every send below

    # Default (off): an ambiguous EgoSMS result must NOT trigger MamboSMS, since the
    # first send may already have been delivered and billed.
    r = await ident(env)
    assert r.status_code == 200 and r.json()["delivery"] == "unconfirmed"
    assert mambo_calls == []

    # Superadmin turns fallback on for this org only.
    put = await env.client.put("/superadmin/security-settings",
                               json={"reason": "test", "sms_fallback_on_timeout": True}, headers=env.sa)
    assert put.status_code == 200 and put.json()["settings"]["sms_fallback_on_timeout"] is True

    tick(seconds=31)                          # clear the resend cooldown for a fresh attempt
    r2 = await ident(env)
    assert r2.status_code == 200
    assert len(mambo_calls) == 1              # now it falls back


# ================================================================================================
# H5 / H6 — session lifecycle: scoped temp-password tokens, expiry, and revocation on change/toggle
# ================================================================================================
import jwt as _jwt  # noqa: E402
from auth import JWT_SECRET, JWT_ALGORITHM  # noqa: E402
from main import SUPERADMIN_JWT_EXPIRE_MINUTES  # noqa: E402


async def _make_it_admin(e, sid="it9", email="it9@example.com", password="Sup3rSecret!9"):
    from main import hash_password
    await e.db.voters.insert_one({
        "org_id": e.org_id, "student_id": sid, "full_name": "IT Nine",
        "is_it_admin": True, "it_admin_email": email,
        "it_admin_password_hash": hash_password(password),
        "it_admin_must_change_password": False,
    })


async def test_temp_password_login_is_scoped_to_password_change_only(env):
    from main import hash_password
    await env.db.voters.insert_one({
        "org_id": env.org_id, "student_id": "it10", "full_name": "IT Ten",
        "is_it_admin": True, "it_admin_email": "it10@example.com",
        "it_admin_password_hash": hash_password("Tempw0rd!XZ"),
        "it_admin_must_change_password": True,
    })
    r = await env.client.post("/verify-admin", json={"email": "it10@example.com", "password": "Tempw0rd!XZ"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Org-Slug": "t1"}
    # Scoped token must not be usable for an ordinary admin route:
    r2 = await env.client.get("/admin/voters", headers=h)
    assert r2.status_code == 403
    # ...but IS allowed on the two paths a must-change flow actually needs:
    r3 = await env.client.post("/admin/logout", headers=h)
    assert r3.status_code == 200


async def test_expired_temp_password_is_rejected_at_login(env):
    from main import hash_password
    await env.db.voters.insert_one({
        "org_id": env.org_id, "student_id": "it11", "full_name": "IT Eleven",
        "is_it_admin": True, "it_admin_email": "it11@example.com",
        "it_admin_password_hash": hash_password("Tempw0rd!XZ"),
        "it_admin_must_change_password": True,
        "it_admin_temp_password_expires": tick_value_in_past(),
    })
    r = await env.client.post("/verify-admin", json={"email": "it11@example.com", "password": "Tempw0rd!XZ"})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def tick_value_in_past():
    import datetime as _dt
    return START - _dt.timedelta(hours=1)


async def test_changing_password_invalidates_the_old_session(env):
    await _make_it_admin(env)
    minted_at = Clock.now
    tick(minutes=1)                                   # so the password-change stamp is strictly later
    old = {"Authorization": f"Bearer {_manual_token('it9', 'it_admin', env.org_id, minted_at)}", "X-Org-Slug": "t1"}
    assert (await env.client.get("/admin/voters", headers=old)).status_code == 200   # sanity: old token works
    r = await env.client.post("/admin/set-password", json={
        "email": "it9@example.com", "old_password": "Sup3rSecret!9", "new_password": "Br4ndNewPass!1"
    }, headers=old)
    assert r.status_code == 200
    # the token used to MAKE this change is now stale too (iat before the stamp) -> next call 401s
    r2 = await env.client.get("/admin/voters", headers=old)
    assert r2.status_code == 401
    # logging in again (as the real frontend does right after set-password) gets a fresh, valid session
    r3 = await env.client.post("/verify-admin", json={"email": "it9@example.com", "password": "Br4ndNewPass!1"})
    assert r3.status_code == 200
    fresh = {"Authorization": f"Bearer {r3.json()['access_token']}", "X-Org-Slug": "t1"}
    assert (await env.client.get("/admin/voters", headers=fresh)).status_code == 200


def _manual_token(sub, role, org_id, when):
    """The test fixture fakes main.py's clock (for OTP timing) but NOT auth.py's, so a token
    from create_access_token() always carries a real wall-clock iat -- comparing that against
    a sessions_valid_after stamped on the fixture's fake clock never lines up here even though
    both are real clocks in production. Mint the token's iat on the fixture's fake clock instead,
    exactly like the guard's datetime.utcfromtimestamp(iat) expects it back."""
    import calendar, datetime as _real_dt
    payload = {"sub": sub, "role": role, "org_id": org_id, "full_name": "", "scope": "full",
               "jti": "manualtoken123",
               # iat is read back by the guard via datetime.utcfromtimestamp() and compared
               # against the fixture's FAKE clock -> must round-trip to `when` exactly.
               "iat": calendar.timegm(when.timetuple()),
               # exp is validated by PyJWT itself against the REAL wall clock (never patched
               # by this fixture) -> must be in the real future, independent of `when`.
               "exp": calendar.timegm((_real_dt.datetime.utcnow() + _real_dt.timedelta(hours=1)).timetuple())}
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def test_revoking_a_role_invalidates_their_existing_session(env):
    await _make_it_admin(env, sid="it12", email="it12@example.com")
    minted_at = Clock.now
    tick(minutes=1)                                   # so the revoke's stamp is strictly later
    tok = {"Authorization": f"Bearer {_manual_token('it12', 'it_admin', env.org_id, minted_at)}",
           "X-Org-Slug": "t1"}
    assert (await env.client.get("/admin/voters", headers=tok)).status_code == 200
    r = await env.client.post("/superadmin/it-admins/it12/toggle", headers=env.sa)  # revoke
    assert r.status_code == 200 and r.json()["is_it_admin"] is False
    assert (await env.client.get("/admin/voters", headers=tok)).status_code == 401


async def test_superadmin_token_has_a_shorter_expiry_than_other_roles(env):
    r = await env.client.post("/verify-admin", json={"email": "root", "password": "x"})
    assert r.status_code == 200
    payload = _jwt.decode(r.json()["access_token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    lifetime_min = (payload["exp"] - payload["iat"]) / 60
    assert lifetime_min == SUPERADMIN_JWT_EXPIRE_MINUTES
    assert SUPERADMIN_JWT_EXPIRE_MINUTES < main.JWT_EXPIRE_MINUTES


# ================================================================================================
# M4 — login lockout: per-(email, IP) keying + capped backoff for the superadmin
# ================================================================================================

async def test_lockout_from_one_ip_does_not_block_a_different_ip(env):
    from main import hash_password
    await env.db.voters.insert_one({
        "org_id": env.org_id, "student_id": "it13", "full_name": "IT Thirteen",
        "is_it_admin": True, "it_admin_email": "it13@example.com",
        "it_admin_password_hash": hash_password("Real3Password!"),
        "it_admin_must_change_password": False,
    })
    attacker = {"X-Forwarded-For": "9.9.9.9, 203.0.113.50"}
    for _ in range(5):
        r = await env.client.post("/verify-admin", json={"email": "it13@example.com", "password": "wrong"},
                                  headers=attacker)
    assert r.status_code == 401                       # 5th failure still just reports "wrong password"...
    r = await env.client.post("/verify-admin", json={"email": "it13@example.com", "password": "wrong"},
                              headers=attacker)
    assert r.status_code == 429                        # ...the 6th is locked, for THIS ip's key
    # ...but the legitimate admin, logging in from a different IP, is unaffected:
    other_ip = {"X-Forwarded-For": "1.1.1.1, 203.0.113.99"}
    r = await env.client.post("/verify-admin", json={"email": "it13@example.com", "password": "Real3Password!"},
                              headers=other_ip)
    assert r.status_code == 200


async def test_superadmin_lockout_is_short_and_capped_not_a_hard_15min_block(env):
    ip_hdr = {"X-Forwarded-For": "8.8.8.8, 203.0.113.77"}
    for _ in range(6):
        await env.client.post("/verify-admin", json={"email": "root", "password": "wrong"}, headers=ip_hdr)
    rec = await env.db.login_attempts.find_one({"key": f"{env.org_id}:root:203.0.113.77"})
    assert rec and rec["locked_until"]
    lock_seconds = (rec["locked_until"] - rec["last_attempt"]).total_seconds()
    assert 0 < lock_seconds <= main.SUPERADMIN_LOCKOUT_SECONDS_CAP     # never the flat 15-minute lock
    assert lock_seconds < main.LOGIN_LOCKOUT_MINUTES * 60


# ================================================================================================
# M3 — opening an election with roster-freeze enabled but no resolvable freeze time
# ================================================================================================

async def test_cannot_open_election_with_no_roster_freeze_time(env):
    # With no election_config doc yet, the election is implicitly "open" (is_open defaults to
    # True), so the FIRST toggle closes it; the SECOND toggle is the "opening" transition that
    # should be blocked without a resolvable roster-freeze time.
    r0 = await env.client.post("/admin/toggle-election", json={}, headers=env.sa)
    assert r0.status_code == 200 and r0.json()["is_open"] is False
    r = await env.client.post("/admin/toggle-election", json={}, headers=env.sa)
    assert r.status_code == 400
    assert "roster freeze" in str(r.json()["detail"]).lower()
    # setting an explicit freeze time clears the block
    await env.db.settings.update_one(
        {"org_id": env.org_id, "name": "security_settings"},
        {"$set": {"roster_freeze_at": tick_value_in_past()}}, upsert=True)
    r2 = await env.client.post("/admin/toggle-election", json={}, headers=env.sa)
    assert r2.status_code == 200


# ================================================================================================
# M9 — public branding endpoint no longer leaks cc_list / org_id
# ================================================================================================

async def test_public_branding_hides_cc_list_and_org_id(env):
    r = await env.client.post("/superadmin/branding", json={
        "logo_url": "https://res.cloudinary.com/x/logo.png", "primary_color": "#000", "accent_color": "#fff",
        "org_name": "Test Uni", "cc_list": ["registrar@example.com", "dean@example.com"],
    }, headers=env.sa)
    assert r.status_code == 200
    pub = await env.client.get("/superadmin/branding")     # no auth header at all
    assert pub.status_code == 200
    body = pub.json()
    assert body["org_name"] == "Test Uni"                   # public fields still there
    assert "cc_list" not in body and "org_id" not in body and "_id" not in body
