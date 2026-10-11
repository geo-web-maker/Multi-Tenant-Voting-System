"""Superadmin-only Performance API (PERF-M4).

summary / timeseries / breakdown / slow / sink / config read memory only (P3). Settings live in the global
platform_settings collection; history is read from the configured sink. Responses carry no identifiers or secrets.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response

import analytics
import analytics_migration
import perf_metrics
import perf_tiers

log = logging.getLogger(__name__)

_BREAKDOWNS = {"collection", "route", "org", "op"}
_WINDOWS = {"15m", "24h"}


def _iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if epoch else None


def config_body() -> dict:
    sink = perf_metrics.sink_status()
    return perf_tiers.public_config({
        "started_at": _iso(perf_metrics._started_at),
        "collecting_since": _iso(perf_metrics._collecting_since),
        "sink_status": sink,
    })


def build_router(get_db, require_role, log_action_fn=None) -> APIRouter:
    router = APIRouter()
    perf_metrics.ensure_sink(get_db)
    guard = Depends(require_role("superadmin"))

    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"

    @router.get("/superadmin/performance/config")
    async def get_config(response: Response, admin: dict = guard):
        no_store(response)
        return config_body()

    @router.put("/superadmin/performance/config")
    async def put_config(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response)
        old = perf_tiers.saved_values()
        try:
            new_values = perf_tiers.apply_update(old, body)
        except ValueError as e:
            detail = e.args[0] if e.args and isinstance(e.args[0], dict) else {"_": str(e)}
            raise HTTPException(400, detail)
        actor = admin.get("sub", "unknown")
        await perf_tiers.save_config(get_db(), new_values, actor)
        if log_action_fn:
            try:
                await log_action_fn("perf_config_changed", actor, {"old": old, "new": new_values})
            except Exception:
                log.debug("perf config audit failed", exc_info=True)
        perf_metrics.invalidate_summary()
        return config_body()

    @router.post("/superadmin/performance/config/reset")
    async def reset_config(response: Response, admin: dict = guard):
        no_store(response)
        await perf_tiers.reset_config(get_db())
        perf_metrics.invalidate_summary()
        return config_body()

    @router.get("/superadmin/performance/sink")
    async def sink(response: Response, admin: dict = guard):
        no_store(response)
        return perf_metrics.sink_status()

    @router.get("/superadmin/performance/summary")
    async def summary(response: Response, admin: dict = guard):
        no_store(response)
        if not perf_tiers.perf_enabled():
            return {"enabled": False}
        return perf_metrics.summary()

    @router.get("/superadmin/performance/timeseries")
    async def timeseries(response: Response, window: str = "15m", admin: dict = guard):
        no_store(response)
        if window not in _WINDOWS:
            raise HTTPException(400, "window must be 15m or 24h.")
        return perf_metrics.timeseries(window)

    @router.get("/superadmin/performance/breakdown")
    async def breakdown(response: Response, by: str = "collection", admin: dict = guard):
        no_store(response)
        if by not in _BREAKDOWNS:
            raise HTTPException(400, "by must be collection, route, org or op.")
        return perf_metrics.breakdown(by)

    def storage_body() -> dict:
        return {**analytics.storage_status(), "migration": analytics_migration.migration_state()}

    @router.get("/superadmin/performance/storage")
    async def get_storage(response: Response, admin: dict = guard):
        no_store(response)
        if analytics_migration.migration_state().get("status") == "idle":
            await analytics_migration.load_last_result(get_db())
        return storage_body()

    @router.put("/superadmin/performance/storage")
    async def put_storage(response: Response, body: dict = Body(...), admin: dict = guard):
        no_store(response)
        before = analytics.storage_mode()
        try:
            await analytics.switch_storage(get_db(), str(body.get("mode") or ""), admin.get("sub", "unknown"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if log_action_fn:
            try:
                await log_action_fn("analytics_storage_switched", admin.get("sub", "unknown"), {"from": before, "to": analytics.storage_mode()})
            except Exception:
                log.debug("analytics storage audit failed", exc_info=True)
        return storage_body()

    @router.post("/superadmin/performance/storage/migrate")
    async def migrate_storage(response: Response, admin: dict = guard):
        no_store(response)
        try:
            analytics_migration.start_migration(get_db())
        except ValueError as e:
            raise HTTPException(409, str(e))
        if log_action_fn:
            try:
                await log_action_fn("analytics_migration_started", admin.get("sub", "unknown"), {"cutoff": analytics_migration.migration_state().get("cutoff")})
            except Exception:
                log.debug("analytics migration audit failed", exc_info=True)
        return storage_body()

    @router.get("/superadmin/performance/orgs")
    async def orgs(response: Response, window: str = "15m", admin: dict = guard):
        no_store(response)
        if window not in ("15m", "24h", "7d"):
            raise HTTPException(400, "window must be 15m, 24h or 7d.")
        return await perf_metrics.org_series(window)

    @router.get("/superadmin/performance/slow")
    async def slow(response: Response, admin: dict = guard):
        no_store(response)
        return {"commands": perf_metrics.slow_commands()}

    @router.get("/superadmin/performance/history")
    async def history(response: Response, start: int | None = Query(None, alias="from"),
                      end: int | None = Query(None, alias="to"), admin: dict = guard):
        no_store(response)
        now = int(time.time())
        end = end if end is not None else now
        start = start if start is not None else end - 86400
        if start >= end:
            raise HTTPException(400, "from must be before to.")
        return await perf_metrics.read_history(start, end)

    return router
