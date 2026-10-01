"""CUSTOM-1: superadmin voter statistics (total, phone coverage, per-section counts, SMS amount)."""
import pytest

from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def seed(e):
    await e.db.settings.insert_one({"name": "voter_fields", "org_id": e.org_id, "fields": [
        {"key": "hostel", "label": "Hostel", "enabled": True},
        {"key": "secretnote", "label": "Secret Note", "enabled": False}]})
    await e.voter("23/u/001", "Alpha One", ("256700111222",), has_voted=True, attrs={"hostel": "Block A", "secretnote": "X"})
    await e.voter("23/u/002", "Beta Two", (), attrs={"hostel": "Block A"})
    await e.voter("23/u/003", "Gamma Three", ("256700333444",), attrs={"hostel": "Block B"})


async def test_stats_counts_sections_and_sms(env):
    await seed(env)
    r = await env.client.get("/admin/voters/stats", headers=env.sa)
    assert r.status_code == 200
    d = r.json()
    base = d["total"] - 3          # the fixture may already hold admin voters; ours are the last three
    assert d["voted"] >= 1 and d["not_voted"] == d["total"] - d["voted"]
    assert d["with_phone"] + d["without_phone"] == d["total"]
    assert [s["key"] for s in d["sections"]] == ["hostel"]          # disabled field never listed
    groups = {g["label"]: g for g in d["sections"][0]["groups"]}
    assert groups["Block A"]["registered"] == 2 and groups["Block A"]["voted"] == 1 and groups["Block A"]["pct"] == 50.0
    assert groups["Block B"]["registered"] == 1
    assert "sent_total" in d["sms"] and "budget_left" in d["sms"]
    assert base >= 0
    assert "X" not in r.text and "256700111222" not in r.text      # no attr values of disabled fields, no phones


async def test_stats_is_superadmin_only(env):
    assert (await env.client.get("/admin/voters/stats", headers=env.it)).status_code == 403
    assert (await env.client.get("/admin/voters/stats")).status_code in (401, 403)
