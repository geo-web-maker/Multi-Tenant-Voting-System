"""Bounded health probes for backup infrastructure; outputs labels/metadata, never secrets."""
from __future__ import annotations
import asyncio
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from motor.motor_asyncio import AsyncIOMotorClient
import backup

TIMEOUT_S = 8


def _safe_error(exc) -> str:
    value = str(exc or "Probe failed")
    value = re.sub(r"mongodb(?:\+srv)?://[^\s]+", "mongodb://[redacted]", value, flags=re.I)
    value = re.sub(r"postgres(?:ql)?://[^\s]+", "postgresql://[redacted]", value, flags=re.I)
    value = re.sub(r"(?i)(password|secret|application[_ -]?key|api[_ -]?key)(\s*[=:]\s*)[^\s,;]+", r"\1\2[redacted]", value)
    return value[:240]


def host_label(uri: str | None) -> str | None:
    if not uri:
        return None
    try:
        parsed = urlparse(uri)
        return parsed.hostname or None
    except Exception:
        return None

async def _probe(label, fn, *, slow_ms=500):
    started = time.monotonic()
    try:
        detail = await asyncio.wait_for(fn(), timeout=TIMEOUT_S)
        elapsed = int((time.monotonic() - started) * 1000)
        status = "slow" if elapsed > slow_ms else "ok"
        return {"id": label[0], "label": label[1], "status": status, "latency_ms": elapsed, "detail": detail}
    except asyncio.TimeoutError:
        return {"id": label[0], "label": label[1], "status": "down", "latency_ms": TIMEOUT_S * 1000, "detail": "Probe timed out after 8 seconds."}
    except NotImplementedError as exc:
        return {"id": label[0], "label": label[1], "status": "unconfigured", "latency_ms": None, "detail": _safe_error(exc)}
    except Exception as exc:
        return {"id": label[0], "label": label[1], "status": "down", "latency_ms": int((time.monotonic()-started)*1000), "detail": _safe_error(exc)}

async def _mongo_probe(db, *, with_info=True):
    await db.client.admin.command("ping")
    version = "unknown"
    if with_info:
        try: version = (await db.command("buildInfo")).get("version", "unknown")
        except Exception: pass
    names = [n for n in await db.list_collection_names() if not n.startswith("system.")]
    counts = {}
    for name in names[:40]:
        try: counts[name] = await db[name].estimated_document_count()
        except Exception: counts[name] = None
    size = None
    try: size = int((await db.command("dbStats")).get("dataSize", 0))
    except Exception: size = None
    temporary_databases = None
    # Atlas roles may deny listDatabases; None means unknown, not that the names are absent.
    try:
        existing = await db.client.list_database_names()
        temporary_databases = [n for n in ("mirror", "restore_test") if n in existing]
    except Exception:
        pass
    return {"database": db.name, "server_version": version, "collections": len(names),
            "collection_counts": counts, "size_bytes": size, "limit_bytes": 512 * 1024 * 1024,
            "temporary_databases": temporary_databases}

async def probe_connections(live_db) -> dict:
    """Probe all configured services concurrently; a stuck connection cannot block other probes."""
    results = []
    tasks = []
    try:
        config_doc = await asyncio.wait_for(live_db.platform_settings.find_one({"name": "backup_monitor_config"}), timeout=2)
    except Exception:
        # A failed live DB must not prevent the independent B2/second-cluster probes from running.
        config_doc = {}
    monitor_cfg = (config_doc or {}).get("values") or {}
    mongo_slow_ms = int(monitor_cfg.get("probe_slow_ms", 500))
    b2_slow_ms = int(monitor_cfg.get("b2_slow_ms", 2000))
    tasks.append(_probe(("live_mongo", "Live database"), lambda: _mongo_probe(live_db), slow_ms=mongo_slow_ms))

    second_url = os.getenv("SECOND_MONGO_URL")
    mirror_name = os.getenv("MIRROR_DB_NAME", "mirror")
    scratch_name = os.getenv("RESTORE_TEST_DB_NAME", "restore_test")
    mig_url = os.getenv("MIGRATION_TARGET_URL") or second_url
    db_name = os.getenv("MONGO_DB_NAME", live_db.name)

    async def second_db(db_name_to_probe):
        if not second_url: raise NotImplementedError("SECOND_MONGO_URL is not set.")
        client = AsyncIOMotorClient(second_url, maxPoolSize=2, serverSelectionTimeoutMS=TIMEOUT_S * 1000)
        try:
            meta = await live_db.backup_meta.find_one({"_id": "mirror_state"}) or {}
            data = await _mongo_probe(client[db_name_to_probe], with_info=False)
            data["last_sync_at"] = meta.get("last_ok_at")
            return data
        finally: client.close()

    tasks.append(_probe(("second_mirror", "Second cluster mirror"), lambda: second_db(mirror_name), slow_ms=mongo_slow_ms))
    async def staging_db():
        if not second_url: raise NotImplementedError("SECOND_MONGO_URL is not set.")
        client = AsyncIOMotorClient(second_url, maxPoolSize=2, serverSelectionTimeoutMS=TIMEOUT_S * 1000)
        try:
            await client.admin.command("ping")
            db = client[scratch_name]
            names = [n for n in await db.list_collection_names() if not n.startswith("system.")]
            return {"database": scratch_name, "collections": len(names), "empty_is_normal": len(names) == 0}
        finally: client.close()
    tasks.append(_probe(("second_staging", "Staging (restore test)"), staging_db))

    async def migration_db():
        if not mig_url: raise NotImplementedError("MIGRATION_TARGET_URL / SECOND_MONGO_URL is not set.")
        client = AsyncIOMotorClient(mig_url, maxPoolSize=2, serverSelectionTimeoutMS=TIMEOUT_S * 1000)
        try: return await _mongo_probe(client[db_name], with_info=False)
        finally: client.close()
    tasks.append(_probe(("migration_target", "Migration target"), migration_db, slow_ms=mongo_slow_ms))

    async def postgres_probe():
        url = (os.getenv("ANALYTICS_POSTGRES_URL") or "").strip()
        if not url: raise NotImplementedError("ANALYTICS_POSTGRES_URL is not set.")
        from analytics_store import PostgresAnalyticsStore
        store = PostgresAnalyticsStore(url, pooled=os.getenv("ANALYTICS_POSTGRES_POOLED", "false").lower() == "true")
        try:
            pool = await store._get_pool()
            async with pool.acquire() as con: await con.fetchval("SELECT 1")
            return {"database": "analytics history", "query": "SELECT 1"}
        finally:
            await store.close()
    tasks.append(_probe(("postgres_history", "Postgres analytics history"), postgres_probe, slow_ms=mongo_slow_ms))

    async def b2_probe():
        cfg = backup.load_config(); client = backup.make_client(cfg)
        def run():
            client.head_bucket(Bucket=cfg["bucket"])
            client.list_objects_v2(Bucket=cfg["bucket"], MaxKeys=1)
            lock = client.get_object_lock_configuration(Bucket=cfg["bucket"])
            return {"bucket_reachable": True, "object_lock_configured": bool(lock.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled"))}
        out = await asyncio.to_thread(run)
        if not out["object_lock_configured"]: raise RuntimeError("Backup bucket object lock is not enabled.")
        return out
    tasks.append(_probe(("b2_backup_bucket", "Backblaze backup bucket"), b2_probe, slow_ms=b2_slow_ms))

    async def nomination_probe():
        import nomination_storage
        if not nomination_storage.is_configured(): raise NotImplementedError("Nomination bucket is not configured.")
        cfg = {k: os.getenv(k, "") for k in nomination_storage.ENV_NAMES}
        import boto3
        from botocore.config import Config
        client = boto3.client("s3", endpoint_url=cfg["NOMINATION_B2_ENDPOINT"],
                              aws_access_key_id=cfg["NOMINATION_B2_KEY_ID"],
                              aws_secret_access_key=cfg["NOMINATION_B2_APPLICATION_KEY"],
                              config=Config(connect_timeout=4, read_timeout=4, retries={"max_attempts": 1}))
        def run():
            client.head_bucket(Bucket=cfg["NOMINATION_B2_BUCKET_NAME"])
            versioning = client.get_bucket_versioning(Bucket=cfg["NOMINATION_B2_BUCKET_NAME"])
            return {"bucket_reachable": True, "versioning_enabled": versioning.get("Status") == "Enabled"}
        return await asyncio.to_thread(run)
    tasks.append(_probe(("b2_nomination_bucket", "Nomination files bucket"), nomination_probe, slow_ms=b2_slow_ms))

    results = await asyncio.gather(*tasks)
    by_id = {r["id"]: r for r in results}
    guard_checks = []
    live_host, second_host = host_label(os.getenv("MONGO_URL")), host_label(second_url)
    guard_checks.append({"name": "Live and second cluster differ (hostname)", "ok": bool(second_host and live_host and second_host != live_host)})
    guard_checks.append({"name": "Scratch database name is restore_test", "ok": scratch_name == "restore_test"})
    guard_checks.append({"name": "Mirror database name differs from live and scratch", "ok": mirror_name not in {live_db.name, scratch_name}})
    guard_checks.append({"name": "Migration target differs from live", "ok": bool(mig_url and host_label(mig_url) and host_label(mig_url) != live_host)})
    # Compare resolved replica-set members as well as hostnames to catch SRV aliases.
    try:
        if second_url:
            second = AsyncIOMotorClient(second_url, maxPoolSize=1, serverSelectionTimeoutMS=TIMEOUT_S * 1000)
            await second.admin.command("ping")
            live_nodes, second_nodes = set(live_db.client.nodes or ()), set(second.nodes or ())
            common = live_nodes & second_nodes
            guard_checks.append({"name": "Live and second cluster nodes do not overlap",
                                 "ok": bool(live_nodes and second_nodes and not common),
                                 **({} if live_nodes and second_nodes else {"detail": "Unable to prove cluster separation from resolved nodes."})})
            second.close()
        else:
            guard_checks.append({"name": "Live and second cluster nodes do not overlap", "ok": False})
    except Exception as exc:
        guard_checks.append({"name": "Live and second cluster nodes do not overlap", "ok": False, "detail": _safe_error(exc)})
    overall = "critical" if any(r["status"] == "down" for r in results) or any(not g["ok"] for g in guard_checks) else (
        "warning" if any(r["status"] in {"slow", "unconfigured"} for r in results) else "healthy")
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "connections": results,
            "guards": guard_checks, "overall": overall}

_B2_CACHE = {"at": 0.0, "data": None}

async def b2_summary(live_db, *, refresh=False) -> dict:
    """Cached 10 minutes because a bucket-wide object listing incurs billed calls."""
    now = time.monotonic()
    if not refresh and _B2_CACHE["data"] is not None and now - _B2_CACHE["at"] < 600:
        data = _B2_CACHE["data"]
    else:
        try:
            cfg = backup.load_config(); client = backup.make_client(cfg)
            objects = await backup._list(client, cfg, "")
            totals = {"routine_bytes": 0, "safety_bytes": 0, "milestone_bytes": 0, "cap_bytes": int(os.getenv("B2_BACKUP_CAP_BYTES", str(10 * 10**9)))}
            for obj in objects:
                key = obj.get("Key", "")
                bucket = key.split("/", 1)[0]
                field = {"routine": "routine_bytes", "safety": "safety_bytes", "milestone": "milestone_bytes"}.get(bucket)
                if field: totals[field] += int(obj.get("Size", 0))
            data = {"totals": totals, "object_count": len([o for o in objects if o.get("Key")]),
                    "last_failure": None, "asset_failures": 0}
            _B2_CACHE.update(at=now, data=data)
        except Exception as exc:
            data = {"totals": {"routine_bytes": 0, "safety_bytes": 0, "milestone_bytes": 0,
                              "cap_bytes": int(os.getenv("B2_BACKUP_CAP_BYTES", str(10 * 10**9)))},
                    "object_count": None, "last_failure": _safe_error(exc), "asset_failures": 0}
    tenants = await backup.list_tenants(live_db)
    rows = []
    if not isinstance(data.get("last_failure"), str):
        # Report a failure only while it remains the latest run for that tenant.
        tenant_keys = [backup.tenant_key(org.get("org_id")) for org in tenants] + ["_global"]
        current_failures = []
        for tenant_key in tenant_keys:
            latest = await live_db.backup_runs.find_one(
                {"tenant": tenant_key}, {"_id": 0, "tenant": 1, "kind": 1, "error": 1, "at": 1, "ok": 1},
                sort=[("at", -1)])
            if latest and latest.get("ok") is False:
                current_failures.append(latest)
        if current_failures:
            latest = max(current_failures, key=lambda x: x.get("at") or datetime.min)
            data = {**data, "last_failure": {k: latest.get(k) for k in ("tenant", "kind", "error", "at")}}
        else:
            data = {**data, "last_failure": None}
    for org in tenants:
        tenant = backup.tenant_key(org.get("org_id"))
        st = await live_db.backup_state.find_one({"_id": tenant}) or {}
        full_at, incr_at = st.get("last_full_at"), st.get("last_incr_at")
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        newest = max([x for x in (full_at, incr_at) if isinstance(x, datetime)], default=None)
        age = (current - newest.replace(tzinfo=None)).total_seconds() / 60 if newest else None
        rows.append({"tenant": tenant, "org_id": org.get("org_id"), "slug": org.get("slug"),
                     "last_full_at": full_at, "last_incr_at": incr_at, "age_minutes": round(age, 1) if age is not None else None,
                     "bytes_gz": int(st.get("last_bytes_gz", 0) or 0),
                     "status": "ok" if age is not None and age <= 36 * 60 else "warning" if age is not None else "never"})
    return {**data, "tenants": rows}

async def write_probe_sample(live_db, probe_data=None) -> dict:
    """Persist a small monitoring sample; opening the UI never calls this function."""
    from datetime import datetime, timezone
    probes = probe_data or await probe_connections(live_db)
    by = {p["id"]: p for p in probes.get("connections", [])}
    mirror = await live_db.backup_meta.find_one({"_id": "mirror_state"}) or {}
    last_ok = mirror.get("last_ok_at")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if isinstance(last_ok, datetime): lag_min = max(0, int((now - last_ok.replace(tzinfo=None)).total_seconds() / 60))
    else: lag_min = None
    b2 = await b2_summary(live_db)
    sizes = b2.get("totals", {})
    full_age = [r.get("age_minutes") for r in b2.get("tenants", []) if r.get("age_minutes") is not None]
    sample = {"at": now,
              "live_ping_ms": by.get("live_mongo", {}).get("latency_ms"),
              "second_ping_ms": by.get("second_mirror", {}).get("latency_ms"),
              "postgres_ping_ms": by.get("postgres_history", {}).get("latency_ms"),
              "b2_ping_ms": by.get("b2_backup_bucket", {}).get("latency_ms"),
              "mirror_lag_min": lag_min,
              "b2_total_bytes": sum(int(sizes.get(k, 0) or 0) for k in ("routine_bytes", "safety_bytes", "milestone_bytes")),
              "newest_backup_age_min": min(full_age) if full_age else None,
              "live_status": by.get("live_mongo", {}).get("status", "unconfigured"),
              "second_status": by.get("second_mirror", {}).get("status", "unconfigured"),
              "postgres_status": by.get("postgres_history", {}).get("status", "unconfigured"),
              "b2_status": by.get("b2_backup_bucket", {}).get("status", "unconfigured"),
              "nomination_status": by.get("b2_nomination_bucket", {}).get("status", "unconfigured"),
              "status": probes.get("overall", "unknown")}
    await live_db.backup_metrics.insert_one(sample)
    await live_db.backup_metrics.create_index("at", expireAfterSeconds=30 * 86400, name="backup_metrics_ttl")
    return sample
