"""Phase Two of the Vetting Panel change (guide section 9, P2).

Covers: votes gated to the panel, the panel denominator, the shared outcome path, the role-based
application shape and audit redaction, the Chair's tie-break with its fallback, the final reason,
and the minimum panel size at scheduling. Reuses the `env` fixture and helpers from test_flows.
"""
from datetime import timedelta

import pytest

import main
from bson import ObjectId
from tests.test_flows import env, START, _mk_position, _apply, _financial_controller  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _ready_application(e, sid="v1", name="Ayebale Elizabeth"):
    """A pending, finance-cleared application (votes can be cast)."""
    pid = await _mk_position(e)
    app_doc = await _apply(e, pid, sid, name)
    await e.db.applications.update_one({"_id": app_doc["_id"]}, {"$set": {"finance_cleared": True}})
    return str(app_doc["_id"])


async def _vote(e, aid, token, vote, who=""):
    return await e.client.post(f"/admin/applications/{aid}/vote", headers=token,
                               json={"commissioner_id": who, "vote": vote})


async def _set_policy(e, policy):
    await e.db.settings.update_one({"name": "security_settings", "org_id": e.org_id},
                                   {"$set": {"approval_policy": policy}}, upsert=True)
    main.invalidate_settings(e.org_id)


# ---- Votes are gated to the panel -----------------------------------------------------------
async def test_only_a_panel_token_can_vote(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    assert (await _vote(env, aid, env.com1, "approve", "com1")).status_code == 403   # commissioner, not on panel
    r = await _vote(env, aid, env.pan1, "approve", "com1")
    assert r.status_code == 200, r.text
    assert r.json()["my_vote"] == "approve" and r.json()["progress"] == {"cast": 1, "panel_count": 2}


async def test_claimed_identity_must_match_the_panel_account(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    assert (await _vote(env, aid, env.pan1, "approve", "com2")).status_code == 403


# ---- The denominator is the panel, not the commissioners (guide 7, item 1) -------------------
async def test_majority_uses_panel_size_not_commissioner_count(env):
    for i in range(3, 6):
        await env.voter(f"com{i}", f"Comm {i}", (f"2567000000{i:02d}",), is_commissioner=True)  # 5 commissioners
    await env.seed_panel(extra=1)                                                              # panel of 3
    aid = await _ready_application(env)
    assert (await _vote(env, aid, env.pan1, "approve", "com1")).status_code == 200
    assert (await _vote(env, aid, env.tok("PM-EXT0", "vetting"), "approve")).status_code == 200
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "approved"                       # 2 of 3 resolves; 3 of 5 would have been needed
    assert "pm-ext0" in doc["votes"]                         # externals vote under their PM- id


# ---- Progress only while pending; the shape is decided per role (guide 7.1) ------------------
async def test_pending_shows_progress_to_the_panel_only_and_overseer_sees_the_stage(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    await _vote(env, aid, env.pan1, "approve", "com1")

    panel_view = (await env.client.get("/admin/applications", headers=env.pan2)).json()[0]
    assert panel_view["progress"] == {"cast": 1, "panel_count": 2} and panel_view["my_vote"] is None
    assert "final_split" not in panel_view and "approve_count" not in panel_view

    over = (await env.client.get("/overseer/dashboard", headers=env.over)).json()
    row = [a for a in over["applications"] if a["id"] == aid][0]
    assert row["stage"] == "with_panel" and "votes_cast" not in row and "final_split" not in row   # tier 1
    assert "awaiting_final_decision" not in row
    assert "approve_count" not in row and "deny_count" not in row and "removal_approve_count" not in row

    it_view = (await env.client.get("/admin/applications", headers=env.it)).json()[0]
    assert "votes" not in it_view and "progress" not in it_view and "final_split" not in it_view


# ---- Audit log redaction (guide 8.1, 13.1 C and I) ---------------------------------------------
async def test_audit_log_hides_who_voted_how_from_everyone_but_superadmin(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    await _vote(env, aid, env.pan1, "deny", "com1")
    await _vote(env, aid, env.pan2, "deny", "com2")          # 2 of 2 -> denied

    def cast_entry(entries):
        return [e for e in entries if e["action"] == "application_vote_cast"][0]

    hidden = (await env.client.get("/admin/audit-log", headers=env.com1)).json()["entries"]
    e = cast_entry(hidden)
    assert e["actor"] == "redacted" and "vote" not in e["details"] and "reason" not in e["details"]
    denied = [x for x in hidden if x["action"] == "application_denied"][0]
    assert "deny_count" not in denied["details"] and "approve_count" not in denied["details"]

    body = (await env.client.get("/superadmin/audit-log", headers=env.sa)).json()
    shown = body["entries"] if isinstance(body, dict) else body
    assert cast_entry(shown)["details"]["vote"] == "deny"


# ---- Tie definition, Chair tie-break and fallback (guide 7.2) ---------------------------------
async def test_chair_on_panel_breaks_a_tie_and_the_split_is_kept(env):
    await env.seed_panel(extra=2)                                   # com1, com2, two externals
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    await _set_policy(env, "majority_total")
    aid = await _ready_application(env)
    ext = [env.tok("PM-EXT0", "vetting"), env.tok("PM-EXT1", "vetting")]
    await _vote(env, aid, env.pan1, "approve", "com1")
    await _vote(env, aid, env.pan2, "deny", "com2")
    await _vote(env, aid, ext[0], "approve")
    await _vote(env, aid, ext[1], "deny")                           # 2-2 of 4: a tie
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "pending" and doc.get("tied_pending_chief") is True

    assert (await env.client.post(f"/admin/applications/{aid}/tie-break", headers=env.pan2,
                                  json={"decision": "approve"})).status_code == 403          # ordinary panelist
    assert (await env.client.post(f"/admin/applications/{aid}/tie-break", headers=env.com1,
                                  json={"decision": "approve"})).status_code == 403          # Chair, commissioner hat
    r = await env.client.post(f"/admin/applications/{aid}/tie-break", headers=env.pan1,
                              json={"decision": "approve", "reason": "ignored on approve"})
    assert r.status_code == 200, r.text
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "approved" and doc["decided_by_tie_break"] is True
    assert "tied_pending_chief" not in doc and "final_reason" not in doc
    assert len(doc["votes"]) == 4 and doc["votes"]["com1"] == "approve"              # votes untouched
    assert (await env.client.post(f"/admin/applications/{aid}/tie-break", headers=env.pan1,
                                  json={"decision": "deny"})).status_code == 409        # no second call


async def test_without_the_chair_on_the_panel_the_superadmin_resolves(env):
    await env.seed_panel(sids=("com2",), extra=3)                   # Chair (com1) is not a panelist
    await env.db.voters.update_one({"student_id": "com1"}, {"$set": {"is_chief_commissioner": True}})
    await _set_policy(env, "majority_total")
    aid = await _ready_application(env)
    tokens = [env.pan2] + [env.tok(f"PM-EXT{i}", "vetting") for i in range(3)]
    for t, v in zip(tokens, ["approve", "deny", "approve", "deny"]):
        await _vote(env, aid, t, v)
    assert (await env.db.applications.find_one({"_id": ObjectId(aid)}))["tied_pending_chief"] is True
    assert (await env.client.post(f"/admin/applications/{aid}/tie-break", headers=tokens[0],
                                  json={"decision": "deny"})).status_code == 403
    assert (await env.client.post(f"/superadmin/applications/{aid}/force-deny", headers=env.sa)).status_code == 200
    assert "tied_pending_chief" not in await env.db.applications.find_one({"_id": ObjectId(aid)})


# ---- Final reason (guide 13.2, H2) -------------------------------------------------------------
async def test_final_reason_is_superadmin_set_and_shown_to_commissioners(env):
    aid = await _ready_application(env)
    assert (await env.client.post(f"/superadmin/applications/{aid}/force-deny", headers=env.sa)).status_code == 200
    assert (await env.client.post(f"/superadmin/applications/{aid}/final-reason", headers=env.com1,
                                  json={"reason": "Receipt does not match"})).status_code == 403
    assert (await env.client.post(f"/superadmin/applications/{aid}/final-reason", headers=env.sa,
                                  json={"reason": "x" * 501})).status_code == 422
    r = await env.client.post(f"/superadmin/applications/{aid}/final-reason", headers=env.sa,
                              json={"reason": "  Receipt does not match  "})
    assert r.status_code == 200 and r.json()["final_reason"] == "Receipt does not match"
    seen = (await env.client.get("/admin/applications", headers=env.com2)).json()
    assert seen[0]["final_reason"] == "Receipt does not match" and "final_split" not in seen[0]


# ---- Minimum panel size at scheduling (guide 7, item 6) ----------------------------------------
async def test_vetting_cannot_be_scheduled_with_fewer_than_three_panelists(env):
    await env.seed_panel()                                          # two panelists only
    body = {"phases": {"vetting": {"start": (START + timedelta(days=1)).isoformat(),
                                   "end": (START + timedelta(days=3)).isoformat(), "enforced": True}}}
    r = await env.client.post("/admin/schedule/phases", headers=env.sa, json=body)
    assert r.status_code == 409 and "3 active panelists" in r.json()["detail"]


# ---- Visibility tiers: only the Vetting Panel sees vote counts; everyone else sees the stage ----
async def test_it_admin_application_list_is_stage_only(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    await _vote(env, aid, env.pan1, "approve", "com1")

    rows = (await env.client.get("/it-admin/applications", headers=env.it)).json()
    row = [r for r in rows if r["_id"] == aid][0]
    assert row["stage"] == "with_panel" and row["stage_label"] == "With the Vetting Panel"
    allowed = {"_id", "student_id", "full_name", "position_id", "position_title", "position_order",
               "submitted_at", "status", "stage", "stage_label"}
    assert set(row) <= allowed            # whitelist: no votes, progress, reasons or payment fields


async def test_finance_stage_shows_only_where_a_fee_applies(env):
    await env.seed_panel()
    pid = await _mk_position(env)
    await env.voter("v9", "Fee Payer", ("256700000099",))
    app_doc = await _apply(env, pid, "v9", "Fee Payer")
    await env.db.applications.update_one({"_id": app_doc["_id"]}, {"$set": {"fee_required": 50000, "finance_cleared": False}})
    rows = (await env.client.get("/it-admin/applications", headers=env.it)).json()
    assert [r for r in rows if r["_id"] == str(app_doc["_id"])][0]["stage"] == "finance_pending"
    await env.db.applications.update_one({"_id": app_doc["_id"]}, {"$set": {"finance_rejected": True}})
    rows = (await env.client.get("/it-admin/applications", headers=env.it)).json()
    assert [r for r in rows if r["_id"] == str(app_doc["_id"])][0]["stage"] == "finance_rejected"


async def test_only_it_admin_and_superadmin_may_open_the_it_admin_list(env):
    await env.seed_panel()
    assert (await env.client.get("/it-admin/applications", headers=env.over)).status_code == 403
    assert (await env.client.get("/it-admin/applications", headers=env.pan1)).status_code in (401, 403)
