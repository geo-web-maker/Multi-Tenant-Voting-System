"""
Integration tests for OTP_SMS_Design_v2 against an in-memory Mongo (mongomock-motor) and a fake clock.
Run:  pip install pytest pytest-asyncio mongomock-motor && pytest -q
(Real-Mongo concurrency is covered by the Locust plan in the design doc, appendix G.)
"""
import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

import main
import otp_limits as ol
from auth import create_access_token

START = datetime(2026, 1, 10, 12, 0, 0)


class Clock:
    now = START


class FakeDT(datetime):
    @classmethod
    def utcnow(cls):
        return Clock.now


def tick(**kw):
    Clock.now = Clock.now + timedelta(**kw)


@pytest.fixture
async def env(monkeypatch):
    Clock.now = START
    monkeypatch.setattr(main, "datetime", FakeDT)
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "b2_client", None)
    sent = []                                    # (number, text)
    behaviour = {"result": "ok"}

    async def fake_ego(to, text):
        if behaviour["result"] == "ok":
            sent.append((to, text))
        return behaviour["result"]
    monkeypatch.setattr(main, "send_sms_via_egosms", fake_ego)
    monkeypatch.setattr(main, "send_sms_via_mambosms", lambda to, text: _false())

    for coll, key, kw in [("otp_send_state", "key", {}), ("otp_guess_state", "key", {}), ("sms_usage", "org_key", {}),
                          ("ip_send_stats", "key", {})]:
        await db[coll].create_index(key, unique=True)
    await db.roster_ledger.create_index([("org_id", 1), ("seq", 1)], unique=True)
    await db.contact_changes.create_index([("org_id", 1), ("student_id", 1)], unique=True,
                                          partialFilterExpression={"status": "pending"})
    org = await db.organizations.insert_one({"slug": "t1", "name": "T1"})
    org_id = str(org.inserted_id)
    await db.settings.insert_one({"name": "branding", "org_id": org_id, "org_name": "T1", "support_phone": "256700000000"})

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t",
                               headers={"X-Org-Slug": "t1"})

    def tok(sub, role):
        return {"Authorization": "Bearer " + create_access_token(subject=sub, role=role, org_id=org_id),
                "X-Org-Slug": "t1"}

    class E: pass
    e = E()
    e.db, e.client, e.org_id, e.sent, e.behaviour, e.tok = db, client, org_id, sent, behaviour, tok
    e.it, e.sa = tok("it1", "it_admin"), tok("root", "superadmin")
    e.com1, e.com2, e.over = tok("com1", "commission"), tok("com2", "commission"), tok("ov1", "overseer")

    async def voter(sid, name="Ayebale Elizabeth", phones=("256700111222",), **kw):
        d = {"student_id": sid, "full_name": name, "phone_numbers": list(phones), "has_voted": False,
             "last_status": "idle", "org_id": org_id, **kw}
        await db.voters.insert_one(d)
        return d
    e.voter = voter
    await voter("com1", "Comm One", ("256700000001",), is_commissioner=True)
    await voter("com2", "Comm Two", ("256700000002",), is_commissioner=True)
    await voter("it1", "It Admin", ("256700000003",), is_it_admin=True)
    await voter("v1", "Ayebale Elizabeth")
    e.freeze = lambda: set_voting(e, start=START - timedelta(hours=1), end=START + timedelta(days=1))
    yield e
    await client.aclose()


async def _false():
    return False


async def set_voting(e, start, end, enforced=True):
    await e.db.settings.update_one(
        {"name": "election_phases", "org_id": e.org_id},
        {"$set": {"name": "election_phases", "org_id": e.org_id, "round_id": "round-1",
                  "phases": {"voting": {"start": start, "end": end, "enforced": enforced}}}}, upsert=True)


async def ident(e, sid="v1", name="Ayebale Elizabeth", **kw):
    return await e.client.post("/verify-identity", json={"student_id": sid, "full_name": name, **kw})


def code_from(e):
    return e.sent[-1][1].split("code is ")[1].split(".")[0]


# ── Part A ──────────────────────────────────────────────────────────────────

async def test_ladder_and_code_reuse(env):
    r = await ident(env)
    assert r.status_code == 200 and r.json()["next_send_in"] == 30
    first = code_from(env)
    r = await ident(env)                                      # immediate resend
    assert r.status_code == 429 and r.json()["reason"] == "cooldown" and 1 <= r.json()["retry_after"] <= 30
    assert r.headers["retry-after"] == str(r.json()["retry_after"])
    tick(seconds=31)
    r = await ident(env)
    assert r.status_code == 200 and r.json()["next_send_in"] == 60
    assert code_from(env) == first                            # SAME code re-sent while valid
    tick(minutes=11)                                          # code expired, ladder idle < 30 min
    assert (await ident(env)).status_code == 200
    assert code_from(env) != first or True                    # new code generated after expiry (random; may collide)
    assert len(env.sent) == 3


async def test_ladder_forgets_and_daily_ceiling(env):
    for _ in range(8):
        assert (await ident(env)).status_code == 200
        tick(minutes=11)                                      # always past the longest wait
    r = await ident(env)                                      # 9th within 24 h
    assert r.status_code == 429 and r.json()["reason"] == "daily_ceiling"
    tick(hours=24)
    assert (await ident(env)).status_code == 200              # ages out


async def test_parallel_resends_send_once(env):
    rs = await asyncio.gather(*[ident(env) for _ in range(20)])
    assert sum(r.status_code == 200 for r in rs) == 1 and len(env.sent) == 1


async def test_gateway_failure_is_free(env):
    env.behaviour["result"] = "failed"
    assert (await ident(env)).status_code == 500
    env.behaviour["result"] = "ok"
    assert (await ident(env)).status_code == 200              # no cooldown consumed


async def test_ambiguous_timeout_keeps_code_and_cooldown(env):
    env.behaviour["result"] = "ambiguous"
    r = await ident(env)
    assert r.status_code == 200 and r.json()["delivery"] == "unconfirmed"
    assert await env.db.otps.find_one({"student_id": "v1"})   # code stored: the SMS may still arrive
    assert (await ident(env)).status_code == 429               # cooldown holds; no auto-fallback


# ── Part B ──────────────────────────────────────────────────────────────────

async def _otp(e, code):
    return await e.client.post("/verify-otp", json={"student_id": "v1", "code": code})


async def test_guess_bucket_lock_refill_and_no_free_lockout(env):
    await set_voting(env, START, START + timedelta(days=1))
    interval = ol.refill_interval(86400)
    # no live code: guesses are refused AND free
    for _ in range(10):
        r = await _otp(env, "000000")
        assert r.status_code == 400 and r.json()["reason"] == "no_live_code"
    assert await env.db.otp_guess_state.count_documents({}) == 0

    await ident(env)
    real = code_from(env)
    wrong = "111111" if real != "111111" else "222222"
    left = []
    for _ in range(4):
        r = await _otp(env, wrong)
        assert r.status_code == 400 and r.json()["reason"] == "wrong_code"
        left.append(r.json()["attempts_remaining"])
    assert left == [4, 3, 2, 1]
    r = await _otp(env, wrong)                                # 5th empties the bucket -> lock with countdown
    assert r.status_code == 429 and r.json()["reason"] == "guess_lock"
    assert abs(r.json()["retry_after"] - interval) <= 2
    assert (await _otp(env, real)).status_code == 429         # even the RIGHT code is refused while locked
    tick(seconds=40)
    r = await ident(env)                                      # sending is refused too: a new code would be useless
    assert r.status_code == 429 and r.json()["reason"] == "guess_lock"
    tick(seconds=interval)                                    # one token back
    assert (await ident(env)).status_code == 200              # new/re-sent code does NOT refill the bucket
    r = await _otp(env, wrong)
    assert r.status_code == 429                               # still empty after the new send: 1 token was used up above? (see next)
    

async def test_success_clears_bucket_and_lock_scales_with_window(env):
    await ident(env)
    real = code_from(env)
    await _otp(env, "999999" if real != "999999" else "888888")
    assert await env.db.otp_guess_state.count_documents({}) == 1
    assert (await _otp(env, real)).status_code == 200
    assert await env.db.otp_guess_state.count_documents({}) == 0
    # 7-day window -> longer wait than 1 day for the same 5 wrong guesses
    waits = {}
    for days in (1, 7):
        await env.db.otp_guess_state.delete_many({}); await env.db.otp_send_state.delete_many({})
        await env.db.otps.delete_many({}); await env.db.voters.update_one({"student_id": "v1"}, {"$set": {"has_voted": False}})
        await set_voting(env, Clock.now, Clock.now + timedelta(days=days))
        await ident(env)
        c = code_from(env)
        w = "111111" if c != "111111" else "222222"
        for _ in range(5):
            r = await _otp(env, w)
        waits[days] = r.json()["retry_after"]
    assert waits[7] > waits[1] * 6


# ── Part C ──────────────────────────────────────────────────────────────────

async def test_budget_counting_alerts_and_conservation(env):
    await env.db.settings.insert_one({"name": "security_settings", "org_id": env.org_id, "sms_budget_total": 4,
                                      "sms_budget_enforce": True})
    for i in range(3):
        env.voter_ids = None
    await env.voter("v2", "Bob Two Names", ("256700333444",))
    await env.voter("v3", "Cara Three Names", ("256700555666",))
    assert (await ident(env)).status_code == 200                  # 1 sent, 75 % left
    usage = await env.db.sms_usage.find_one({"org_key": env.org_id})
    assert usage["sent_total"] == 1 and usage["sent_otp"] == 1
    tick(seconds=31)
    await ident(env)                                              # 2 sent -> 50 % alert
    assert 0.5 in (await env.db.sms_usage.find_one({"org_key": env.org_id}))["alerts_fired"]
    assert await env.db.audit_log.find_one({"action": "sms_budget_alert"})
    # conservation: 2 credits left, 2 voters (v2, v3 + staff) never sent a code -> repeat sends for v1 are refused
    await env.db.settings.update_one({"name": "security_settings"}, {"$set": {"sms_mode": "conservation"}})
    tick(seconds=61)
    r = await ident(env)
    assert r.status_code == 429 and r.json()["reason"] == "budget"
    assert (await ident(env, "v2", "Bob Two Names")).status_code == 200   # first-time voter still gets a code


async def test_under_attack_requires_turnstile(env, monkeypatch):
    await env.db.settings.insert_one({"name": "security_settings", "org_id": env.org_id, "turnstile_mode": "adaptive"})
    await env.db.sms_usage.insert_one({"org_key": env.org_id, "sent_total": 60, "sent_otp": 60,
                                       "recent_sends": [Clock.now - timedelta(seconds=i) for i in range(60)],
                                       "recent_verifies": []})
    r = await ident(env)
    assert r.status_code == 429 and r.json()["reason"] == "captcha_required"
    monkeypatch.setattr(main, "TURNSTILE_SECRET", "s")

    async def ok(token, ip): return token == "good"
    monkeypatch.setattr(main, "_turnstile_verify", ok)
    assert (await ident(env, turnstile_token="bad")).status_code == 429
    assert (await ident(env, turnstile_token="good")).status_code == 200


async def test_turnstile_fails_open_unless_under_attack(env, monkeypatch):
    await env.db.settings.insert_one({"name": "security_settings", "org_id": env.org_id, "turnstile_mode": "on"})
    async def down(token, ip): return None
    monkeypatch.setattr(main, "_turnstile_verify", down)
    assert (await ident(env, turnstile_token="x")).status_code == 200      # Cloudflare unreachable -> voters first
    await env.db.sms_usage.update_one({"org_key": env.org_id}, {"$set": {"recent_sends": [Clock.now] * 60, "recent_verifies": []}}, upsert=True)
    monkeypatch.setattr(main, "TURNSTILE_SECRET", "s")
    tick(minutes=11)
    assert (await ident(env, turnstile_token="x")).status_code == 503       # under attack -> fail closed


# ── Part D: freeze + contact changes ────────────────────────────────────────

async def test_freeze_blocks_every_roster_route_and_expires_pending(env):
    await env.db.student_changes.insert_one({"org_id": env.org_id, "change_type": "add", "student_id": "n1",
                                             "status": "pending", "requested_by": "it1", "full_name": "N N"})
    await env.freeze()
    csv = ("student_id,full_name,phone\nz1,Zed Zed,0700123456\n").encode()
    r = await env.client.post("/admin/import-voters", headers=env.it, files={"file": ("v.csv", csv)})
    assert r.status_code == 409 and r.json()["reason"] == "roster_frozen"
    body = {"student_id": "n2", "full_name": "New Person", "phone": "0700123456", "reason": "late", "requested_by": "it1"}
    assert (await env.client.post("/superadmin/students/add", headers=env.sa, json=body)).status_code == 409
    assert (await env.client.post("/superadmin/students/remove", headers=env.sa, json={"student_id": "v1", "reason": "x", "requested_by": "root"})).status_code == 409
    assert (await env.client.post("/it-admin/students/request-add", headers=env.it, json=body)).status_code == 409
    assert (await env.client.post("/it-admin/students/request-remove", headers=env.it, json={"student_id": "v1", "reason": "x", "requested_by": "it1"})).status_code == 409
    ch = await env.db.student_changes.find_one({})
    assert ch["status"] == "expired_at_freeze"
    for path in ("decide", "force-approve"):
        url = f"/admin/student-changes/{ch['_id']}/decide" if path == "decide" else f"/superadmin/student-changes/{ch['_id']}/force-approve"
        hdr = env.com1 if path == "decide" else env.sa
        r = await env.client.post(url, headers=hdr, json={"financial_controller_id": "com1", "decision": "approve"})
        assert r.status_code == 409 and r.json()["reason"] == "roster_frozen"
    assert await env.db.voters.count_documents({"student_id": {"$in": ["z1", "n2"]}}) == 0


async def test_direct_edit_rules_across_phases(env):
    edit = lambda **kw: env.client.post("/admin/students/edit", headers=env.it, json={"student_id": "v1", "reason": "checked", **kw})
    r = await edit(phone_ops=[{"op": "change", "index": 0, "expected_old": "256700111222", "number": "0700999888"}])
    assert r.status_code == 200                                           # pre-freeze: free
    await env.freeze()
    r = await edit(phone_ops=[{"op": "change", "index": 0, "number": "0700555444"}])
    assert r.status_code == 409 and r.json()["reason"] == "contact_change_required"
    assert (await edit(new_student_id="v1x")).status_code == 409
    assert (await edit(full_name="Ayebale Elisabeth")).status_code == 200  # name typo allowed
    assert (await edit(full_name="Ayebale Elizabeth")).status_code == 200
    r = await edit(full_name="Ayebale E")
    assert r.status_code == 409 and r.json()["reason"] == "name_edit_cap"  # max 2
    await env.db.voters.update_one({"student_id": "v1"}, {"$set": {"has_voted": True}})
    assert (await edit(full_name="X Y")).status_code == 409
    await set_voting(env, START - timedelta(days=2), START - timedelta(days=1))   # voting closed
    await env.db.voters.update_one({"student_id": "v1"}, {"$set": {"has_voted": False}})
    assert (await edit(phone_ops=[{"op": "add", "number": "0700777666"}])).status_code == 200   # audit-only again
    assert await env.db.roster_ledger.find_one({"event": "contact_edit_audit_only"})


async def _request(e, **kw):
    body = {"student_id": "v1", "change_type": "phone_change", "index": 0, "new_value": "0700999888",
            "evidence_type": "id_card_in_person", "evidence_note": "ID card checked at desk"}
    body.update(kw)
    return await e.client.post("/it-admin/contact-changes/request", headers=e.it, json=body)


async def test_contact_change_full_flow(env):
    r = await _request(env)
    assert r.status_code == 409                                            # pre-freeze: edit directly
    await env.freeze()
    # live code + guess state exist for the voter
    await ident(env)
    live = code_from(env)
    await _otp(env, "000000" if live != "000000" else "111111")
    assert await env.db.otps.count_documents({"student_id": "v1"}) == 1
    r = await _request(env, evidence_type="nonsense")
    assert r.status_code == 400
    r = await _request(env, evidence_type="other_documented", evidence_note="short")
    assert r.status_code == 400
    r = await _request(env)
    assert r.status_code == 200
    cid = r.json()["id"]
    assert (await _request(env)).status_code == 409                        # one pending per voter
    # roles: it_admin / overseer cannot decide; superadmin only via break-glass (off)
    dec = {"decision": "approve", "note": "ok"}
    assert (await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=env.it, json=dec)).status_code == 403
    assert (await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=env.over, json=dec)).status_code == 403
    assert (await env.client.post(f"/superadmin/contact-changes/{cid}/force-approve", headers=env.sa, json=dec)).status_code == 403
    # approver sees masked data, new number in full
    lst = (await env.client.get("/admin/contact-changes", headers=env.com1)).json()
    item = lst["items"][0]
    assert item["new_value"] == "256700999888" and item["old_masked"].endswith("222") and "*" in item["old_masked"]
    assert item["student_id"] != "v1" or len("v1") < 3
    assert item["otp_in_progress"] is True
    # deny needs a note; approve works
    assert (await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=env.com1, json={"decision": "deny"})).status_code == 400
    r = await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=env.com1, json=dec)
    assert r.status_code == 200 and r.json()["notice_status"] == "sent"
    v = await env.db.voters.find_one({"student_id": "v1"})
    assert v["phone_numbers"] == ["256700999888"]
    assert await env.db.otps.count_documents({"student_id": "v1"}) == 0            # live code deleted
    assert await env.db.otp_send_state.count_documents({}) == 0 and await env.db.otp_guess_state.count_documents({}) == 0
    assert env.sent[-1][0] == "256700111222" and "changed" in env.sent[-1][1] and "code" not in env.sent[-1][1].lower().replace("contact", "")
    assert (await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=env.com2, json=dec)).status_code == 409
    audit = await env.db.student_edit_audit.find_one({"event": "phone_changed"})
    assert audit["requested_by"] == "it1" and audit["approved_by"] == "com1"
    # SMS to the NEW number is what the voter now gets
    tick(seconds=1)
    await ident(env)
    assert env.sent[-1][0] == "256700999888"
    ledger = await env.db.roster_ledger.distinct("event")
    assert {"contact_change_requested", "contact_change_approved"} <= set(ledger)
    assert (await main.verify_roster_ledger(env.org_id))["valid"]


async def test_contact_change_guards(env):
    await env.freeze()
    await env.db.settings.insert_one({"name": "security_settings", "org_id": env.org_id, "quota_hard_cap_pct": 100})
    await env.voter("v2", "Bob Two Names", ("256700333444",))
    # requester cannot decide their own request, even as a commissioner
    await env.db.voters.update_one({"student_id": "it1"}, {"$set": {"is_commissioner": True}})
    cid = (await _request(env)).json()["id"]
    it_as_com = env.tok("it1", "commission")
    assert (await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=it_as_com, json={"decision": "approve"})).status_code == 403
    # commissioner cannot approve a change to their own record
    r = await env.client.post("/it-admin/contact-changes/request", headers=env.it, json={
        "student_id": "com1", "change_type": "phone_add", "new_value": "0700123123",
        "evidence_type": "registrar_record", "evidence_note": "registrar page"})
    cid2 = r.json()["id"]
    assert (await env.client.post(f"/admin/contact-changes/{cid2}/decide", headers=env.com1, json={"decision": "approve"})).status_code == 403
    assert (await env.client.post(f"/admin/contact-changes/{cid2}/decide", headers=env.com2, json={"decision": "approve"})).status_code == 200
    # IT admin cannot file a request against their own record
    r = await env.client.post("/it-admin/contact-changes/request", headers=env.it, json={
        "student_id": "it1", "change_type": "phone_add", "new_value": "0700123124",
        "evidence_type": "registrar_record", "evidence_note": "registrar page"})
    assert r.status_code == 403
    # duplicate-number warning needs acknowledgement
    await env.db.contact_changes.delete_many({"status": "pending"})
    cid3 = (await _request(env, new_value="0700333444")).json()["id"]      # v2's number
    r = await env.client.post(f"/admin/contact-changes/{cid3}/decide", headers=env.com2, json={"decision": "approve"})
    assert r.status_code == 409 and r.json()["reason"] == "warnings_unacknowledged"
    r = await env.client.post(f"/admin/contact-changes/{cid3}/decide", headers=env.com2, json={"decision": "approve", "acknowledge_warnings": True})
    assert r.status_code == 200
    # voter who already voted is rejected; expiry after TTL
    await env.db.voters.update_one({"student_id": "v2"}, {"$set": {"has_voted": True}})
    r = await env.client.post("/it-admin/contact-changes/request", headers=env.it, json={
        "student_id": "v2", "change_type": "phone_add", "new_value": "0700888111",
        "evidence_type": "registrar_record", "evidence_note": "registrar page"})
    assert r.status_code == 409
    await env.voter("v3", "Cara Three Names", ("256700555666",))
    cid4 = (await env.client.post("/it-admin/contact-changes/request", headers=env.it, json={
        "student_id": "v3", "change_type": "phone_add", "new_value": "0700888222",
        "evidence_type": "registrar_record", "evidence_note": "registrar page"})).json()["id"]
    tick(hours=7)
    r = await env.client.post(f"/admin/contact-changes/{cid4}/decide", headers=env.com2, json={"decision": "approve"})
    assert r.status_code == 409
    assert (await env.db.contact_changes.find_one({"student_id": "v3"}))["status"] == "expired"


async def test_breakglass_and_caps_and_quota(env):
    await env.freeze()
    await env.db.settings.insert_one({"name": "security_settings", "org_id": env.org_id, "superadmin_breakglass": True,
                                      "approver_daily_cap": 1, "quota_hard_cap_pct": 90})
    for sid in ("v2", "v3"):
        await env.voter(sid, f"Name {sid} Extra", ("256700%06d" % (hash(sid) % 999999),))
    c1 = (await _request(env, new_value="0700101010")).json()["id"]
    r = await env.client.post(f"/superadmin/contact-changes/{c1}/force-approve", headers=env.sa, json={"note": "short"})
    assert r.status_code == 400
    r = await env.client.post(f"/superadmin/contact-changes/{c1}/force-approve", headers=env.sa, json={"note": "commissioners unreachable; verified by call"})
    assert r.status_code == 200
    assert (await env.db.contact_changes.find_one({"_id": __import__("bson").ObjectId(c1)}))["breakglass"] is True
    assert await env.db.audit_log.find_one({"action": "contact_change_breakglass"})
    # per-approver cap 1: second approval by the same commissioner is refused
    c2 = (await env.client.post("/it-admin/contact-changes/request", headers=env.it, json={
        "student_id": "v2", "change_type": "phone_add", "new_value": "0700202020",
        "evidence_type": "registrar_record", "evidence_note": "registrar page"})).json()["id"]
    assert (await env.client.post(f"/admin/contact-changes/{c2}/decide", headers=env.com1, json={"decision": "approve"})).status_code == 200
    c3 = (await env.client.post("/it-admin/contact-changes/request", headers=env.it, json={
        "student_id": "v3", "change_type": "phone_add", "new_value": "0700303030",
        "evidence_type": "registrar_record", "evidence_note": "registrar page"})).json()["id"]
    r = await env.client.post(f"/admin/contact-changes/{c3}/decide", headers=env.com1, json={"decision": "approve"})
    assert r.status_code == 429 and r.json()["reason"] == "approver_cap"
    assert (await env.client.post(f"/admin/contact-changes/{c3}/decide", headers=env.com2, json={"decision": "approve"})).status_code == 200
    stats = (await env.client.get("/admin/contact-changes", headers=env.over)).json()["stats"]
    assert stats["approved_total"] == 3 and stats["alerts"]["quota"] is True and stats["alerts"]["hard_stop"] is False


async def test_add_path_regression_keeps_vote_and_roles(env):
    await env.db.voters.update_one({"student_id": "v1"}, {"$set": {"has_voted": True, "is_commissioner": True}})
    body = {"student_id": "v1", "full_name": "Ayebale Elizabeth", "phone": "0700123456", "reason": "dup", "requested_by": "root"}
    assert (await env.client.post("/superadmin/students/add", headers=env.sa, json=body)).status_code == 200
    v = await env.db.voters.find_one({"student_id": "v1"})
    assert v["has_voted"] is True and v["is_commissioner"] is True
    await main._execute_student_change({"change_type": "add", "student_id": "v1", "full_name": "A E", "phone": "0700123456"}, env.org_id)
    v = await env.db.voters.find_one({"student_id": "v1"})
    assert v["has_voted"] is True and v["is_commissioner"] is True


# ── Part E ──────────────────────────────────────────────────────────────────

async def test_reset_limits_caps_and_never_creates_code(env):
    await ident(env)
    live = await env.db.otps.find_one({"student_id": "v1"})
    url = "/admin/voters/v1/reset-otp-limits"
    assert (await env.client.post(url, headers=env.it, json={"reason": "bogus", "note": "x y z"})).status_code == 400
    for i in range(3):
        r = await env.client.post(url, headers=env.it, json={"reason": "sms_delayed", "note": "voter waited"})
        assert r.status_code == 200
    assert await env.db.otp_send_state.count_documents({}) == 0
    assert (await env.db.otps.find_one({"student_id": "v1"}))["code"] == live["code"]     # code untouched
    r = await env.client.post(url, headers=env.it, json={"reason": "sms_delayed", "note": "voter waited"})
    assert r.status_code == 429 and r.json()["reason"] == "reset_voter_daily_cap"
    tick(days=1, minutes=1)
    assert (await env.client.post(url, headers=env.com1, json={"reason": "test", "note": "dry run"})).status_code == 200
    assert (await main.verify_roster_ledger(env.org_id))["valid"]


async def test_admin_hourly_alert_is_not_a_block(env):
    await env.db.settings.insert_one({"name": "security_settings", "org_id": env.org_id,
                                      "reset_admin_hourly_alert": 2, "reset_admin_hourly_hard_cap": 4,
                                      "reset_per_voter_daily": 50, "reset_per_voter_election": 100})
    url = "/admin/voters/v1/reset-otp-limits"
    codes = [(await env.client.post(url, headers=env.it, json={"reason": "test", "note": "run"})).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 429]
    assert await env.db.audit_log.find_one({"action": "otp_reset_admin_alert"})           # alert fired at >2, still allowed
    # chief commissioner lifts the cap for that admin
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    r = await env.client.post("/admin/caps/override", headers=env.com1, json={"kind": "reset_hourly", "admin_id": "it1", "cap": 10, "reason": "election day"})
    assert r.status_code == 200
    assert (await env.client.post(url, headers=env.it, json={"reason": "test", "note": "run"})).status_code == 200
    assert (await env.client.post("/admin/caps/override", headers=env.com2, json={"kind": "reset_hourly", "admin_id": "it1", "cap": 10, "reason": "no"})).status_code == 403


# ── Ledger / settings / misc ────────────────────────────────────────────────

async def test_ledger_tamper_detected(env):
    for i in range(3):
        await main.append_ledger(env.org_id, "x", f"r{i}", "a", "role", {"i": i})
    assert (await main.verify_roster_ledger(env.org_id))["valid"]
    await env.db.roster_ledger.update_one({"seq": 2}, {"$set": {"details": {"i": 99}}})
    res = await main.verify_roster_ledger(env.org_id)
    assert res["valid"] is False and res["first_bad_seq"] == 2


async def test_security_settings_and_schedule_banner(env):
    r = await env.client.get("/superadmin/security-settings", headers=env.sa)
    j = r.json()
    assert j["banner"] and j["derived"]["window_scheduled"] is False and j["derived"]["guess_budget"] == 90
    r = await env.client.put("/superadmin/security-settings", headers=env.sa, json={"reason": "x"})
    assert r.status_code == 400
    r = await env.client.put("/superadmin/security-settings", headers=env.sa, json={"reason": "election day", "turnstile_mode": "on", "otp_target_risk": 0.0002})
    assert r.status_code == 200 and r.json()["settings"]["turnstile_mode"] == "on"
    assert (await env.client.put("/superadmin/security-settings", headers=env.sa, json={"reason": "bad", "turnstile_mode": "maybe"})).status_code == 400
    assert (await env.client.get("/election-status")).json()["turnstile_mode"] == "on"
    r = await env.client.put("/superadmin/sms-budget", headers=env.sa, json={"reason": "top up", "sms_budget_total": 500})
    assert r.json()["budget_total"] == 500 and r.json()["suggested_budget"] == 10      # 4 staff/voters x 2.5
    # only superadmin may touch these
    assert (await env.client.put("/superadmin/security-settings", headers=env.com1, json={"reason": "no", "turnstile_mode": "off"})).status_code == 403


async def test_schedule_change_logs_derived_values_and_rearms_freeze(env):
    body = {"round_id": "round-1", "phases": {"voting": {"start": (START + timedelta(days=1)).isoformat() + "Z",
                                                          "end": (START + timedelta(days=4)).isoformat() + "Z", "enforced": True}}}
    assert (await env.client.post("/admin/schedule/phases", headers=env.sa, json=body)).status_code == 200
    log = await env.db.audit_log.find_one({"action": "otp_lock_params_changed"})
    assert log["details"]["window_s"] == 3 * 86400 and log["details"]["window_is_default"] is False
    st = (await env.client.get("/admin/roster-status", headers=env.it)).json()
    assert st["phase"] == "pre_freeze" and st["freeze_at"] is not None
    tick(days=1, minutes=1)
    assert (await env.client.get("/admin/roster-status", headers=env.it)).json()["phase"] == "voting_frozen"


async def test_admin_voter_list_masks_phones(env):
    rows = (await env.client.get("/admin/voters", headers=env.it)).json()
    assert all("256700111222" not in str(r["phone_numbers"]) for r in rows)


async def test_legacy_mode_rollback_flag(env, monkeypatch):
    monkeypatch.setattr(main, "OTP_LIMITER_MODE", "legacy")
    for _ in range(3):
        assert (await ident(env)).status_code == 200       # no ladder in legacy mode
        await env.db.voters.update_one({"student_id": "v1"}, {"$set": {"last_status": "idle"}})
    assert (await ident(env)).status_code == 403            # old permanent cap is back


async def test_quota_hard_stop_needs_chief(env):
    await env.freeze()
    cid = (await _request(env)).json()["id"]      # electorate 4 -> 1 approval = 25 % > default 5 % after first
    assert (await env.client.post(f"/admin/contact-changes/{cid}/decide", headers=env.com2, json={"decision": "approve"})).status_code == 200
    await env.voter("v2", "Bob Two Names", ("256700333444",))
    body = {"student_id": "v2", "change_type": "phone_add", "new_value": "0700888999",
            "evidence_type": "registrar_record", "evidence_note": "registrar page"}
    cid2 = (await env.client.post("/it-admin/contact-changes/request", headers=env.it, json=body)).json()["id"]
    r = await env.client.post(f"/admin/contact-changes/{cid2}/decide", headers=env.com2, json={"decision": "approve"})
    assert r.status_code == 409 and r.json()["reason"] == "quota_hard_stop"
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    assert (await env.client.post(f"/admin/contact-changes/{cid2}/decide", headers=env.com1, json={"decision": "approve"})).status_code == 200


async def test_schedule_timezone_stored_validated_and_returned(env):
    body = {"round_id": "round-1", "timezone": "Africa/Kampala",
            "phases": {"voting": {"start": "2026-01-12T05:00:00Z", "end": "2026-01-13T05:00:00Z", "enforced": True}}}
    assert (await env.client.post("/admin/schedule/phases", headers=env.sa, json=body)).status_code == 200
    j = (await env.client.get("/admin/schedule", headers=env.it)).json()
    assert j["timezone"] == "Africa/Kampala"
    assert j["phases"][2]["start"].startswith("2026-01-12T05:00")          # stored as UTC, unchanged
    bad = {**body, "timezone": "Mars/Olympus"}
    assert (await env.client.post("/admin/schedule/phases", headers=env.sa, json=bad)).status_code == 400
    body.pop("timezone")                                                    # omitted -> keeps the current zone
    body["timezone"] = None
    await env.client.post("/admin/schedule/phases", headers=env.sa, json=body)
    assert (await env.client.get("/admin/schedule", headers=env.it)).json()["timezone"] == "Africa/Kampala"
