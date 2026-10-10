"""Vetting close-out: when the vetting window ends, a clear majority of the votes that were
actually cast decides the application. A tie, or no votes, is not guessed — the Chairperson
(or the superadmin, if the Chairperson cannot) decides, and that decision is logged.
"""
from datetime import timedelta

import pytest
from bson import ObjectId

import main
from tests.test_flows import START, _apply, _financial_controller, _mk_position, env  # noqa: F401
from tests.test_vetting_panel_p2 import _ready_application, _set_policy, _vote

pytestmark = pytest.mark.asyncio


async def _end_vetting(e, ended=True, enforced=True, end_date=True):
    end = (START - timedelta(hours=1) if ended else START + timedelta(days=2)) if end_date else None
    await e.db.settings.update_one(
        {"name": "election_phases", "org_id": e.org_id},
        {"$set": {"name": "election_phases", "org_id": e.org_id, "round_id": "round-1",
                  "phases": {"vetting": {"start": START - timedelta(days=2), "end": end, "enforced": enforced}}}},
        upsert=True)
    main.invalidate_settings(e.org_id)


async def _panel_of_five(e):
    """com1, com2 and three externals. com1 is the Chairperson."""
    await e.seed_panel(extra=3)
    await e.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    await _set_policy(e, "majority_cast")
    return [e.pan1, e.pan2] + [e.tok(f"PM-EXT{i}", "vetting") for i in range(3)]


def _approved(entries):
    return [x for x in entries if x["action"] == "application_approved"]


async def _audit(e, headers, path="/admin/audit-log"):
    body = (await e.client.get(path, headers=headers)).json()
    return body["entries"] if isinstance(body, dict) else body


async def test_clear_majority_of_cast_votes_is_decided_and_logged(env):
    tokens = await _panel_of_five(env)
    aid = await _ready_application(env)
    for token, choice, who in (
        (tokens[0], "approve", "com1"), (tokens[1], "approve", "com2"),
        (tokens[2], "approve", ""), (tokens[3], "deny", ""),
    ):
        assert (await _vote(env, aid, token, choice, who)).status_code == 200
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "pending"                       # majority_cast still waits for the fifth vote

    await _end_vetting(env)
    rows = (await env.client.get("/admin/applications", headers=env.pan1)).json()
    row = rows[0]
    assert row["status"] == "approved" and row["decided_by_closeout"] is True
    assert row["final_split"] == {"approve": 3, "deny": 1}
    assert "closeout_decider" not in row                     # nobody had to break it

    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["closeout_counts"] == {"approve": 3, "deny": 1}
    assert doc["votes"]["com1"] == "approve" and "pm-ext2" not in doc["votes"]

    shown = await _audit(env, env.sa, "/superadmin/audit-log")
    approved = _approved(shown)[0]
    assert approved["details"]["closeout"] is True
    assert approved["details"]["approve_count"] == 3 and approved["details"]["deny_count"] == 1

    hidden = await _audit(env, env.com2)
    approved = _approved(hidden)[0]
    assert "approve_count" not in approved["details"] and "closeout" not in approved["details"]
    over = [x for x in await _audit(env, env.over) if x["action"] == "application_approved"][0]
    assert over["details"].get("closeout") is True and "approve_count" not in over["details"]

    again = (await env.client.get("/admin/applications", headers=env.pan1)).json()
    assert again[0]["status"] == "approved"
    assert len(_approved(await _audit(env, env.sa, "/superadmin/audit-log"))) == 1


async def test_a_tie_or_no_votes_waits_for_the_chair_and_is_logged(env):
    tokens = await _panel_of_five(env)
    tied = await _ready_application(env, "v1", "Ayebale Elizabeth")
    await env.voter("v2", "Kato John", ("256700111333",))
    empty = await _ready_application(env, "v2", "Kato John")
    assert (await _vote(env, tied, tokens[0], "approve", "com1")).status_code == 200
    assert (await _vote(env, tied, tokens[1], "deny", "com2")).status_code == 200

    await _end_vetting(env)
    rows = {r["_id"]: r for r in (await env.client.get("/admin/applications", headers=tokens[0])).json()
            if r["status"] == "pending"}
    assert rows[tied]["vetting_closed_undecided"] is True
    assert rows[tied]["closeout_counts"] == {"approve": 1, "deny": 1}
    assert rows[tied]["closeout_decider"] == "chair" and rows[tied]["closeout_decision_available"] is True
    assert rows[empty]["closeout_counts"] == {"approve": 0, "deny": 0}
    assert rows[empty]["closeout_decision_available"] is True

    ordinary = {r["_id"]: r for r in (await env.client.get("/admin/applications", headers=tokens[1])).json()}
    assert ordinary[tied]["closeout_decision_available"] is False
    assert ordinary[tied]["closeout_decider"] == "chair"

    it = [r for r in (await env.client.get("/it-admin/applications", headers=env.it)).json() if r["_id"] == tied][0]
    assert it["stage"] == "needs_decision" and it["stage_label"] == "Vetting closed without a decision"
    assert "closeout_counts" not in it and "votes" not in it

    assert (await _vote(env, tied, tokens[2], "approve")).status_code == 409
    assert (await env.client.post(f"/admin/applications/{tied}/tie-break", headers=tokens[0],
                                  json={"decision": "approve"})).status_code == 409
    assert (await env.client.post(f"/admin/applications/{tied}/closeout-decision", headers=tokens[1],
                                  json={"decision": "approve"})).status_code == 403
    assert (await env.client.post(f"/admin/applications/{tied}/closeout-decision", headers=env.com1,
                                  json={"decision": "approve"})).status_code == 403
    # The superadmin may decide even though a Chairperson is on the panel.
    sa_row = [r for r in (await env.client.get("/admin/applications", headers=env.sa)).json() if r["_id"] == tied][0]
    assert sa_row["vetting_closed_undecided"] is True
    r = await env.client.post(f"/superadmin/applications/{tied}/closeout-decision", headers=env.sa,
                              json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert (await env.db.applications.find_one({"_id": ObjectId(tied)}))["closeout_decider"] == "superadmin"

    r = await env.client.post(f"/admin/applications/{empty}/closeout-decision", headers=tokens[0],
                              json={"decision": "deny", "reason": "  Nobody voted  "})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(empty)})
    assert doc["status"] == "denied" and doc["decided_by_closeout"] is True
    assert doc["closeout_decider"] == "chair" and doc["final_reason"] == "Nobody voted"
    assert "vetting_closed_undecided" not in doc and doc["votes"] == {}
    assert (await env.client.post(f"/admin/applications/{empty}/closeout-decision", headers=tokens[0],
                                  json={"decision": "approve"})).status_code == 409

    r = await env.client.post(f"/admin/applications/{tied}/closeout-decision", headers=tokens[0],
                              json={"decision": "approve"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(tied)})
    assert doc["status"] == "approved" and doc["votes"]["com1"] == "approve"   # votes untouched
    assert "tied_pending_chief" not in doc

    hidden = await _audit(env, env.com2)
    undecided = [x for x in hidden if x["action"] == "application_closeout_undecided"]
    assert {x["details"].get("app_id") for x in undecided} == {tied, empty}
    assert all(x["actor"] == "system" and "approve_count" not in x["details"] for x in undecided)
    assert not [x for x in hidden if x["action"] == "application_closeout_decided"]
    full = await _audit(env, env.sa, "/superadmin/audit-log")
    empty_log = [x for x in full if x["action"] == "application_closeout_undecided" and x["details"].get("app_id") == empty][0]
    assert empty_log["details"]["approve_count"] == 0 and empty_log["details"]["deny_count"] == 0


async def test_superadmin_decides_when_the_chair_cannot(env):
    await env.seed_panel(sids=("com2",), extra=1)               # Chair (com1) is not a panelist
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    await _set_policy(env, "majority_cast")
    aid = await _ready_application(env)
    await _end_vetting(env)
    row = (await env.client.get("/admin/applications", headers=env.pan2)).json()[0]
    assert row["vetting_closed_undecided"] is True and row["closeout_decider"] == "superadmin"
    assert row["closeout_decision_available"] is False
    assert (await env.client.post(f"/admin/applications/{aid}/closeout-decision", headers=env.pan2,
                                  json={"decision": "deny"})).status_code == 403
    sa = (await env.client.get("/admin/applications", headers=env.sa)).json()[0]
    assert sa["closeout_awaiting"] == "superadmin" and sa["closeout_counts"] == {"approve": 0, "deny": 0}
    r = await env.client.post(f"/superadmin/applications/{aid}/closeout-decision", headers=env.sa,
                              json={"decision": "approve"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "approved" and doc["closeout_decider"] == "superadmin"


async def test_chair_cannot_decide_their_own_application(env):
    await _panel_of_five(env)
    # A serving panelist cannot apply, so lift that for the setup only.
    await env.db.panel_members.update_one({"student_id": "com1"}, {"$set": {"active": False}})
    aid = await _ready_application(env, "com1", "Comm One")
    await env.db.panel_members.update_one({"student_id": "com1"}, {"$set": {"active": True}})
    await _end_vetting(env)
    row = (await env.client.get("/admin/applications", headers=env.pan1)).json()[0]
    assert row["closeout_decider"] == "superadmin" and row["closeout_decision_available"] is False
    assert (await env.client.post(f"/admin/applications/{aid}/closeout-decision", headers=env.pan1,
                                  json={"decision": "approve"})).status_code == 403
    assert (await env.client.post(f"/superadmin/applications/{aid}/closeout-decision", headers=env.sa,
                                  json={"decision": "deny", "reason": "own application"})).status_code == 200
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "denied" and doc["closeout_decider"] == "superadmin"


async def test_votes_of_panelists_whose_access_ended_still_count(env):
    tokens = await _panel_of_five(env)
    await env.db.panel_members.update_one({"panel_member_id": "PM-EXT0"}, {"$set": {"expires_with_phase": "vetting"}})
    aid = await _ready_application(env)
    assert (await _vote(env, aid, tokens[0], "approve", "com1")).status_code == 200
    assert (await _vote(env, aid, tokens[2], "deny")).status_code == 200
    await _end_vetting(env)                                     # the external's access ends with the phase
    row = (await env.client.get("/admin/applications", headers=env.pan1)).json()[0]
    # Dropping the ended vote would leave a lone approve and decide it. The close-out keeps it: 1-1.
    assert row["status"] == "pending" and row["closeout_counts"] == {"approve": 1, "deny": 1}
    assert row["vetting_closed_undecided"] is True


async def test_an_open_window_and_an_uncleared_payment_are_left_alone(env):
    tokens = await _panel_of_five(env)
    aid = await _ready_application(env)
    assert (await _vote(env, aid, tokens[0], "approve", "com1")).status_code == 200
    assert (await _vote(env, aid, tokens[1], "approve", "com2")).status_code == 200
    assert (await _vote(env, aid, tokens[2], "approve")).status_code == 200
    await _end_vetting(env, ended=False)
    row = (await env.client.get("/admin/applications", headers=env.pan1)).json()[0]
    assert row["status"] == "pending" and "vetting_closed_undecided" not in row

    await _end_vetting(env)
    pid = await _mk_position(env, title="Secretary")
    await env.voter("v3", "Uncleared", ("256700111444",))
    uncleared = await _apply(env, pid, "v3", "Uncleared")
    # _apply drops the phase schedule; put the ended window back.
    await _end_vetting(env)
    rows = {r["_id"]: r for r in (await env.client.get("/admin/applications", headers=env.sa)).json()}
    assert rows[aid]["status"] == "approved" and rows[aid]["decided_by_closeout"] is True
    assert rows[str(uncleared["_id"])]["status"] == "pending"
    assert rows[str(uncleared["_id"])].get("vetting_closed_undecided") is not True


async def test_chair_is_told_on_their_own_dashboard(env):
    await _panel_of_five(env)
    await _ready_application(env)
    await _end_vetting(env)
    link = (await env.client.get("/admin/panel-link", headers=env.com1)).json()
    assert link["panel_linked"] is True and link["closeout_waiting"] == 1 and link["tie_waiting"] == 0
    other = (await env.client.get("/admin/panel-link", headers=env.com2)).json()
    assert other["closeout_waiting"] == 0


async def test_a_payment_cleared_after_the_window_is_closed_out_at_once(env):
    """No votes were cast, so this is not guessed. It must not sit pending until the next screen load."""
    await _panel_of_five(env)
    pid = await _mk_position(env, title="Treasurer")
    await env.voter("v9", "Late Payer", ("256700111999",))
    app = await _apply(env, pid, "v9", "Late Payer")
    await _end_vetting(env)
    await env.client.get("/admin/applications", headers=env.sa)
    doc = await env.db.applications.find_one({"_id": app["_id"]})
    assert doc["status"] == "pending" and "vetting_closed_undecided" not in doc

    fc = await _financial_controller(env)
    r = await env.client.post(f"/admin/applications/{app['_id']}/finance-clear", headers=fc,
                              json={"financial_controller_id": "fc1", "reason": "Paid after vetting"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": app["_id"]})
    assert doc["status"] == "pending" and doc["vetting_closed_undecided"] is True
    assert doc["closeout_counts"] == {"approve": 0, "deny": 0}
    assert doc["closeout_handled"] is True


async def test_reversing_a_clearance_clears_the_closeout_so_it_can_be_cleared_again(env):
    tokens = await _panel_of_five(env)
    aid = await _ready_application(env)
    assert (await _vote(env, aid, tokens[0], "approve", "com1")).status_code == 200
    assert (await _vote(env, aid, tokens[1], "deny", "com2")).status_code == 200
    await _end_vetting(env)
    await env.client.get("/admin/applications", headers=env.pan1)
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["vetting_closed_undecided"] is True and doc["closeout_handled"] is True

    fc = await _financial_controller(env)
    r = await env.client.post(f"/admin/applications/{aid}/finance-reverse", headers=fc,
                              json={"financial_controller_id": "fc1", "reason": "Receipt does not match"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["finance_cleared"] is False and doc["votes"] == {}
    assert "vetting_closed_undecided" not in doc and "closeout_handled" not in doc
    assert "closeout_counts" not in doc

    r = await env.client.post(f"/admin/applications/{aid}/finance-clear", headers=fc,
                              json={"financial_controller_id": "fc1", "reason": "Correct receipt"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    # The old 1-1 was set aside with the reversal. No votes remain, so it waits again rather than
    # replaying the decision that was made on a payment Finance has withdrawn.
    assert doc["status"] == "pending" and doc["vetting_closed_undecided"] is True
    assert doc["closeout_counts"] == {"approve": 0, "deny": 0}


async def test_reinstating_straight_to_cleared_after_the_window_is_closed_out(env):
    await _panel_of_five(env)
    pid = await _mk_position(env, title="Secretary")
    await env.voter("v8", "Returned Payer", ("256700111888",))
    app = await _apply(env, pid, "v8", "Returned Payer")
    fc = await _financial_controller(env)
    r = await env.client.post(f"/admin/applications/{app['_id']}/finance-reject", headers=fc,
                              json={"financial_controller_id": "fc1", "reason": "Short payment"})
    assert r.status_code == 200, r.text
    await _end_vetting(env)
    r = await env.client.post(f"/admin/applications/{app['_id']}/finance-reinstate", headers=fc,
                              json={"financial_controller_id": "fc1", "target": "cleared",
                                    "reason": "Balance received"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": app["_id"]})
    assert doc["finance_cleared"] is True and doc["vetting_closed_undecided"] is True
    assert doc["closeout_counts"] == {"approve": 0, "deny": 0}
    assert doc["status"] == "pending"


async def test_the_sweep_closes_out_with_no_screen_opened(env):
    """Nothing hits a panel route here: only the background sweep runs."""
    tokens = await _panel_of_five(env)
    aid = await _ready_application(env)
    for t, who in zip(tokens[:3], ("com1", "com2", "")):
        assert (await _vote(env, aid, t, "approve", who)).status_code == 200
    await _end_vetting(env)
    assert (await env.db.applications.find_one({"_id": ObjectId(aid)}))["status"] == "pending"

    assert await main._sweep_vetting_closeouts() >= 1
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "approved" and doc["decided_by_closeout"] is True
    # A second sweep changes nothing.
    await main._sweep_vetting_closeouts()
    assert len(_approved(await _audit(env, env.sa))) == 1


async def test_the_sweep_hands_a_tie_to_the_chair_without_a_screen(env):
    await _panel_of_five(env)
    aid = await _ready_application(env)
    await _end_vetting(env)
    await main._sweep_vetting_closeouts()
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "pending" and doc["vetting_closed_undecided"] is True


async def test_the_sweep_keeps_going_when_one_organisation_fails(env, monkeypatch):
    await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    calls = []

    async def flaky(org_id):
        calls.append(org_id)
        if len(calls) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "_maybe_close_vetting", flaky)
    assert await main._sweep_vetting_closeouts() == 2
    assert len(calls) == 2


async def test_an_unenforced_window_with_an_end_date_in_the_past_is_closed_out(env):
    tokens = await _panel_of_five(env)
    aid = await _ready_application(env)
    for t, who in zip(tokens[:3], ("com1", "com2", "")):
        assert (await _vote(env, aid, t, "approve", who)).status_code == 200
    await _end_vetting(env, enforced=False)
    await main._sweep_vetting_closeouts()
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "approved" and doc["decided_by_closeout"] is True


async def test_a_vetting_phase_with_no_end_date_is_never_closed_out(env):
    await _panel_of_five(env)
    aid = await _ready_application(env)
    await _end_vetting(env, enforced=False, end_date=False)
    await main._sweep_vetting_closeouts()
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "pending" and "vetting_closed_undecided" not in doc
