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
