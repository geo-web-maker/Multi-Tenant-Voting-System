"""HTTP-level checks: superadmin only, no org header needed, token endpoints, no secrets, freeze/final guards."""
import os
import pytest

import main
import write_freeze
from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_security_regressions import _FakeClient

pytestmark = pytest.mark.asyncio
ROOT = "/superadmin/backups"
GETS = ["summary", "connections", "b2", "mirror", "jobs", "stats", "migration", "config"]
SECRET = "mongodb+srv://leakuser:leakpass123@secret-host.example.net/"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(main, "client", _FakeClient())
    monkeypatch.setenv("MONGO_URL", SECRET)
    monkeypatch.setenv("SECOND_MONGO_URL", "mongodb+srv://u2:pw2second@second-host.example.net/")
    write_freeze.lift()
    yield
    write_freeze.lift()


def no_org(headers):
    return {k: v for k, v in headers.items() if k.lower() != "x-org-slug"}


@pytest.mark.parametrize("name", GETS)
async def test_every_get_is_superadmin_only(env, name):
    assert (await env.client.get(f"{ROOT}/{name}")).status_code in (401, 403)
    for role in (env.it, env.com1, env.over):
        assert (await env.client.get(f"{ROOT}/{name}", headers=role)).status_code in (401, 403)


@pytest.mark.parametrize("name", GETS)
async def test_superadmin_works_without_org_header(env, name):
    r = await env.client.get(f"{ROOT}/{name}", headers=no_org(env.sa))
    assert r.status_code == 200, (name, r.status_code, r.text[:200])


async def test_no_response_contains_connection_strings_or_credentials(env):
    for name in GETS:
        text = (await env.client.get(f"{ROOT}/{name}", headers=no_org(env.sa))).text
        for leak in ("leakpass123", "pw2second", "leakuser", "u2:pw", "mongodb+srv://"):
            assert leak not in text, (name, leak)


async def test_opening_the_tab_never_writes_a_metrics_sample(env):
    for name in ("summary", "connections", "stats"):
        await env.client.get(f"{ROOT}/{name}", headers=no_org(env.sa))
    assert await main.db.backup_metrics.count_documents({}) == 0


async def test_stats_rejects_unknown_range_and_filters_window(env):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    await main.db.backup_metrics.insert_many([{"at": now - timedelta(hours=1), "live_ping_ms": 1},
                                              {"at": now - timedelta(days=3), "live_ping_ms": 2}])
    assert (await env.client.get(f"{ROOT}/stats?range=1y", headers=no_org(env.sa))).status_code == 400
    assert len((await env.client.get(f"{ROOT}/stats?range=24h", headers=no_org(env.sa))).json()["points"]) == 1
    assert len((await env.client.get(f"{ROOT}/stats?range=7d", headers=no_org(env.sa))).json()["points"]) == 2


async def test_final_pass_is_refused_without_freeze(env):
    r = await env.client.post(f"{ROOT}/migration/final", json={"confirm": "FINAL PASS"}, headers=no_org(env.sa))
    assert r.status_code == 409


async def test_non_superadmin_cannot_start_freeze_or_jobs(env):
    for path in ("freeze", "health-check", "b2/run", "mirror/sync", "restore-test/run", "migration/plan"):
        r = await env.client.post(f"{ROOT}/{path}", json={}, headers=env.it)
        assert r.status_code in (401, 403), path


async def test_freeze_is_refused_while_an_election_is_open(env):
    org = await main.db.organizations.find_one({})
    await main.db.settings.update_one({"name": "election_config", "org_id": str(org["_id"])},
                                      {"$set": {"is_open": True, "is_certified": False}}, upsert=True)
    r = await env.client.post(f"{ROOT}/freeze", json={"minutes": 5}, headers=no_org(env.sa))
    assert r.status_code == 409 and not write_freeze.active()
    await main.db.settings.update_one({"name": "election_config", "org_id": str(org["_id"])},
                                      {"$set": {"is_open": False}})
    assert (await env.client.post(f"{ROOT}/freeze", json={"minutes": 5}, headers=no_org(env.sa))).status_code == 200
    assert write_freeze.active()


@pytest.mark.parametrize("path,method", [("run", "post"), ("status", "get"), ("report", "get"), ("selftest", "post"),
                                         ("probe", "post"), ("mirror-sync", "post"), ("restore-test", "post")])
async def test_token_endpoints_reject_missing_and_bad_token(env, monkeypatch, path, method):
    call = getattr(env.client, method)
    url = f"/internal/backup/{path}"
    monkeypatch.delenv("BACKUP_TRIGGER_TOKEN", raising=False)
    assert (await call(url)).status_code == 503              # disabled when no token configured
    monkeypatch.setenv("BACKUP_TRIGGER_TOKEN", "t" * 32)
    assert (await call(url)).status_code == 401
    assert (await call(url, headers={"X-Backup-Token": "wrong" * 8})).status_code == 401


def test_new_paths_are_org_exempt_and_public_to_the_session_guard():
    src = open("main.py", encoding="utf-8").read()
    assert '"/superadmin/backups"' in src.split("ORG_EXEMPT_PREFIXES", 1)[1][:600]
    for p in ("/internal/backup/probe", "/internal/backup/mirror-sync", "/internal/backup/restore-test"):
        assert p in src


async def test_monitor_alerts_are_emailed_with_correct_severity(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    import alerts, backup_admin_routes as bar, backup_probes
    sent = []
    async def crit(s, b): sent.append(("critical", s))
    async def warn(s, b): sent.append(("warning", s))
    monkeypatch.setattr(alerts, "alert_critical", crit)
    monkeypatch.setattr(alerts, "alert_warning", warn)
    async def b2(db, **k): return {"totals": {"routine_bytes": 0, "cap_bytes": 10}, "tenants": [],
                                   "last_failure": {"error": "upload failed", "tenant": "t"}}
    monkeypatch.setattr(backup_probes, "b2_summary", b2)
    db = AsyncMongoMockClient()["alerts"]
    await bar.emit_monitor_alerts(db, {"overall": "warning", "connections": [], "guards": []})
    assert any(k == "critical" and "backup_failed" in s for k, s in sent), sent
    assert any(k == "warning" for k, s in sent)
