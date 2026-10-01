"""Endpoint tests: per-org optional voter fields, import (preview/apply/legacy), admin + public turnout
breakdown. Reuses the `env` fixture (mongomock, org 't1', tokens e.it / e.sa) from test_flows."""
import pytest

import main  # noqa: F401
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

HDR = "student_id,full_name,phone,GENDER,Programme,hostel\n"


def sid(n):
    return f"24/u/baf/{n:05d}/pd"


def csv_bytes(rows, header=HDR):
    return (header + "\n".join(rows) + "\n").encode()


async def put_fields(e, **body):
    return await e.client.put("/superadmin/voter-fields", headers=e.sa, json={"reason": "test setup", **body})


async def enable_all(e):
    r = await put_fields(e, fields=[{"key": "gender", "enabled": True}, {"key": "programme", "enabled": True},
                                    {"key": "hostel", "label": "Hostel", "enabled": True}])
    assert r.status_code == 200, r.text
    return r.json()


async def preview(e, content, who=None):
    return await e.client.post("/admin/import-voters/preview", headers=who or e.it,
                               files={"file": ("v.csv", content)})


async def apply(e, pid, **kw):
    return await e.client.post("/admin/import-voters/apply", headers=e.it, json={"preview_id": pid, **kw})


# ── config ──────────────────────────────────────────────────────────────────

async def test_defaults_off_and_superadmin_only(env):
    r = await env.client.get("/superadmin/voter-fields", headers=env.sa)
    body = r.json()
    assert [f["key"] for f in body["fields"]] == ["gender", "programme"]
    assert not any(f["enabled"] or f["public"] for f in body["fields"]) and body["min_group_size"] == 10
    assert (await env.client.get("/superadmin/voter-fields", headers=env.it)).status_code == 403
    assert (await env.client.put("/superadmin/voter-fields", headers=env.it,
                                 json={"reason": "x y z", "fields": []})).status_code == 403


async def test_config_edit_rules(env):
    assert (await env.client.put("/superadmin/voter-fields", headers=env.sa,
                                 json={"reason": "", "fields": [{"key": "gender", "enabled": True}]})).status_code == 400
    assert (await put_fields(env, fields=[{"key": "phone"}])).status_code == 400          # reserved
    assert (await put_fields(env, remove=["gender"])).status_code == 400                  # standard
    assert (await put_fields(env, min_group_size=2)).status_code == 400
    assert (await put_fields(env)).status_code == 400                                     # nothing to change
    r = await put_fields(env, fields=[{"key": "hostel", "enabled": True, "public": True}], min_group_size=6)
    assert r.status_code == 200
    body = r.json()
    assert body["min_group_size"] == 6 and body["fields"][2]["key"] == "hostel" and body["fields"][2]["public"]
    events = [x async for x in env.db.roster_ledger.find({"event": "voter_fields_changed"})]
    assert len(events) == 1                                                               # audited


# ── import ──────────────────────────────────────────────────────────────────

async def test_import_reads_only_enabled_fields_and_applies_them(env):
    await put_fields(env, fields=[{"key": "gender", "enabled": True}])                    # programme/hostel off
    rows = [f"{sid(1)},anne okello,0700111001,f,BAF,A", f"{sid(2)},BEN OTIM,0700111002,Male,BBA,B"]
    r = await preview(env, csv_bytes(rows))
    assert r.status_code == 200, r.text
    p = r.json()
    assert [f["key"] for f in p["summary"]["fields_in_file"]] == ["gender"]
    assert {x["student_id"]: x["attrs"] for x in p["new"]} == {sid(1): {"gender": "F"}, sid(2): {"gender": "Male"}}
    assert (await apply(env, p["preview_id"])).json()["added"] == 2
    v = await env.db.voters.find_one({"student_id": sid(1)})
    assert v["attrs"] == {"gender": "F"}                                                  # programme never stored


async def test_disabled_since_preview_is_not_stored(env):
    await enable_all(env)
    p = (await preview(env, csv_bytes([f"{sid(1)},Anne Okello,0700111001,F,BAF,A"]))).json()
    await put_fields(env, fields=[{"key": "programme", "enabled": False}, {"key": "hostel", "enabled": False}])
    await apply(env, p["preview_id"])
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"gender": "F"}


async def test_fill_is_silent_overwrite_is_a_reviewed_change(env):
    await enable_all(env)
    await env.voter(sid(1), "Anne Okello", ("256700111001",), attrs={"gender": "F"})
    await env.voter(sid(2), "Ben Otim", ("256700111002",))                                # no attrs yet
    rows = [f"{sid(1)},Anne Okello,0700111001,M,,", f"{sid(2)},Ben Otim,0700111002,M,BBA,"]
    p = (await preview(env, csv_bytes(rows))).json()
    s = p["summary"]
    assert (s["changed"], s["attr_fills"], s["unchanged"]) == (1, 1, 1)                   # fill != change
    ch = p["changed"][0]
    assert ch["student_id"] == sid(1) and ch["attrs_changed"] == {"gender": {"old": "F", "new": "M"}}
    assert not ch["name_changed"] and not ch["phones_changed"]

    # Skipping the reviewed change keeps F, but the fill for Ben still lands.
    res = (await apply(env, p["preview_id"], changed_default="skip")).json()
    assert res["attrs_filled"] == 1 and res["updated"] == 0
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"gender": "F"}
    assert (await env.db.voters.find_one({"student_id": sid(2)}))["attrs"] == {"gender": "M", "programme": "BBA"}

    p2 = (await preview(env, csv_bytes(rows))).json()
    res = (await apply(env, p2["preview_id"])).json()                                     # now accept
    assert res["updated"] == 1
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"gender": "M"}


async def test_blank_cell_never_wipes_and_file_without_column_changes_nothing(env):
    await enable_all(env)
    await env.voter(sid(1), "Anne Okello", ("256700111001",), attrs={"gender": "F", "programme": "BAF"})
    p = (await preview(env, csv_bytes([f"{sid(1)},Anne Okello,0700111001,,,"]))).json()
    assert p["summary"]["changed"] == 0 and p["summary"]["attr_fills"] == 0
    p = (await preview(env, csv_bytes([f"{sid(1)},Anne Okello,0700111001"], "student_id,full_name,phone\n"))).json()
    assert p["summary"]["changed"] == 0 and p["summary"]["fields_in_file"] == []


async def test_id_shape_warning_in_preview_and_still_imported(env):
    rows = [f"{sid(n)},Student {'abcdefghijklmnopqrstuvwxyz'[n % 26]},07001110{n:02d}" for n in range(1, 26)]
    rows.append('"24/u/msd,02527/pd",Bad Id,0700111099')   # quoted, as a spreadsheet export writes it
    p = (await preview(env, csv_bytes(rows, "student_id,full_name,phone\n"))).json()
    assert p["summary"]["new"] == 26                                                       # warn only
    assert any("24/u/msd,02527/pd" in w and "format" in w for w in p["warnings"])
    assert len([w for w in p["warnings"] if "format" in w]) == 1


async def test_whole_file_in_wrong_format_is_flagged_against_the_register(env):
    for n in range(30):
        await env.voter(sid(n), f"Existing {n}", ("256700111000",))
    rows = [f"S{n:04d},New Person {'abcdefghij'[n]},07001110{n:02d}" for n in range(10)]
    p = (await preview(env, csv_bytes(rows, "student_id,full_name,phone\n"))).json()
    assert len(p["warnings"]) == 1 and "existing voter register" in p["warnings"][0]


async def test_legacy_import_stores_attrs(env):
    await enable_all(env)
    r = await env.client.post("/admin/import-voters", headers=env.it,
                              files={"file": ("v.csv", csv_bytes([f"{sid(1)},Anne Okello,0700111001,F,BAF,A"]))})
    assert r.status_code == 200
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"gender": "F", "programme": "BAF", "hostel": "A"}


# ── turnout breakdown ───────────────────────────────────────────────────────

async def seed_turnout(e):
    plan = [("F", 10, 6), ("M", 6, 3), ("X", 2, 1)]                     # gender, registered, voted
    n = 100
    for g, reg, voted in plan:
        for i in range(reg):
            n += 1
            await e.voter(sid(n), f"Voter {n}", ("256700111000",), has_voted=i < voted,
                          attrs={"gender": g, "programme": "BAF"})


async def test_admin_breakdown_counts_and_never_sends_raw_fields(env):
    await enable_all(env)
    await seed_turnout(env)
    r = await env.client.get("/admin/analytics/turnout-breakdown", headers=env.it)
    assert r.status_code == 200
    body = r.json()
    by = {f["key"]: {g["label"]: g for g in f["groups"]} for f in body["fields"]}
    assert set(by) == {"gender", "programme", "hostel"}
    assert by["gender"]["F"]["registered"] == 10 and by["gender"]["F"]["voted"] == 6 and by["gender"]["F"]["pct"] == 60.0
    assert by["gender"]["X"]["registered"] == 2                          # admins see small groups
    assert by["gender"]["Not recorded"]["registered"] == 4               # the 4 seeded staff/voters
    assert body["total"]["registered"] == 22
    assert "student_id" not in r.text and "full_name" not in r.text
    assert (await env.client.get("/admin/analytics/turnout-breakdown")).status_code in (401, 403)


async def test_admin_breakdown_empty_when_no_field_enabled(env):
    assert (await env.client.get("/admin/analytics/turnout-breakdown", headers=env.it)).json()["fields"] == []


async def test_public_breakdown_needs_public_flag_and_closed_election(env):
    await enable_all(env)
    await seed_turnout(env)
    # enabled but not public -> nothing, even when closed
    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_open": False})
    assert (await env.client.get("/election-results/turnout-breakdown")).json() == {"available": False, "fields": []}

    await put_fields(env, fields=[{"key": "gender", "public": True}], min_group_size=5)
    await env.db.settings.update_one({"name": "election_config", "org_id": env.org_id}, {"$set": {"is_open": True}})
    assert (await env.client.get("/election-results/turnout-breakdown")).json()["available"] is False   # still open

    await env.db.settings.update_one({"name": "election_config", "org_id": env.org_id}, {"$set": {"is_open": False}})
    r = await env.client.get("/election-results/turnout-breakdown")                     # no auth header needed
    body = r.json()
    assert body["available"] and [f["key"] for f in body["fields"]] == ["gender"]        # programme not public
    groups = {g["label"]: g for g in body["fields"][0]["groups"]}
    # X(2) + Not recorded(4) fold into Other(6) which is >= 5; F and M stay
    assert set(groups) == {"F", "M", "Other"}
    assert groups["Other"]["registered"] == 6 and groups["Other"]["voted"] == 1 + 0
    assert all(g["registered"] >= 5 for g in groups.values())
    assert sum(g["registered"] for g in groups.values()) == 22                          # totals still add up
    assert "student_id" not in r.text and "vote_count" not in r.text


async def test_public_breakdown_withheld_when_groups_too_small(env):
    await enable_all(env)
    await put_fields(env, fields=[{"key": "gender", "public": True}], min_group_size=50)
    await env.db.settings.insert_one({"name": "election_config", "org_id": env.org_id, "is_certified": True})
    body = (await env.client.get("/election-results/turnout-breakdown")).json()
    assert body["available"] and body["fields"][0]["groups"] == [] and body["fields"][0]["suppressed"] is True


async def test_public_breakdown_opens_when_voting_window_ends(env):
    from tests.test_flows import set_voting, START
    from datetime import timedelta
    await enable_all(env)
    await seed_turnout(env)
    await put_fields(env, fields=[{"key": "gender", "public": True}], min_group_size=5)
    await set_voting(env, start=START - timedelta(days=2), end=START + timedelta(hours=1))
    assert (await env.client.get("/election-results/turnout-breakdown")).json()["available"] is False
    await set_voting(env, start=START - timedelta(days=2), end=START - timedelta(hours=1))
    assert (await env.client.get("/election-results/turnout-breakdown")).json()["available"] is True


# ── data lifecycle ──────────────────────────────────────────────────────────

async def test_purge_and_remove_erase_stored_values(env):
    await enable_all(env)
    await env.voter(sid(1), "Anne Okello", ("256700111001",), attrs={"gender": "F", "programme": "BAF", "hostel": "A"})
    r = await put_fields(env, purge=["gender"])
    assert r.status_code == 200 and r.json()["fields"][0]["enabled"]                     # definition kept
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"programme": "BAF", "hostel": "A"}
    r = await put_fields(env, remove=["hostel"])
    assert [f["key"] for f in r.json()["fields"]] == ["gender", "programme"]
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"programme": "BAF"}


async def test_disabling_keeps_data_and_public_register_never_exposes_attrs(env):
    await enable_all(env)
    await env.voter(sid(1), "Anne Okello", ("256700111001",), attrs={"gender": "F"})
    await put_fields(env, fields=[{"key": "gender", "enabled": False}])
    assert (await env.db.voters.find_one({"student_id": sid(1)}))["attrs"] == {"gender": "F"}
    r = await env.client.get("/voter-register?q=anne")
    assert r.status_code == 200 and "attrs" not in r.text and "gender" not in r.text.lower()
