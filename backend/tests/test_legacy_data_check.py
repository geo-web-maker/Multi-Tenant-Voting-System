"""Superadmin 'Legacy data' check: find documents that belong to no organization, then assign or remove them."""
import pytest

import main
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

BASE = "/superadmin/legacy-data"


async def _seed(env):
    await env.db.voters.insert_one({"student_id": "old1", "org_id": None})
    await env.db.voters.insert_one({"student_id": "old2"})                       # field missing entirely
    await env.db.voters.insert_one({"student_id": "ok1", "org_id": env.org_id})  # tenant data: untouched
    await env.db.candidates.insert_one({"name": "Old Cand", "org_id": None})


def _by_name(r):
    return {c["name"]: c for c in r.json()["collections"]}


async def test_clean_database_reports_nothing(env):
    r = await env.client.get(BASE, headers=env.sa)
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_scan_counts_only_ownerless_documents(env):
    await _seed(env)
    await main.log_action("organization_created", "root")        # system event: must NOT be flagged
    r = await env.client.get(BASE, headers=env.sa)
    c = _by_name(r)
    assert c["voters"]["count"] == 2
    assert c["candidates"]["count"] == 1
    assert c["audit_log"]["count"] == 0
    assert r.json()["total"] == 3


async def test_scan_also_finds_default_sms_and_otp_keys(env):
    await env.db.sms_usage.insert_one({"org_key": "default", "sent_total": 5})
    await env.db.sms_usage.insert_one({"org_key": env.org_id, "sent_total": 9})
    await env.db.otp_send_state.insert_one({"key": "default:otp:v1"})
    await env.db.otp_send_state.insert_one({"key": f"{env.org_id}:otp:v1"})
    c = _by_name(await env.client.get(BASE, headers=env.sa))
    assert c["sms_usage"]["count"] == 1
    assert c["otp_send_state"]["count"] == 1 and c["otp_send_state"]["assignable"] is False


async def test_only_the_superadmin_can_use_it(env):
    assert (await env.client.get(BASE, headers=env.it)).status_code == 403
    assert (await env.client.post(f"{BASE}/delete", headers=env.it,
                                  json={"collections": ["voters"], "confirm": main.LEGACY_DELETE_CONFIRM})).status_code == 403
    assert (await env.client.get(BASE, headers={"X-Org-Slug": "t1"})).status_code in (401, 403)


async def test_works_without_an_org_header_for_the_superadmin(env):
    await _seed(env)
    r = await env.client.get(BASE, headers={**env.sa, "X-Org-Slug": ""})
    assert r.status_code == 200 and r.json()["total"] == 3


async def test_assign_moves_only_the_selected_ownerless_documents(env):
    base = await env.db.voters.count_documents({"org_id": env.org_id})      # the fixture already seeds voters
    await _seed(env)
    r = await env.client.post(f"{BASE}/assign", headers=env.sa,
                              json={"org_id": env.org_id, "collections": ["voters"]})
    assert r.status_code == 200
    assert r.json()["results"] == [{"name": "voters", "moved": 2}]
    assert await env.db.voters.count_documents({"org_id": env.org_id}) == base + 1 + 2
    assert await env.db.voters.count_documents({"org_id": None}) == 0
    assert await env.db.candidates.count_documents({"org_id": None}) == 1      # not selected: still legacy
    assert r.json()["remaining"] == 1
    log = await env.db.audit_log.find_one({"action": "legacy_data_assigned"})
    assert log["org_id"] == env.org_id and log["details"]["moved"] == {"voters": 2}


async def test_assign_validates_the_target_and_the_selection(env):
    await _seed(env)
    assert (await env.client.post(f"{BASE}/assign", headers=env.sa,
                                  json={"org_id": "nope", "collections": ["voters"]})).status_code == 400
    assert (await env.client.post(f"{BASE}/assign", headers=env.sa,
                                  json={"org_id": "507f1f77bcf86cd799439011", "collections": ["voters"]})).status_code == 404
    assert (await env.client.post(f"{BASE}/assign", headers=env.sa,
                                  json={"org_id": env.org_id, "collections": ["users"]})).status_code == 400
    assert (await env.client.post(f"{BASE}/assign", headers=env.sa,
                                  json={"org_id": env.org_id, "collections": ["positions"]})).status_code == 400   # nothing to move
    assert await env.db.voters.count_documents({"org_id": None}) == 2


async def test_hash_chained_collections_cannot_be_assigned(env):
    await env.db.vote_events.insert_one({"candidate_id": "c", "org_id": None})
    r = await env.client.post(f"{BASE}/assign", headers=env.sa,
                              json={"org_id": env.org_id, "collections": ["vote_events"]})
    assert r.status_code == 400
    assert await env.db.vote_events.count_documents({"org_id": None}) == 1


async def test_assign_sms_usage_renames_the_default_counter_and_reports_a_clash(env):
    await env.db.sms_usage.insert_one({"org_key": "default", "sent_total": 5})
    r = await env.client.post(f"{BASE}/assign", headers=env.sa,
                              json={"org_id": env.org_id, "collections": ["sms_usage"]})
    assert r.json()["results"] == [{"name": "sms_usage", "moved": 1}]
    assert await env.db.sms_usage.find_one({"org_key": env.org_id}) is not None
    # a second default counter now clashes with the one the org already has
    await env.db.sms_usage.insert_one({"org_key": "default", "sent_total": 2})
    r = await env.client.post(f"{BASE}/assign", headers=env.sa,
                              json={"org_id": env.org_id, "collections": ["sms_usage"]})
    assert r.json()["results"][0]["moved"] == 0 and "error" in r.json()["results"][0]
    assert await env.db.sms_usage.find_one({"org_key": "default"}) is not None


async def test_delete_needs_the_confirmation_phrase(env):
    await _seed(env)
    r = await env.client.post(f"{BASE}/delete", headers=env.sa, json={"collections": ["voters"], "confirm": "yes"})
    assert r.status_code == 400
    assert await env.db.voters.count_documents({"org_id": None}) == 2


async def test_delete_takes_a_snapshot_first_and_removes_only_ownerless_documents(env, monkeypatch):
    base = await env.db.voters.count_documents({"org_id": env.org_id})      # the fixture already seeds voters
    await _seed(env)
    calls = []

    async def fake_snapshot(db, label):
        calls.append(label)
        return {"prefix": "safety/default/legacy-delete-x"}
    monkeypatch.setattr(main.backup, "snapshot_legacy_data", fake_snapshot)
    r = await env.client.post(f"{BASE}/delete", headers=env.sa,
                              json={"collections": ["voters"], "confirm": main.LEGACY_DELETE_CONFIRM})
    assert r.status_code == 200 and r.json()["deleted"] == {"voters": 2}
    assert calls == ["legacy-delete"]
    assert await env.db.voters.count_documents({"org_id": env.org_id}) == base + 1      # tenant data survives
    assert await env.db.candidates.count_documents({"org_id": None}) == 1        # not selected


async def test_delete_aborts_when_the_snapshot_fails(env, monkeypatch):
    await _seed(env)

    async def boom(db, label):
        raise RuntimeError("b2 down")
    monkeypatch.setattr(main.backup, "snapshot_legacy_data", boom)
    r = await env.client.post(f"{BASE}/delete", headers=env.sa,
                              json={"collections": ["voters"], "confirm": main.LEGACY_DELETE_CONFIRM})
    assert r.status_code == 503
    assert await env.db.voters.count_documents({"org_id": None}) == 2


async def test_removing_only_short_lived_sms_state_needs_no_snapshot(env, monkeypatch):
    await env.db.sms_usage.insert_one({"org_key": "default"})
    await env.db.otp_send_state.insert_one({"key": "default:otp:v1"})

    async def never(db, label):
        raise AssertionError("no snapshot expected for non-backed-up collections")
    monkeypatch.setattr(main.backup, "snapshot_legacy_data", never)
    r = await env.client.post(f"{BASE}/delete", headers=env.sa,
                              json={"collections": ["sms_usage", "otp_send_state"], "confirm": main.LEGACY_DELETE_CONFIRM})
    assert r.status_code == 200 and r.json()["remaining"] == 0
