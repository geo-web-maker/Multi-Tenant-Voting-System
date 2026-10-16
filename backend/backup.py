"""
Per-tenant backups to Backblaze B2 (Task 4).

Atlas M0 has no snapshots, so every copy comes from this module: application-side
reads through the Motor driver with an `org_id` filter (no privileged commands, no
mongodump), compressed, checksummed, and written to a SEPARATE B2 bucket with Object
Lock set per object.

Key layout (one prefix per retention class, so B2 lifecycle rules can target a class):

    routine/<tenant>/full-<ts>/<collection>.jsonl.gz + manifest.json   14d governance lock
    routine/<tenant>/incr-<ts>/<collection>.jsonl.gz + manifest.json   14d governance lock
    routine/<tenant>/assets/<sha1(url)><ext>                           14d governance lock
    safety/<tenant>/<label>-<ts>/...                                   90d governance lock (pre-reset / pre-wipe)
    milestone/<tenant>/<name>-<ts>/...  (+ assets/)                    compliance lock >= 1y after results release
    _reports/<ts>-size-report.json                                     14d governance lock

<tenant> is the org_id, or "default" for the legacy single-tenant data (org_id None).
The manifest is uploaded LAST, so a backup without a manifest is incomplete and ignored.
"""
import asyncio
import base64
import contextlib
import gzip
import hashlib
import json
import logging
import os
import tempfile
import zlib
from datetime import datetime, timedelta
from urllib.parse import urlparse

import boto3
import httpx
from botocore.config import Config
from bson import ObjectId, json_util, encode as bson_encode

from backup_runtime import env_float, env_int, keep_awake

logger = logging.getLogger("BallotBoxBackup")

FORMAT_VERSION = 1

# Small collections: always dumped in full.
FULL_COLLECTIONS = [
    "voters", "applications", "candidates", "settings", "positions",
    "student_changes", "exception_grants", "audit_checkpoints",
    # Previously missed in the backup coverage audit (BK-1).
    "panel_members", "contact_changes", "candidate_lists", "candidate_tokens",
    "certificates", "nomination_uploads", "sms_usage", "sms_campaigns",
    # Round/tie metadata must survive routine, safety and milestone restores.
    "rounds", "ties", "shared_contact_acks",
    # Soft-deleted applications (superadmin archive; restorable).
    "deleted_applications",
]
# Append-only collections: incremental on the 15-minute job.
APPEND_ONLY = ["vote_events", "audit_log", "student_edit_audit", "roster_ledger"]

SECURITY_ONLY = {
    "otps", "admin_otps", "otp_attempts", "login_attempts", "revoked_tokens",
    "ip_rate_limits", "otp_send_state", "otp_guess_state", "ip_send_stats",
}
# One authoritative list for intentional omissions. A restore coverage audit compares live
# collection names against the backed-up collections and these explicit exclusions.
EXCLUDED_BY_DESIGN = {
    "voter_import_previews": "Temporary import preview; deleted after import.",
    "demo_inbox": "Demo-mode inbox; wiped by demo reset.",
    "sms_campaign_recipients": "Per-message send queue (expires after 90 days); the campaign summary is backed up.",
    "app_meta": "Application startup metadata and index schema marker are rebuilt.",
    "backup_jobs": "Operational job history is rebuilt by subsequent runs.",
    "backup_metrics": "Monitoring samples are rebuilt by subsequent probes.",
    **{name: "Short-lived authentication or rate-limit state; users re-authenticate after cutover."
       for name in SECURITY_ONLY},
}
# sms_usage is keyed by org_key rather than org_id. Never weaken the ownership filter to include
# ownerless rows: those must be resolved in the legacy-data panel before the first full backup.
FILTER_OVERRIDES = {"sms_usage": lambda org_id: {"org_key": org_id or "default"}}

# Fields holding Cloudinary URLs (photos, receipts, branding files).
ASSET_FIELDS = {
    "applications": ("image_url", "payment_proof_url"),
    "deleted_applications": ("image_url", "payment_proof_url"),
    "candidates": ("image_url",),
    "student_changes": ("payment_proof_url",),
    "settings": ("logo_url", "university_logo_url"),
}

ROUTINE_LOCK_DAYS = 14
SAFETY_LOCK_DAYS = 90
MILESTONE_LOCK_DAYS = 400          # >= 1 year after results release, plus margin
MILESTONE_UNKNOWN_RELEASE_DAYS = 180   # assumed gap until release when it is not known yet
ASSET_REFRESH_DAYS = 10            # re-copy a routine object before its lock/lifecycle expires
FULL_REFRESH_DAYS = 10             # an unchanged idle tenant still gets a fresh copy this often
INCR_OVERLAP_SECONDS = 120         # ObjectIds are only roughly time-ordered across processes
# The daily full also carries the complete append-only collections, so restore never
# depends on incrementals that the lifecycle rule has already deleted.
FULL_INCLUDES_APPEND_ONLY = True
MAX_ASSET_BYTES = 25 * 1024 * 1024
# --- Render free tier (about 0.1 CPU, 512 MB RAM): every value is overridable from the environment ---
BATCH_SIZE = env_int("BACKUP_BATCH_SIZE", 500)          # documents per Mongo round trip
CPU_SLICE = env_int("BACKUP_CPU_SLICE", 100)            # documents serialised/compressed before yielding the loop
BATCH_PAUSE_S = env_float("BACKUP_BATCH_PAUSE_S", 0.05)  # stay gentle on M0 throughput limits and let voters through
SPOOL_MEM_BYTES = env_int("BACKUP_SPOOL_MEM_BYTES", 1024 * 1024)   # larger exports spill to disk, not RAM
GZIP_LEVEL = env_int("BACKUP_GZIP_LEVEL", 1)            # level 1 is ~4x cheaper than 6 for ~10% larger JSONL
MIRROR_TIMEOUT_S = env_float("BACKUP_MIRROR_TIMEOUT_S", 300)
MIRROR_INCR_MIN_GAP_MIN = env_float("BACKUP_MIRROR_INCR_MIN_GAP_MIN", 30)
PROBE_INCR_MIN_GAP_MIN = env_float("BACKUP_PROBE_INCR_MIN_GAP_MIN", 30)
FREE_TIER_BYTES = 10 * 10 ** 9
M0_CAP_BYTES = 512 * 1024 * 1024


class BackupError(Exception):
    pass


# --------------------------------------------------------------------------
# Configuration / clients
# --------------------------------------------------------------------------
def load_config() -> dict:
    cfg = {
        "endpoint": os.getenv("B2_BACKUP_ENDPOINT") or os.getenv("B2_ENDPOINT"),
        "key_id": os.getenv("B2_BACKUP_KEY_ID"),
        "app_key": os.getenv("B2_BACKUP_APPLICATION_KEY"),
        "bucket": os.getenv("B2_BACKUP_BUCKET_NAME"),
        "cloud_name": os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    }
    missing = [k for k in ("endpoint", "key_id", "app_key", "bucket") if not cfg[k]]
    if missing:
        raise BackupError(
            "Backup is not configured: set B2_BACKUP_KEY_ID, B2_BACKUP_APPLICATION_KEY, "
            "B2_BACKUP_BUCKET_NAME (and B2_BACKUP_ENDPOINT) for the SEPARATE backup bucket. "
            f"Missing: {missing}"
        )
    return cfg


_CLIENT_CACHE: dict = {}


def make_client(cfg: dict):
    """boto3 clients are thread-safe and costly to build (tens of ms of CPU, several MB): build one per credential set."""
    key = (cfg.get("endpoint"), cfg.get("key_id"), cfg.get("app_key"))
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = _CLIENT_CACHE[key] = _build_client(cfg)
    return client


def _build_client(cfg: dict):
    kwargs = dict(
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["app_key"],
    )
    try:
        # Newer boto3 adds CRC checksum trailers B2 may not accept; ask only when required.
        kwargs["config"] = Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 5, "mode": "standard"},
            connect_timeout=10, read_timeout=60, max_pool_connections=4,
        )
    except TypeError:
        kwargs["config"] = Config(retries={"max_attempts": 5, "mode": "standard"},
                                  connect_timeout=10, read_timeout=60, max_pool_connections=4)
    return boto3.client("s3", **kwargs)


def tenant_key(org_id) -> str:
    return org_id or "default"


def _now() -> datetime:
    return datetime.utcnow()


def _ts(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------
# Alerts (email to superadmin) and run log
# --------------------------------------------------------------------------
# The sender itself now lives in alerts.py so every critical system in the app
# (not just backups) can use the same Resend-based emailer, with per-subject
# cooldown so a flapping failure doesn't flood the inbox. `send_alert` is kept
# as a name here, thin-wrapped at "critical" level, so every existing call
# site in this file (and in backup_routes.py / main.py) keeps working
# unchanged.
from alerts import alert_critical as send_alert  # noqa: E402  (kept after module docstring/constants)


async def _log_run(db, tenant: str, kind: str, ok: bool, size: int = 0,
                   detail: dict | None = None, error: str | None = None) -> None:
    doc = {"tenant": tenant, "kind": kind, "ok": ok, "bytes": size,
           "detail": detail or {}, "error": error, "at": _now()}
    logger.info("backup run tenant=%s kind=%s ok=%s bytes=%s err=%s", tenant, kind, ok, size, error)
    await db.backup_runs.insert_one(doc)


def _is_cap_error(exc: Exception) -> bool:
    return "cap_exceeded" in str(exc).lower() or "cap exceeded" in str(exc).lower()


# --------------------------------------------------------------------------
# B2 primitives (boto3 is synchronous -> thread)
# --------------------------------------------------------------------------
def _lock_args(cls: str, retain_until: datetime) -> dict:
    mode = "COMPLIANCE" if cls == "milestone" else "GOVERNANCE"
    return {"ObjectLockMode": mode, "ObjectLockRetainUntilDate": retain_until}


def _retain_until(cls: str, release_hint: datetime | None = None) -> datetime:
    now = _now()
    if cls == "routine":
        return now + timedelta(days=ROUTINE_LOCK_DAYS)
    if cls == "safety":
        return now + timedelta(days=SAFETY_LOCK_DAYS)
    base = max(now, release_hint) if release_hint else now + timedelta(days=MILESTONE_UNKNOWN_RELEASE_DAYS)
    return base + timedelta(days=MILESTONE_LOCK_DAYS)


def _md5_b64(body) -> str:
    """Object Lock uploads must carry Content-MD5 (S3 rule; harmless on B2)."""
    h = hashlib.md5(usedforsecurity=False)
    if isinstance(body, (bytes, bytearray)):
        h.update(body)
    else:
        pos = body.tell()
        body.seek(0)
        for chunk in iter(lambda: body.read(1024 * 1024), b""):
            h.update(chunk)
        body.seek(pos)
    return base64.b64encode(h.digest()).decode()


async def _put(client, cfg, key: str, body, cls: str, retain_until: datetime,
               content_type="application/octet-stream", metadata: dict | None = None) -> None:
    def go():
        client.put_object(
            Bucket=cfg["bucket"], Key=key, Body=body, ContentType=content_type,
            ContentMD5=_md5_b64(body),
            ServerSideEncryption="AES256", Metadata=metadata or {},
            **_lock_args(cls, retain_until),
        )
    await asyncio.to_thread(go)


async def _list(client, cfg, prefix: str, delimiter: str | None = None) -> list[dict]:
    def go():
        out, token = [], None
        while True:
            kw = {"Bucket": cfg["bucket"], "Prefix": prefix}
            if delimiter:
                kw["Delimiter"] = delimiter
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            out.extend(resp.get("Contents", []))
            if delimiter:
                out.extend({"Prefix": p["Prefix"]} for p in resp.get("CommonPrefixes", []))
            if not resp.get("IsTruncated"):
                return out
            token = resp["NextContinuationToken"]
    return await asyncio.to_thread(go)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def _dump_line(doc: dict) -> bytes:
    return (json_util.dumps(doc, json_options=json_util.CANONICAL_JSON_OPTIONS) + "\n").encode()


def _sha256_file(fh) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


async def export_collection(db, name: str, query: dict, on_doc=None) -> dict:
    """Stream one filtered collection into a gzip spool. Deterministic (sorted by _id,
    gzip mtime 0) so an unchanged collection hashes identically run to run.

    Render-free tuning: the spool only stays in RAM up to SPOOL_MEM_BYTES (then it is a temp file), documents are
    serialised CPU_SLICE at a time and compressed/hashed in a worker thread (zlib and hashlib release the GIL), and
    the loop is handed back between slices, so a backup cannot freeze request handling for seconds on 0.1 CPU."""
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEM_BYTES)
    raw = hashlib.sha256()
    raw_bytes = count = 0
    first = last = None
    pending: list[bytes] = []
    gz = gzip.GzipFile(fileobj=spool, mode="wb", mtime=0, compresslevel=GZIP_LEVEL)

    def write_slice(chunk: bytes) -> None:
        raw.update(chunk)
        gz.write(chunk)

    async def flush() -> None:
        nonlocal pending
        if pending:
            chunk, pending = b"".join(pending), []
            await asyncio.to_thread(write_slice, chunk)
            await asyncio.sleep(BATCH_PAUSE_S)

    try:
        async for doc in db[name].find(query).sort("_id", 1).batch_size(BATCH_SIZE):
            line = _dump_line(doc)
            pending.append(line)
            raw_bytes += len(line)
            count += 1
            first = first or doc["_id"]
            last = doc["_id"]
            if on_doc:
                on_doc(name, doc)
            if len(pending) >= CPU_SLICE:
                await flush()
        await flush()
        await asyncio.to_thread(gz.close)       # writes the gzip trailer into the spool (does not close it)
        gz_bytes = spool.tell()
        spool.seek(0)
        gz_sha = await asyncio.to_thread(_sha256_file, spool)
        spool.seek(0)
    except BaseException:
        with contextlib.suppress(Exception):
            gz.close()
        spool.close()
        raise
    return {
        "spool": spool, "count": count, "raw_sha256": raw.hexdigest(),
        "gz_sha256": gz_sha, "raw_bytes": raw_bytes, "gz_bytes": gz_bytes,
        "first_id": str(first) if first else None, "last_id": str(last) if last else None,
    }


def _org_filter(org_id) -> dict:
    return {"org_id": org_id}   # org_id None matches legacy docs with null/missing org_id


def collection_filter(name: str, org_id) -> dict:
    """Per-collection tenant filter; sms_usage intentionally keys on org_key."""
    override = FILTER_OVERRIDES.get(name)
    return override(org_id) if override else _org_filter(org_id)


def coverage_audit_names(live_names) -> list[str]:
    """Return collection names not backed up and not explicitly excluded by design."""
    covered = set(FULL_COLLECTIONS) | set(APPEND_ONLY) | set(EXCLUDED_BY_DESIGN) | {"organizations", "platform_settings"}
    return sorted(n for n in set(live_names) if not n.startswith("system.") and n not in covered)


def _is_cloudinary_url(url: str, cloud_name: str) -> bool:
    """Only Cloudinary https URLs are ever fetched. URLs come from user-submitted
    fields (public /apply), so anything else would be a server-side request forgery."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme != "https" or p.hostname != "res.cloudinary.com":
        return False
    return (not cloud_name) or p.path.startswith(f"/{cloud_name}/")


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------
def _asset_key(prefix: str, url: str) -> str:
    ext = os.path.splitext(urlparse(url).path)[1][:8]
    return f"{prefix}/assets/{hashlib.sha1(url.encode()).hexdigest()}{ext}"


async def _ensure_routine_asset(client, cfg, tenant: str, url: str, existing: dict) -> dict:
    """Copy one Cloudinary asset to routine/<tenant>/assets/ unless a fresh copy exists.
    Cloudinary URLs embed a version, so a replaced file has a new URL -> new key."""
    key = _asset_key(f"routine/{tenant}", url)
    entry = existing.get(key)
    if entry and (_now() - entry["LastModified"].replace(tzinfo=None)).days < ASSET_REFRESH_DAYS:
        head = await asyncio.to_thread(client.head_object, Bucket=cfg["bucket"], Key=key)
        meta = head.get("Metadata", {})
        return {"url": url, "key": key, "sha256": meta.get("sha256"), "bytes": entry["Size"], "copied": False}
    # Stream into a spool (RAM only up to SPOOL_MEM_BYTES) instead of a bytearray + bytes() copy of up to 25 MB.
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEM_BYTES)
    try:
        h, size = hashlib.sha256(), 0
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
            async with http.stream("GET", url) as r:
                if r.status_code != 200:
                    raise BackupError(f"asset fetch {r.status_code}")
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_ASSET_BYTES:
                        raise BackupError("asset larger than 25 MB")
                    h.update(chunk)
                    spool.write(chunk)
                ctype = r.headers.get("content-type", "application/octet-stream")
        spool.seek(0)
        await _put(client, cfg, key, spool, "routine", _retain_until("routine"),
                   ctype, {"source-url": url[:1000], "sha256": h.hexdigest()})
    finally:
        spool.close()
    return {"url": url, "key": key, "sha256": h.hexdigest(), "bytes": size, "copied": True}


async def _copy_assets(client, cfg, tenant: str, urls: set, cls: str, dest_prefix: str,
                       retain_until: datetime) -> tuple[list, list]:
    existing = {o["Key"]: o for o in await _list(client, cfg, f"routine/{tenant}/assets/")}
    done, failed = [], []
    for url in sorted(urls):
        if not _is_cloudinary_url(url, cfg["cloud_name"]):
            failed.append({"url": url, "error": "not a Cloudinary URL of this account; skipped"})
            continue
        try:
            item = await _ensure_routine_asset(client, cfg, tenant, url, existing)
            if cls == "milestone":
                dest = _asset_key(dest_prefix, url)
                await asyncio.to_thread(
                    client.copy_object, Bucket=cfg["bucket"], Key=dest,
                    CopySource={"Bucket": cfg["bucket"], "Key": item["key"]},
                    ServerSideEncryption="AES256", MetadataDirective="COPY")
                await asyncio.to_thread(
                    client.put_object_retention, Bucket=cfg["bucket"], Key=dest,
                    Retention={"Mode": "COMPLIANCE", "RetainUntilDate": retain_until})
                item = {**item, "key": dest}
            done.append(item)
        except (BackupError, httpx.HTTPError) as e:
            failed.append({"url": url, "error": str(e)})
    return done, failed


# --------------------------------------------------------------------------
# One backup of one tenant
# --------------------------------------------------------------------------
async def _upload_export(client, cfg, key: str, ex: dict, cls: str, until: datetime):
    await _put(client, cfg, key, ex["spool"], cls, until, "application/gzip")


def _manifest_entry(name: str, ex: dict, incremental: bool, since: str | None = None) -> dict:
    return {
        "file": f"{name}.jsonl.gz", "count": ex["count"], "incremental": incremental,
        "since_id": since, "first_id": ex["first_id"], "last_id": ex["last_id"],
        "sha256_uncompressed": ex["raw_sha256"], "sha256_gz": ex["gz_sha256"],
        "bytes_uncompressed": ex["raw_bytes"], "bytes_gz": ex["gz_bytes"],
    }


async def backup_tenant(db, client, cfg, org: dict, kind: str, *, label: str | None = None,
                        release_hint: datetime | None = None, force: bool = False) -> dict:
    """
    kind: "full" (routine), "incr" (routine), "milestone" (label=open/close/certified),
          "safety" (label=reset-election / wipe-script).
    Returns {"status": "uploaded"|"skipped", ...}. Raises on failure.
    """
    org_id, tenant = org["org_id"], tenant_key(org["org_id"])
    cls = {"full": "routine", "incr": "routine", "milestone": "milestone", "safety": "safety"}[kind]
    state = await db.backup_state.find_one({"_id": tenant}) or {}
    flt = _org_filter(org_id)
    ts = _ts()
    until = _retain_until(cls, release_hint)
    dirname = f"{label or kind}-{ts}" if kind in ("milestone", "safety") else f"{kind}-{ts}"
    prefix = f"{cls}/{tenant}/{dirname}"
    files: dict[str, dict] = {}
    exports: list[tuple[str, dict]] = []
    urls: set = set()

    def collect(name, doc):
        for f in ASSET_FIELDS.get(name, ()):
            v = doc.get(f)
            if isinstance(v, str) and v.startswith("http"):
                urls.add(v)

    try:
        if kind == "incr":
            wm = state.get("watermarks", {})
            if not state.get("last_full_at"):
                return await backup_tenant(db, client, cfg, org, "full")   # needs a baseline first
            new_wm, incr_any = dict(wm), False
            for name in APPEND_ONLY:
                last = ObjectId(wm[name]) if wm.get(name) else None
                q = collection_filter(name, org_id)
                if last:
                    q["_id"] = {"$gt": last}
                if not await db[name].find_one(q, {"_id": 1}):
                    continue
                if last:
                    back = ObjectId.from_datetime(last.generation_time.replace(tzinfo=None)
                                                  - timedelta(seconds=INCR_OVERLAP_SECONDS))
                    q["_id"] = {"$gte": back}
                ex = await export_collection(db, name, q)
                exports.append((name, ex))
                files[name] = _manifest_entry(name, ex, True, wm.get(name))
                new_wm[name] = ex["last_id"]
                incr_any = True
            if not incr_any:
                return {"status": "skipped", "reason": "no new vote/audit records", "tenant": tenant}
        else:
            names = list(FULL_COLLECTIONS) + (
                APPEND_ONLY if (FULL_INCLUDES_APPEND_ONLY or kind != "full") else [])
            for name in names:
                ex = await export_collection(db, name, collection_filter(name, org_id), collect)
                exports.append((name, ex))
                files[name] = _manifest_entry(name, ex, False)
            if org_id:
                try:
                    org_oid = ObjectId(org_id)
                except Exception as e:  # malformed org id would be a data bug worth surfacing
                    raise BackupError(f"organization id {org_id!r} is not an ObjectId") from e
                ex = await export_collection(db, "organizations", {"_id": org_oid})
                exports.append(("organizations", ex))
                files["organizations"] = _manifest_entry("organizations", ex, False)
            hashes = {n: e["raw_sha256"] for n, e in exports}
            if kind == "full" and not force and state.get("last_full_hashes") == hashes:
                age = (_now() - state["last_full_at"]).days if state.get("last_full_at") else 999
                if age < FULL_REFRESH_DAYS:
                    return {"status": "skipped", "reason": "unchanged since last backup", "tenant": tenant}

        assets, asset_fail = [], []
        if kind in ("full", "milestone") and urls and not (await _hold_assets(db)):
            assets, asset_fail = await _copy_assets(client, cfg, tenant, urls, cls, prefix, until)

        for name, ex in exports:
            await _upload_export(client, cfg, f"{prefix}/{name}.jsonl.gz", ex, cls, until)
        manifest = {
            "format_version": FORMAT_VERSION, "kind": kind, "label": label,
            "tenant": tenant, "org_id": org_id, "org_slug": org.get("slug"),
            "created_at": _now().isoformat() + "Z", "retain_until": until.isoformat() + "Z",
            "lock_class": cls, "collections": files,
            "assets": assets, "asset_failures": asset_fail,
            "asset_bytes": sum(a["bytes"] for a in assets),
        }
        body = json.dumps(manifest, indent=2).encode()
        await _put(client, cfg, f"{prefix}/manifest.json", body, cls, until, "application/json")
    finally:
        for _, ex in exports:
            ex["spool"].close()

    size = sum(f["bytes_gz"] for f in files.values())
    upd = {"last_backup_at": _now()}
    if kind == "incr":
        upd["watermarks"] = {**state.get("watermarks", {}), **new_wm}
        upd["last_incr_at"] = _now()
    elif kind == "full":
        upd.update(last_full_at=_now(), last_full_hashes=hashes)
        wm = dict(state.get("watermarks", {}))
        for n in APPEND_ONLY:
            if files.get(n, {}).get("last_id"):
                wm[n] = files[n]["last_id"]
        upd["watermarks"] = wm
    await db.backup_state.update_one({"_id": tenant}, {"$set": upd}, upsert=True)
    return {"status": "uploaded", "tenant": tenant, "prefix": prefix, "bytes_gz": size,
            "asset_bytes": manifest["asset_bytes"], "asset_failures": asset_fail,
            "counts": {n: f["count"] for n, f in files.items()}}


async def backup_global_settings(db, client, cfg, *, force: bool = False) -> dict:
    """Daily locked snapshot of global platform_settings under routine/_global/."""
    ts = _ts()
    prefix = f"routine/_global/full-{ts}"
    ex = await export_collection(db, "platform_settings", {})
    try:
        entry = _manifest_entry("platform_settings", ex, False)
        await _upload_export(client, cfg, f"{prefix}/platform_settings.jsonl.gz", ex,
                             "routine", _retain_until("routine"))
        manifest = {
            "format_version": FORMAT_VERSION, "kind": "global", "label": None,
            "tenant": "_global", "org_id": None, "org_slug": None,
            "created_at": _now().isoformat() + "Z",
            "retain_until": _retain_until("routine").isoformat() + "Z",
            "lock_class": "routine", "collections": {"platform_settings": entry},
            "assets": [], "asset_failures": [], "asset_bytes": 0,
        }
        await _put(client, cfg, f"{prefix}/manifest.json", json.dumps(manifest, indent=2).encode(),
                   "routine", _retain_until("routine"), "application/json")
        result = {"status": "uploaded", "tenant": "_global", "kind": "global", "prefix": prefix,
                  "bytes_gz": ex["gz_bytes"], "counts": {"platform_settings": ex["count"]}}
        await db.backup_runs.insert_one({"tenant": "_global", "kind": "global", "ok": True,
                                         "bytes": ex["gz_bytes"], "detail": result, "error": None, "at": _now()})
        return result
    finally:
        ex["spool"].close()


async def ownerless_preflight(db) -> dict:
    """Count missing org_id values in all newly covered tenant collections; does not mutate data.
    Seven collection scans on a shared M0: always fresh here (backups gate on it); dashboards read it through
    backup_runtime.cached instead."""
    names = sorted({"panel_members", "contact_changes", "roster_ledger", "candidate_lists",
                    "candidate_tokens", "certificates", "nomination_uploads"})
    out = {}
    for name in names:
        out[name] = await db[name].count_documents({"$or": [{"org_id": {"$exists": False}}, {"org_id": None}]})
    return {"counts": out, "safe": not any(out.values())}


async def coverage_audit(db) -> list[str]:
    """Find live collections with tenant data that the backup engine neither exports nor excludes."""
    uncovered = []
    for name in coverage_audit_names(await db.list_collection_names()):
        if await db[name].find_one({"org_id": {"$exists": True}}, {"_id": 1}):
            uncovered.append(name)
    return uncovered


async def _hold_assets(db) -> bool:
    meta = await db.backup_meta.find_one({"_id": "size_report"}) or {}
    return bool(meta.get("hold_assets")) and not meta.get("assets_approved")


# --------------------------------------------------------------------------
# Tenants, status, scheduling
# --------------------------------------------------------------------------
async def list_tenants(db) -> list[dict]:
    tenants = [{"org_id": str(o["_id"]), "slug": o.get("slug")} async for o in db.organizations.find({})]
    has_legacy = (await db.voters.find_one({"org_id": None}, {"_id": 1})
                  or await db.settings.find_one({"org_id": None}, {"_id": 1})
                  or await db.sms_usage.find_one({"org_key": "default"}, {"_id": 1}))
    if has_legacy and not any(t.get("org_id") is None for t in tenants):
        tenants.append({"org_id": None, "slug": None})
    return tenants


async def _election_flags(db, org_id) -> dict:
    cfg = await db.settings.find_one({"name": "election_config", "org_id": org_id}) or {}
    # is_open defaults to True when never configured — same rule as /admin/toggle-election.
    return {"is_open": bool(cfg.get("is_open", True)), "is_certified": bool(cfg.get("is_certified", False))}


def _active(flags: dict) -> bool:
    return flags["is_open"] and not flags["is_certified"]


async def _results_release_hint(db, org_id) -> datetime | None:
    doc = await db.settings.find_one({"name": "election_phases", "org_id": org_id}) or {}
    end = ((doc.get("phases") or {}).get("results") or {}).get("end")
    return end if isinstance(end, datetime) else None


async def extend_milestone_locks(client, cfg, tenant: str, until: datetime) -> int:
    """Compliance retention can only be extended, never shortened. Called on
    certification (= results release) so earlier milestone snapshots also last
    >= 1 year past release."""
    n = 0
    for obj in await _list(client, cfg, f"milestone/{tenant}/"):
        await asyncio.to_thread(
            client.put_object_retention, Bucket=cfg["bucket"], Key=obj["Key"],
            Retention={"Mode": "COMPLIANCE", "RetainUntilDate": until})
        n += 1
    return n


async def _detect_milestones(db, client, cfg, org: dict, results: list) -> None:
    """Milestones are detected from state transitions on each scheduler call, so no
    election route has to be touched (open -> 'open', closed -> 'close', certified)."""
    tenant = tenant_key(org["org_id"])
    flags = await _election_flags(db, org["org_id"])
    prev = (await db.backup_state.find_one({"_id": tenant}) or {}).get("flags")
    todo = []
    if prev:
        if not prev["is_open"] and flags["is_open"]:
            todo.append("open")
        if prev["is_open"] and not flags["is_open"]:
            todo.append("close")
        if not prev["is_certified"] and flags["is_certified"]:
            todo.append("certified")
    for label in todo:
        hint = _now() if label == "certified" else await _results_release_hint(db, org["org_id"])
        try:
            res = await backup_tenant(db, client, cfg, org, "milestone", label=label, release_hint=hint)
            if label == "certified":
                res["locks_extended"] = await extend_milestone_locks(
                    client, cfg, tenant, _now() + timedelta(days=MILESTONE_LOCK_DAYS))
            await _log_run(db, tenant, f"milestone:{label}", True, res["bytes_gz"], res)
            results.append(res)
        except Exception as e:  # noqa: BLE001 — recorded, alerted, re-raised via results
            await _fail(db, tenant, f"milestone:{label}", e, results)
            return   # keep the old flags so the next call retries this milestone
    await db.backup_state.update_one({"_id": tenant}, {"$set": {"flags": flags}}, upsert=True)


async def _fail(db, tenant, kind, exc, results):
    cap = _is_cap_error(exc)
    await _log_run(db, tenant, kind, False, error=str(exc)[:500])
    await send_alert(
        f"[BallotBox] BACKUP {'SPENDING CAP HIT' if cap else 'FAILED'}: {tenant} ({kind})",
        f"Backup '{kind}' for tenant '{tenant}' failed at {_now().isoformat()}Z.\n\n"
        f"Error: {exc}\n\n"
        + ("The Backblaze B2 spending cap has been reached; uploads are stopped until it is raised.\n"
           if cap else "") +
        "Until this is fixed the latest data is NOT protected by a new backup.")
    results.append({"status": "failed", "tenant": tenant, "kind": kind, "error": str(exc)[:500]})


_run_lock = asyncio.Lock()


async def run_scheduled(db, mode: str) -> dict:
    """mode: 'incr' (every 15 min) | 'full' (daily) | 'weekly' (idle tenants).
    One tenant at a time, never concurrently with another run."""
    if mode not in ("incr", "full", "weekly"):
        raise BackupError("mode must be incr, full or weekly")
    if _run_lock.locked():
        return {"status": "busy", "results": []}
    async with _run_lock, keep_awake():   # keep_awake: a sleeping Render instance would kill the run mid-upload
        cfg = load_config()
        client = make_client(cfg)
        results: list = []
        preflight = await ownerless_preflight(db)
        if not preflight.get("safe"):
            details = {k: v for k, v in preflight.get("counts", {}).items() if v}
            await send_alert("[BallotBox] Backup ownerless-data preflight failed",
                             "Newly covered collections have documents without org_id. Assign or remove them before cutover: " + json.dumps(details))
            results.append({"status": "failed", "tenant": "_preflight", "kind": "coverage_preflight",
                            "error": "Ownerless records must be assigned or removed before cutover.", "counts": details})
        await _missed_run_check(db, mode)
        report = await first_run_report(db, client, cfg) if preflight.get("safe") else {
            "status": "blocked", "reason": "Ownerless legacy rows must be resolved before tenant backups run."}
        for org in (await list_tenants(db) if preflight.get("safe") else []):
            tenant = tenant_key(org["org_id"])
            await _detect_milestones(db, client, cfg, org, results)
            flags = await _election_flags(db, org["org_id"])
            active = _active(flags)
            if mode in ("incr", "full") and not active:
                continue
            if mode == "weekly" and active:
                continue
            kind = "incr" if mode == "incr" else "full"
            try:
                res = await backup_tenant(db, client, cfg, org, kind)
                await _log_run(db, tenant, kind, True, res.get("bytes_gz", 0), res)
                if res.get("asset_failures"):
                    await send_alert(f"[BallotBox] Backup: {len(res['asset_failures'])} asset(s) not copied ({tenant})",
                                     json.dumps(res["asset_failures"][:20], indent=2))
                results.append(res)
            except Exception as e:  # noqa: BLE001 — recorded, alerted, surfaced in the response
                await _fail(db, tenant, kind, e, results)
        await db.backup_meta.update_one({"_id": f"last_{mode}"}, {"$set": {"at": _now()}}, upsert=True)
        if mode == "full":
            try:
                results.append(await backup_global_settings(db, client, cfg))
            except Exception as e:  # global settings are important; surface as a normal failed run
                await _fail(db, "_global", "global", e, results)
        mirror_res = None
        monitor_cfg = await _monitor_values(db)
        try:
            import backup_mirror
            # 15-minute incrementals copy new votes to B2 every run; the mirror (a full read of every small
            # collection) only needs to stay inside its lag alert window, so on the free tier it runs less often.
            gap = min(MIRROR_INCR_MIN_GAP_MIN, max(5.0, float(monitor_cfg.get("mirror_lag_active_minutes", 60)) / 2))
            if mode == "incr" and await _recent(db.backup_meta, {"_id": "mirror_state"}, "last_ok_at", gap):
                mirror_res = {"status": "skipped", "reason": f"mirror synced within the last {gap:g} minutes"}
            else:
                mirror_res = await asyncio.wait_for(
                    backup_mirror.sync_mirror(db, "full" if mode in ("full", "weekly") else "incr"),
                    timeout=MIRROR_TIMEOUT_S)
        except Exception as e:  # mirror must never fail or delay a completed backup
            logger.error("mirror sync skipped: %s", e)
            mirror_res = {"status": "failed", "error": str(e)[:300]}
        # Sample after the mirror attempt so mirror lag/health reflects this run's outcome.
        try:
            import backup_probes
            gap = min(PROBE_INCR_MIN_GAP_MIN, 40.0)   # the "monitor samples stopped" alert fires after 45 minutes
            if mode == "incr" and await _recent(db.backup_metrics, {}, "at", gap, sort_desc=True):
                logger.info("monitoring sample skipped: newest sample is under %g minutes old", gap)
            else:
                probe_result = await backup_probes.probe_connections(db)
                await backup_probes.write_probe_sample(db, probe_result)
                from backup_admin_routes import emit_monitor_alerts
                await emit_monitor_alerts(db, probe_result)
        except Exception as e:  # monitoring must not fail an otherwise completed backup
            logger.error("backup monitoring sample skipped: %s", str(e)[:250])
        failed = [r for r in results if r.get("status") == "failed"]
        return {"status": "failed" if failed else "ok", "mode": mode,
                "first_run_report": report, "ownerless_preflight": preflight, "results": results, "mirror": mirror_res}


async def _monitor_values(db) -> dict:
    try:
        doc = await db.platform_settings.find_one({"name": "backup_monitor_config"}) or {}
    except Exception:  # noqa: BLE001 - config is advisory here; defaults are safe
        return {}
    return doc.get("values") or {}


async def _recent(coll, query: dict, field: str, gap_min: float, sort_desc: bool = False) -> bool:
    """True when the newest `field` timestamp is younger than 80% of gap_min (jitter must not skip a whole cycle)."""
    doc = await (coll.find_one(query, {field: 1}, sort=[(field, -1)]) if sort_desc else coll.find_one(query, {field: 1}))
    at = (doc or {}).get(field)
    return isinstance(at, datetime) and (_now() - at.replace(tzinfo=None)) < timedelta(minutes=gap_min * 0.8)


async def _missed_run_check(db, mode: str) -> None:
    """If the 15-minute job was silent for > 45 min while an election is open, say so."""
    if mode != "incr":
        return
    last = await db.backup_meta.find_one({"_id": "last_incr"})
    if not last or (_now() - last["at"]) < timedelta(minutes=45):
        return
    for org in await list_tenants(db):
        if _active(await _election_flags(db, org["org_id"])):
            await send_alert("[BallotBox] Backup scheduler was silent",
                             f"No 15-minute backup ran between {last['at'].isoformat()}Z and now while "
                             f"an election is open. Check the external scheduler.")
            return


# --------------------------------------------------------------------------
# Pre-reset / pre-wipe safety snapshot (4.4)
# --------------------------------------------------------------------------
async def snapshot_before_destructive(db, org_id, label: str) -> list[dict]:
    """Dump ONE tenant to B2 BEFORE deleting anything. Raises on any failure; callers must abort
    the destructive action when this raises. A missing org_id is refused (no all-tenants mode)."""
    if not org_id:
        raise BackupError("snapshot_before_destructive requires an org_id")
    cfg = load_config()
    client = make_client(cfg)
    known = await list_tenants(db)
    tenants = [
        next((t for t in known if t["org_id"] == org_id), {"org_id": org_id, "slug": None})]
    out = []
    for org in tenants:
        res = await backup_tenant(db, client, cfg, org, "safety", label=label)
        await _log_run(db, tenant_key(org["org_id"]), f"safety:{label}", True, res["bytes_gz"], res)
        out.append(res)
    return out


async def snapshot_legacy_data(db, label: str) -> dict:
    """Dump the ownerless (org_id missing/null) documents to B2 before they are deleted from the
    superadmin 'Legacy data' check. This is the ONLY place a null org is accepted, and it is
    read-only. Raises on any failure; the caller must abort the delete when this raises."""
    cfg = load_config()
    client = make_client(cfg)
    org = {"org_id": None, "slug": None}
    res = await backup_tenant(db, client, cfg, org, "safety", label=label)
    await _log_run(db, tenant_key(None), f"safety:{label}", True, res["bytes_gz"], res)
    return res


# --------------------------------------------------------------------------
# First-run size report (4.9)
# --------------------------------------------------------------------------
async def _measure(db, name: str, query: dict, urls: set | None = None) -> dict:
    comp = zlib.compressobj(GZIP_LEVEL, zlib.DEFLATED, 31)
    raw = gz = count = 0
    n = 0
    async for doc in db[name].find(query).batch_size(BATCH_SIZE):
        line = _dump_line(doc)
        raw += len(line)
        gz += len(comp.compress(line))
        count += 1
        if urls is not None:
            for f in ASSET_FIELDS.get(name, ()):
                v = doc.get(f)
                if isinstance(v, str) and v.startswith("http"):
                    urls.add(v)
        n += 1
        if n % BATCH_SIZE == 0:
            await asyncio.sleep(BATCH_PAUSE_S)
    gz += len(comp.flush())
    return {"count": count, "raw_bytes": raw, "gz_bytes": gz}


async def _asset_sizes(urls: set, cloud_name: str) -> tuple[int, int]:
    total = unknown = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
        for url in sorted(urls):
            if not _is_cloudinary_url(url, cloud_name):
                unknown += 1
                continue
            try:
                r = await http.head(url)
                size = int(r.headers.get("content-length", 0))
            except (httpx.HTTPError, ValueError):
                size = 0
            total += size
            unknown += 0 if size else 1
    return total, unknown


def estimate_monthly_bytes(per_tenant: dict, asset_bytes: int) -> dict:
    """Worst case for the 4.2 schedule: every tenant open the whole month.
    15 daily fulls live at once (14-day lock + 1 day lifecycle lag), incrementals bounded by
    the append-only data once (+10% overlap), 3 milestones/tenant/year and 2 safety snapshots
    per tenant kept for 90 days. Milestone asset copies count again."""
    full = sum(t["full_gz"] for t in per_tenant.values())
    append = sum(t["append_only_gz"] for t in per_tenant.values())
    routine = full * 15 + append * 1.1 + asset_bytes * 1.1
    milestone = 3 * full + 3 * asset_bytes
    safety = 2 * full
    total = routine + milestone + safety
    return {"routine": int(routine), "milestone_per_election": int(milestone),
            "safety": int(safety), "total": int(total),
            "over_free_tier": total > FREE_TIER_BYTES}


async def first_run_report(db, client, cfg) -> dict | None:
    """Runs once, before the first upload. Measures, estimates, emails, and — if the
    estimate exceeds B2's free 10 GB — holds the asset copies until the owner decides."""
    if await db.backup_meta.find_one({"_id": "size_report"}):
        return None
    urls: set = set()
    per_tenant, db_raw, db_gz = {}, 0, 0
    for org in await list_tenants(db):
        flt, t = _org_filter(org["org_id"]), {"collections": {}}
        for name in FULL_COLLECTIONS + APPEND_ONLY:
            m = await _measure(db, name, collection_filter(name, org["org_id"]), urls)
            t["collections"][name] = m
        t["raw_bytes"] = sum(m["raw_bytes"] for m in t["collections"].values())
        t["full_gz"] = sum(m["gz_bytes"] for m in t["collections"].values())
        t["append_only_gz"] = sum(t["collections"][n]["gz_bytes"] for n in APPEND_ONLY)
        per_tenant[tenant_key(org["org_id"])] = t
        db_raw += t["raw_bytes"]
        db_gz += t["full_gz"]
    try:
        stats = await db.command("dbStats")
        db_total = int(stats.get("dataSize", 0)) + int(stats.get("indexSize", 0))
    except Exception as e:  # noqa: BLE001 — informational only; a failure here is reported, not fatal
        db_total, stats = 0, {"error": str(e)}
    asset_bytes, asset_unknown = await _asset_sizes(urls, cfg["cloud_name"])
    est = estimate_monthly_bytes(per_tenant, asset_bytes)
    ratio = (db_gz / db_raw) if db_raw else 0.2
    m0_bound = estimate_monthly_bytes(
        {"m0_cap": {"full_gz": M0_CAP_BYTES * ratio, "append_only_gz": M0_CAP_BYTES * ratio}}, asset_bytes)
    report = {
        "generated_at": _now().isoformat() + "Z",
        "database_total_bytes": db_total,
        "database_export_bytes_uncompressed": db_raw,
        "database_export_bytes_compressed": db_gz,
        "per_tenant": {k: {"raw_bytes": v["raw_bytes"], "compressed_bytes": v["full_gz"],
                           "vote_events": v["collections"]["vote_events"]} for k, v in per_tenant.items()},
        "vote_events_bytes_total": sum(v["collections"]["vote_events"]["raw_bytes"] for v in per_tenant.values()),
        "cloudinary_assets": {"count": len(urls), "total_bytes": asset_bytes,
                              "unmeasured": asset_unknown},
        "estimate_worst_case_monthly": est,
        "estimate_if_database_fills_m0_512mb": m0_bound,
        "free_tier_bytes": FREE_TIER_BYTES,
    }
    if est["over_free_tier"] or m0_bound["over_free_tier"]:
        report["warning"] = "Projected B2 storage exceeds the free 10 GB."
        report["options"] = [
            "Full backups every 2 days instead of daily (about halves the routine share).",
            "Keep fewer routine copies: shorten the 14-day lock to 7 days.",
            "Skip Cloudinary asset copies in routine runs and copy them only in the 3 milestone snapshots.",
            "Accept the overage: about $6.95 per TB per month beyond 10 GB.",
        ]
        report["action"] = ("Database backups continue. Asset copying is ON HOLD until you approve "
                            "(POST /internal/backup/approve-assets) or choose another option.")
    await db.backup_meta.update_one(
        {"_id": "size_report"},
        {"$set": {"report": report, "hold_assets": bool(report.get("warning")), "at": _now()}},
        upsert=True)
    body = json.dumps(report, indent=2)
    try:
        await _put(client, cfg, f"_reports/{_ts()}-size-report.json", body.encode(), "routine",
                   _retain_until("routine"), "application/json")
    except Exception as e:  # noqa: BLE001 — the report is also in Mongo and the email; log the upload failure
        logger.error("size report upload failed: %s", e)
    await send_alert("[BallotBox] Backup size report" + (" - OVER FREE TIER" if report.get("warning") else ""), body)
    return report


# --------------------------------------------------------------------------
# Self-test (confirms the export method works against the connected database)
# --------------------------------------------------------------------------
async def selftest(db) -> dict:
    out = {"driver_reads": {}, "b2": {}}
    org = (await list_tenants(db) or [{"org_id": None}])[0]
    for name in FULL_COLLECTIONS + APPEND_ONLY:
        ex = await export_collection(db, name, collection_filter(name, org["org_id"]))
        out["driver_reads"][name] = {"count": ex["count"], "gz_bytes": ex["gz_bytes"]}
        ex["spool"].close()
    try:
        s = await db.command("dbStats")
        out["dbStats"] = {"dataSize": s.get("dataSize"), "storageSize": s.get("storageSize")}
    except Exception as e:  # noqa: BLE001 — report the M0 limitation instead of failing the test
        out["dbStats"] = {"error": str(e)}
    cfg = load_config()
    client = make_client(cfg)
    key = f"_selftest/{_ts()}.txt"
    await _put(client, cfg, key, b"ok", "routine", _retain_until("routine"))
    got = await asyncio.to_thread(client.get_object, Bucket=cfg["bucket"], Key=key)
    out["b2"] = {"put_with_governance_lock": True, "read_back": got["Body"].read() == b"ok",
                 "lock_mode": got.get("ObjectLockMode")}
    return out
