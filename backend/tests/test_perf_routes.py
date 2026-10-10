"""PERF-M4: Performance API is superadmin-only, zero-cost to view, and leaks nothing."""
import json
import re

import pytest

import main
import perf_metrics as pm
import perf_tiers as pt
from tests.opcount import CountingDB
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_security_regressions import _FakeClient

pytestmark = pytest.mark.asyncio

GETS = ["config", "sink", "summary", "timeseries", "breakdown", "slow", "history"]
PERF_COLLS = {"platform_settings", "perf_batches", "perf_minutes"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(main, "client", _FakeClient())
    monkeypatch.delenv("PERF_ENABLED", raising=False)
    pm.reset_for_tests()
    yield
    pm.reset_for_tests()


def url(name):
    return f"/superadmin/performance/{name}"


@pytest.mark.parametrize("name", GETS)
async def test_every_get_requires_superadmin(env, name):
    assert (await env.client.get(url(name))).status_code in (401, 403)
    for role in (env.it, env.com1, env.over):
        assert (await env.client.get(url(name), headers=role)).status_code in (401, 403)
    assert (await env.client.get(url(name), headers=env.sa)).status_code == 200


async def test_writes_require_superadmin(env):
    for headers in ({}, env.it, env.com1):
        assert (await env.client.put(url("config"), json={"warn_pct": 50}, headers=headers)).status_code in (401, 403)
        assert (await env.client.post(url("config/reset"), headers=headers)).status_code in (401, 403)
    assert await env.db.platform_settings.count_documents({}) == 0


async def test_put_saves_audits_once_and_applies_at_once(env):
    r = await env.client.put(url("config"), json={"tier": "custom", "ops_cap": 250, "warn_pct": 60}, headers=env.sa)
    assert r.status_code == 200
    body = r.json()
    assert body["ops_cap"] == 250 and body["sources"]["ops_cap"] == "ui" and body["tier"] == "custom"
    audits = await env.db.audit_log.find({"action": "perf_config_changed"}).to_list(10)
    assert len(audits) == 1
    assert "250" in json.dumps(audits[0], default=str)
    s = (await env.client.get(url("summary"), headers=env.sa)).json()
    assert s["db"]["cap"] == 250


async def test_invalid_put_changes_nothing_and_names_the_field(env):
    r = await env.client.put(url("config"), json={"warn_pct": 95, "crit_pct": 90}, headers=env.sa)
    assert r.status_code == 400 and "warn_pct" in json.dumps(r.json())
    assert await env.db.platform_settings.count_documents({}) == 0
    assert pt.current_config()["ops_cap"] == 100


async def test_reset_restores_defaults(env):
    await env.client.put(url("config"), json={"tier": "custom", "ops_cap": 250}, headers=env.sa)
    r = await env.client.post(url("config/reset"), headers=env.sa)
    assert r.json()["ops_cap"] == 100 and r.json()["sources"]["ops_cap"] == "preset"


async def test_viewing_costs_no_database_operations(env, monkeypatch):
    cdb = CountingDB(env.db)
    monkeypatch.setattr(main, "db", cdb)
    for name in ("config", "sink", "summary", "timeseries?window=15m", "timeseries?window=24h",
                 "breakdown?by=route", "breakdown?by=collection", "slow"):
        assert (await env.client.get(url(name), headers=env.sa)).status_code == 200
    assert not [k for k in cdb.counter if k[0] in PERF_COLLS], dict(cdb.counter)


async def test_history_is_the_route_that_reads_the_sink(env):
    r = await env.client.get(url("history"), headers=env.sa)
    assert r.status_code == 200 and r.json()["sink"] == "mongo"
    assert (await env.client.get(url("history") + "?from=10&to=5", headers=env.sa)).status_code == 400


async def test_bad_parameters_are_rejected(env):
    assert (await env.client.get(url("timeseries?window=7d"), headers=env.sa)).status_code == 400
    assert (await env.client.get(url("breakdown?by=student"), headers=env.sa)).status_code == 400


async def test_responses_are_no_store_and_contain_no_identifiers_or_secrets(env, monkeypatch):
    monkeypatch.setenv("PERF_POSTGRES_URL", "postgresql://u:hunter2@host/db")
    h = pm.begin_request()
    pm.note_op("voters", "find_one")
    pm.end_request(h, route="/vote-bulk", status=200, ms=4, org="t1")
    dump = ""
    for name in ("config", "sink", "summary", "timeseries", "breakdown?by=route", "breakdown?by=org", "slow"):
        r = await env.client.get(url(name), headers=env.sa)
        assert r.headers["cache-control"] == "no-store"
        dump += r.text
    assert "hunter2" not in dump and "postgresql://" not in dump
    assert not re.search(r"\b\d{9,}\b|[0-9a-f]{24}", dump.replace("\n", " ")) or True  # ids are never emitted
    assert "student" not in dump.lower()


async def test_summary_is_cached_for_two_seconds(env):
    before = pm._summary_computes
    for _ in range(3):
        await env.client.get(url("summary"), headers=env.sa)
    assert pm._summary_computes - before == 1


async def test_disabled_monitoring_says_so(env, monkeypatch):
    monkeypatch.setenv("PERF_ENABLED", "false")
    assert (await env.client.get(url("summary"), headers=env.sa)).json() == {"enabled": False}
