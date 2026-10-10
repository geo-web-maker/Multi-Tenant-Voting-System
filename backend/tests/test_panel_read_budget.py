"""Guide 06 / OPT-01: one panel_members read for the tally and the response, not four. Who may vote is still
decided by a separate fresh lookup (_acting_panelist, audit S-08), so a vote costs 1 shared read plus that lookup."""
import pytest
from bson import ObjectId

import main
from tests.opcount import CountingDB, FakeClient
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_vetting_panel_p2 import _ready_application, _vote, _set_policy  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def counted(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    monkeypatch.setattr(main, "client", FakeClient())
    monkeypatch.setattr(main, "_SETTINGS_TTL", 5.0)
    main.invalidate_settings()
    yield cdb
    main.invalidate_settings()


def _panel_finds(d):
    return sum(n for (c, m), n in d.items() if c == "panel_members" and m == "find")


def _panel_find_ones(d):
    return sum(n for (c, m), n in d.items() if c == "panel_members" and m == "find_one")


async def test_a_panel_vote_reads_the_panel_list_once(env, counted):
    await env.seed_panel()
    aid = await _ready_application(env)
    s = counted.snapshot()
    r = await _vote(env, aid, env.pan1, "approve", "com1")
    assert r.status_code == 200, r.text
    d = counted.since(s)
    assert _panel_finds(d) == 1, d                       # was 4 (resolve x2, response x2)
    assert _panel_find_ones(d) <= 2, d                   # the fresh _acting_panelist lookups stay as they were


async def test_vote_result_is_unchanged(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    r = await _vote(env, aid, env.pan1, "approve", "com1")
    assert r.json()["progress"] == {"cast": 1, "panel_count": 2}


async def test_resolution_still_uses_the_panel_size(env):
    await env.seed_panel(extra=1)                         # panel of 3, majority of total = 2
    aid = await _ready_application(env)
    assert (await _vote(env, aid, env.pan1, "approve", "com1")).status_code == 200
    assert (await _vote(env, aid, env.tok("PM-EXT0", "vetting"), "approve")).status_code == 200
    assert (await env.db.applications.find_one({"_id": ObjectId(aid)}))["status"] == "approved"


async def test_a_removed_panelist_still_cannot_vote(env):
    """The shared list never decides who may vote."""
    await env.seed_panel()
    aid = await _ready_application(env)
    await env.db.panel_members.update_many({}, {"$set": {"active": False}})
    r = await _vote(env, aid, env.pan1, "approve", "com1")
    assert r.status_code in (401, 403)                   # refused by the auth guard or _acting_panelist, never counted


async def test_resolve_without_live_behaves_as_before(env):
    await env.seed_panel()
    aid = await _ready_application(env)
    app_doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    await main._resolve_application(aid, app_doc, env.org_id)                      # no live= passed
    await main._resolve_application(aid, app_doc, env.org_id, live=await main._live_panelists(env.org_id))
