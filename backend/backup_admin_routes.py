"""Superadmin control-room API for B2 backups, mirror, restore tests and migration jobs."""
from __future__ import annotations
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from motor.motor_asyncio import AsyncIOMotorClient

import backup
import backup_jobs
import backup_mirror
import backup_probes
import migrate_core
import restore_check
import write_freeze
from chain_verify import chain_verify_db
from restore_core import plan_restore, list_backups, ts_of

log = logging.getLogger("BallotBoxBackupAdmin")
_PROBE_CACHE = {"at": 0.0, "data": None}
_CONFIG_DEFAULTS = {
    "full_backup_active_hours": 36, "full_backup_idle_hours": 192,
    "mirror_lag_active_minutes": 60, "mirror_lag_idle_minutes": 2160,
    "mirror_size_warn_bytes": 400 * 1024 * 1024,
    "restore_test_warn_days": 10, "probe_slow_ms": 500, "b2_slow_ms": 2000,
    "sampling_minutes": 15, "restore_test_weekly": True,
}


def _iso(value):
    if not value: return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)

def _host(url):
    return (urlparse(url or "").hostname or "").lower()

def _safe_error(value):
    text = str(value or "Operation failed")
    text = re.sub(r"mongodb(?:\+srv)?://[^\s]+", "mongodb://[redacted]", text, flags=re.I)
    text = re.sub(r"postgres(?:ql)?://[^\s]+", "postgresql://[redacted]", text, flags=re.I)
    text = re.sub(r"(?i)(password|secret|application[_ -]?key|api[_ -]?key|token)(\s*[=:]\s*)[^\s,;]+", r"\1\2[redacted]", text)
    return text[:300]

def _next_restore_schedule(enabled=True):
    if not enabled:
        return None
    now = datetime.now(timezone.utc)
    days_until_sunday = (6 - now.weekday()) % 7
    target = now.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
    if target <= now:
        target += timedelta(days=7)
    return target.isoformat().replace("+00:00", "Z")

def _age_minutes(value):
    if not isinstance(value, datetime): return None
    current = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, int((current - value.replace(tzinfo=None)).total_seconds() / 60))

async def _connections(live_db, *, refresh=False):
    import time
    if not refresh and _PROBE_CACHE["data"] is not None and time.monotonic() - _PROBE_CACHE["at"] < 15:
        return _PROBE_CACHE["data"]
    data = await backup_probes.probe_connections(live_db)
    _PROBE_CACHE.update(at=time.monotonic(), data=data)
    return data

async def _verify_backups(live_db):
    cfg = backup.load_config(); s3 = backup.make_client(cfg)
    rows, errors = [], []
    for org in await backup.list_tenants(live_db):
        tenant = backup.tenant_key(org.get("org_id"))
        try:
            prefixes = await asyncio.to_thread(list_backups, s3, cfg, tenant, "routine")
            fulls = [p for p in prefixes if "/full-" in p]
            if not fulls: raise RuntimeError("No routine full backup found")
            prefix = max(fulls, key=ts_of)
            org_id, merged = await asyncio.to_thread(plan_restore, s3, cfg, tenant, prefix, None, False)
            rows.append({"tenant": tenant, "prefix": prefix, "collections": len(merged), "status": "passed"})
        except Exception as exc:
            errors.append({"tenant": tenant, "error": _safe_error(exc)})
            rows.append({"tenant": tenant, "status": "failed", "error": _safe_error(exc)})
    try:
        glob = await asyncio.to_thread(list_backups, s3, cfg, "_global", "routine")
        fulls = [p for p in glob if "/full-" in p]
        if not fulls: raise RuntimeError("No global platform_settings backup found")
        await asyncio.to_thread(plan_restore, s3, cfg, "_global", max(fulls, key=ts_of), None, True)
        rows.append({"tenant": "_global", "status": "passed"})
    except Exception as exc:
        errors.append({"tenant": "_global", "error": _safe_error(exc)})
    return {"status": "failed" if errors else "passed", "tenants": rows, "errors": errors}

async def _section(errors, name, awaitable, fallback):
    """Run one summary section; a failure degrades only that section instead of 500-ing the whole panel."""
    try:
        return await awaitable
    except Exception as exc:  # noqa: BLE001 - deliberately broad: the dashboard must stay readable
        errors.append({"section": name, "error": _safe_error(exc)})
        return fallback


async def _mirror_info(live_db):
    state = await live_db.backup_meta.find_one({"_id": "mirror_state"}) or {}
    last = state.get("last_ok_at")
    counts = []
    for name, value in (state.get("counts") or {}).items():
        counts.append({"collection": name, "live": value.get("live"), "mirror": value.get("mirror"),
                       "differs": value.get("live") != value.get("mirror")})
    counts.sort(key=lambda r: (not r["differs"], r["collection"]))
    return {"enabled": backup_mirror.enabled(), "last_ok_at": _iso(last), "lag_minutes": _age_minutes(last),
            "ping_ms": state.get("ping_ms"), "size_bytes": state.get("size_bytes"),
            "limit_bytes": 512 * 1024 * 1024, "consecutive_failures": state.get("consecutive_failures", 0),
            "last_error": state.get("last_error"), "last_mode": state.get("last_mode"),
            "counts": counts, "second_host_fp": state.get("second_host_fp")}

async def _restore_info(live_db):
    last = await live_db.backup_jobs.find_one({"kind": "restore_test", "finished_at": {"$ne": None}}, {"_id": 1, "status": 1, "finished_at": 1,
        "started_at": 1, "result": 1, "steps": 1, "error": 1}, sort=[("started_at", -1)])
    running = await live_db.backup_jobs.find_one({"kind": "restore_test", "status": {"$in": ["queued", "running"]}},
        {"_id": 1, "status": 1, "steps": 1, "started_at": 1}, sort=[("started_at", -1)])
    return {"last": ({"run_id": str(last.get("_id")), "status": last.get("status"),
                       "finished_at": _iso(last.get("finished_at")), "started_at": _iso(last.get("started_at")),
                       "duration_s": round((last["finished_at"] - last["started_at"]).total_seconds(), 1)
                       if last.get("finished_at") and last.get("started_at") else None,
                       "steps": last.get("steps", []), "result": last.get("result"), "error": last.get("error")}
                      if last else None),
            "running": ({"run_id": str(running.get("_id")), "status": running.get("status"),
                         "steps": running.get("steps", [])} if running else None)}

async def _alerts(live_db, connections, b2, mirror, restore, cfg):
    alerts = []
    def add(kind, level, metric, value, threshold, message):
        alerts.append({"kind": kind, "level": level, "metric": metric, "value": value,
                       "threshold": threshold, "message": message})
    probes = {p["id"]: p for p in connections.get("connections", [])}
    history = await live_db.backup_metrics.find({}, {"_id": 0, "live_status": 1, "second_status": 1,
        "postgres_status": 1, "b2_status": 1, "nomination_status": 1, "at": 1}).sort("at", -1).limit(3).to_list(3)
    status_field = {"live_mongo": "live_status", "second_mirror": "second_status",
                    "postgres_history": "postgres_status", "b2_backup_bucket": "b2_status",
                    "b2_nomination_bucket": "nomination_status"}
    for probe_id, level in (("live_mongo", "critical"), ("second_mirror", "warning"),
                            ("b2_backup_bucket", "critical"), ("postgres_history", "critical"),
                            ("b2_nomination_bucket", "warning")):
        p = probes.get(probe_id, {})
        status = p.get("status", "unconfigured")
        field = status_field[probe_id]
        streak = 0
        for sample in history:
            if sample.get(field) == status:
                streak += 1
            else:
                break
        down_threshold = {"live_mongo": 2, "second_mirror": 3, "b2_backup_bucket": 1,
                          "postgres_history": 1, "b2_nomination_bucket": 1}[probe_id]
        # Database outages are debounced to avoid a single network blip paging; backup bucket
        # lock/unreachable failures are immediate because a missed backup can be irreversible.
        if status == "down" and streak >= down_threshold:
            add(f"{probe_id}_down", level, "probe_status", "down", "ok", f"{p.get('label', probe_id)} probe is down")
        elif status == "slow" and streak >= 3:
            limit = cfg["b2_slow_ms"] if probe_id.startswith("b2_") else cfg["probe_slow_ms"]
            add(f"{probe_id}_slow", "warning", "latency_ms", p.get("latency_ms"), limit,
                f"{p.get('label', probe_id)} probe has been slow for {streak} samples")
        elif status == "unconfigured":
            add(f"{probe_id}_unconfigured", "warning", "configured", False, True,
                f"{p.get('label', probe_id)} is not configured")
    recent_latency = await live_db.backup_metrics.find({}, {"_id": 0, "live_ping_ms": 1, "at": 1}).sort("at", -1).limit(3).to_list(3)
    if len(recent_latency) == 3 and all(isinstance(x.get("live_ping_ms"), (int, float)) and x["live_ping_ms"] > 150 for x in recent_latency):
        add("live_latency_target", "warning", "live_ping_ms", recent_latency[0]["live_ping_ms"], 150,
            "Live database ping remains above the post-Frankfurt 150 ms target")
    last_sample = await live_db.backup_metrics.find_one({}, {"_id": 0, "at": 1}, sort=[("at", -1)])
    if not last_sample or _age_minutes(last_sample.get("at")) is None or _age_minutes(last_sample.get("at")) > 45:
        add("monitor_samples_stopped", "warning", "sample_age_min",
            _age_minutes(last_sample.get("at")) if last_sample else None, 45,
            "Backup monitoring samples have stopped for more than 45 minutes")
    for guard in connections.get("guards", []):
        if not guard.get("ok"): add("backup_guard_failed", "critical", guard.get("name"), False, True, guard.get("name", "Backup safety guard failed"))
    for row in b2.get("tenants", []):
        full_at = row.get("last_full_at")
        age = _age_minutes(full_at)
        org_id = row.get("org_id")
        active = backup._active(await backup._election_flags(live_db, org_id))
        threshold = cfg["full_backup_active_hours"] * 60 if active else cfg["full_backup_idle_hours"] * 60
        if age is None or age > threshold:
            add("full_backup_stale", "warning", "full_backup_age_min", age, threshold,
                f"No sufficiently recent full backup for {row.get('slug') or row.get('tenant')}")
    mirror_lag = mirror.get("lag_minutes")
    # NB: no `await` inside a generator expression handed to any()/all()/sum(): that makes it an async
    # generator, which sync consumers cannot iterate (TypeError -> plain-text 500 on /summary).
    open_any = False
    for x in await backup.list_tenants(live_db):
        if backup._active(await backup._election_flags(live_db, x.get("org_id"))):
            open_any = True
            break
    lag_threshold = cfg["mirror_lag_active_minutes"] if open_any else cfg["mirror_lag_idle_minutes"]
    if mirror.get("enabled") and (mirror_lag is None or mirror_lag > lag_threshold):
        add("mirror_behind", "warning", "mirror_lag_min", mirror_lag, lag_threshold, "Mirror is stale or has never completed a sync")
    if not mirror.get("enabled"):
        add("mirror_unconfigured", "warning", "configured", False, True, "Second-cluster mirror is not configured")
    if mirror.get("consecutive_failures", 0) >= 3:
        add("mirror_failing", "critical", "consecutive_failures", mirror.get("consecutive_failures"), 3, "Mirror sync has failed three or more times")
    if any(x.get("differs") for x in mirror.get("counts", [])):
        add("mirror_count_mismatch", "warning", "count_mismatches", sum(1 for x in mirror["counts"] if x.get("differs")), 0, "One or more mirror collection counts differ from live")
    if (mirror.get("size_bytes") or 0) > cfg["mirror_size_warn_bytes"]:
        add("mirror_near_cap", "warning", "mirror_size_bytes", mirror.get("size_bytes"), cfg["mirror_size_warn_bytes"], "Mirror is above the configured size warning threshold")
    totals = b2.get("totals", {})
    total_bytes = sum(totals.get(k, 0) or 0 for k in ("routine_bytes", "safety_bytes", "milestone_bytes"))
    if totals.get("cap_bytes") and total_bytes >= totals["cap_bytes"]:
        add("b2_cap_reached", "critical", "b2_total_bytes", total_bytes, totals.get("cap_bytes"), "B2 backup storage cap reached")
    if b2.get("last_failure"):
        add("backup_failed", "critical", "last_failure", str(b2["last_failure"].get("error") if isinstance(b2["last_failure"], dict) else b2["last_failure"]), None, "A backup run failed")
    nomination = next((x for x in connections.get("connections", []) if x.get("id") == "b2_nomination_bucket"), None)
    if nomination and nomination.get("status") == "ok" and nomination.get("detail", {}).get("versioning_enabled") is False:
        add("nomination_bucket_versioning", "warning", "versioning_enabled", False, True,
            "Nomination-file bucket is reachable but versioning is not enabled")
    last = restore.get("last")
    if not last:
        add("restore_never_run", "warning", "restore_test", "never", "10 days", "Restore test has never run")
    else:
        finished = last.get("finished_at")
        try: age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(finished.replace("Z", "+00:00"))).total_seconds()/86400 if finished else 999
        except Exception: age_days = 999
        if last.get("status") == "failed": add("restore_failed", "critical", "restore_status", "failed", "passed", "Latest restore test failed")
        elif last.get("status") == "warning": add("restore_warning", "warning", "restore_status", "warning", "passed", "Latest restore test has warnings")
        if age_days > cfg["restore_test_warn_days"]:
            add("restore_stale", "warning", "restore_age_days", round(age_days, 1), cfg["restore_test_warn_days"], "Restore test has not run recently")
    ownerless = await backup.ownerless_preflight(live_db)
    orphan_total = sum(ownerless.get("counts", {}).values())
    if orphan_total:
        add("ownerless_backup_data", "critical", "ownerless_documents", orphan_total, 0,
            "Newly covered collections contain documents without org_id; assign or remove them before cutover")
    if write_freeze.active():
        add("write_freeze_active", "warning", "write_freeze", True, False, "Write freeze is active; it lifts automatically")
    if not any(x.get("id") == "postgres_history" and x.get("status") == "ok" for x in connections.get("connections", [])):
        # Probe-level unconfigured/down above carries the actionable state.
        pass
    order = {"critical": 0, "warning": 1}
    alerts.sort(key=lambda a: order.get(a["level"], 2))
    return alerts


async def emit_monitor_alerts(live_db, probe_data=None):
    """Send thresholded monitor alerts from scheduler/manual probes (not from GET requests)."""
    connections = probe_data or await backup_probes.probe_connections(live_db)
    b2 = await backup_probes.b2_summary(live_db)
    mirror = await _mirror_info(live_db)
    restore = await _restore_info(live_db)
    doc = await live_db.platform_settings.find_one({"name": "backup_monitor_config"}) or {}
    cfg = {**_CONFIG_DEFAULTS, **(doc.get("values") or {})}
    alerts = await _alerts(live_db, connections, b2, mirror, restore, cfg)
    try:
        from alerts import alert_critical, alert_warning
        for item in alerts:
            subject = f"[BallotBox] {item['level'].upper()}: {item['kind']}"
            body = f"{item['message']}\nMetric: {item['metric']}\nValue: {item['value']}\nThreshold: {item['threshold']}"
            if item["level"] == "critical": await alert_critical(subject, body)
            else: await alert_warning(subject, body)
    except Exception as exc:
        log.error("Unable to send backup monitoring alert: %s", str(exc)[:300])
    return alerts


def build_router(get_db, require_role, log_action_fn=None) -> APIRouter:
    router = APIRouter()
    guard = Depends(require_role("superadmin"))

    def no_store(response: Response): response.headers["Cache-Control"] = "no-store"

    async def audit(action, admin, params):
        if log_action_fn:
            await log_action_fn(action, admin.get("sub", "unknown"), params)

    async def spawn(db, kind, body, admin, worker, action):
        await audit(action, admin, body)
        try:
            result = await backup_jobs.start_job(db, kind, "manual", admin.get("sub", "unknown"), body, worker)
        except backup_jobs.JobBusy as exc:
            raise HTTPException(409, {"detail": str(exc), "run_id": exc.run_id})
        return result

    @router.get("/superadmin/backups/summary")
    async def summary(response: Response, admin: dict = guard):
        no_store(response); db = get_db(); errors = []
        connections = await _section(errors, "connections", _connections(db), {"connections": [], "guards": [], "overall": "unknown"})
        b2 = await _section(errors, "b2", backup_probes.b2_summary(db), {"totals": {}, "object_count": None, "last_failure": "unavailable", "asset_failures": 0, "tenants": []})
        mirror = await _section(errors, "mirror", _mirror_info(db), {"enabled": False, "counts": [], "consecutive_failures": 0})
        restore = await _section(errors, "restore", _restore_info(db), {"last": None, "running": None})
        async def _cfg():
            doc = await db.platform_settings.find_one({"name": "backup_monitor_config"}) or {}
            return {**_CONFIG_DEFAULTS, **(doc.get("values") or {})}
        cfg = await _section(errors, "config", _cfg(), dict(_CONFIG_DEFAULTS))
        alerts = await _section(errors, "alerts", _alerts(db, connections, b2, mirror, restore, cfg), [])
        migration = await _section(errors, "migration", _migration_state(db, connections, b2, mirror, restore), None)
        ownerless = await _section(errors, "ownerless_preflight", backup.ownerless_preflight(db), {"counts": {}, "safe": None})
        levels = {a["level"] for a in alerts}
        overall = "critical" if "critical" in levels else "warning" if levels or errors or connections.get("overall") != "healthy" else "healthy"
        async def _jobs():
            rows = await db.backup_jobs.find({"status": {"$in": ["queued", "running"]}},
                {"_id": 1, "kind": 1, "status": 1, "steps": 1, "started_at": 1}).sort("started_at", -1).limit(8).to_list(8)
            for job in rows: job["run_id"] = str(job.pop("_id")); job["started_at"] = _iso(job.get("started_at"))
            return rows
        jobs = await _section(errors, "jobs_running", _jobs(), [])
        return {"overall": overall, "checked_at": datetime.now(timezone.utc).isoformat(), "alerts": alerts,
                "connections": connections.get("connections", []), "guards": connections.get("guards", []),
                "b2": b2, "mirror": mirror, "restore": {**restore, "next_scheduled": _next_restore_schedule(cfg.get("restore_test_weekly", True))},
                "migration": migration, "ownerless_preflight": ownerless, "jobs_running": jobs, "section_errors": errors}

    @router.get("/superadmin/backups/connections")
    async def connections(response: Response, admin: dict = guard):
        no_store(response); db = get_db()
        return await _connections(db)

    @router.post("/superadmin/backups/connections/test")
    async def test_connections(response: Response, admin: dict = guard):
        no_store(response); db = get_db()
        result = await _connections(db, refresh=True)
        await backup_probes.write_probe_sample(db, result)
        await emit_monitor_alerts(db, result)
        await audit("backup_connections_tested", admin, {})
        return result

    @router.get("/superadmin/backups/b2")
    async def b2_status(response: Response, refresh: bool = False, admin: dict = guard):
        no_store(response); return await backup_probes.b2_summary(get_db(), refresh=refresh)

    @router.get("/superadmin/backups/mirror")
    async def mirror_status(response: Response, admin: dict = guard):
        no_store(response); return await _mirror_info(get_db())

    @router.get("/superadmin/backups/jobs")
    async def jobs(response: Response, kind: str | None = None, limit: int = Query(20, ge=1, le=100), admin: dict = guard):
        no_store(response); q = {"kind": kind} if kind else {}
        rows = await get_db().backup_jobs.find(q, {"_id": 1, "kind": 1, "status": 1, "trigger": 1,
            "actor": 1, "params": 1, "progress": 1, "steps": 1, "result": 1, "error": 1,
            "started_at": 1, "finished_at": 1}).sort("started_at", -1).limit(limit).to_list(limit)
        for row in rows: row["run_id"] = str(row.pop("_id"))
        return {"jobs": rows}

    @router.get("/superadmin/backups/jobs/{run_id}")
    async def job_status(run_id: str, response: Response, admin: dict = guard):
        no_store(response); job = await backup_jobs.get_job(get_db(), run_id)
        if not job: raise HTTPException(404, "Job not found.")
        return {"run_id": run_id, **job}

    @router.get("/superadmin/backups/stats")
    async def stats(response: Response, range: str = "24h", admin: dict = guard):
        no_store(response)
        windows = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
        if range not in windows: raise HTTPException(400, "range must be 24h, 7d or 30d.")
        start = datetime.now(timezone.utc).replace(tzinfo=None) - windows[range]
        rows = await get_db().backup_metrics.find({"at": {"$gte": start}}, {"_id": 0}).sort("at", 1).limit(3000).to_list(3000)
        for row in rows: row["at"] = _iso(row.get("at"))
        return {"range": range, "points": rows}

    @router.get("/superadmin/backups/migration")
    async def migration(response: Response, admin: dict = guard):
        no_store(response)
        return await _migration_state(get_db(), await _connections(get_db()), await backup_probes.b2_summary(get_db()),
                                      await _mirror_info(get_db()), await _restore_info(get_db()))

    @router.get("/superadmin/backups/config")
    async def get_config(response: Response, admin: dict = guard):
        no_store(response); doc = await get_db().platform_settings.find_one({"name": "backup_monitor_config"}) or {}
        return {"values": {**_CONFIG_DEFAULTS, **(doc.get("values") or {})},
                "environment": {"restore_test_keep_data": os.getenv("RESTORE_TEST_KEEP_DATA", "false").lower() == "true"},
                "updated_at": _iso(doc.get("updated_at")), "updated_by": doc.get("updated_by")}

    @router.put("/superadmin/backups/config")
    async def put_config(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response)
        if "values" in body and isinstance(body["values"], dict): body = body["values"]
        unknown = set(body) - set(_CONFIG_DEFAULTS)
        if unknown: raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")
        merged = {**_CONFIG_DEFAULTS, **body}
        for key in ("full_backup_active_hours", "full_backup_idle_hours", "mirror_lag_active_minutes",
                    "mirror_lag_idle_minutes", "mirror_size_warn_bytes", "restore_test_warn_days",
                    "probe_slow_ms", "b2_slow_ms", "sampling_minutes"):
            if isinstance(merged[key], bool) or not isinstance(merged[key], (int, float)) or merged[key] <= 0:
                raise HTTPException(400, f"{key} must be a positive number")
        if merged["sampling_minutes"] < 5 or merged["sampling_minutes"] > 60:
            raise HTTPException(400, "sampling_minutes must be between 5 and 60")
        old = await get_db().platform_settings.find_one({"name": "backup_monitor_config"}) or {}
        await get_db().platform_settings.update_one({"name": "backup_monitor_config"}, {"$set": {
            "values": merged, "updated_at": datetime.utcnow(), "updated_by": admin.get("sub", "unknown")}}, upsert=True)
        await audit("backup_config_changed", admin, {"old": old.get("values", {}), "new": merged})
        return {"values": merged, "environment": {"restore_test_keep_data": os.getenv("RESTORE_TEST_KEEP_DATA", "false").lower() == "true"},
                "updated_at": datetime.utcnow().isoformat() + "Z", "updated_by": admin.get("sub", "unknown")}

    @router.post("/superadmin/backups/health-check")
    async def health_check(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db()
        async def worker(ctx):
            results = {}
            p = await _connections(db, refresh=True); results["connections"] = p
            await ctx["step"]("connections", "passed" if p.get("overall") == "healthy" else "warning", p.get("overall"))
            try:
                results["b2_verify"] = await _verify_backups(db)
                await ctx["step"]("b2_verify", "passed" if results["b2_verify"]["status"] == "passed" else "failed", results["b2_verify"]["status"])
            except Exception as exc:
                results["b2_verify"] = {"status": "failed", "error": _safe_error(exc)}
                await ctx["step"]("b2_verify", "failed", _safe_error(exc))
            results["mirror"] = await backup_mirror.sync_mirror(db, "incr")
            await ctx["step"]("mirror_sync", "passed" if results["mirror"].get("status") == "ok" else "warning", results["mirror"].get("status"))
            chains = []
            for org in await backup.list_tenants(db):
                chains.append({"tenant": backup.tenant_key(org.get("org_id")), **(await chain_verify_db(db, org.get("org_id")))})
            results["chain_live"] = chains
            await ctx["step"]("chain_live", "failed" if any(not x.get("valid") for x in chains) else "passed", f"Verified {len(chains)} live tenant chain(s)")
            if backup_mirror.enabled():
                client = AsyncIOMotorClient(os.environ["SECOND_MONGO_URL"], maxPoolSize=2, serverSelectionTimeoutMS=8000)
                try:
                    await client.admin.command("ping"); mdb = client[os.getenv("MIRROR_DB_NAME", "mirror")]
                    mch = [{"tenant": backup.tenant_key(org.get("org_id")), **(await chain_verify_db(mdb, org.get("org_id")))} for org in await backup.list_tenants(db)]
                    results["chain_mirror"] = mch
                    await ctx["step"]("chain_mirror", "failed" if any(not x.get("valid") for x in mch) else "passed", f"Verified {len(mch)} mirror tenant chain(s)")
                finally: client.close()
            if body.get("include_restore_test"):
                async def prog(name, status, detail, done, total): await ctx["step"](name, status, detail, done=done, total=total)
                results["restore_test"] = await restore_check.run_restore_test(db, "manual", override_election_guard=bool(body.get("override_election_guard")), progress=prog)
                await ctx["step"]("restore_test", results["restore_test"].get("status", "failed"), "Restore test completed")
            # Store the sample after sync/optional restore so mirror lag and test result are current.
            await backup_probes.write_probe_sample(db, p)
            await emit_monitor_alerts(db, p)
            statuses = [x.get("status") for x in results.values() if isinstance(x, dict)]
            chain_invalid = any(not row.get("valid") for key in ("chain_live", "chain_mirror")
                                for row in results.get(key, []))
            result_status = ("failed" if chain_invalid or p.get("overall") == "critical" or any(s == "failed" for s in statuses)
                             else "warning" if p.get("overall") != "healthy" or results.get("mirror", {}).get("status") != "ok"
                             or any(s in {"warning", "busy"} for s in statuses) else "passed")
            return {"status": result_status, **results}
        response.status_code = 202
        return await spawn(db, "health_check", body, admin, worker, "backup_health_check_started")

    @router.post("/superadmin/backups/b2/run")
    async def b2_run(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response); db = get_db(); tenant = str(body.get("tenant") or "default"); kind = body.get("kind", "full")
        if kind not in {"full", "incr"}: raise HTTPException(400, "kind must be full or incr")
        async def worker(ctx):
            if backup._run_lock.locked(): raise HTTPException(409, "A scheduled backup is running.")
            preflight = await backup.ownerless_preflight(db)
            if not preflight.get("safe"):
                unsafe = {name: count for name, count in preflight.get("counts", {}).items() if count}
                raise HTTPException(409, {"detail": "Ownerless records must be assigned or removed before backup.",
                                          "ownerless_preflight": unsafe})
            async with backup._run_lock:
                org = next((o for o in await backup.list_tenants(db) if backup.tenant_key(o.get("org_id")) == tenant), None)
                if not org: raise HTTPException(404, "Tenant not found.")
                cfg = backup.load_config(); result = await backup.backup_tenant(db, backup.make_client(cfg), cfg, org, kind, force=bool(body.get("force", False)))
                await backup._log_run(db, tenant, kind, result.get("status") == "uploaded", result.get("bytes_gz", 0), result)
                await ctx["step"]("backup", "passed" if result.get("status") in {"uploaded", "skipped"} else "failed", result.get("status"))
                mirror_result = None
                if result.get("status") in {"uploaded", "skipped"}:
                    try:
                        mirror_result = await asyncio.wait_for(backup_mirror.sync_mirror(db, "incr"), timeout=120)
                    except Exception as exc:  # B2 backup success is independent of mirror health.
                        mirror_result = {"status": "failed", "error": _safe_error(exc)}
                        log.warning("manual backup mirror sync skipped: %s", _safe_error(exc))
                return {"status": "passed" if result.get("status") in {"uploaded", "skipped"} else "failed",
                        "backup": result, "mirror": mirror_result}
        result = await spawn(db, "b2_backup", {"tenant": tenant, "kind": kind, "force": bool(body.get("force", False))}, admin, worker, "backup_b2_run_started")
        response.status_code = 202; return result

    @router.post("/superadmin/backups/b2/verify")
    async def b2_verify(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db()
        async def worker(ctx):
            result = await _verify_backups(db)
            await ctx["step"]("verify", result["status"], f"Verified {len(result['tenants'])} backup sets")
            return result
        response.status_code = 202
        return await spawn(db, "b2_verify", body, admin, worker, "backup_b2_verify_started")

    @router.post("/superadmin/backups/b2/selftest")
    async def b2_selftest(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db()
        async def worker(ctx):
            result = await backup.selftest(db)
            ok = bool(result.get("b2", {}).get("read_back")) and bool(result.get("b2", {}).get("put_with_governance_lock"))
            await ctx["step"]("selftest", "passed" if ok else "failed", "B2 put and read-back" if ok else str(result.get("b2")))
            return {"status": "passed" if ok else "failed", **result}
        response.status_code = 202
        return await spawn(db, "b2_selftest", body, admin, worker, "backup_b2_selftest_started")

    @router.post("/superadmin/backups/mirror/sync")
    async def mirror_sync(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db(); mode = body.get("mode", "incr")
        if mode not in {"incr", "full"}: raise HTTPException(400, "mode must be incr or full")
        async def worker(ctx):
            res = await backup_mirror.sync_mirror(db, mode)
            await ctx["step"]("mirror_sync", "passed" if res.get("status") == "ok" else "failed", res.get("status"))
            return {**res, "status": "passed" if res.get("status") == "ok" else "failed" if res.get("status") == "failed" else "warning"}
        response.status_code = 202
        return await spawn(db, "mirror_sync", {"mode": mode}, admin, worker, "backup_mirror_sync_started")

    @router.post("/superadmin/backups/restore-test/run")
    async def restore_test_run(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db(); override = bool(body.get("override_election_guard", False))
        open_names = []
        for org in await backup.list_tenants(db):
            if backup._active(await backup._election_flags(db, org.get("org_id"))): open_names.append(org.get("slug") or backup.tenant_key(org.get("org_id")))
        if open_names and not override:
            raise HTTPException(409, {"code": "election_open", "detail": "An election is open; confirm the extra restore-test load to continue.", "open_tenants": open_names})
        async def worker(ctx):
            async def prog(name, status, detail, done, total): await ctx["step"](name, status, detail, done=done, total=total)
            return await restore_check.run_restore_test(db, "manual", override_election_guard=override, progress=prog)
        response.status_code = 202
        return await spawn(db, "restore_test", {"override_election_guard": override}, admin, worker, "backup_restore_test_started")

    @router.post("/superadmin/backups/chain-verify")
    async def chain_verify(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response); db = get_db(); target = body.get("target", "live"); tenant = body.get("tenant", "all")
        if target not in {"live", "mirror"}: raise HTTPException(400, "target must be live or mirror")
        async def worker(ctx):
            remote = None
            try:
                if target == "mirror":
                    if not backup_mirror.enabled(): raise RuntimeError("Second cluster mirror is not configured")
                    remote = AsyncIOMotorClient(os.environ["SECOND_MONGO_URL"], maxPoolSize=2, serverSelectionTimeoutMS=8000)
                    await remote.admin.command("ping"); target_db = remote[os.getenv("MIRROR_DB_NAME", "mirror")]
                else: target_db = db
                orgs = await backup.list_tenants(db)
                if tenant != "all": orgs = [o for o in orgs if backup.tenant_key(o.get("org_id")) == tenant]
                if tenant != "all" and not orgs: raise HTTPException(404, "Tenant not found")
                rows = [{"tenant": backup.tenant_key(o.get("org_id")), **(await chain_verify_db(target_db, o.get("org_id")))} for o in orgs]
                valid = all(r.get("valid") for r in rows)
                await ctx["step"]("chain_verify", "passed" if valid else "failed", f"Checked {len(rows)} chain(s)")
                return {"status": "passed" if valid else "failed", "target": target, "results": rows}
            finally:
                if remote: remote.close()
        response.status_code = 202
        return await spawn(db, "chain_verify", {"target": target, "tenant": tenant}, admin, worker, "backup_chain_verify_started")

    @router.post("/superadmin/backups/migration/plan")
    async def migration_plan(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db()
        async def worker(ctx):
            client, url = _migration_target_client()
            try:
                plan = await migrate_core.migrate_database(db, client[os.getenv("MONGO_DB_NAME", db.name)], mode="plan",
                    source_url=os.getenv("MONGO_URL"), target_url=url)
                await ctx["step"]("plan", "passed", f"Planned {len(plan['collections'])} collections")
                return plan
            finally: client.close()
        response.status_code = 202
        return await spawn(db, "migration_plan", body, admin, worker, "backup_migration_plan_started")

    @router.post("/superadmin/backups/migration/run")
    async def migration_run(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response); db = get_db()
        if body.get("confirm") != "MIGRATE": raise HTTPException(400, 'Type confirm="MIGRATE" to start the copy.')
        async def worker(ctx):
            client, url = _migration_target_client()
            async def progress(p): await ctx["step"](p.get("collection", "migration"), "passed" if p.get("ok", True) else "warning", p.get("phase"), done=p.get("index"), total=p.get("total"))
            try:
                result = await migrate_core.migrate_database(db, client[os.getenv("MONGO_DB_NAME", db.name)], mode="copy",
                    source_url=os.getenv("MONGO_URL"), target_url=url, progress=progress)
                result["status"] = "passed" if result.get("status") == "passed" else "failed"
                return result
            finally: client.close()
        response.status_code = 202
        return await spawn(db, "migration_copy", {"confirm": "MIGRATE"}, admin, worker, "backup_migration_copy_started")

    @router.post("/superadmin/backups/migration/final")
    async def migration_final(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response); db = get_db()
        if body.get("confirm") != "FINAL PASS": raise HTTPException(400, 'Type confirm="FINAL PASS" to proceed.')
        if not write_freeze.active(): raise HTTPException(409, "Final pass is refused unless the write freeze is active.")
        async def worker(ctx):
            client, url = _migration_target_client()
            async def progress(p): await ctx["step"](p.get("collection", "migration"), "passed" if p.get("ok", True) else "warning", p.get("phase"), done=p.get("index"), total=p.get("total"))
            try:
                result = await migrate_core.migrate_database(db, client[os.getenv("MONGO_DB_NAME", db.name)], mode="final",
                    source_url=os.getenv("MONGO_URL"), target_url=url, progress=progress)
                result["status"] = "passed" if result.get("status") == "passed" else "failed"
                return result
            finally: client.close()
        response.status_code = 202
        return await spawn(db, "migration_final", {"confirm": "FINAL PASS", "freeze_active": True}, admin, worker, "backup_migration_final_started")

    @router.post("/superadmin/backups/migration/verify")
    async def migration_verify(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db()
        async def worker(ctx):
            client, url = _migration_target_client()
            try:
                result = await migrate_core.migrate_database(db, client[os.getenv("MONGO_DB_NAME", db.name)], mode="verify",
                    source_url=os.getenv("MONGO_URL"), target_url=url)
                chains = []
                if result.get("status") == "passed":
                    for org in await backup.list_tenants(db):
                        chains.append({"tenant": backup.tenant_key(org.get("org_id")), **(await chain_verify_db(client[os.getenv("MONGO_DB_NAME", db.name)], org.get("org_id")))})
                result["chain_verify"] = chains
                if any(not c.get("valid") for c in chains): result["status"] = "failed"
                await ctx["step"]("migration_verify", result.get("status", "failed"), f"Checked {len(result.get('collections', []))} collections")
                return result
            finally: client.close()
        response.status_code = 202
        return await spawn(db, "migration_verify", body, admin, worker, "backup_migration_verify_started")

    @router.post("/superadmin/backups/freeze")
    async def freeze_start(response: Response, body: dict = Body(default={}), admin: dict = guard):
        no_store(response); db = get_db()
        for org in await backup.list_tenants(db):
            if backup._active(await backup._election_flags(db, org.get("org_id"))):
                raise HTTPException(409, "Write freeze cannot start while any election is open.")
        try: state = write_freeze.start(body.get("minutes", 20))
        except ValueError as exc: raise HTTPException(400, str(exc))
        await audit("backup_write_freeze_started", admin, {"minutes": body.get("minutes", 20)})
        return state

    @router.delete("/superadmin/backups/freeze")
    async def freeze_lift(response: Response, admin: dict = guard):
        no_store(response); before = write_freeze.status(); state = write_freeze.lift()
        await audit("backup_write_freeze_lifted", admin, {"was_active": before.get("active")})
        return state

    return router


def _migration_target_client():
    url = (os.getenv("MIGRATION_TARGET_URL") or os.getenv("SECOND_MONGO_URL") or "").strip()
    if not url: raise HTTPException(503, "MIGRATION_TARGET_URL / SECOND_MONGO_URL is not configured.")
    target_db = os.getenv("MONGO_DB_NAME", "electiondbaccounting")
    if target_db in {"mirror", "restore_test"}:
        raise HTTPException(409, f"Migration target database {target_db!r} is reserved and cannot be used.")
    if _host(url) == _host(os.getenv("MONGO_URL")):
        raise HTTPException(409, "Migration target resolves to the live cluster.")
    return AsyncIOMotorClient(url, maxPoolSize=2, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000), url

async def _migration_state(db, connections, b2, mirror, restore):
    tenants = await backup.list_tenants(db)
    open_tenants = []
    for org in tenants:
        if backup._active(await backup._election_flags(db, org.get("org_id"))): open_tenants.append(org)
    jobs = {}
    for kind in ("b2_verify", "restore_test", "migration_final", "migration_verify"):
        jobs[kind] = await db.backup_jobs.find_one({"kind": kind}, {"_id": 1, "status": 1, "started_at": 1,
            "finished_at": 1, "result": 1, "params": 1}, sort=[("started_at", -1)])
    probes = {r["id"]: r for r in connections.get("connections", [])}
    checks = []
    checks.append({"name": "No election open", "ok": not open_tenants, "detail": [o.get("slug") or backup.tenant_key(o.get("org_id")) for o in open_tenants]})
    required_probes = ("live_mongo", "migration_target", "b2_backup_bucket", "postgres_history")
    checks.append({"name": "Live, migration target, B2 and Postgres probes healthy",
                   "ok": all(probes.get(x, {}).get("status") == "ok" for x in required_probes),
                   "detail": {x: probes.get(x, {}).get("status", "not run") for x in required_probes}})
    full_fresh = True
    for org in tenants:
        st = await db.backup_state.find_one({"_id": backup.tenant_key(org.get("org_id"))}) or {}
        age = _age_minutes(st.get("last_full_at")); maxage = 36 * 60 if backup._active(await backup._election_flags(db, org.get("org_id"))) else 8 * 24 * 60
        full_fresh &= age is not None and age <= maxage
    verify_job = jobs.get("b2_verify")
    verify_recent = bool(verify_job and verify_job.get("status") == "passed" and verify_job.get("finished_at") and verify_job["finished_at"] >= datetime.utcnow() - timedelta(hours=24))
    checks.append({"name": "Recent full backups and B2 verification in last 24 hours", "ok": full_fresh and verify_recent})
    mirror_ok = mirror.get("enabled") and mirror.get("last_ok_at") and not mirror.get("last_error") and not any(x.get("differs") for x in mirror.get("counts", []))
    checks.append({"name": "Mirror synced successfully with matching counts", "ok": bool(mirror_ok)})
    restore_job = jobs.get("restore_test")
    restore_ok = bool(restore_job and restore_job.get("status") == "passed" and restore_job.get("finished_at") and restore_job["finished_at"] >= datetime.utcnow() - timedelta(days=7))
    checks.append({"name": "Restore test passed in last 7 days", "ok": restore_ok})
    freeze = write_freeze.status()
    final_job = jobs.get("migration_final")
    freeze_time = None
    if freeze.get("started_at"):
        try: freeze_time = datetime.fromisoformat(freeze["started_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception: pass
    final_after_freeze = bool(freeze.get("active") and final_job and final_job.get("status") == "passed" and final_job.get("started_at") and freeze_time and final_job["started_at"] >= freeze_time)
    checks.append({"name": "Final migration pass completed during active write freeze", "ok": final_after_freeze})
    final_finished = final_job.get("finished_at") if final_job else None
    verify_after = bool(final_finished and jobs.get("migration_verify") and jobs["migration_verify"].get("status") == "passed"
                        and jobs["migration_verify"].get("started_at") and jobs["migration_verify"]["started_at"] > final_finished)
    checks.append({"name": "Migration counts, digests and target Chain Verify passed after final pass", "ok": verify_after})
    uncovered = await backup.coverage_audit(db)
    checks.append({"name": "No uncovered tenant-data collections", "ok": not uncovered, "detail": uncovered})
    ownerless = await backup.ownerless_preflight(db)
    checks.append({"name": "No ownerless records in newly covered collections", "ok": ownerless.get("safe", False), "detail": ownerless.get("counts", {})})
    # After cutover, the role swap checklist can be checked separately; it is not a pre-cutover gate.
    target_url = os.getenv("MIGRATION_TARGET_URL") or os.getenv("SECOND_MONGO_URL") or ""
    second_url = os.getenv("SECOND_MONGO_URL") or ""
    live_detail = probes.get("live_mongo", {}).get("detail") or {}
    temp_dbs = live_detail.get("temporary_databases") if isinstance(live_detail, dict) else None
    role_swap = {
        "second_cluster_not_migration_target": bool(second_url and target_url and _host(second_url) != _host(target_url)),
        "mirror_last_mode_full": mirror.get("last_mode") == "full",
        # Unknown (e.g. Atlas denies listDatabases) is not a passing safety check.
        "no_temporary_dbs_on_live": temp_dbs == [],
    }
    for name, ok in role_swap.items():
        # This checklist is informational until post-cutover; don't block initial cutover readiness on it.
        pass
    return {"ready": all(c.get("ok") for c in checks), "freeze_active": freeze.get("active"), "freeze": freeze,
            "checklist": checks, "source": {"label": "Live database", "database": db.name},
            "target": {"label": "Migration target", "database": os.getenv("MONGO_DB_NAME", db.name)},
            "role_swap_checklist": role_swap}
