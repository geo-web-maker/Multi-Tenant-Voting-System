"""Token-protected backup trigger endpoints (Task 4.5). Called by an EXTERNAL scheduler
(GitHub Actions / cron-job.org) because the Render instance sleeps when idle; the call
itself wakes it. Auth is a shared secret, not an admin session."""
import logging
import os
import secrets

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

import backup

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
            return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)

    return router


def _jsonable(obj):
    from bson import json_util
    import json
    return JSONResponse(json.loads(json_util.dumps(obj)))
