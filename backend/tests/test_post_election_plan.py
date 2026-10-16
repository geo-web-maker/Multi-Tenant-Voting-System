"""Regression tests for the post-election plan (provisional results, ties and rounds)."""
from datetime import timedelta
import pytest

from tests.test_flows import env, START
import main

pytestmark = pytest.mark.asyncio


async def _closed_schedule(e, *, end_offset=-1, round_id="round-1"):
    await e.db.settings.update_one(
        {"org_id": e.org_id, "name": "election_phases"},
        {"$set": {"org_id": e.org_id, "name": "election_phases", "round_id": round_id,
                  "timezone": "Africa/Kampala",
                  "phases": {"voting": {"start": START - timedelta(hours=2),
                                          "end": START + timedelta(minutes=end_offset),
                                          "enforced": True}}}}, upsert=True)


async def _results_security(e, mode="closed"):
    await e.db.settings.update_one(
        {"org_id": e.org_id, "name": "security_settings"},
        {"$set": {"org_id": e.org_id, "name": "security_settings", "public_results_mode": mode}}, upsert=True)
    await e.db.settings.update_one(
        {"org_id": e.org_id, "name": "election_config"},
        {"$set": {"org_id": e.org_id, "name": "election_config", "is_open": True,
                  "is_certified": False}}, upsert=True)


async def test_closed_mode_releases_when_scheduled_window_ends_even_if_master_switch_true(env):
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=-1)
    candidate = await env.db.candidates.insert_one({"org_id": env.org_id, "name": "Candidate A", "position": "Chair", "order": 1})
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": candidate.inserted_id,
                                        "cast_at": START, "round_id": "round-1"})
    r = await env.client.get("/election-results")
    assert r.status_code == 200
    assert r.json()["results_released"] is True
    assert r.json()["results"][0]["votes"] == 1


async def test_closed_mode_still_embargoes_while_window_open(env):
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=30)
    r = await env.client.get("/election-results")
    assert r.status_code == 200
    assert r.json()["results_released"] is False
    assert r.json()["results"] == []


async def test_certified_mode_remains_released(env):
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=30)
    await env.db.settings.update_one({"org_id": env.org_id, "name": "election_config"}, {"$set": {"is_certified": True}})
    r = await env.client.get("/election-results")
    assert r.status_code == 200
    assert r.json()["results_released"] is True


async def test_tie_is_persisted_without_voter_identity_after_window_ends(env):
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=-1)
    one = await env.db.candidates.insert_one({"org_id": env.org_id, "name": "Candidate A", "position": "Chair", "order": 1})
    two = await env.db.candidates.insert_one({"org_id": env.org_id, "name": "Candidate B", "position": "Chair", "order": 2})
    await env.db.vote_events.insert_many([
        {"org_id": env.org_id, "candidate_id": one.inserted_id, "cast_at": START, "round_id": "round-1"},
        {"org_id": env.org_id, "candidate_id": two.inserted_id, "cast_at": START, "round_id": "round-1"},
    ])
    r = await env.client.get("/election-results")
    assert r.status_code == 200
    ties = await env.db.ties.find({"org_id": env.org_id, "round_id": "round-1"}).to_list(None)
    assert len(ties) == 1
    assert set(ties[0]["candidate_ids"]) == {str(one.inserted_id), str(two.inserted_id)}
    assert ties[0]["count"] == 1
    assert "voter_id" not in ties[0] and "student_id" not in ties[0]


async def test_unenforced_window_does_not_force_closed_results(env):
    await _results_security(env, "closed")
    await env.db.settings.update_one(
        {"org_id": env.org_id, "name": "election_phases"},
        {"$set": {"org_id": env.org_id, "name": "election_phases", "round_id": "round-1",
                  "phases": {"voting": {"start": START - timedelta(hours=2), "end": START - timedelta(hours=1), "enforced": False}}}}, upsert=True)
    r = await env.client.get("/election-results")
    assert r.status_code == 200
    assert r.json()["results_released"] is False


async def test_multi_seat_cutoff_tie_is_detected(env):
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=-1)
    await env.db.positions.insert_one({"org_id": env.org_id, "title": "Council", "seats": 2})
    candidates = []
    for name, order in [("A", 1), ("B", 2), ("C", 3), ("D", 4)]:
        candidates.append(await env.db.candidates.insert_one({
            "org_id": env.org_id, "name": name, "position": "Council", "order": order,
        }))
    for candidate, count in zip(candidates, [3, 2, 2, 1]):
        await env.db.vote_events.insert_many([
            {"org_id": env.org_id, "candidate_id": candidate.inserted_id,
             "cast_at": START, "round_id": "round-1"}
            for _ in range(count)
        ])

    response = await env.client.get("/election-results")
    assert response.status_code == 200
    tie = await env.db.ties.find_one({"org_id": env.org_id, "round_id": "round-1", "tie_type": "cutoff"})
    assert tie is not None
    assert set(tie["candidate_ids"]) == {str(candidates[1].inserted_id), str(candidates[2].inserted_id)}
    assert tie["count"] == 2


async def test_prior_round_certification_does_not_release_scheduled_by_election(env):
    await _results_security(env, "closed")
    await env.db.settings.update_one(
        {"org_id": env.org_id, "name": "election_config"},
        {"$set": {"is_open": False, "is_certified": True}},
    )
    new_round_id = "by-election-test"
    await env.db.rounds.insert_one({
        "org_id": env.org_id, "round_id": new_round_id, "kind": "by_election",
        "status": "scheduled", "candidate_ids": [], "parent_round_id": "round-1",
        "phases": {"voting": {"start": START + timedelta(minutes=5),
                              "end": START + timedelta(hours=1), "enforced": True}},
    })
    await _closed_schedule(env, end_offset=60, round_id=new_round_id)
    # Ensure the future scheduled start is preserved on the current round's schedule.
    await env.db.settings.update_one(
        {"org_id": env.org_id, "name": "election_phases"},
        {"$set": {"phases.voting.start": START + timedelta(minutes=5),
                  "phases.voting.end": START + timedelta(hours=1)}},
    )
    response = await env.client.get("/election-results")
    assert response.status_code == 200
    assert response.json()["results_released"] is False
    assert response.json()["results"] == []


def test_otp_limiter_state_is_scoped_by_round_without_changing_round_one_key():
    # Student ids are normalised (lower-cased) before keying; Round 1's key format is unchanged.
    assert main._otp_key_for("org-a", "S123", "round-1") == "org-a:otp:s123"
    assert main._otp_key_for("org-a", "S123", "by-election-abc") == "org-a:otp:s123:round:by-election-abc"
    assert main._otp_key_for("org-b", "S123", "by-election-abc") != main._otp_key_for("org-a", "S123", "by-election-abc")


async def test_by_election_results_only_include_its_candidates(env):
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=-1)
    round_id = "by-election-results-test"
    round_candidates = []
    for name in ("Tied A", "Tied B"):
        row = await env.db.candidates.insert_one({
            "org_id": env.org_id, "name": name, "position": "Chair", "order": 1,
        })
        round_candidates.append(row.inserted_id)
    await env.db.candidates.insert_one({
        "org_id": env.org_id, "name": "Unrelated Round 1 Candidate", "position": "Treasurer", "order": 1,
    })
    await env.db.rounds.insert_one({
        "org_id": env.org_id, "round_id": round_id, "kind": "by_election",
        "status": "closed", "candidate_ids": [str(value) for value in round_candidates],
        "parent_round_id": "round-1", "phases": {"voting": {"start": START - timedelta(hours=2),
            "end": START - timedelta(minutes=1), "enforced": True}},
    })
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": round_candidates[0],
        "cast_at": START, "round_id": round_id})
    response = await env.client.get("/election-results", params={"round_id": round_id})
    assert response.status_code == 200
    assert {row["name"] for row in response.json()["results"]} == {"Tied A", "Tied B"}
    assert sum(row["votes"] for row in response.json()["results"]) == 1

async def test_round1_candidate_snapshot_preserves_closed_results_after_candidate_edit(env, monkeypatch):
    monkeypatch.setattr(main, "_RESULTS_TTL", 0)
    await _results_security(env, "closed")
    await _closed_schedule(env, end_offset=-1)
    original = await env.db.candidates.insert_one({
        "org_id": env.org_id, "name": "Original Chair", "position": "Chair", "order": 1,
    })
    await env.db.vote_events.insert_one({
        "org_id": env.org_id, "candidate_id": original.inserted_id,
        "cast_at": START, "round_id": "round-1",
    })

    before = await env.client.get("/election-results")
    assert before.status_code == 200
    assert any(row["name"] == "Original Chair" for row in before.json()["results"])
    snapshot = await env.db.rounds.find_one({"org_id": env.org_id, "round_id": "round-1"})
    assert snapshot and snapshot.get("candidate_snapshot")

    await env.db.candidates.update_one(
        {"org_id": env.org_id, "_id": original.inserted_id},
        {"$set": {"name": "Renamed After Close", "position": "Treasurer"}},
    )
    await env.db.candidates.insert_one({
        "org_id": env.org_id, "name": "Late Candidate", "position": "President", "order": 2,
    })

    after = await env.client.get("/election-results")
    assert after.status_code == 200
    by_id = {row["id"]: row for row in after.json()["results"]}
    assert by_id[str(original.inserted_id)]["name"] == "Original Chair"
    assert by_id[str(original.inserted_id)]["position"] == "Chair"
    assert not any(row["name"] == "Late Candidate" for row in after.json()["results"])


async def _by_election_round(env, round_id="by-election-sched", with_tie=True):
    tie = await env.db.ties.insert_one({"org_id": env.org_id, "round_id": "round-1", "position": "Chair",
                                        "candidate_ids": [], "count": 2, "status": "by_election_ordered"})
    await env.db.rounds.insert_one({"parent_tie_id": str(tie.inserted_id) if with_tie else None,
        "org_id": env.org_id, "round_id": round_id, "kind": "by_election", "status": "scheduled",
        "position": "Chair", "candidate_ids": [], "parent_round_id": "round-1", "phases": {}})
    await _closed_schedule(env, end_offset=-1, round_id=round_id)
    return round_id


async def test_by_election_schedule_is_set_from_its_own_endpoint(env):
    rid = await _by_election_round(env)
    start = (main.datetime.utcnow() + timedelta(hours=1)).replace(microsecond=0)
    end = start + timedelta(hours=4)
    r = await env.client.post(f"/superadmin/by-elections/{rid}/schedule", headers=env.sa,
                              json={"start": start.isoformat() + "Z", "end": end.isoformat() + "Z"})
    assert r.status_code == 200, r.text
    got = (await env.client.get(f"/superadmin/by-elections/{rid}/schedule", headers=env.sa)).json()
    assert got["state"] == "upcoming" and got["is_active_round"] is True
    assert got["voting"]["enforced"] is True
    doc = await env.db.rounds.find_one({"round_id": rid})
    assert doc["phases"]["voting"]["start"] == start and doc["status"] == "scheduled"


async def test_by_election_schedule_validation_and_access(env):
    rid = await _by_election_round(env, "by-election-sched2")
    now = main.datetime.utcnow()
    bad = await env.client.post(f"/superadmin/by-elections/{rid}/schedule", headers=env.sa,
        json={"start": (now + timedelta(hours=2)).isoformat() + "Z", "end": (now + timedelta(hours=1)).isoformat() + "Z"})
    assert bad.status_code == 400
    past = await env.client.post(f"/superadmin/by-elections/{rid}/schedule", headers=env.sa,
        json={"start": (now - timedelta(hours=3)).isoformat() + "Z", "end": (now - timedelta(hours=2)).isoformat() + "Z"})
    assert past.status_code == 400
    ok_body = {"start": (now + timedelta(hours=1)).isoformat() + "Z", "end": (now + timedelta(hours=2)).isoformat() + "Z"}
    assert (await env.client.post("/superadmin/by-elections/round-1/schedule", headers=env.sa, json=ok_body)).status_code == 404
    assert (await env.client.post(f"/superadmin/by-elections/{rid}/schedule", headers=env.it, json=ok_body)).status_code == 403
    await env.db.rounds.update_one({"round_id": rid}, {"$set": {"status": "certified"}})
    assert (await env.client.post(f"/superadmin/by-elections/{rid}/schedule", headers=env.sa, json=ok_body)).status_code == 409


async def test_by_election_schedule_refused_without_a_recorded_tie(env):
    rid = await _by_election_round(env, "by-election-orphan", with_tie=False)
    now = main.datetime.utcnow()
    body = {"start": (now + timedelta(hours=1)).isoformat() + "Z", "end": (now + timedelta(hours=2)).isoformat() + "Z"}
    assert (await env.client.post(f"/superadmin/by-elections/{rid}/schedule", headers=env.sa, json=body)).status_code == 409


async def _voter(env, sid, name, phones, **kw):
    await env.db.voters.insert_one({"org_id": env.org_id, "student_id": sid, "full_name": name,
                                    "phone_numbers": phones, **kw})


async def test_shared_contacts_work_without_a_tie_and_report_statistics(env):
    await _voter(env, "s1", "A One", ["256772000111"], has_voted=True)
    await _voter(env, "s2", "B Two", ["256772000111"])
    await _voter(env, "s3", "C Three", ["256700999999"])
    r = await env.client.get("/admin/shared-contacts", headers=env.it)
    assert r.status_code == 200, r.text
    st = r.json()["stats"]
    assert st["total_voters"] >= 3 and st["shared_numbers"] == 1 and st["voters_sharing"] == 2
    assert st["unresolved_numbers"] == 1 and st["already_voted_sharing"] == 1 and st["largest_group"] == 2
    assert (await env.client.get("/admin/shared-contacts", headers=env.over)).status_code == 403


async def test_shared_contacts_groups_and_recommendations(env):
    await _voter(env, "s1", "Jane Doe", ["256772000111"], has_voted=True)
    await _voter(env, "s2", "jane  doe", ["256772000111"])           # duplicate record
    await _voter(env, "s3", "Amos K", ["256772000111", "256701000222"])
    await _voter(env, "s4", "Solo", ["256700999999"])
    r = await env.client.get("/admin/shared-contacts", headers=env.sa)
    assert r.status_code == 200, r.text
    groups = r.json()["groups"]
    assert len(groups) == 1 and groups[0]["count"] == 3 and groups[0]["possible_duplicate"] is True
    rec = {v["student_id"]: v["recommended"] for v in groups[0]["voters"]}
    assert rec == {"s1": "keep", "s2": "delete_voter", "s3": "remove_contact"}
    assert groups[0]["phone_masked"].endswith("111") and "256772" not in groups[0]["phone_masked"]
    assert (await env.client.get("/admin/shared-contacts", headers=env.over)).status_code == 403


async def test_shared_contact_can_be_acknowledged_with_a_reason(env):
    await env.db.ties.insert_one({"org_id": env.org_id, "round_id": "round-1", "position": "Chair",
                                  "candidate_ids": [], "count": 2, "status": "pending"})
    await _voter(env, "s1", "A One", ["256772000111"])
    await _voter(env, "s2", "B Two", ["256772000111"])
    short = await env.client.post("/admin/shared-contacts/acknowledge", headers=env.sa,
                                  json={"phone": "256772000111", "reason": "short"})
    assert short.status_code == 422
    ok = await env.client.post("/admin/shared-contacts/acknowledge", headers=env.sa,
                               json={"phone": "256772000111", "reason": "Siblings share one household phone"})
    assert ok.status_code == 200
    g = (await env.client.get("/admin/shared-contacts", headers=env.sa)).json()["groups"][0]
    assert g["acknowledged"] is True
    missing = await env.client.post("/admin/shared-contacts/acknowledge", headers=env.sa,
                                    json={"phone": "256700000000", "reason": "Not on any voter at all"})
    assert missing.status_code == 404


def test_otp_split_order_follows_the_ratio_and_always_keeps_a_fallback():
    assert main.otp_split_order(100, 0.999) == ["egosms", "mambosms"]
    assert main.otp_split_order(0, 0.0) == ["mambosms", "egosms"]
    firsts = [main.otp_split_order(30, i / 1000)[0] for i in range(1000)]
    assert firsts.count("egosms") == 300
    assert all(len(main.otp_split_order(30, r)) == 2 for r in (0.1, 0.9))


async def test_otp_split_settings_are_saved_validated_and_reported(env):
    r = await env.client.put("/superadmin/sms-budget", headers=env.sa, json={
        "reason": "ratio test", "otp_split_enabled": True, "otp_first_ego_pct": 30, "otp_resend_ego_pct": 100})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["otp_split_enabled"] is True and j["otp_first_ego_pct"] == 30 and j["otp_resend_ego_pct"] == 100
    bad = await env.client.put("/superadmin/sms-budget", headers=env.sa, json={"reason": "ratio test", "otp_first_ego_pct": 130})
    assert bad.status_code == 400


async def test_routed_otp_uses_the_configured_split(env, monkeypatch):
    calls = []
    async def fake(provider, to, msg):
        calls.append(provider); return "ok"
    monkeypatch.setattr(main, "_sms_try_provider", fake)
    async def noop(*a, **k): return None
    monkeypatch.setattr(main, "_safe_count_sms", noop)
    await env.client.put("/superadmin/sms-budget", headers=env.sa, json={
        "reason": "ratio test", "otp_split_enabled": True, "otp_first_ego_pct": 0, "otp_resend_ego_pct": 100})
    assert await main._send_sms_routed("256700000001", "x", env.org_id, "otp", is_resend=False) == "ok"
    assert await main._send_sms_routed("256700000001", "x", env.org_id, "otp", is_resend=True) == "ok"
    assert calls == ["mambosms", "egosms"]
