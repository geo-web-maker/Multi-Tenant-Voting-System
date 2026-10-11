"""Official List of Candidates: automatic issue, debounce, supersede, roles, public verify."""
from datetime import timedelta

import pytest

import candidate_list
import main
from tests.test_flows import env, tick, Clock, START  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def _vetting(e, ended=True):
    end = START - timedelta(hours=1) if ended else START + timedelta(days=3)
    await e.db.settings.update_one(
        {"name": "election_phases", "org_id": e.org_id},
        {"$set": {"name": "election_phases", "org_id": e.org_id, "round_id": "round-1",
                  "phases": {"vetting": {"start": START - timedelta(days=5), "end": end, "enforced": False}}}},
        upsert=True)


async def _cand(e, name, position="Chairperson", order=1, **kw):
    r = await e.db.candidates.insert_one({"org_id": e.org_id, "name": name, "position": position, "order": order,
                                          "votes": 0, "student_id": "SECRET-1", "phone": "256700999999", **kw})
    return r.inserted_id


async def _get(e, headers):
    return await e.client.get("/admin/candidate-list", headers=headers)


async def _lists(e):
    return [d async for d in e.db.candidate_lists.find({}).sort("seq", 1)]


async def test_no_list_before_vetting_closes(env):
    await _vetting(env, ended=False)
    await _cand(env, "Jane Namukasa")
    r = await _get(env, env.sa)
    assert r.status_code == 200 and r.json() == {"available": False, "reason": "not_closed", "can_issue": True}
    assert await _lists(env) == []


async def test_first_list_after_close_out_is_ballot_ordered_names_only(env):
    await _vetting(env)
    await _cand(env, "Aisha Nakato", "General Secretary", order=3)
    await _cand(env, "Brian Okello", "Chairperson", order=1)
    await _cand(env, "Jane Namukasa", "Chairperson", order=1)
    await _cand(env, "David Mugisha", "Vice Chairperson", order=2)
    r = await _get(env, env.it)
    body = r.json()
    assert r.status_code == 200 and body["available"] and body["list"]["list_id"].startswith("LIST-")
    assert [(s["position"], s["names"]) for s in body["list"]["sections"]] == [
        ("Chairperson", ["Brian Okello", "Jane Namukasa"]),
        ("Vice Chairperson", ["David Mugisha"]),
        ("General Secretary", ["Aisha Nakato"])]
    assert "SECRET-1" not in str(body) and "256700999999" not in str(body)
    assert (await env.db.audit_log.find_one({"action": "candidate_list_issued"}))["actor"] == "system"


async def test_waits_while_close_out_still_has_open_applications(env):
    await _vetting(env)
    await _cand(env, "Jane Namukasa")
    await env.db.applications.insert_one({"org_id": env.org_id, "student_id": "v9", "status": "pending",
                                          "finance_cleared": True, "votes": {}})
    assert await main._maybe_issue_candidate_list(env.org_id) is None
    await env.db.applications.update_many({}, {"$set": {"closeout_handled": True}})
    assert (await main._maybe_issue_candidate_list(env.org_id))["list_id"]


async def test_reissue_waits_for_quiet_then_supersedes(env):
    await _vetting(env)
    await _cand(env, "Jane Namukasa")
    first = (await _get(env, env.sa)).json()["list"]["list_id"]
    await _cand(env, "Brian Okello")
    await main._candidates_changed(env.org_id, "Candidate approved")
    tick(seconds=60)
    await main._candidates_changed(env.org_id, "Candidate approved")      # another change resets the wait
    tick(seconds=100)
    assert await main._maybe_issue_candidate_list(env.org_id) is None
    tick(seconds=30)
    new = await main._maybe_issue_candidate_list(env.org_id)
    assert new and new["reason"] == "Candidate approved" and new["count"] == 2
    old, cur = await _lists(env)
    assert old["list_id"] == first and old["superseded_by"] == cur["list_id"] and cur["superseded_at"] is None

    stale = await env.client.get(f"/verify-list/{first}")
    assert stale.json()["current"] is False and stale.json()["superseded_at"] is not None
    assert (await env.client.get(f"/verify-list/{cur['list_id']}")).json()["current"] is True


async def test_change_that_leaves_the_list_identical_issues_nothing(env):
    await _vetting(env)
    cid = await _cand(env, "Jane Namukasa")
    await _get(env, env.sa)
    await env.db.candidates.update_one({"_id": cid}, {"$set": {"image_url": "x.png"}})
    await main._candidates_changed(env.org_id, "Candidate updated")
    tick(minutes=5)
    assert await main._maybe_issue_candidate_list(env.org_id) is None
    assert len(await _lists(env)) == 1
    assert "dirty_at" not in (await env.db.settings.find_one({"name": candidate_list.STATE_NAME}) or {})


async def test_ballot_changes_flag_the_list(env):
    await _vetting(env)
    r = await env.client.post("/candidates", headers=env.sa, json={"name": "Grace Atim", "position": "Treasurer", "image_url": "x", "order": 4})
    assert r.status_code == 200
    state = await env.db.settings.find_one({"name": candidate_list.STATE_NAME})
    assert state["dirty_reason"] == "Candidate added"
    await env.client.delete(f"/candidates/{r.json()['id']}", headers=env.sa)
    assert (await env.db.settings.find_one({"name": candidate_list.STATE_NAME}))["dirty_reason"] == "Candidate deleted"


async def test_roles_download_vs_issue(env):
    await _vetting(env)
    await _cand(env, "Jane Namukasa")
    fc = env.tok("fc1", "financial_controller")
    for h in (env.sa, env.com1, env.it, fc):
        assert (await _get(env, h)).status_code == 200
    assert (await _get(env, env.it)).json()["can_issue"] is False
    assert (await _get(env, env.over)).status_code == 403
    for h in (env.it, fc, env.over):
        assert (await env.client.post("/admin/candidate-list/issue", headers=h)).status_code == 403
    assert (await env.client.get("/admin/candidate-list", headers={"X-Org-Slug": "t1"})).status_code in (401, 403)


async def test_manual_issue_is_audited_and_skips_identical(env):
    await _vetting(env)
    await _cand(env, "Jane Namukasa")
    await _get(env, env.sa)                                                # system issues list 1
    same = await env.client.post("/admin/candidate-list/issue", headers=env.com1)
    assert same.json()["status"] == "unchanged" and len(await _lists(env)) == 1
    await _cand(env, "Brian Okello")
    done = await env.client.post("/admin/candidate-list/issue", headers=env.com1)
    assert done.json()["status"] == "issued" and len(await _lists(env)) == 2
    log = await env.db.audit_log.find_one({"action": "candidate_list_issued", "actor": "com1"})
    assert log["details"]["reason"] == "Issued manually"


async def test_public_verify_has_no_names_and_unknown_id_is_404(env):
    await _vetting(env)
    await _cand(env, "Jane Namukasa")
    lid = (await _get(env, env.sa)).json()["list"]["list_id"]
    r = await env.client.get(f"/verify-list/{lid}", headers={})            # no auth, no org header
    assert r.status_code == 200 and "Jane" not in r.text and r.json()["org_name"] == "T1"
    assert (await env.client.get("/verify-list/LIST-NOPE", headers={})).status_code == 404


async def test_two_workers_cannot_issue_the_same_seq(env):
    await env.db.candidate_lists.create_index([("org_id", 1), ("seq", 1)], unique=True)
    t = main.tdb_for(env.org_id)
    await _cand(env, "Jane Namukasa")
    secs = await candidate_list.current_sections(t)
    assert await candidate_list.issue(t, reason="winner", actor="system", branding={}, now=Clock.now, sections=secs)

    class StaleRead:   # the loser read "no list yet" just before the winner inserted
        candidate_lists = type("C", (), {
            "find_one": staticmethod(lambda *a, **k: _none()),
            "insert_one": staticmethod(t.candidate_lists.insert_one),
            "update_many": staticmethod(t.candidate_lists.update_many)})

    async def _none():
        return None

    assert await candidate_list.issue(StaleRead, reason="loser", actor="system", branding={}, now=Clock.now,
                                      sections=secs) is None
    assert len(await _lists(env)) == 1 and (await _lists(env))[0]["superseded_at"] is None


def test_signature_ignores_everything_but_names_positions_and_order():
    a = candidate_list.build_sections([{"name": "A", "position": "P", "order": 1, "_id": 1, "phone": "1"}])
    b = candidate_list.build_sections([{"name": "A", "position": "P", "order": 9, "_id": 2, "image_url": "x"}])
    c = candidate_list.build_sections([{"name": "B", "position": "P", "order": 1, "_id": 1}])
    assert candidate_list.signature(a) == candidate_list.signature(b) != candidate_list.signature(c)
