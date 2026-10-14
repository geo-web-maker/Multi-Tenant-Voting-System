"""Render free tier (0.1 CPU, 512 MB, sleeps after 15 idle minutes): the backup stack must stream, yield, cache,
answer schedulers immediately and survive restarts. These tests pin each of those behaviours."""
import asyncio
import gzip
import hashlib
import os
from datetime import datetime, timedelta

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI
from mongomock_motor import AsyncMongoMockClient

import backup
import backup_admin_routes as bar
import backup_jobs
import backup_mirror
import backup_routes
import backup_runtime
import restore_core
from tests._fakes import FakeS3, put_backup, CFG
from tests.test_backup_admin_routes import ROOT, no_org, _clean  # noqa: F401  (autouse fixture)
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio
TOKEN = "t" * 32
ORG = T = "org-1"


# ---------------------------------------------------------------- export: bounded memory, loop stays responsive
async def test_export_streams_to_disk_and_matches_a_reference_dump(monkeypatch):
    monkeypatch.setattr(backup, "SPOOL_MEM_BYTES", 2048)
    monkeypatch.setattr(backup, "CPU_SLICE", 7)
    monkeypatch.setattr(backup, "BATCH_PAUSE_S", 0)
    db = AsyncMongoMockClient()["x"]
    docs = [{"_id": ObjectId(), "org_id": "o", "n": i, "pad": os.urandom(80).hex()} for i in range(60)]
    await db.voters.insert_many(docs)
    await db.voters.insert_one({"_id": ObjectId(), "org_id": "someone-else"})
    ex = await backup.export_collection(db, "voters", {"org_id": "o"})
    try:
        raw = b"".join(backup._dump_line(d) for d in sorted(docs, key=lambda d: d["_id"]))
        assert ex["count"] == 60 and ex["raw_bytes"] == len(raw)
        assert ex["raw_sha256"] == hashlib.sha256(raw).hexdigest()
        assert ex["spool"]._rolled, "a large export must spill to a temp file instead of staying in RAM"
        data = ex["spool"].read()
        assert len(data) == ex["gz_bytes"] and hashlib.sha256(data).hexdigest() == ex["gz_sha256"]
        assert gzip.decompress(data) == raw
    finally:
        ex["spool"].close()


async def test_export_hands_the_event_loop_back_while_compressing(monkeypatch):
    monkeypatch.setattr(backup, "CPU_SLICE", 5)
    monkeypatch.setattr(backup, "BATCH_PAUSE_S", 0)
    db = AsyncMongoMockClient()["x"]
    await db.voters.insert_many([{"_id": i, "org_id": "o", "pad": "x" * 100} for i in range(100)])
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0)
            ticks += 1
    task = asyncio.create_task(ticker())
    ex = await backup.export_collection(db, "voters", {"org_id": "o"})
    task.cancel()
    ex["spool"].close()
    assert ticks >= 20, "other requests (voters) must be served between slices of the export"


async def test_failed_export_propagates_the_error(monkeypatch):
    class Boom:
        def find(self, *a, **k):
            raise RuntimeError("mongo down")
    class FakeDb:
        def __getitem__(self, name): return Boom()
    with pytest.raises(RuntimeError):
        await backup.export_collection(FakeDb(), "voters", {})


def test_b2_client_is_built_once_per_credential_set(monkeypatch):
    built = []
    monkeypatch.setattr(backup, "_build_client", lambda cfg: built.append(1) or object())
    backup._CLIENT_CACHE.clear()
    cfg = {"endpoint": "e", "key_id": "k", "app_key": "a"}
    try:
        assert backup.make_client(cfg) is backup.make_client(cfg) and len(built) == 1
        backup.make_client({**cfg, "key_id": "other"})
        assert len(built) == 2
    finally:
        backup._CLIENT_CACHE.clear()


async def test_recent_window_is_eighty_percent_of_the_gap():
    db = AsyncMongoMockClient()["x"]
    await db.backup_meta.insert_one({"_id": "mirror_state", "last_ok_at": datetime.utcnow() - timedelta(minutes=20)})
    assert await backup._recent(db.backup_meta, {"_id": "mirror_state"}, "last_ok_at", 30) is True
    await db.backup_meta.update_one({"_id": "mirror_state"}, {"$set": {"last_ok_at": datetime.utcnow() - timedelta(minutes=25)}})
    assert await backup._recent(db.backup_meta, {"_id": "mirror_state"}, "last_ok_at", 30) is False
    assert await backup._recent(db.backup_meta, {"_id": "missing"}, "last_ok_at", 30) is False


# ---------------------------------------------------------------- scheduler endpoint: answer fast, work in background
def _app(db):
    app = FastAPI()
    app.include_router(backup_routes.build_router(lambda: db))
    return app


async def _poll(client, path, headers, done=("passed", "failed", "warning", "skipped")):
    for _ in range(300):
        body = (await client.get(path, headers=headers)).json()
        if body["status"] in done:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("job never finished")


async def test_run_answers_202_immediately_then_finishes_in_the_background(monkeypatch):
    monkeypatch.setenv("BACKUP_TRIGGER_TOKEN", TOKEN)
    monkeypatch.delenv("BACKUP_RUN_WAIT", raising=False)
    db = AsyncMongoMockClient()["r"]
    gate = asyncio.Event()

    async def fake_run(_db, mode):
        await gate.wait()
        return {"status": "ok", "mode": mode, "results": []}
    monkeypatch.setattr(backup, "run_scheduled", fake_run)
    h = {"X-Backup-Token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as c:
        first = await c.post("/internal/backup/run?mode=full", headers=h)
        assert first.status_code == 202 and first.json()["status"] == "queued"
        busy = await c.post("/internal/backup/run?mode=incr", headers=h)
        assert busy.status_code == 202 and busy.json()["status"] == "busy"
        gate.set()
        done = await _poll(c, f"/internal/backup/run/{first.json()['run_id']}", h)
    assert done["status"] == "passed" and done["result"]["mode"] == "full"


async def test_background_run_failure_is_recorded_on_the_job(monkeypatch):
    monkeypatch.setenv("BACKUP_TRIGGER_TOKEN", TOKEN)
    db = AsyncMongoMockClient()["r"]

    async def fake_run(_db, mode):
        return {"status": "failed", "results": [{"status": "failed", "tenant": "t"}]}
    monkeypatch.setattr(backup, "run_scheduled", fake_run)
    h = {"X-Backup-Token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as c:
        run_id = (await c.post("/internal/backup/run?mode=incr", headers=h)).json()["run_id"]
        assert (await _poll(c, f"/internal/backup/run/{run_id}", h))["status"] == "failed"


async def test_backup_error_before_start_alerts_and_fails_the_job(monkeypatch):
    monkeypatch.setenv("BACKUP_TRIGGER_TOKEN", TOKEN)
    db = AsyncMongoMockClient()["r"]
    sent = []

    async def fake_run(_db, mode):
        raise backup.BackupError("not configured")

    async def fake_alert(subject, body):
        sent.append(subject)
    monkeypatch.setattr(backup, "run_scheduled", fake_run)
    monkeypatch.setattr(backup, "send_alert", fake_alert)
    h = {"X-Backup-Token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as c:
        run_id = (await c.post("/internal/backup/run", headers=h)).json()["run_id"]
        job = await _poll(c, f"/internal/backup/run/{run_id}", h)
    assert job["status"] == "failed" and "not configured" in job["error"]
    assert sent == ["[BallotBox] Backup could not start"]


async def test_wait_true_keeps_the_synchronous_contract(monkeypatch):
    monkeypatch.setenv("BACKUP_TRIGGER_TOKEN", TOKEN)
    db = AsyncMongoMockClient()["r"]
    outcome = {"status": "ok", "results": []}

    async def fake_run(_db, mode):
        return outcome
    monkeypatch.setattr(backup, "run_scheduled", fake_run)
    h = {"X-Backup-Token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as c:
        assert (await c.post("/internal/backup/run?wait=true", headers=h)).status_code == 200
        outcome.update(status="failed")
        assert (await c.post("/internal/backup/run?wait=true", headers=h)).status_code == 500
        outcome.update(status="busy")
        assert (await c.post("/internal/backup/run?wait=true", headers=h)).status_code == 202
        monkeypatch.setenv("BACKUP_RUN_WAIT", "true")
        outcome.update(status="ok")
        assert (await c.post("/internal/backup/run", headers=h)).status_code == 200


async def test_run_checks_token_and_mode(monkeypatch):
    monkeypatch.setenv("BACKUP_TRIGGER_TOKEN", TOKEN)
    db = AsyncMongoMockClient()["r"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db)), base_url="http://t") as c:
        assert (await c.post("/internal/backup/run")).status_code == 401
        assert (await c.post("/internal/backup/run", headers={"X-Backup-Token": "wrong" * 8})).status_code == 401
        assert (await c.post("/internal/backup/run?mode=nope", headers={"X-Backup-Token": TOKEN})).status_code == 400
        assert (await c.get("/internal/backup/run/missing", headers={"X-Backup-Token": TOKEN})).status_code == 404


# ---------------------------------------------------------------- restarts and keep-alive
async def test_recover_interrupted_fails_orphaned_jobs_so_nothing_stays_blocked():
    db = AsyncMongoMockClient()["j"]
    now = datetime.utcnow()
    await db.backup_jobs.insert_many([
        {"_id": "a", "kind": "b2_backup", "status": "running", "started_at": now},
        {"_id": "b", "kind": "restore_test", "status": "queued", "started_at": now},
        {"_id": "c", "kind": "b2_verify", "status": "passed", "started_at": now, "finished_at": now}])
    assert await backup_jobs.recover_interrupted(db) == 2
    a = await db.backup_jobs.find_one({"_id": "a"})
    assert a["status"] == "failed" and "restarted" in a["error"] and a["finished_at"]
    assert (await db.backup_jobs.find_one({"_id": "c"}))["status"] == "passed"
    assert await backup_jobs.find_running(db, "b2_backup") is None   # a new run is allowed straight away


async def test_job_progress_is_written_in_a_single_update():
    db = AsyncMongoMockClient()["j"]

    async def worker(ctx):
        await ctx["step"]("copy", "running", "x", done=3, total=9)
        await ctx["step"]("copy", "passed", "y", done=9)
        return {"status": "passed"}
    out = await backup_jobs.start_job(db, "k", "manual", "root", {}, worker)
    for _ in range(200):
        doc = await db.backup_jobs.find_one({"_id": out["run_id"]})
        if doc["status"] == "passed":
            break
        await asyncio.sleep(0.01)
    assert doc["progress"] == {"done": 9, "total": 9} and [s["status"] for s in doc["steps"]] == ["running", "passed"]


async def test_keep_awake_pings_the_public_url_only_while_work_runs(monkeypatch):
    monkeypatch.delenv("BACKUP_KEEPALIVE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://svc.example/")
    monkeypatch.setattr(backup_runtime, "KEEPALIVE_INTERVAL_S", 0.01)
    hits = []

    class FakeHttp:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): hits.append(url)
    monkeypatch.setattr(backup_runtime.httpx, "AsyncClient", FakeHttp)
    async with backup_runtime.keep_awake():
        async with backup_runtime.keep_awake():            # nested/concurrent jobs share one pinger
            await asyncio.sleep(0.08)
            assert backup_runtime._beat_task is not None
        assert backup_runtime._beat_task is not None        # outer job still running
    assert backup_runtime._beat_task is None
    assert hits and set(hits) == {"https://svc.example/health"}
    count = len(hits)
    await asyncio.sleep(0.05)
    assert len(hits) == count, "no pings once the job is over"


async def test_keep_awake_is_a_noop_without_a_public_url(monkeypatch):
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("BACKUP_KEEPALIVE_URL", raising=False)
    async with backup_runtime.keep_awake():
        assert backup_runtime._beat_task is None


# ---------------------------------------------------------------- restore/verify: constant memory, same answers
def _docs(n, org=ORG):
    return [{"_id": ObjectId(), "org_id": org, "n": i} for i in range(n)]


async def test_streaming_restore_equals_plan_restore_including_incrementals_and_replace():
    s3, v = FakeS3(), _docs(3)
    put_backup(s3, f"routine/{T}/full-20261001", T, ORG, {"voters": v, "applications": _docs(2)})
    put_backup(s3, f"routine/{T}/incr-20261002", T, ORG, {"voters": [dict(v[0], n=99)]}, kind="incr")
    base = f"routine/{T}/full-20261001"
    _, merged = restore_core.plan_restore(s3, CFG, T, base)
    org_id, stream = restore_core.open_restore_stream(s3, CFG, T, base)
    db = AsyncMongoMockClient()["scratch"]
    await db.voters.insert_one({"_id": "stale", "org_id": ORG})
    await db.voters.insert_one({"_id": "other-tenant", "org_id": "keep-me"})
    ids = await restore_core.stream_apply(db, org_id, stream, replace=True, tenant=T)
    assert org_id == ORG and ids == {name: set(docs) for name, docs in merged.items()}
    assert {d["_id"]: d async for d in db.voters.find({"org_id": ORG})} == merged["voters"]
    assert await db.voters.find_one({"_id": "other-tenant"}), "replace only clears this tenant's rows"


async def test_streaming_restore_batches_without_holding_everything(monkeypatch):
    monkeypatch.setattr(restore_core, "BATCH_SIZE", 4)
    s3, v = FakeS3(), _docs(10)
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": v})
    org_id, stream = restore_core.open_restore_stream(s3, CFG, T, f"routine/{T}/full-1")
    db = AsyncMongoMockClient()["scratch"]
    ids = await restore_core.stream_apply(db, org_id, stream, tenant=T)
    assert len(ids["voters"]) == 10 and await db.voters.count_documents({}) == 10


@pytest.mark.parametrize("tamper,match", [("checksum", "CHECKSUM"), ("count", "COUNT")])
async def test_streaming_restore_still_rejects_tampered_backups(tamper, match):
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(2)}, tamper=tamper)
    org_id, stream = restore_core.open_restore_stream(s3, CFG, T, f"routine/{T}/full-1")
    with pytest.raises(restore_core.RestoreVerifyError, match=match):
        await restore_core.stream_apply(AsyncMongoMockClient()["scratch"], org_id, stream, tenant=T)


async def test_streaming_restore_refuses_foreign_tenant_rows():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(1) + _docs(1, org="someone-else")})
    with pytest.raises(restore_core.RestoreVerifyError, match="Refusing"):
        restore_core.verify_restore(s3, CFG, T, f"routine/{T}/full-1")


async def test_verify_restore_reports_collections_without_keeping_documents():
    s3 = FakeS3()
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(3), "settings": _docs(1)})
    org_id, names = restore_core.verify_restore(s3, CFG, T, f"routine/{T}/full-1")
    assert org_id == ORG and names == {"voters", "settings"}


# ---------------------------------------------------------------- mirror: cheaper change detection
async def test_mirror_digest_is_stable_and_sees_changes():
    db = AsyncMongoMockClient()["m"]
    await db.c.insert_many([{"_id": 1, "a": 1}, {"_id": 2, "a": 2}])
    first = await backup_mirror._digest(db.c)
    assert first == await backup_mirror._digest(db.c)
    await db.c.update_one({"_id": 2}, {"$set": {"a": 3}})
    assert await backup_mirror._digest(db.c) != first


async def test_mirror_counts_are_exact_when_they_disagree():
    live, mirror = AsyncMongoMockClient()["l"], AsyncMongoMockClient()["m"]
    await live.c.insert_many([{"_id": i} for i in range(5)])
    await mirror.c.insert_many([{"_id": i} for i in range(3)])
    assert await backup_mirror._counts(live.c, mirror.c) == {"live": 5, "mirror": 3}
    await mirror.c.insert_many([{"_id": i} for i in (3, 4)])
    assert await backup_mirror._counts(live.c, mirror.c) == {"live": 5, "mirror": 5}


# ---------------------------------------------------------------- dashboard: bounded work per refresh
async def test_alert_emails_are_not_repeated_after_a_restart_wipes_process_memory():
    db = AsyncMongoMockClient()["a"]
    alerts = [{"kind": "mirror_behind", "level": "warning"}, {"kind": "b2_cap_reached", "level": "critical"}]
    assert [a["kind"] for a in await bar._not_recently_sent(db, alerts)] == ["mirror_behind", "b2_cap_reached"]
    assert await bar._not_recently_sent(db, alerts) == []                         # within the cooldown, even in a new process
    fresh = await bar._not_recently_sent(db, alerts + [{"kind": "restore_stale", "level": "warning"}])
    assert [a["kind"] for a in fresh] == ["restore_stale"]
    await db.backup_meta.update_one({"_id": "alert_cooldowns"},
                                    {"$set": {"sent.b2_cap_reached": datetime.utcnow() - timedelta(minutes=10)}})
    assert [a["kind"] for a in await bar._not_recently_sent(db, alerts[1:])] == ["b2_cap_reached"]


async def test_dashboard_reads_are_cached_between_refreshes():
    db = AsyncMongoMockClient()["c"]
    await db.organizations.insert_one({"_id": ObjectId(), "slug": "a"})
    first = await backup_runtime.tenants(backup, db, 30)
    await db.organizations.insert_one({"_id": ObjectId(), "slug": "b"})
    assert await backup_runtime.tenants(backup, db, 30) == first
    assert len(await backup.list_tenants(db)) == 2, "the backup engine itself always reads fresh"
    backup_runtime.clear_cache()
    assert len(await backup_runtime.tenants(backup, db, 30)) == 2


async def test_stats_for_long_ranges_are_downsampled(env):
    from main import db
    now = datetime.utcnow()
    await db.backup_metrics.insert_many([{"at": now - timedelta(minutes=15 * i), "live_ping_ms": i} for i in range(1000)])
    pts = (await env.client.get(f"{ROOT}/stats?range=30d", headers=no_org(env.sa))).json()["points"]
    assert len(pts) <= bar._STATS_MAX_POINTS + 1
    assert pts[0]["live_ping_ms"] == 999 and pts[-1]["live_ping_ms"] == 0     # still spans the whole window


async def test_jobs_list_omits_heavy_result_but_detail_keeps_it(env):
    from main import db
    await db.backup_jobs.insert_one({"_id": "j1", "kind": "restore_test", "status": "passed", "started_at": datetime.utcnow(),
                                     "steps": [{"name": f"s{i}", "status": "passed"} for i in range(11)],
                                     "result": {"tenants": [{"manifest": {"big": "x" * 1000}}]}})
    listing = (await env.client.get(f"{ROOT}/jobs", headers=no_org(env.sa))).json()["jobs"][0]
    assert "result" not in listing and [s["name"] for s in listing["steps"]] == ["s10"]
    detail = (await env.client.get(f"{ROOT}/jobs/j1", headers=no_org(env.sa))).json()
    assert len(detail["steps"]) == 11 and detail["result"]["tenants"]
