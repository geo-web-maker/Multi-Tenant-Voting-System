"""Warm, best-effort mirror of live Mongo data to SECOND_MONGO_URL / mirror.

This is deliberately independent of perf_metrics.motor_kwargs(), isolated from the request path,
and never raises to the backup scheduler. It does not constitute automatic failover.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReplaceOne
import backup
from alerts import alert_critical, alert_warning

log = logging.getLogger("BallotBoxMirror")
BATCH, PAUSE_S, OVERLAP_S = 500, 0.05, 120
_lock = asyncio.Lock()


def enabled() -> bool:
    return os.getenv("MIRROR_ENABLED", "true").lower() == "true" and bool(os.getenv("SECOND_MONGO_URL"))

def host_of(uri: str) -> str:
    return (urlparse(uri).hostname or "").lower()

def _safe_error(value) -> str:
    text = str(value or "Mirror sync failed")
    text = re.sub(r"mongodb(?:\+srv)?://[^\s]+", "mongodb://[redacted]", text, flags=re.I)
    text = re.sub(r"postgres(?:ql)?://[^\s]+", "postgresql://[redacted]", text, flags=re.I)
    text = re.sub(r"(?i)(password|secret|application[_ -]?key|api[_ -]?key|token)(\s*[=:]\s*)[^\s,;]+", r"\1\2[redacted]", text)
    return text[:500]

def _host_fingerprint(uri: str) -> str:
    return hashlib.sha256(host_of(uri).encode()).hexdigest()

def second_client() -> AsyncIOMotorClient:
    # Do not attach live perf listeners; the second DB is outside the live M0 ops budget.
    return AsyncIOMotorClient(os.environ["SECOND_MONGO_URL"], maxPoolSize=2,
                              serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)

def assert_mirror_safe(live_url: str, live_db: str, mirror_db: str) -> None:
    second = os.getenv("SECOND_MONGO_URL", "")
    if not second:
        raise RuntimeError("SECOND_MONGO_URL is not configured.")
    if not host_of(live_url) or host_of(second) == host_of(live_url):
        raise RuntimeError("SECOND_MONGO_URL points at the live cluster. Refusing.")
    if mirror_db in {live_db, "restore_test"}:
        raise RuntimeError(f"Mirror db name {mirror_db!r} is not allowed.")

async def _digest(coll) -> str:
    h = hashlib.sha256()
    async for doc in coll.find({}).sort("_id", 1).batch_size(BATCH):
        h.update(backup._dump_line(doc))
    return h.hexdigest()

async def _upsert(src, dst, query: dict) -> int:
    count, ops = 0, []
    async for doc in src.find(query).sort("_id", 1).batch_size(BATCH):
        ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True)); count += 1
        if len(ops) >= BATCH:
            await dst.bulk_write(ops, ordered=False); ops = []; await asyncio.sleep(PAUSE_S)
    if ops:
        await dst.bulk_write(ops, ordered=False)
    return count

async def _prune(src, dst) -> int:
    # Dataset is sized for Atlas M0. Process ids in a set to avoid one delete command per document.
    keep = {d["_id"] async for d in src.find({}, {"_id": 1}).batch_size(BATCH)}
    stale = [d["_id"] async for d in dst.find({}, {"_id": 1}).batch_size(BATCH) if d["_id"] not in keep]
    for i in range(0, len(stale), BATCH):
        await dst.delete_many({"_id": {"$in": stale[i:i + BATCH]}})
    return len(stale)

async def sync_mirror(live_db, mode: str = "incr") -> dict:
    """mode='incr' after each scheduled run, 'full' for daily reconciliation incl. deletes."""
    if not enabled():
        return {"status": "disabled"}
    if mode not in {"incr", "full"}:
        return {"status": "failed", "error": "mode must be incr or full"}
    if _lock.locked():
        return {"status": "busy"}
    async with _lock:
        meta = live_db.backup_meta
        state = await meta.find_one({"_id": "mirror_state"}) or {}
        started, client = time.monotonic(), None
        try:
            mirror_name = os.getenv("MIRROR_DB_NAME", "mirror")
            live_url = os.getenv("MONGO_URL", "")
            assert_mirror_safe(live_url, live_db.name, mirror_name)
            client = second_client()
            ping_start = time.monotonic()
            await client.admin.command("ping")
            await live_db.client.admin.command("ping")
            second_nodes, live_nodes = set(client.nodes or ()), set(live_db.client.nodes or ())
            if not second_nodes or not live_nodes:
                raise RuntimeError("Could not verify that the second cluster has distinct replica-set members. Refusing.")
            shared_nodes = second_nodes & live_nodes
            if shared_nodes:
                raise RuntimeError("SECOND_MONGO_URL shares replica-set members with the live cluster. Refusing.")
            ping_ms = int((time.monotonic() - ping_start) * 1000)
            mdb = client[mirror_name]
            digests = dict(state.get("digests", {}))
            watermarks = dict(state.get("watermarks", {}))
            fingerprint = _host_fingerprint(os.environ["SECOND_MONGO_URL"])
            if state.get("second_host_fp") != fingerprint:
                # A role swap (Frankfurt temp cluster -> Cape Town) invalidates all prior skip/watermark data.
                digests, watermarks, mode = {}, {}, "full"
            security = backup.SECURITY_ONLY
            names = [n for n in await live_db.list_collection_names()
                     if not n.startswith("system.") and n not in security]
            counts = {}
            for name in sorted(names):
                src, dst = live_db[name], mdb[name]
                if name in backup.APPEND_ONLY and watermarks.get(name) and mode != "full":
                    try:
                        last = ObjectId(watermarks[name])
                        back = ObjectId.from_datetime((last.generation_time - timedelta(seconds=OVERLAP_S)).replace(tzinfo=None))
                        await _upsert(src, dst, {"_id": {"$gte": back}})
                    except Exception:
                        # If an old watermark isn't an ObjectId, do a safe reconciliation for this collection.
                        await _prune(src, dst); await _upsert(src, dst, {})
                else:
                    dg = await _digest(src)
                    if mode == "full" or digests.get(name) != dg:
                        await _prune(src, dst)  # prune before insert/upsert to protect unique key reuse
                        await _upsert(src, dst, {})
                    digests[name] = dg
                if name in backup.APPEND_ONLY:
                    newest = await src.find_one({}, {"_id": 1}, sort=[("_id", -1)])
                    if newest:
                        watermarks[name] = str(newest["_id"])
                counts[name] = {"live": await src.count_documents({}), "mirror": await dst.count_documents({})}
            try:
                size = (await mdb.command("dbStats")).get("dataSize")
            except Exception:
                size = None  # dbStats can be restricted on M0
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            new_state = {"last_ok_at": now, "last_error": None, "consecutive_failures": 0,
                         "digests": digests, "watermarks": watermarks, "counts": counts,
                         "ping_ms": ping_ms, "size_bytes": size,
                         "duration_s": round(time.monotonic() - started, 1), "second_host_fp": fingerprint,
                         "last_mode": mode}
            if mode == "full": new_state["last_reconcile_at"] = now
            await meta.update_one({"_id": "mirror_state"}, {"$set": new_state}, upsert=True)
            mismatches = [n for n, v in counts.items() if v["live"] != v["mirror"]]
            if mismatches:
                await alert_warning("[BallotBox] Mirror count mismatch", f"Collections after sync: {', '.join(mismatches[:30])}")
            return {"status": "ok", "mode": mode, "ping_ms": ping_ms,
                    "duration_s": new_state["duration_s"], "count_mismatches": mismatches}
        except Exception as exc:  # mirror failures never fail a backup run
            failures = int(state.get("consecutive_failures", 0)) + 1
            safe = _safe_error(exc)
            await meta.update_one({"_id": "mirror_state"}, {"$set": {
                "last_error": safe, "consecutive_failures": failures,
                "last_error_at": datetime.utcnow()}}, upsert=True)
            log.error("mirror sync failed (%s consecutive): %s", failures, safe)
            if failures >= 3:
                await alert_critical("[BallotBox] Mirror database sync failing",
                                     f"{failures} failed runs in a row. Last error: {safe}")
            return {"status": "failed", "error": safe[:300]}
        finally:
            if client:
                client.close()
