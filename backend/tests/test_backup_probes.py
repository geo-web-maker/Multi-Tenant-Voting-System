"""backup_probes: probe states, 8 s timeout isolation, secret redaction, unconfigured services."""
import asyncio
import pytest
from mongomock_motor import AsyncMongoMockClient

import backup_probes as bp

pytestmark = pytest.mark.asyncio
L = ("x", "X")


async def test_ok_slow_down_and_unconfigured_states():
    async def fast(): return {"k": 1}
    async def slow():
        await asyncio.sleep(0.02); return {}
    async def broken(): raise RuntimeError("boom")
    async def unset(): raise NotImplementedError("X is not set.")
    assert (await bp._probe(L, fast, slow_ms=500))["status"] == "ok"
    assert (await bp._probe(L, slow, slow_ms=1))["status"] == "slow"
    assert (await bp._probe(L, broken))["status"] == "down"
    r = await bp._probe(L, unset)
    assert r["status"] == "unconfigured" and r["latency_ms"] is None


async def test_hanging_probe_times_out_without_blocking_others(monkeypatch):
    monkeypatch.setattr(bp, "TIMEOUT_S", 0.05)
    async def hang(): await asyncio.sleep(5)
    async def fine(): return {}
    res = await asyncio.gather(bp._probe(("a", "A"), hang), bp._probe(("b", "B"), fine))
    assert res[0]["status"] == "down" and "timed out" in res[0]["detail"] and res[1]["status"] == "ok"


async def test_errors_never_leak_urls_or_passwords():
    async def leak(): raise RuntimeError("mongodb+srv://u:pw@h.example/ password=hunter2 postgres://a:b@c/d")
    out = await bp._probe(L, leak)
    assert "pw@" not in out["detail"] and "hunter2" not in out["detail"] and "a:b@" not in out["detail"]


async def test_host_label_is_hostname_only():
    assert bp.host_label("mongodb+srv://user:secret@cluster0.abc.mongodb.net/db") == "cluster0.abc.mongodb.net"
    assert bp.host_label(None) is None


async def test_unset_environment_reports_unconfigured_not_ok(monkeypatch):
    for k in ("SECOND_MONGO_URL", "MIGRATION_TARGET_URL", "ANALYTICS_POSTGRES_URL", "B2_BACKUP_BUCKET_NAME"):
        monkeypatch.delenv(k, raising=False)
    db = AsyncMongoMockClient()["live"]
    res = await bp.probe_connections(db)
    by = {c["id"]: c for c in res["connections"]}
    assert by["second_mirror"]["status"] == "unconfigured" and by["second_staging"]["status"] == "unconfigured"
    assert res["overall"] != "healthy"
    assert "://" not in str(res)


async def test_timeout_env_and_message(monkeypatch):
    monkeypatch.setattr(bp, "TIMEOUT_S", 0.05)
    async def hang(): await asyncio.sleep(5)
    out = await bp._probe(L, hang)
    assert out["status"] == "down" and "0.05 seconds" in out["detail"]
    assert bp._env_num("PROBE_TIMEOUT_S", "8") == 8.0
    monkeypatch.setenv("PROBE_TIMEOUT_S", "bad")
    assert bp._env_num("PROBE_TIMEOUT_S", "8") == 8.0


async def test_concurrency_limit_serialises_probes(monkeypatch):
    monkeypatch.setenv("PROBE_CONCURRENCY", "1")
    bp._SEMS.clear()
    running, peak = 0, 0
    async def work():
        nonlocal running, peak
        running += 1; peak = max(peak, running)
        await asyncio.sleep(0.01); running -= 1
        return {}
    await asyncio.gather(*(bp._probe((str(i), "x"), work) for i in range(4)))
    assert peak == 1
    bp._SEMS.clear()
