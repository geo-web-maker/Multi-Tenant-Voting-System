"""PERF-M3: per-request attribution through the tenant wrapper agrees with the application-level call counter
(tests/opcount.py, the oracle used by the budget tests). Tenant collections are attributed; global collections
are the 'unattributed' remainder, so attributed + global == counted."""
import pytest

import main
import perf_metrics as pm
from tests.opcount import CountingDB, FakeClient
from tests.test_flows import env, ident, code_from  # noqa: F401

pytestmark = pytest.mark.asyncio

from tenant_db import TENANT_COLLECTIONS   # authoritative: everything else is reached through the raw `db` handle


@pytest.fixture
def counted(env, monkeypatch):
    cdb = CountingDB(main.db)
    monkeypatch.setattr(main, "db", cdb)
    monkeypatch.setattr(main, "client", FakeClient())
    return cdb


def _route_row(name):
    rows = {r["name"]: r for r in pm.breakdown("route")["rows"]}
    return rows.get(name)


async def test_voter_routes_attributed_ops_match_the_counter(env, counted):
    pm.reset_for_tests()
    cand = str((await env.db.candidates.insert_one(
        {"org_id": env.org_id, "name": "A", "position": "President", "order": 1})).inserted_id)
    out = {}

    s = counted.snapshot()
    assert (await ident(env)).status_code == 200
    out["/verify-identity"] = counted.since(s)

    s = counted.snapshot()
    r = await env.client.post("/verify-otp", json={"student_id": "v1", "code": code_from(env)})
    assert r.status_code == 200, r.text
    out["/verify-otp"] = counted.since(s)
    tok = r.json()["voter_token"]

    s = counted.snapshot()
    r = await env.client.post("/vote-bulk", headers={"X-Voter-Token": tok},
                              json={"student_id": "v1", "candidate_ids": [cand]})
    assert r.status_code == 200, r.text
    out["/vote-bulk"] = counted.since(s)

    for route, d in out.items():
        row = _route_row(route)
        assert row is not None, (route, [r["name"] for r in pm.breakdown("route")["rows"]])
        tenant_calls = sum(n for (c, _m), n in d.items() if c in TENANT_COLLECTIONS)
        total_calls = sum(d.values())
        per_req = row["ops_per_request"]
        assert 0 < per_req <= total_calls, (route, per_req, d)
        assert per_req == tenant_calls, (route, per_req, tenant_calls, dict(d))
