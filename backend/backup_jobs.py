"""Persistent shared job records for backup administration and restore tests."""
from __future__ import annotations
import asyncio
import logging
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable

from backup_runtime import keep_awake

log = logging.getLogger("BallotBoxBackupJobs")

def _safe_error(value) -> str:
    text = str(value or "Job failed")
    text = re.sub(r"mongodb(?:\+srv)?://[^\s]+", "mongodb://[redacted]", text, flags=re.I)
    text = re.sub(r"postgres(?:ql)?://[^\s]+", "postgresql://[redacted]", text, flags=re.I)
    text = re.sub(r"(?i)(password|secret|application[_ -]?key|api[_ -]?key|token)(\s*[=:]\s*)[^\s,;]+", r"\1\2[redacted]", text)
    return text[:1000]

_TERMINAL = {"passed", "warning", "failed", "skipped"}
_locks: dict[str, asyncio.Lock] = {}

class JobBusy(RuntimeError):
    def __init__(self, run_id: str):
        super().__init__(f"A job of this kind is already running: {run_id}")
        self.run_id = run_id

def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

_indexed: set = set()


async def ensure_indexes(db):
    # Two index round trips per job start were pure overhead after the first; once per process and database is enough.
    if id(db) in _indexed:
        return
    _indexed.add(id(db))
    await db.backup_jobs.create_index("finished_at", expireAfterSeconds=180 * 86400, name="backup_jobs_ttl")
    await db.backup_jobs.create_index([("kind", 1), ("status", 1), ("started_at", -1)], name="backup_jobs_kind_status")

async def recover_interrupted(db) -> int:
    """Call once at boot. Jobs run as in-process tasks, and a Render free instance restarts whenever it has slept,
    deployed or run out of memory, so any queued/running record found at boot belongs to a process that no longer
    exists. Fail them now instead of blocking that job kind for the 2-hour stale timeout."""
    res = await db.backup_jobs.update_many(
        {"status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "failed", "finished_at": now_utc(),
                  "error": "Interrupted: the server restarted (Render free instances sleep and restart). Run it again."}})
    return int(getattr(res, "modified_count", 0) or 0)


async def find_running(db, kind: str):
    doc = await db.backup_jobs.find_one({"kind": kind, "status": {"$in": ["queued", "running"]}}, sort=[("started_at", -1)])
    if not doc:
        return None
    # A stale running job after process restart is failed rather than locking the action forever.
    started = doc.get("started_at")
    if started and started < now_utc() - timedelta(hours=2):
        await db.backup_jobs.update_one({"_id": doc["_id"]}, {"$set": {
            "status": "failed", "error": "Job abandoned by an earlier process (stale running record).", "finished_at": now_utc()}})
        return None
    return doc

async def start_job(db, kind: str, trigger: str, actor: str | None, params: dict,
                    worker: Callable[[dict], Awaitable[dict]], *, reject_busy=True) -> dict:
    await ensure_indexes(db)
    lock = _locks.setdefault(kind, asyncio.Lock())
    async with lock:
        existing = await find_running(db, kind)
        if existing:
            if reject_busy:
                raise JobBusy(str(existing.get("_id")))
            return {"run_id": str(existing["_id"]), "status": "busy"}
        run_id = secrets.token_urlsafe(16)
        now = now_utc()
        document = {"_id": run_id, "kind": kind, "status": "queued", "trigger": trigger,
                    "actor": actor or "scheduler", "params": params or {}, "steps": [],
                    "progress": {"done": 0, "total": 0}, "result": {}, "error": None,
                    "started_at": now, "finished_at": None}
        await db.backup_jobs.insert_one(document)
        async def update(**fields):
            await db.backup_jobs.update_one({"_id": run_id}, {"$set": fields})
        async def step(name: str, status: str, detail=None, *, done=None, total=None):
            record = {"name": name, "status": status, "detail": detail, "at": now_utc()}
            op = {"$push": {"steps": record}}
            sets = {}
            if done is not None: sets["progress.done"] = done
            if total is not None: sets["progress.total"] = total
            if sets: op["$set"] = sets
            await db.backup_jobs.update_one({"_id": run_id}, op)   # was push + find + set: three Atlas round trips
        context = {"run_id": run_id, "update": update, "step": step}
        async def execute():
            await update(status="running")
            try:
                async with keep_awake():   # no inbound request is open once 202 is returned; stop Render sleeping
                    result = await worker(context)
                status = result.get("status", "passed") if isinstance(result, dict) else "passed"
                if status not in _TERMINAL: status = "passed"
                await update(status=status, result=result if isinstance(result, dict) else {"value": str(result)},
                             finished_at=now_utc())
            except asyncio.CancelledError:
                await update(status="failed", error="Job was cancelled.", finished_at=now_utc())
                raise
            except Exception as exc:  # job result is persisted instead of leaving a forever-running record
                safe = _safe_error(exc)
                log.error("backup job %s (%s) failed: %s", run_id, kind, safe)
                await update(status="failed", error=safe, finished_at=now_utc())
                try: await step("job", "failed", safe[:500])
                except Exception: pass
        asyncio.create_task(execute(), name=f"backup-job-{kind}-{run_id}")
        return {"run_id": run_id, "status": "queued"}

async def get_job(db, run_id: str):
    doc = await db.backup_jobs.find_one({"_id": run_id}, {"_id": 0})
    return doc
