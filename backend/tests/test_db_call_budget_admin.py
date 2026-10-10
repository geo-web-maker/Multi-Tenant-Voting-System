"""Database-call budgets for the polled admin / public screens and the SMS send path. Counts are what main.py asks
Mongo for (tests/opcount.py). Guards the N+1 and repeated-lookup fixes: a regression shows up as a count that
grows with the number of rows instead of staying flat."""
import pytest

import auth
import main
from tests.opcount import CountingDB, FakeClient
from tests.test_flows import env, ident  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def counted(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    monkeypatch.setattr(main, "client", FakeClient())
    monkeypatch.setattr(main, "_SETTINGS_TTL", 5.0)
    monkeypatch.setattr(main, "_RESULTS_TTL", 5.0)
    main.invalidate_settings()
    yield cdb
    main.invalidate_settings()


async def _positions_and_apps(env, n_apps):
    pos = [str((await env.db.positions.insert_one({"org_id": env.org_id, "title": t, "order": i})).inserted_id)
           for i, t in enumerate(["President", "Secretary", "Treasurer"])]
    for i in range(n_apps):
        await env.db.applications.insert_one({
            "org_id": env.org_id, "student_id": f"a{i}", "full_name": f"A {i}", "position_id": pos[i % 3],
            "status": "pending", "finance_cleared": True, "round_id": "r1",
            "submitted_at": main.datetime.utcnow(), "votes": {}})
    return pos


async def _ops(counted, env, path, hdr):
    await env.client.get(path, headers=hdr)                      # warm the settings cache
    s = counted.snapshot()
    r = await env.client.get(path, headers=hdr)
    assert r.status_code == 200, r.text
    return counted.since(s), r


@pytest.mark.parametrize("path,hdr", [("/admin/applications", "sa"), ("/it-admin/applications", "it")])
async def test_application_lists_do_not_query_per_row(env, counted, path, hdr):
    await _positions_and_apps(env, 12)
    d, r = await _ops(counted, env, path, getattr(env, hdr))
    assert len(r.json()) == 12
    assert sum(n for (c, m), n in d.items() if c == "positions") == 1, d      # was one lookup per application
    assert sum(d.values()) <= 4, d
    assert {a["position_title"] for a in r.json()} == {"President", "Secretary", "Treasurer"}


async def test_unknown_or_malformed_position_ids_keep_their_fallback(env):
    pos = await env.db.positions.insert_one({"org_id": env.org_id, "title": "President", "order": 7})
    got = await main._resolve_position_titles([str(pos.inserted_id), "nonsense", "5" * 24, None, ""], env.org_id)
    assert got == {str(pos.inserted_id): ("President", 7), "nonsense": ("nonsense", 0), "5" * 24: ("5" * 24, 0)}
    for pid in got:
        assert got[pid] == await main._resolve_position_title(pid, env.org_id)


async def test_voter_stats_is_one_pass_and_matches_the_counts(env, counted):
    await env.db.settings.insert_one({"org_id": env.org_id, "name": "voter_fields", "fields": [
        {"key": "gender", "label": "Gender", "standard": True, "enabled": True, "public": True},
        {"key": "programme", "label": "Programme", "standard": True, "enabled": True, "public": False}]})
    for i in range(30):
        await env.voter(f"s{i}", f"Stu {i}", () if i % 5 == 0 else ("256700000%03d" % i,),
                        attrs={"gender": "M" if i % 2 else "F", "programme": f"P{i % 3}"}, has_voted=i % 3 == 0)
    d, r = await _ops(counted, env, "/admin/voters/stats", env.sa)
    assert sum(n for (c, m), n in d.items() if c == "voters") == 1, d          # was 6 with two enabled fields
    body = r.json()
    total = await env.db.voters.count_documents({})
    assert body["total"] == total
    assert body["voted"] == await env.db.voters.count_documents({"has_voted": True})
    assert body["with_phone"] == await env.db.voters.count_documents({"phone_numbers": {"$exists": True, "$ne": []}})
    for sec in body["sections"]:
        assert sum(g["registered"] for g in sec["groups"]) == total
    d, r = await _ops(counted, env, "/admin/analytics/turnout-breakdown", env.sa)
    assert sum(n for (c, m), n in d.items() if c == "voters") == 1, d


async def test_admin_request_checks_revocation_once_and_a_revoked_token_is_still_refused(env, counted):
    auth.set_revocation_check(main._is_token_revoked)
    try:
        s = counted.snapshot()
        assert (await env.client.get("/admin/voters/stats", headers=env.sa)).status_code == 200
        assert counted.since(s).get(("revoked_tokens", "find_one"), 0) == 1      # was 2 (guard + route dependency)
        import jwt
        jti = jwt.decode(env.sa["Authorization"].split()[1], options={"verify_signature": False})["jti"]
        await env.db.revoked_tokens.insert_one({"jti": jti})
        assert (await env.client.get("/admin/voters/stats", headers=env.sa)).status_code == 401
    finally:
        auth.set_revocation_check(None)


async def test_fired_budget_alerts_cost_no_extra_writes(env, counted):
    await env.db.settings.insert_one({"org_id": env.org_id, "name": "security_settings", "sms_budget_total": 100})
    await env.db.sms_usage.insert_one({"org_key": env.org_id, "sent_total": 80, "sent_otp": 80,
                                       "alerts_fired": [0.5, 0.25]})            # 20% left, both thresholds fired
    await env.voter("w1", "Warm Up", ("256700111333",))
    await ident(env, "w1", "Warm Up")
    s = counted.snapshot()
    assert (await ident(env)).status_code == 200
    d = counted.since(s)
    assert d.get(("sms_usage", "update_one"), 0) == 0, d                         # was 2 (one per fired threshold)
    assert sum(d.values()) <= 10, d


async def test_a_new_threshold_still_fires_exactly_once(env, counted):
    await env.db.settings.insert_one({"org_id": env.org_id, "name": "security_settings", "sms_budget_total": 100})
    await env.db.sms_usage.insert_one({"org_key": env.org_id, "sent_total": 90, "sent_otp": 90, "alerts_fired": [0.5, 0.25]})
    await env.voter("w1", "Warm Up", ("256700111333",))
    await ident(env, "w1", "Warm Up")
    doc = await env.db.sms_usage.find_one({"org_key": env.org_id})
    assert sorted(doc["alerts_fired"]) == [0.1, 0.25, 0.5]
    n_alerts = await env.db.audit_log.count_documents({"action": "sms_budget_alert"})
    await ident(env, "w1", "Warm Up")                                            # another send: no repeat alert
    assert await env.db.audit_log.count_documents({"action": "sms_budget_alert"}) == n_alerts


async def test_ip_lookup_is_skipped_when_turnstile_is_off_but_kept_for_adaptive(env, counted):
    await env.voter("w2", "Warm Two", ("256700111444",))
    await ident(env, "w2", "Warm Two")                                            # warm caches
    s = counted.snapshot()
    assert (await ident(env)).status_code == 200                                   # default mode "off"
    assert counted.since(s).get(("ip_send_stats", "find_one"), 0) == 0

    await env.db.settings.insert_one({"org_id": env.org_id, "name": "security_settings", "turnstile_mode": "adaptive"})
    main.invalidate_settings()
    await env.voter("w3", "Warm Three", ("256700111555",))
    s = counted.snapshot()
    assert (await ident(env, "w3", "Warm Three")).status_code == 200               # unflagged IP passes
    assert counted.since(s).get(("ip_send_stats", "find_one"), 0) == 1             # adaptive still reads the IP record
