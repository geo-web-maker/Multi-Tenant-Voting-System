"""Regression cover for the 'Unable to load Backups.' outage.

Root cause: `_alerts` had `any(<genexp containing await> ...)`. An `await` inside a generator expression makes
it an async generator, which any() cannot iterate -> TypeError -> plain-text 500 from /superadmin/backups/summary
-> the panel showed only the frontend's fallback string. These tests pin the fix and the error surface around it.
"""
import ast
import pathlib

import pytest

import backup
import backup_admin_routes as bar
import backup_probes
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_backup_admin_routes import _clean, no_org  # noqa: F401  (autouse fixture + helper)

pytestmark = pytest.mark.asyncio
SUMMARY = "/superadmin/backups/summary"
BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- static guard: the bug class itself
def _await_in_sync_genexp(tree):
    """Line numbers of generator expressions (inside async defs) that await in their element/conditions.

    An await in the *outermost iterable* is evaluated eagerly in the enclosing coroutine and is fine."""
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.GeneratorExp):
                continue
            parts = [node.elt]
            for i, gen in enumerate(node.generators):
                parts.append(gen.target)
                parts.extend(gen.ifs)
                if i > 0:
                    parts.append(gen.iter)
            if any(isinstance(m, ast.Await) for part in parts for m in ast.walk(part)):
                bad.append(node.lineno)
    return sorted(set(bad))


def test_scanner_detects_the_original_bug():
    src = "async def f(db):\n    return any(await g(x) for x in await h(db))\n"
    assert _await_in_sync_genexp(ast.parse(src)) == [2]
    ok = "async def f(db):\n    return sum(c for c in await h(db))\n"
    assert _await_in_sync_genexp(ast.parse(ok)) == []


def test_no_await_inside_generator_expressions_in_backend():
    offenders = {}
    for path in BACKEND.glob("*.py"):
        lines = _await_in_sync_genexp(ast.parse(path.read_text(encoding="utf-8")))
        if lines:
            offenders[path.name] = lines
    assert not offenders, f"await inside a generator expression (async generator -> TypeError in any/all/sum): {offenders}"


# ---------------------------------------------------------------- _alerts itself
async def _db_with_tenants(*, is_open_flags):
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["alerts_unit"]
    for i, is_open in enumerate(is_open_flags):
        res = await db.organizations.insert_one({"slug": f"org{i}", "name": f"Org {i}"})
        await db.settings.insert_one({"name": "election_config", "org_id": str(res.inserted_id), "is_open": is_open})
    return db


def _kinds(alerts):
    return {a["kind"] for a in alerts}


async def _run_alerts(db, *, lag):
    connections = {"connections": [], "guards": [], "overall": "healthy"}
    mirror = {"enabled": True, "lag_minutes": lag, "consecutive_failures": 0, "counts": []}
    cfg = {**bar._CONFIG_DEFAULTS, "mirror_lag_active_minutes": 30, "mirror_lag_idle_minutes": 600}
    b2 = {"totals": {}, "object_count": 0, "last_failure": None, "asset_failures": 0, "tenants": []}
    return await bar._alerts(db, connections, b2, mirror, {"last": None, "running": None}, cfg)


async def test_alerts_use_tight_mirror_threshold_when_any_election_open():
    db = await _db_with_tenants(is_open_flags=[False, True])
    assert "mirror_behind" in _kinds(await _run_alerts(db, lag=120))  # 120 > 30 (active)


async def test_alerts_use_idle_mirror_threshold_when_no_election_open():
    db = await _db_with_tenants(is_open_flags=[False, False])
    assert "mirror_behind" not in _kinds(await _run_alerts(db, lag=120))  # 120 < 600 (idle)


async def test_alerts_do_not_crash_with_no_tenants():
    db = await _db_with_tenants(is_open_flags=[])
    await _run_alerts(db, lag=5)


# ---------------------------------------------------------------- HTTP: /summary degrades instead of 500
async def test_summary_returns_200_and_shape(env):
    r = await env.client.get(SUMMARY, headers=no_org(env.sa))
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    for key in ("overall", "alerts", "connections", "b2", "mirror", "restore", "migration",
                "ownerless_preflight", "jobs_running", "section_errors"):
        assert key in body, key
    assert body["section_errors"] == []


@pytest.mark.parametrize("section,target,attr", [
    ("alerts", bar, "_alerts"),
    ("mirror", bar, "_mirror_info"),
    ("restore", bar, "_restore_info"),
    ("migration", bar, "_migration_state"),
    ("ownerless_preflight", backup, "ownerless_preflight"),
    ("b2", backup_probes, "b2_summary"),
    ("connections", bar, "_connections"),
])
async def test_summary_survives_a_failing_section(env, monkeypatch, section, target, attr):
    async def boom(*a, **k):
        raise RuntimeError("boom mongodb://user:secretpw@host.example.net/db")
    monkeypatch.setattr(target, attr, boom)
    r = await env.client.get(SUMMARY, headers=no_org(env.sa))
    assert r.status_code == 200, (section, r.status_code, r.text[:300])
    body = r.json()
    failed = {e["section"]: e["error"] for e in body["section_errors"]}
    assert section in failed
    assert "secretpw" not in failed[section]          # connection strings are redacted
    assert body["overall"] in ("warning", "critical")  # a degraded panel is never reported 'healthy'


async def test_summary_stays_superadmin_only(env):
    assert (await env.client.get(SUMMARY)).status_code in (401, 403)
    assert (await env.client.get(SUMMARY, headers=env.it)).status_code in (401, 403)
