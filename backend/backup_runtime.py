"""Small runtime helpers that keep the backup stack inside a Render *free* web service.

Render free gives roughly 0.1 CPU and 512 MB of RAM, spins the instance down after 15 minutes without
inbound HTTP traffic, and restarts it from scratch on the next request. The backup code therefore:

* never holds a whole backup in memory (see backup.export_collection and restore_core.stream_*),
* hands the event loop back often so voters are not starved while a backup compresses/hashes,
* answers scheduler calls immediately and runs the work in the background (backup_routes.run),
* pings its own public URL while a background job runs so Render does not put it to sleep mid-job,
* caches the few expensive read paths behind the Backups tab for a short time.

Every knob is an environment variable with a free-tier default; a bigger instance can raise them.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time

import httpx

log = logging.getLogger("BallotBoxBackupRuntime")


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return int(default)


# --------------------------------------------------------------------------
# Short in-process cache (per process; a restart simply recomputes)
# --------------------------------------------------------------------------
_cache: dict = {}


async def cached(key, ttl_s: float, fn):
    """Return fn()'s result, reusing it for ttl_s seconds. ttl_s <= 0 always recomputes (and stores nothing)."""
    if ttl_s <= 0:
        return await fn()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl_s:
        return hit[1]
    value = await fn()
    _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    _cache.clear()


# Read-through wrappers for dashboard paths (the backup engine itself always reads fresh).
# They take the backup module as an argument so this file stays import-free of it.
async def tenants(backup_mod, db, ttl: float = 30):
    return await cached(("tenants", id(db)), ttl, lambda: backup_mod.list_tenants(db))


async def election_flags(backup_mod, db, org_id, ttl: float = 30):
    return await cached(("flags", id(db), org_id), ttl, lambda: backup_mod._election_flags(db, org_id))


async def ownerless(backup_mod, db, ttl: float = 300):
    return await cached(("ownerless", id(db)), ttl, lambda: backup_mod.ownerless_preflight(db))


# --------------------------------------------------------------------------
# Keep the instance awake while a background job runs
# --------------------------------------------------------------------------
KEEPALIVE_INTERVAL_S = env_float("BACKUP_KEEPALIVE_INTERVAL_S", 240)   # Render sleeps after 15 idle minutes
_active = 0
_beat_task: asyncio.Task | None = None


def _self_url() -> str | None:
    """Public URL of this service. Render sets RENDER_EXTERNAL_URL itself; absent locally, so dev is a no-op."""
    base = os.getenv("BACKUP_KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    return (base.rstrip("/") + "/health") if base else None


async def _beat(url: str) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            try:
                await http.get(url)   # goes out through Render's proxy, so it counts as inbound traffic
            except Exception as exc:  # noqa: BLE001 - best effort; a failed ping must never fail a backup
                log.warning("keepalive ping failed: %s", str(exc)[:120])


@contextlib.asynccontextmanager
async def keep_awake():
    """Hold the instance awake for the duration of the block (re-entrant, shared by concurrent jobs)."""
    global _active, _beat_task
    url = _self_url()
    if not url:
        yield
        return
    _active += 1
    if _beat_task is None or _beat_task.done():
        _beat_task = asyncio.create_task(_beat(url), name="backup-keepalive")
    try:
        yield
    finally:
        _active = max(0, _active - 1)
        if _active == 0 and _beat_task is not None:
            task, _beat_task = _beat_task, None
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
