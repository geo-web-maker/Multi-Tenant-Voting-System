"""backup_metrics: sample is written with a 30-day TTL index; reading the tab never writes."""
import pytest
from mongomock_motor import AsyncMongoMockClient

import backup_probes as bp

pytestmark = pytest.mark.asyncio


async def _stub(monkeypatch):
    async def b2(db, **k): return {"totals": {"routine_bytes": 5}, "tenants": [{"age_minutes": 30}]}
    monkeypatch.setattr(bp, "b2_summary", b2)


PROBES = {"overall": "healthy", "connections": [
    {"id": "live_mongo", "status": "ok", "latency_ms": 12},
    {"id": "second_mirror", "status": "slow", "latency_ms": 900}]}


async def test_sample_records_values_and_creates_ttl_index(monkeypatch):
    await _stub(monkeypatch)
    db = AsyncMongoMockClient()["m"]
    s = await bp.write_probe_sample(db, PROBES)
    assert s["live_ping_ms"] == 12 and s["second_status"] == "slow" and s["newest_backup_age_min"] == 30
    assert s["b2_total_bytes"] == 5
    info = await db.backup_metrics.index_information()
    ttl = [v for v in info.values() if v.get("expireAfterSeconds") == 30 * 86400]
    assert ttl and ttl[0]["key"] == [("at", 1)]


async def test_sample_with_no_mirror_has_null_lag(monkeypatch):
    await _stub(monkeypatch)
    db = AsyncMongoMockClient()["m2"]
    assert (await bp.write_probe_sample(db, PROBES))["mirror_lag_min"] is None


def test_only_probe_paths_write_samples_not_read_endpoints():
    src = open("backup_admin_routes.py", encoding="utf-8").read()
    for route in ("def summary", "def connections(", "def stats", "def b2_info", "def mirror_info"):
        if route in src:
            body = src.split(route, 1)[1].split("@router.", 1)[0]
            assert "write_probe_sample" not in body, route
