"""Token-protected backup trigger endpoints (Task 4.5). Called by an EXTERNAL scheduler
(GitHub Actions / cron-job.org) because the Render instance sleeps when idle; the call
itself wakes it. Auth is a shared secret, not an admin session."""
import logging
import os
import secrets

from fastapi import APIRouter, Header, HTTPException, Body
from fastapi.responses import JSONResponse

import backup
import backup_jobs
import backup_mirror
import backup_probes
import restore_check

logger = logging.getLogger("BallotBoxBackup")


def build_router(get_db) -> APIRouter:
    router = APIRouter(prefix="/internal/backup", tags=["backup"])

    def check_token(supplied: str | None):
        expected = os.getenv("BACKUP_TRIGGER_TOKEN")
        if not expected or len(expected) < 24:
            raise HTTPException(503, "Backup trigger is disabled: set BACKUP_TRIGGER_TOKEN (24+ chars).")
        if not supplied or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Invalid backup token.")

    @router.post("/run")
    async def run(mode: str = "incr", x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        try:
            result = await backup.run_scheduled(get_db(), mode)
        except backup.BackupError as e:
            await backup.send_alert("[BallotBox] Backup could not start", str(e))
            return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)
        # Non-2xx on any failure so the scheduler's own failure alert fires too.
        code = 500 if result["status"] == "failed" else (202 if result["status"] == "busy" else 200)
        return JSONResponse(result, status_code=code)

    @router.get("/status")
    async def status(x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        db = get_db()
        runs = await db.backup_runs.find({}, {"_id": 0}).sort("at", -1).limit(30).to_list(30)
        return _jsonable({"recent_runs": runs})

    @router.get("/report")
    async def report(x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        meta = await get_db().backup_meta.find_one({"_id": "size_report"}, {"_id": 0})
        return _jsonable(meta or {"report": None})

    @router.post("/approve-assets")
    async def approve_assets(x_backup_token: str | None = Header(default=None)):
        """The owner's decision after the size report warned about the free tier."""
        check_token(x_backup_token)
        await get_db().backup_meta.update_one(
            {"_id": "size_report"}, {"$set": {"assets_approved": True}}, upsert=True)
        return {"status": "approved"}

    @router.post("/selftest")
    async def selftest(x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        try:
            return _jsonable(await backup.selftest(get_db()))
        except Exception as e:  # noqa: BLE001 — the point of a self-test is to return the failure
            return JSONResponse({"status": "failed", "error": str(e)[:300]}, status_code=500)

    @router.post("/probe")
    async def probe(x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        db = get_db()
        try:
            result = await backup_probes.probe_connections(db)
            sample = await backup_probes.write_probe_sample(db, result)
            try:
                from backup_admin_routes import emit_monitor_alerts
                await emit_monitor_alerts(db, result)
            except Exception as alert_exc:
                logger.warning("backup monitor alert evaluation skipped: %s", str(alert_exc)[:200])
            return _jsonable({"status": result.get("overall", "warning"), "probes": result, "sample": sample})
        except Exception as e:
            # The monitor failing must be visible to scheduler logs without exposing credentials.
            logger.exception("backup probe sample failed")
            return JSONResponse({"status": "failed", "error": str(e)[:250]}, status_code=500)

    @router.post("/mirror-sync")
    async def mirror_sync(body: dict = Body(default={}), x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        result = await backup_mirror.sync_mirror(get_db(), body.get("mode", "incr"))
        return _jsonable(result)

    @router.post("/restore-test")
    async def restore_test(body: dict = Body(default={}), x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        trigger = body.get("trigger", "schedule")
        if trigger not in {"schedule", "manual"}:
            raise HTTPException(400, "trigger must be schedule or manual")
        db = get_db()
        async def worker(ctx):
            config_doc = await db.platform_settings.find_one({"name": "backup_monitor_config"}) or {}
            if trigger == "schedule" and (config_doc.get("values") or {}).get("restore_test_weekly", True) is False:
                await ctx["step"]("schedule", "skipped", "Weekly restore test disabled in Backups settings")
                return {"status": "skipped", "reason": "weekly restore test disabled"}
            async def progress(name, status, detail, done, total):
                await ctx["step"](name, status, detail, done=done, total=total)
            return await restore_check.run_restore_test(db, trigger,
                override_election_guard=bool(body.get("override_election_guard", False)), progress=progress)
        try:
            job = await backup_jobs.start_job(db, "restore_test", trigger, "scheduler" if trigger == "schedule" else "internal-manual",
                                              {"override_election_guard": bool(body.get("override_election_guard", False))}, worker)
        except backup_jobs.JobBusy as exc:
            return JSONResponse({"status": "busy", "run_id": exc.run_id}, status_code=409)
        return JSONResponse(job, status_code=202)

    @router.get("/restore-test/{run_id}")
    async def restore_test_status(run_id: str, x_backup_token: str | None = Header(default=None)):
        check_token(x_backup_token)
        result = await backup_jobs.get_job(get_db(), run_id)
        if not result or result.get("kind") != "restore_test":
            raise HTTPException(404, "Restore-test job not found.")
        result["run_id"] = run_id
        return _jsonable(result)

    return router


def _jsonable(obj):
    from bson import json_util
    import json
    return JSONResponse(json.loads(json_util.dumps(obj)))
