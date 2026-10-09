from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Response, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
import secrets
from collections import Counter
import asyncio
import motor.motor_asyncio
from pymongo.errors import DuplicateKeyError
from pymongo import UpdateOne
import os
import calendar
import struct
import copy
import csv
import io
import re
from urllib.parse import urlparse
import httpx
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from bson import ObjectId
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import bcrypt
import string
import cloudinary
import cloudinary.uploader
import pyotp
import hashlib
import json
import math
import time
import boto3
from fastapi.concurrency import run_in_threadpool
import backup
from backup_routes import build_router as build_backup_router
from alerts import alert_critical, alert_warning, send_alert
from name_utils import normalize_name
from roster_utils import (
    DEFAULT_MIN_GROUP, MIN_GROUP_RANGE, UNRECORDED_LABEL, apply_field_changes, attr_columns, attr_set_paths,
    check_id_shapes, diff_attrs, finish_groups, merge_voter_fields, normalize_attr_value, row_attrs, shape_warnings,
    suppress_small_groups,
)
from name_backfill import run_backfill as run_name_backfill
from tabular_import import (
    CORE_KEYS, TableError, describe_table, guess_header_row, read_table, suggest_mapping, validate_mapping,
)
from regno_audit import audit_reg_numbers
import otp_limits as ol
from tenant_db import scoped_db as _tenant_scoped_db, scoped_db_for as _tenant_scoped_db_for, cross_tenant
import analytics
import nomination_storage

from auth import (
    create_access_token,
    decode_access_token,
    get_bearer_token,
    require_admin,
    require_role,
    set_revocation_check,
    ADMIN_ROLES,
    JWT_EXPIRE_MINUTES,
    create_voter_token,
    verify_voter_token,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BallotBoxAPI")
# httpx logs full request URLs at INFO; EgoSMS takes username/password/number/message (the OTP)
# as query params, so this would write SMS credentials and live codes into the platform logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# --- CONFIGURATION & SECRETS ---
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
EGOSMS_USER = os.getenv("EGOSMS_USERNAME")
EGOSMS_PASS = os.getenv("EGOSMS_PASSWORD")
EGOSMS_SENDER_ID = os.getenv("ESMS_SENDER_ID", "SMS").strip()

# EgoSMS above is the primary OTP provider; MamboSMS is the automatic
# fallback if EgoSMS's send fails (bad response, non-2xx, timeout, exception).
# See send_sms() below for the actual primary/fallback dispatch — the two
# provider-specific functions never call each other directly.
MAMBOSMS_API_KEY = os.getenv("MAMBOSMS_API_KEY")
MAMBOSMS_SENDER_ID = os.getenv("MAMBOSMS_SENDER_ID", "MamboSMS").strip()
# "non_customised" (random number), "info" (INFO-prefixed), or "customised"
# (a real registered sender ID on MTN/Airtel/UTL) — see Mambo's docs. Defaults
# to non_customised since that's the only category that works without your
# sender_id being pre-approved by the networks.
MAMBOSMS_MESSAGE_CATEGORY = os.getenv("MAMBOSMS_MESSAGE_CATEGORY", "non_customised").strip()

SUPER_ADMIN_ID       = os.getenv("SUPER_ADMIN_ID")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD")
if not SUPER_ADMIN_ID or not SUPER_ADMIN_PASSWORD:
    raise RuntimeError(
        "SUPER_ADMIN_ID / SUPER_ADMIN_PASSWORD must be set via environment variables. "
        "No hardcoded fallback is used on purpose."
    )

# Optional: once SUPERADMIN_TOTP_SECRET is set in the environment, MFA
# becomes mandatory on the next login — no further code change needed.
# One secret can be enrolled into multiple authenticator apps/devices (phone
# AND laptop) — TOTP doesn't care how many places know the secret, it just
# checks the 6-digit code against what the secret + current time produce.
# Generate one via GET /superadmin/mfa/generate (works pre-MFA, as a one-time
# bootstrap step) and scan/paste the same secret into every device you want
# to use.
SUPERADMIN_TOTP_SECRET = os.getenv("SUPERADMIN_TOTP_SECRET")

# --- CLOUDINARY (signed, server-side uploads only — no unsigned preset) ---
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

# --- MONGODB ---
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

async def _is_token_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    return await db.revoked_tokens.find_one({"jti": jti}) is not None


# Lookups that run on every voter request or every admin request and had no index (performance audit P1-3).
# student_id / panel_member_id come FIRST so the same index also serves the (rare) lookups that carry no
# org_id. All are non-unique on purpose, and each is created on its own so one failure (for example an
# index with the same keys but another name made by hand in Atlas) can never stop the app from booting.
PERF_INDEXES = [
    ("otps", [("student_id", 1), ("org_id", 1)]),
    ("admin_otps", [("student_id", 1), ("org_id", 1)]),
    ("revoked_tokens", [("jti", 1)]),
    ("panel_members", [("panel_member_id", 1)]),
    ("panel_members", [("student_id", 1), ("org_id", 1)]),
    ("applications", [("org_id", 1), ("status", 1)]),
    ("applications", [("org_id", 1), ("submitted_at", -1)]),
    ("candidate_tokens", [("token", 1)]),
    ("candidate_tokens", [("org_id", 1), ("round_id", 1), ("student_id", 1)]),
    ("certificates", [("certificate_id", 1)]),
    ("organizations", [("slug", 1)]),
    ("voters", [("org_id", 1), ("has_voted", 1)]),
]


async def _ensure_perf_indexes() -> None:
    for coll, keys in PERF_INDEXES:
        try:
            await db[coll].create_index(keys)
        except Exception:
            logger.warning("Could not create index %s on %s (continuing without it)", keys, coll, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # OTP_EXPIRY_MINUTES is enforced explicitly in verify_otp too — this index
    # is cleanup, not the actual security boundary, since Mongo's TTL monitor
    # only sweeps roughly once a minute rather than at the exact expiry instant.
    await db.otps.create_index("created_at", expireAfterSeconds=OTP_EXPIRY_MINUTES * 60)
    # Revoked-token records only need to live as long as the token itself
    # would have been valid — once it's past its natural exp it can't be
    # replayed anyway, so there's no need to keep the revocation record.
    
    await db.revoked_tokens.create_index("revoked_at", expireAfterSeconds=JWT_EXPIRE_MINUTES * 60)
    # login_attempts had no TTL at all — a five-year-old failed-login record for a
    # long-departed IT admin sat in the collection forever. An hour past the longest
    # possible lockout (LOGIN_LOCKOUT_MINUTES) is enough margin for the lock to have
    # already expired naturally before Mongo reaps the document.
    await db.login_attempts.create_index("last_attempt", expireAfterSeconds=(LOGIN_LOCKOUT_MINUTES + 60) * 60)
    # Per-IP rate-limit buckets (upload, voter-register search) — Mongo-backed
    # replacement for the old in-memory dicts (see _check_rate_limit). TTL'd
    # well past the longest window used (UPLOAD_RATE_WINDOW_S) so a bucket
    # cleans itself up instead of growing for the life of the process.
    await db.ip_rate_limits.create_index("key", unique=True)
    await db.ip_rate_limits.create_index("last_hit", expireAfterSeconds=3600)
    
    # student_id lookups happen on every OTP send, OTP verify, and vote cast
    # — the single highest-traffic query pattern on election day. Requires
    # student_id to already be normalized (see migrate_normalize_student_ids.py)
    # so this can be a plain compound index rather than needing a text/regex index.
    await db.vote_events.create_index([("org_id", 1), ("candidate_id", 1)])
    # audit_checkpoints has no update/delete route anywhere in this file —
    # write-once is enforced by never writing code that touches an existing
    # checkpoint. The unique index on to_id is a DB-level backstop against
    # accidentally creating two checkpoints over the same range. The index
    # on from_id closes a race: two checkpoint calls firing near-simultaneously
    # (manual trigger + cron overlap) could both read the same "last
    # checkpoint" and try to write a child with the same from_id — this
    # makes the second one fail loudly instead of silently forking the chain.
    await db.audit_checkpoints.create_index([("org_id", 1), ("to_id", 1)], unique=True)
    await db.audit_checkpoints.create_index([("org_id", 1), ("from_id", 1)], unique=True)
    # OTP verify-attempt lockouts (brute-force guard on /verify-otp).
    await db.otp_attempts.create_index("key", unique=True)
    await db.otp_attempts.create_index("last_attempt", expireAfterSeconds=24 * 3600)
    # OTP_SMS_Design_v2 state. Unique keys make reserve_send / consume_guess race-safe.
    await db.otp_send_state.create_index("key", unique=True)
    await db.otp_send_state.create_index("last_send_at", expireAfterSeconds=48 * 3600)
    await db.otp_guess_state.create_index("key", unique=True)
    await db.otp_guess_state.create_index("updated_at", expireAfterSeconds=7 * 24 * 3600)  # > a full refill at the 12 h cap
    await db.sms_usage.create_index("org_key", unique=True)
    await db.ip_send_stats.create_index("key", unique=True)
    await db.ip_send_stats.create_index("updated_at", expireAfterSeconds=2 * 3600)
    await db.contact_changes.create_index([("org_id", 1), ("status", 1)])
    await db.contact_changes.create_index("student_id")
    await db.contact_changes.create_index("change.new_value")     # duplicate-number warning
    await db.contact_changes.create_index(                         # one pending request per voter, atomically
        [("org_id", 1), ("student_id", 1)], unique=True, partialFilterExpression={"status": "pending"})
    await db.roster_ledger.create_index([("org_id", 1), ("seq", 1)], unique=True)
    await db.voter_import_previews.create_index("created_at", expireAfterSeconds=3600)
    await db.voter_import_previews.create_index("preview_id", unique=True)
    await db.roster_ledger.create_index([("org_id", 1), ("event", 1), ("ref_id", 1), ("ts", -1)])
    await db.voters.create_index([("has_voted", 1), ("sms_sends_total", 1)])
    # Hot-path lookups. Non-unique on purpose, and wrapped so an index problem can never stop the app
    # from booting (guide 3.4). Indexes hand-made in Atlas with the same keys are simply reused.
    try:
        await db.settings.create_index([("org_id", 1), ("name", 1)])
        await db.positions.create_index([("org_id", 1), ("order", 1)])
        await db.candidates.create_index([("org_id", 1), ("order", 1)])
        await db.voters.create_index([("org_id", 1), ("student_id", 1)])
    except Exception:
        logger.exception("Could not create hot-path indexes (continuing without them)")
    # Phase exception grants — looked up on every gated action.
    await db.exception_grants.create_index([("org_id", 1), ("student_id", 1), ("phase", 1)])
    await db.nomination_uploads.create_index([("org_id", 1), ("created_at", -1)])
    await db.nomination_uploads.create_index([("org_id", 1), ("upload_id", 1)], unique=True)
    # NOTE: no TTL index here. A TTL on created_at also deleted *attached* records after 24h, which made
    # submitted forms unreadable. Stale pending uploads are swept by _sweep_stale_nomination_uploads(), which
    # removes the private file as well as the record. Drop the legacy TTL index if an earlier build created it.
    try:
        await db.nomination_uploads.drop_index("created_at_1")
    except Exception:
        pass
    await db.demo_inbox.create_index([("org_id", 1), ("created_at", -1)])
    await db.demo_inbox.create_index("created_at", expireAfterSeconds=14 * 24 * 3600)
    # The activity log is read by every admin role now, filtered and sorted.
    await db.student_edit_audit.create_index([("org_id", 1), ("student_key", 1), ("at", -1)])
    await db.student_edit_audit.create_index([("org_id", 1), ("search_terms", 1)])
    await db.audit_log.create_index([("org_id", 1), ("timestamp", -1)])
    await db.audit_log.create_index([("org_id", 1), ("action", 1), ("timestamp", -1)])
    # Turnout-velocity aggregation scans cast_at.
    await db.vote_events.create_index([("org_id", 1), ("cast_at", 1)])
    await _ensure_perf_indexes()
    set_revocation_check(_is_token_revoked)
    if DEBUG_MODE:
        # DEBUG_MODE sends no real SMS and writes every OTP and temporary password into the logs.
        logger.critical("DEBUG_MODE is ON: SMS is mocked and OTPs / temp passwords are logged in clear text. "
                        "This must never be set on a production deployment.")
    await _check_config_on_boot()
    analytics.set_org_slug_resolver(_org_slug_for_id)
    analytics.set_org_resolver(_resolve_org_id)
    await analytics.start(db)
    yield
    await analytics.stop()
    await _close_sms_http()
    client.close()


async def _check_config_on_boot() -> None:
    """One-time check of every optional service integration's credentials.
    A missing env var for these doesn't crash boot (each degrades at the
    point of use instead — e.g. Turnstile returns None and fails open,
    B2 backups raise BackupError only when a backup actually runs), which
    is the right call operationally, but it means a bad deploy can go
    unnoticed until election day. This surfaces it immediately instead.
    """
    missing = []
    if not os.getenv("RESEND_API_KEY"):
        missing.append("RESEND_API_KEY (alert emails will only be logged, never sent)")
    if not (os.getenv("BACKUP_ALERT_EMAIL") or os.getenv("SUPER_ADMIN_ID")):
        missing.append("BACKUP_ALERT_EMAIL / SUPER_ADMIN_ID (no alert recipient configured)")
    if not (B2_ENDPOINT and B2_KEY_ID and B2_APPLICATION_KEY and B2_BUCKET_NAME):
        missing.append("B2_* backup credentials (backups will fail on first run)")
    if not (os.getenv("CLOUDINARY_CLOUD_NAME") and os.getenv("CLOUDINARY_API_KEY")
            and os.getenv("CLOUDINARY_API_SECRET")):
        missing.append("CLOUDINARY_* credentials (image uploads will fail)")
    if not EGOSMS_USER:
        missing.append("EGOSMS_USERNAME (primary OTP provider unavailable)")
    if not MAMBOSMS_API_KEY:
        missing.append("MAMBOSMS_API_KEY (fallback OTP provider unavailable)")
    if not TURNSTILE_SECRET:
        missing.append("TURNSTILE_SECRET (captcha disabled; informational only if intentional)")

    if not missing:
        logger.info("Boot config check: all optional service credentials present.")
        return

    body = "Missing or unset on this deploy:\n- " + "\n- ".join(missing)
    logger.warning("Boot config check found gaps:\n%s", body)
    # If Resend itself isn't configured, this alert can only ever be logged —
    # still worth calling send_alert so that gap is spelled out in the log
    # the same way every other missing credential is, rather than silently
    # skipping it.
    await send_alert("Boot config check found missing credentials", body, level="warning", cooldown_s=0)

# =============================================================================
# API DOCS (Swagger/ReDoc) — locked down by default
# =============================================================================
# DOCS_ENABLED unset or "false" (the default): /docs, /redoc, and
# /openapi.json don't exist as routes at all — a plain 404, same as any
# other unknown path. No API surface, no schema, nothing to unlock.
#
# DOCS_ENABLED=true: routes are registered, but ALSO require HTTP Basic Auth
# via DOCS_USERNAME/DOCS_PASSWORD (separate from your admin login — Swagger
# UI has no way to prompt for a Bearer token before it loads, so this is the
# standard lightweight pattern instead). Set all three env vars together;
# turning docs on without setting credentials fails closed (422/401), not open.
DOCS_ENABLED = os.getenv("DOCS_ENABLED", "false").lower() == "true"
DOCS_USERNAME = os.getenv("DOCS_USERNAME")
DOCS_PASSWORD = os.getenv("DOCS_PASSWORD")

app = FastAPI(
    title="BallotBox Master API",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

if DOCS_ENABLED:
    import secrets as _secrets
    import base64 as _base64

    @app.middleware("http")
    async def docs_basic_auth_middleware(request: Request, call_next):
        if request.url.path in ("/docs", "/redoc", "/openapi.json"):
            auth_header = request.headers.get("Authorization", "")
            ok = False
            if auth_header.startswith("Basic ") and DOCS_USERNAME and DOCS_PASSWORD:
                try:
                    decoded = _base64.b64decode(auth_header[len("Basic "):]).decode()
                    username, _, password = decoded.partition(":")
                    ok = _secrets.compare_digest(username, DOCS_USERNAME) and \
                         _secrets.compare_digest(password, DOCS_PASSWORD)
                except Exception:
                    ok = False
            if not ok:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Docs require authentication."},
                    headers={"WWW-Authenticate": "Basic"},
                )
        return await call_next(request)

client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URL,
    maxPoolSize=20,
    minPoolSize=1,
    waitQueueTimeoutMS=2500
)
db = client[os.getenv("MONGO_DB_NAME", "electiondbaccounting")]

B2_ENDPOINT = os.getenv("B2_ENDPOINT")
B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")

# A bad or missing B2_* value (e.g. an endpoint without the https:// scheme)
# used to raise here at import time and take the ENTIRE app down before
# uvicorn could even start — voting, auth, everything — just because the
# audit-checkpoint external anchor was misconfigured. That feature already
# degrades gracefully at the point of use (_publish_checkpoint_externally
# logs audit_checkpoint_anchor_failed and continues instead of raising), so
# a boot-time misconfiguration should degrade the same way, not crash boot.
try:
    b2_client = boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APPLICATION_KEY,
    )
except Exception as e:
    logging.error(f"B2 client init failed — audit checkpoint anchoring disabled: {e}")
    b2_client = None

# =============================================================================
# MULTI-TENANCY: ORG CONTEXT MIDDLEWARE
# =============================================================================
# Every request may carry an X-Org-Slug header (set by the frontend at build
# time via VITE_ORG_SLUG). This middleware resolves it to an org_id and
# attaches it to request.state so route handlers can filter by tenant.
#
# Fail-closed tenancy, no legacy mode. A request without X-Org-Slug is rejected (400) unless its
# path is in ORG_EXEMPT_PREFIXES, and org_query()/org_stamp() refuse to run without a tenant, so
# there is no "unscoped" path that could read or write across clients. The old REQUIRE_ORG_CONTEXT
# switch and the org_id=None "legacy default tenant" have been removed on purpose.
ORG_CACHE_TTL_S = float(os.getenv("ORG_CACHE_TTL_S", "60"))
_ORG_CACHE: dict[str, tuple[str, float]] = {}

async def _resolve_org_id(slug):
    if not slug:
        return None
    now = time.monotonic()
    hit = _ORG_CACHE.get(slug)
    if hit and hit[1] > now:
        return hit[0]
    if hit:
        _ORG_CACHE.pop(slug, None)
    doc = await db.organizations.find_one({"slug": slug}, {"_id": 1})
    if not doc:
        return None
    if len(_ORG_CACHE) >= 200:
        oldest = min(_ORG_CACHE, key=lambda k: _ORG_CACHE[k][1])
        _ORG_CACHE.pop(oldest, None)
    _ORG_CACHE[slug] = (str(doc["_id"]), now + ORG_CACHE_TTL_S)
    return _ORG_CACHE[slug][0]

def _org_slug_for_id(org_id):
    for slug, (cached_id, expires_at) in list(_ORG_CACHE.items()):
        if expires_at > time.monotonic() and cached_id == str(org_id):
            return slug
    return None

def _invalidate_org_cache(slug=None):
    if slug is None:
        _ORG_CACHE.clear()
    else:
        _ORG_CACHE.pop(slug, None)

# Render free-tier keep-warm ping (BALLOTBOX_PHASE_RUNBOOK.md). Deliberately NOT
# named /health or /ping: both are predictable, and /health is already documented
# here in plain sight as the uptime-monitor / DB-check endpoint. The actual path
# is read from KEEPWARM_PING_PATH, set only in Render's env vars and never
# committed, so a cron job that's been given the value can hit it, but reading
# this file — or the repo on GitHub — does not reveal where it lives. No DB
# round trip and no alerting on purpose: this has one job (stop the process
# sleeping), and shouldn't add to the Atlas M0 ops count or share /health's
# DB-outage alert cooldown. Unset -> a path nothing will ever request, so the
# route is effectively off rather than silently falling back to something
# guessable.
_KEEPWARM_PATH = "/" + os.getenv("KEEPWARM_PING_PATH", "__keepwarm_unconfigured__").strip("/")


@app.get(_KEEPWARM_PATH, include_in_schema=False)
def _keepwarm_ping():
    return {"ok": True}


ORG_EXEMPT_PREFIXES = ("/health", "/internal/backup", "/docs", "/redoc", "/openapi.json",
                       # /superadmin/legacy-data is a cross-tenant superadmin check (finds documents that
                       # belong to NO tenant), so it cannot require a tenant header itself.
                       "/superadmin/orgs", "/superadmin/mfa", "/superadmin/legacy-data", "/verify-admin",
                       # Token/id-scoped, not header-scoped (candidate-portal-spec §3.2/§3.4) —
                       # the token or certificate_id itself carries the org, so an
                       # X-Org-Slug header is neither required nor consulted.
                       "/candidates/status/", "/verify/", _KEEPWARM_PATH)


@app.middleware("http")
async def org_context_middleware(request: Request, call_next):
    org_slug = request.headers.get("X-Org-Slug")
    request.state.org_id = None
    request.state.org_slug = None
    if org_slug:
        org_id = await _resolve_org_id(org_slug)
        if not org_id:
            return JSONResponse(status_code=404, content={"detail": "Unknown organization."})
        request.state.org_id = org_id
        request.state.org_slug = org_slug
    elif (request.method != "OPTIONS" and request.url.path != "/"
          and not request.url.path.startswith(ORG_EXEMPT_PREFIXES)):
        return JSONResponse(status_code=400, content={"detail": "X-Org-Slug header is required."})
    response = await call_next(request)
    return response

# =============================================================================
# AUTH GUARD MIDDLEWARE
# =============================================================================
# Fail-closed by design: everything is protected UNLESS it's explicitly listed
# as public below. This is deliberately the opposite of sprinkling
# Depends(require_role(...)) on individual routes one-by-one — with 80+ routes
# in this file, a per-route allowlist is one forgotten decorator away from
# reopening the hole we're closing here. A new /admin/whatever route is
# protected automatically the moment it's added, with no extra step.
#
# Voter-facing endpoints (verify-identity, verify-otp, vote, apply, etc.) stay
# public on purpose — voters authenticate per-request via student_id + OTP,
# not via this admin session layer.

PUBLIC_PATHS = {
    "/", "/health", "/election-status", _KEEPWARM_PATH,
    "/verify-identity", "/verify-otp", "/vote", "/vote-bulk", "/vote-status",
    "/apply/check-eligibility", "/apply", "/apply/upload-image", "/apply/upload-document",
    "/verify-admin", "/election-results", "/election-results/voter-roll",
    "/election-results/turnout-breakdown",
    "/voter-register", "/voter-register/check-number",
    "/analytics/collect", "/demo/inbox",
    # Backup triggers: called by an external scheduler with a shared secret
    # (X-Backup-Token, checked in backup_routes.py), not by an admin session.
    "/internal/backup/run", "/internal/backup/status", "/internal/backup/report",
    "/internal/backup/approve-assets", "/internal/backup/selftest",
}
PUBLIC_DOC_PREFIXES = ("/docs", "/openapi.json", "/redoc")


def _is_public(path: str, method: str) -> bool:
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_DOC_PREFIXES):
        return True
    # Public read-only endpoints voters/applicants need before they're
    # "logged in" anywhere. Branding is logo/colors/org-name/support-contact —
    # nothing sensitive — and is fetched unauthenticated on every page load
    # by App.jsx and Results.jsx for every visitor, not just superadmin.
    if method == "GET" and path in {"/candidates", "/positions", "/payment-info", "/nomination-form", "/superadmin/branding", "/election-schedule", "/election-roadmap", "/public/bootstrap"}:
        return True
    # candidate-portal-spec §3.2/§3.4: read-only, token/id-scoped, no admin
    # session involved at all — same reasoning as the voter-facing routes
    # in PUBLIC_PATHS above (auth happens per-request via the token itself).
    if method == "GET" and (path.startswith("/candidates/status/") or path.startswith("/verify/")):
        return True
    return False


# Every unauthenticated hit on a protected path used to write an audit_log row (and the audit log is
# read by every admin role), so anyone could fill the database and bury real events. Log at most one
# such row per client IP per window; the rest are counted in the application log only.
_GUARD_401_LOG_GAP_S = 30.0
_GUARD_401_MAX_TRACKED = 2000
_GUARD_401_LAST: dict[str, float] = {}


def _should_log_guard_401(ip: str) -> bool:
    now = time.monotonic()
    last = _GUARD_401_LAST.get(ip)
    if last is not None and now - last < _GUARD_401_LOG_GAP_S:
        return False
    if len(_GUARD_401_LAST) >= _GUARD_401_MAX_TRACKED:
        for k in [k for k, t in _GUARD_401_LAST.items() if now - t >= _GUARD_401_LOG_GAP_S]:
            _GUARD_401_LAST.pop(k, None)
        if len(_GUARD_401_LAST) >= _GUARD_401_MAX_TRACKED:
            return False
    _GUARD_401_LAST[ip] = now
    return True


@app.middleware("http")
async def auth_guard_middleware(request: Request, call_next):
    if _is_public(request.url.path, request.method):
        return await call_next(request)

    try:
        token = get_bearer_token(request)
        payload = await decode_access_token(token)
    except HTTPException as exc:
        # Logged at debug volume on purpose — this fires on every expired
        # session, not just attacks. record_failed_login already covers the
        # security-relevant signal (repeated bad *credentials*); this is
        # mainly useful for spotting a sudden wave of 401s.
        if exc.status_code == 401:
            if _should_log_guard_401(real_client_ip(request)):
                await log_action("admin_guard_401", "unknown", {"path": request.url.path}, org_id=None)
            else:
                logger.info("admin_guard_401 (throttled) path=%s", request.url.path)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if payload.get("role") not in ADMIN_ROLES:
        return JSONResponse(status_code=403, content={"detail": "Not authorized."})

    # "View as" sessions (minted by /superadmin/view-as) are strictly read-only: enforced here, on
    # the server, so it holds no matter what the browser does. Only GET/HEAD/OPTIONS get through.
    if payload.get("view_only") and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse(status_code=403, content={"detail": "Read-only view: this action is disabled."})

    # Superadmin-only namespace, even though every caller here already holds
    # a valid admin token.
    if request.url.path.startswith("/superadmin") and payload["role"] != "superadmin":
        await log_action(
            "admin_guard_403", payload.get("sub", "unknown"),
            {"path": request.url.path, "role": payload.get("role")}, org_id=payload.get("org_id")
        )
        return JSONResponse(status_code=403, content={"detail": "Superadmin access required."})

    # A token minted for tenant A must not work on tenant B by swapping X-Org-Slug. NB: this guard
    # runs BEFORE org_context_middleware (Starlette runs the last-registered middleware first), so
    # request.state.org_id isn't set yet: resolve the tenant here. Only the superadmin crosses tenants.
    req_org = getattr(request.state, "org_id", None)
    if req_org is None and request.headers.get("X-Org-Slug"):
        req_org = await _resolve_org_id(request.headers["X-Org-Slug"])
    if payload["role"] != "superadmin" and (not req_org or payload.get("org_id") != req_org):
        await log_action(
            "admin_guard_tenant_mismatch", payload.get("sub", "unknown"),
            {"path": request.url.path, "role": payload.get("role")}, org_id=payload.get("org_id"))
        return JSONResponse(status_code=403, content={"detail": "This session does not belong to this organization."})

    # Everything below (and the helpers it calls, e.g. _panel_access_ended -> get_phase_schedule) reads
    # request.state.org_id, which org_context_middleware has not set yet at this point. Publish the tenant
    # resolved above, otherwise a panelist whose access is tied to a timeline phase hits an AttributeError
    # (HTTP 500) on every guarded request, including /admin/set-password.
    request.state.org_id = req_org
    request.state.org_slug = request.headers.get("X-Org-Slug")

    # A temp-password login's token is scoped to password_change_only until the admin
    # actually changes their password — everything else 403s even with a valid token.
    if payload.get("scope") == SCOPE_PASSWORD_CHANGE_ONLY and request.url.path not in PASSWORD_CHANGE_ONLY_ALLOWED_PATHS:
        return JSONResponse(status_code=403, content={
            "detail": "You must change your temporary password before continuing."})

    # An overseer who is serving on the Vetting Panel does not oversee it: overseer access is paused
    # (everything but the hat switch, the notice check and sign-out). View-as sessions are exempt so
    # the superadmin can still see what the overseer sees.
    if payload.get("role") == "overseer" and not payload.get("view_only") \
            and request.url.path not in OVERSEER_PAUSED_ALLOWED_PATHS \
            and await _active_panel_record(request, payload.get("sub")):
        return JSONResponse(status_code=403, content={
            "detail": "Overseer access is paused while you serve on the Vetting Panel. "
                      "Switch to the panel view.", "code": "overseer_paused"})

    if payload.get("role") == "vetting" and request.url.path.startswith(PANEL_GUARDED_PREFIXES) \
            and not request.url.path.startswith(PANEL_ALLOWED_PREFIXES):
        return JSONResponse(status_code=403, content={"detail": "The Vetting Panel cannot access this area."})

    # Per-account session cutoff: a password reset or role revocation stamps
    # sessions_valid_after on the voter doc (see _invalidate_sessions), so any token
    # issued before that moment stops working here even though the JWT itself hasn't
    # expired yet. Superadmin has no voter doc to stamp — it relies on its own shorter
    # SUPERADMIN_JWT_EXPIRE_MINUTES lifetime instead.
    if payload["role"] == "vetting":
        # Panel tokens are keyed by panel_member_id and have no voter row (guide 6.6).
        acct = await tdb_for(req_org).panel_members.find_one(
            {"panel_member_id": payload.get("sub")},
            {"sessions_valid_after": 1, "active": 1, "access_expires_at": 1, "expires_with_phase": 1,
             "is_member": 1, "confidentiality_version": 1}
        )
        if not acct or not acct.get("active", False):
            return JSONResponse(status_code=401, content={
                "detail": "Your panel access is no longer active. Please log in again."})
        if await _panel_access_ended(request, acct):
            return JSONResponse(status_code=401, content={
                "detail": "Your panel access has ended."})
        # A superadmin's read-only view-as session cannot accept on the panelist's behalf, and the
        # superadmin can already read everything, so the gate does not apply to it.
        if not payload.get("view_only") \
                and not acct.get("is_member") and acct.get("confidentiality_version") != CONFIDENTIALITY_VERSION \
                and request.url.path not in CONFIDENTIALITY_ALLOWED_PATHS:
            return JSONResponse(status_code=403, content={
                "detail": "Please read and accept the confidentiality notice before continuing.",
                "code": "confidentiality_required"})
        cutoff = acct.get("sessions_valid_after")
        if cutoff:
            iat = payload.get("iat")
            iat_dt = datetime.utcfromtimestamp(iat) if isinstance(iat, (int, float)) else iat
            # iat is whole seconds (PyJWT truncates) but cutoff keeps microseconds: compare at second
            # precision, or the token minted by the re-login right after a password change (same second)
            # is rejected as "session ended".
            if iat_dt and iat_dt < cutoff.replace(microsecond=0):
                return JSONResponse(status_code=401, content={
                    "detail": "Your session was ended (password changed or access updated). Please log in again."})
    elif payload["role"] != "superadmin":
        # NB: no flag_field filter here — a revoked role's whole point is that the flag is
        # now False, so filtering on it True would make the lookup miss exactly the account
        # whose session we most need to cut off. Role authorization is a separate check
        # (require_role); this is only about "does this token still correspond to a live
        # session for this account at all."
        acct = await tdb_for(req_org).voters.find_one(
            {"student_id": payload.get("sub")},
            {"sessions_valid_after": 1}
        )
        cutoff = acct.get("sessions_valid_after") if acct else None
        if cutoff:
            iat = payload.get("iat")
            iat_dt = datetime.utcfromtimestamp(iat) if isinstance(iat, (int, float)) else iat
            # iat is whole seconds (PyJWT truncates) but cutoff keeps microseconds: compare at second
            # precision, or the token minted by the re-login right after a password change (same second)
            # is rejected as "session ended".
            if iat_dt and iat_dt < cutoff.replace(microsecond=0):
                await log_action("admin_guard_session_invalidated", payload.get("sub", "unknown"),
                                  {"path": request.url.path, "role": payload.get("role")}, org_id=payload.get("org_id"))
                return JSONResponse(status_code=401, content={
                    "detail": "Your session was ended (password changed or access updated). Please log in again."})

    request.state.admin = payload
    return await call_next(request)

# =============================================================================
# CORS — registered LAST on purpose
# =============================================================================
# Starlette's middleware stack runs in reverse-registration order: whatever
# is added last becomes the OUTERMOST layer, executed first on the way in
# and last on the way out. CORSMiddleware needs to be outermost so it can
# intercept OPTIONS preflights and stamp Access-Control-Allow-Origin onto
# every response — including 401/403 error responses from the two custom
# middlewares above. Registering it earlier (before those) meant preflights
# for any non-public route hit the auth guard first, got rejected with no
# CORS headers attached, and the browser blocked the request entirely
# before the real GET/POST was ever sent.

# SECURITY: allow_origins=["*"] previously let ANY website on the internet
# script requests against this API from a visitor's browser. Now driven by
# ALLOWED_ORIGINS (comma-separated) so only the real frontend deployments can
# talk to it. Unset in local dev falls back to localhost origins, never "*".
_raw_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = (
    [o.strip().rstrip("/") for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["http://localhost:5173", "http://127.0.0.1:5173"]
)
# Optional regex for preview deployments (e.g. Vercel branch URLs):
#   ALLOWED_ORIGIN_REGEX=https://.*\.vercel\.app
ALLOWED_ORIGIN_REGEX = os.getenv("ALLOWED_ORIGIN_REGEX") or None

# Compress JSON/text responses (big rosters, results, exports) — a real saving on 3G. Registered BEFORE
# CORS so CORS stays the outermost layer and still stamps headers on every response.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Org-Slug", "X-Voter-Token"],
    expose_headers=["Content-Disposition", "X-Export-Mode", "X-Export-Rows"],
    max_age=7200,    # Chrome's ceiling (2 h); removes most repeat preflights on slow links
)

# =============================================================================
# TRUSTED PROXY / REAL CLIENT IP
# =============================================================================
# Render, Railway, etc. terminate TLS and forward every request through a
# reverse proxy — without this, request.client.host (used by the per-IP
# rate limiters above) is the PROXY's address for every single visitor, not
# the real caller. That silently turns a "per-IP" limit into one shared
# bucket for all traffic combined. ProxyHeadersMiddleware rewrites
# request.client from the X-Forwarded-For header, but ONLY when the
# immediate connecting peer is in trusted_hosts — otherwise a client could
# forge X-Forwarded-For to inject an arbitrary "IP" and bypass rate limits
# entirely.
#
# TRUSTED_PROXY_HOSTS defaults to "*" because on a single-hop PaaS
# (Render/Railway) every inbound connection genuinely does come from the
# platform's own edge, whose address isn't published/stable enough to pin
# down — but if this is ever deployed behind your own reverse proxy at a
# known address, set TRUSTED_PROXY_HOSTS to that address (or a comma
# separated list) instead of leaving it wildcarded.
# uvicorn's ProxyHeadersMiddleware with trusted_hosts="*" takes the LEFTMOST X-Forwarded-For entry,
# which is whatever the client typed, so every per-IP limiter was bypassable with a fresh fake header.
# Proxies APPEND the peer they saw: the trustworthy entry is N hops from the RIGHT (N = proxies in
# front of the app). Verify N for your host (Render / Cloudflare) by logging the header once.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))


def real_client_ip(request: Request) -> str:
    xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if TRUSTED_PROXY_HOPS > 0 and len(xff) >= TRUSTED_PROXY_HOPS:
        return xff[-TRUSTED_PROXY_HOPS]
    return request.client.host if request.client else "unknown"


# =============================================================================
# SECURITY HEADERS
# =============================================================================
# Registered after CORS so it becomes the outermost layer and stamps these
# onto every response, including 401/403s from the guards above.

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    )
    # This is a JSON API — nothing here should ever be rendered as a document.
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
    )
    # Admin/audit payloads must never sit in a shared cache or browser bfcache.
    if request.url.path.startswith(("/admin", "/superadmin", "/it-admin", "/overseer", "/commission")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response

app.middleware("http")(analytics.outcome_middleware)
app.include_router(analytics.build_router(lambda: db, require_role, lambda action, actor, details, org_id=None: log_action(action, actor, details, org_id=org_id)))
app.include_router(build_backup_router(lambda: db))

# =============================================================================
# MODELS
# =============================================================================     
class PanelMemberCreate(BaseModel):
    full_name:       str
    email:           str
    phone:           str                    # required; used for the temp-password SMS
    is_member:       bool                   # True = internal (voter roll), False = external
    appointment_reason: str                 # required, free text
    affiliation:     str = ""
    student_id:      str | None = None      # required when is_member, links to voter row
    access_expires_at: datetime | None = None
    expires_with_phase: str | None = None   # e.g. "vetting"; used when no fixed date

class PanelCommissionerLink(BaseModel):
    """Put an existing commissioner on the Vetting Panel with no separate login (they use the hat switch)."""
    student_id:         str = Field(..., max_length=100)
    appointment_reason: str = Field(..., max_length=1000)

class PanelMemberCredentials(BaseModel):
    email: str

class PanelMemberUpdate(BaseModel):
    """Fields a superadmin may change on an existing panelist. Omitted = unchanged."""
    affiliation:        str | None = None
    phone:              str | None = None
    access_expires_at:  datetime | None = None
    expires_with_phase: str | None = None
    clear_access_end:   bool = False        # members only: remove the end date / phase

class CommissionerRoleUpdate(BaseModel):
    role_label: str   # e.g. "Finance Commissioner", "Deputy Finance", "General Commissioner"
    
class IdentityCheck(BaseModel):
    student_id: str
    full_name: str
    phone_index: int | None = None
    turnstile_token: str | None = None   # Cloudflare Turnstile (see enforce_turnstile)

class AdminIdentityCheck(BaseModel):
    student_id: str
    full_name: str
    phone_index: int | None = None

class OTPCheck(BaseModel):
    student_id: str
    code: str

class AdminLoginCheck(BaseModel):
    email:    str
    password: str
    totp_code: str | None = None  # only used/required for superadmin, once SUPERADMIN_TOTP_SECRET is set

class CommissionerCredentials(BaseModel):
    email:    str
    password: str

class VoteRequest(BaseModel):
    student_id: str
    candidate_id: str

class BulkVoteRequest(BaseModel):
    student_id: str
    candidate_ids: list[str]

class CandidateCreate(BaseModel):
    name: str
    position: str
    image_url: str
    order: int = 0

class AdminTestSMS(BaseModel):
    phone: str
    # None = send exactly like a real OTP would (follows the routing setting); "egosms" / "mambosms" =
    # test that one provider directly, ignoring routing.
    provider: str | None = None

# --- Branding & Positions ---
class BrandingUpdate(BaseModel):
    logo_url:            str
    primary_color:       str
    accent_color:        str
    org_name:            str = ""
    university_name:     str = ""
    university_logo_url: str = ""
    support_phone:       str = ""
    support_contacts:    list[dict] = []   # [{reason, contacts: [{name, link}]}] — WhatsApp number or link per reason
    cc_list:             list[str] = []
    signatories:         list[dict] = []   # [{full_name, role}, ...] — manual override; see get_official_report
    # Voter-login wording, per organisation (blank = the original defaults on the frontend)
    id_label:            str = ""          # what this org calls the voter ID, e.g. "Student Number"
    id_examples:         list[str] = []    # sample IDs for the login placeholders
    name_examples:       list[str] = []    # sample names for the login placeholders
    id_format_hint:      str = ""          # sentence shown when an ID is not found

class PositionCreate(BaseModel):
    title: str
    description: str = ""
    order: int = 0
    # Nomination fee in UGX shown to applicants next to the proof-of-payment upload. 0 = no fee stated.
    application_fee: int = Field(0, ge=0, le=100_000_000)

class PositionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    order: int | None = None
    application_fee: int | None = Field(None, ge=0, le=100_000_000)

# --- Applications ---
MANIFESTO_MAX_CHARS = 3000  # ~500 words; keep in sync with the frontend constant

# Base URL the candidate status-link SMS points into (frontend/vercel.json's
# SPA catch-all loads the app shell for any /status/<token> path).
# Multi-tenant: each organisation has its own frontend deployment (its own VITE_ORG_SLUG build), so the link
# must point at THAT org's site. The per-org `frontend_url` on the organizations document wins; this env var is
# only the platform-wide fallback for orgs that have none set yet.
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://yourapp.vercel.app").rstrip("/")


def normalize_frontend_url(raw: str) -> str:
    """Validates a site address and returns it without a trailing slash ('' = not set). Only a bare origin is
    accepted (https, or http for localhost): no path, query, fragment or credentials, so a typo or a malicious
    value can't turn an SMS link into something else."""
    from urllib.parse import urlsplit
    v = (raw or "").strip().rstrip("/")
    if not v:
        return ""
    u = urlsplit(v)
    host = (u.hostname or "").lower()
    local = host in ("localhost", "127.0.0.1")
    if u.scheme not in ("https", "http") or not host or (u.scheme == "http" and not local):
        raise HTTPException(400, "Frontend URL must be a full https:// address, e.g. https://vote.example.org")
    if u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
        raise HTTPException(400, "Frontend URL must be just the site address, with no path, query or login details.")
    return f"{u.scheme}://{u.netloc}"


async def frontend_url_for(request: Request) -> str:
    """The frontend base URL for the tenant making this request (no trailing slash)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id:
        try:
            doc = await db.organizations.find_one({"_id": ObjectId(org_id)}, {"frontend_url": 1})
        except Exception:
            doc = None
        url = ((doc or {}).get("frontend_url") or "").strip().rstrip("/")
        if url:
            return url
    logger.warning("No frontend_url set for org %s; falling back to FRONTEND_URL.", org_id)
    return FRONTEND_URL

# Candidate status links expire automatically (default 60 days) and can be revoked
# by a superadmin. Resending a still-valid link extends it; an expired or revoked
# one is replaced with a fresh link.
STATUS_LINK_TTL_DAYS = int(os.getenv("STATUS_LINK_TTL_DAYS", "60"))


def _status_link_expired(token_doc: dict) -> bool:
    if token_doc.get("revoked"):
        return True
    expires = token_doc.get("expires_at") or (
        (token_doc.get("created_at") or datetime.utcnow()) + timedelta(days=STATUS_LINK_TTL_DAYS))  # pre-expiry tokens
    return expires <= datetime.utcnow()


async def _get_or_create_status_token(student_id: str, round_id, org_id) -> dict:
    """Returns (and if needed creates) the student's one live status link for this round."""
    now = datetime.utcnow()
    async for t in tdb_for(org_id).candidate_tokens.find(
            {"student_id": student_id, "round_id": round_id, "org_id": org_id}).sort("created_at", -1):
        if not _status_link_expired(t):
            return t
    doc = {"token": secrets.token_urlsafe(32), "student_id": student_id, "round_id": round_id, "org_id": org_id,
           "created_at": now, "expires_at": now + timedelta(days=STATUS_LINK_TTL_DAYS), "revoked": False,
           "is_demo": bool(await _demo_active(org_id))}
    await tdb_for(org_id).candidate_tokens.insert_one(doc)
    return doc

class ApplicationSubmit(BaseModel):
    # Public, unauthenticated body: every field is length-bounded so one request cannot store megabytes.
    student_id:        str = Field(..., max_length=64)
    full_name:         str = Field(..., max_length=200)
    position_id:       str = Field(..., max_length=64)
    manifesto:         str = Field("", max_length=MANIFESTO_MAX_CHARS)
    image_url:         str = Field("", max_length=2000)
    payment_method:    str = Field("", max_length=100)
    payment_proof_url: str = Field("", max_length=2000)
    nomination_upload_id: str = Field("", max_length=64)   # id returned by /apply/upload-document (N2); never a URL
    phone:             str = Field("", max_length=32)      # only read when the org turned on collect_phone; saved to the voter record, not the application

class CommissionerVote(BaseModel):
    commissioner_id: str = Field("", max_length=64)   # optional; if sent it must match the panel account (student_id or PM- id)
    vote: str = Field(..., max_length=16)             # "approve" or "deny"
    reason: str = Field("", max_length=500)           # written to the audit log, so bounded

class TieBreakDecision(BaseModel):
    decision: str                                 # "approve" | "deny"
    reason: str = Field("", max_length=500)       # stored only when deny

class FinalReasonUpdate(BaseModel):
    reason: str = Field("", max_length=500)       # empty clears it

class FinanceClear(BaseModel):
    financial_controller_id: str   # must belong to a voter flagged is_financial_controller
    reason: str = ""               # optional note on a clearance; kept on the application + audit log

class FinanceReject(BaseModel):
    financial_controller_id: str   # must belong to a voter flagged is_financial_controller
    reason: str = Field(..., max_length=500)   # required; shown to the candidate on their status page

class FinanceReverse(BaseModel):
    financial_controller_id: str
    reason: str = Field(..., max_length=500)   # required; internal (audit log + finance history), never shown to the candidate

class FinanceReinstate(BaseModel):
    financial_controller_id: str
    target: str                                # "pending" (back to awaiting) | "cleared" (payment confirmed)
    reason: str = Field(..., max_length=500)   # required; internal, e.g. "Balance of UGX 20,000 paid, receipt #123"
    

class ITAdminStudentAdd(BaseModel):
    student_id:        str
    full_name:         str
    phones:            list[str]
    attrs:             dict[str, str] = {}
    reason:            str = ""
    requested_by:      str
    payment_method:    str = ""
    payment_proof_url: str = ""
    
class ITAdminStudentRemove(BaseModel):
    student_id:   str
    reason:       str
    requested_by: str

class FinancialControllerDecision(BaseModel):
    financial_controller_id: str   # must belong to a voter flagged is_financial_controller
    decision:                 str   # "approve" or "deny"
    reason:                   str = ""

class StudentChangeCancelRequest(BaseModel):
    requested_by:      str   # must match original requester
    cancelled_reason:  str = ""
    
class SetEmailOnly(BaseModel):
    email: str

class SetNewPassword(BaseModel):
    email:        str
    old_password: str   # the temp password they logged in with
    new_password: str

class ResetPasswordRequest(BaseModel):
    pass   # no body needed — student_id comes from the URL path

class OrganizationCreate(BaseModel):
    name: str            # display name, e.g. "KYUCCU"
    slug: str = ""        # url/header-safe identifier; auto-generated from name if blank
    frontend_url: str = ""   # this org's own site, e.g. https://vote.kyuccu.org (used in SMS links); optional

class OrganizationFrontendUrl(BaseModel):
    frontend_url: str = ""   # blank clears it (falls back to the FRONTEND_URL env var)

class ApplicationEligibilityCheck(BaseModel):
    student_id: str
    full_name: str
    phone: str = Field("", max_length=32)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def normalize_student_id(student_id: str) -> str:
    """Single source of truth for student_id normalization: lowercase,
    strip whitespace, strip surrounding quotes. Used at write time (import,
    student-add) and, after the migration script has run once against
    existing data, at query time too — enabling a plain exact-match query
    that can use a standard B-tree index instead of the case-insensitive
    regex scan get_forgiving_filter requires."""
    return student_id.strip().strip('"').replace(" ", "").lower()


def get_forgiving_filter(student_id: str):
    """Exact-match filter on the normalized student_id. Renamed in spirit
    only — kept this name so none of the ~23 call sites need to change.
    Requires the migration script to have already normalized existing
    voter documents; see migrate_normalize_student_ids.py."""
    return {"student_id": normalize_student_id(student_id)}

def _mask_name(name: str) -> str:
    parts = name.strip().split()
    if len(parts) <= 1:
        return parts[0] if parts else name
    return parts[0] + " " + " ".join(f"{p[0]}." for p in parts[1:])

def _mask_student_id(sid: str) -> str:
    # Display only: stored form is lowercase, people see registration numbers capitalised.
    sid = (sid or "").upper()
    parts = sid.split("/")
    if len(parts) < 2:
        return sid[:3] + "***"
    core = parts[-2]
    parts[-2] = core[:1] + "*" * max(len(core) - 1, 1)
    return "/".join(parts)

def _mask_phone(phone: str) -> str:
    if len(phone) <= 8:
        return "*" * len(phone)
    return f"{phone[:6]}****{phone[-2:]}"

def _mask_email(email: str) -> str:
    """For activity-log entries visible to every admin role (full-transparency
    design) — keeps enough to recognize which account, without broadcasting
    a usable address to roles that have no reason to email that person."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return email
    shown = local[:2] if len(local) > 2 else local[:1]
    return f"{shown}{'*' * max(len(local) - len(shown), 1)}@{domain}"

def _mask_ip(ip: str) -> str:
    """Same rationale as _mask_email — this shows up in the activity log for
    every admin role, not just whoever handles security incidents. Keeps the
    network enough to spot repeated attempts from the same source without
    broadcasting an exact host address."""
    if not ip:
        return ip
    if ":" in ip:  # IPv6 — keep the routed prefix, drop the host portion
        parts = ip.split(":")
        return ":".join(parts[:4]) + ":****"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.***"
    return ip

def names_match(registered_name: str, input_name: str) -> bool:
    reg_parts   = set(registered_name.strip().lower().split())
    input_parts = set(input_name.strip().lower().split())
    common_parts = reg_parts.intersection(input_parts)
    match_threshold = 2 if len(reg_parts) >= 2 else 1
    return len(common_parts) >= match_threshold

# One shared HTTP client for the SMS providers: keep-alive connections skip a fresh TLS handshake on every
# code. The connect timeout is short (a provider we cannot even reach has sent nothing, so it fails fast and
# the next provider is tried); the read timeout stays 15 s because the "ambiguous" logic below depends on it.
_SMS_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SMS_HTTP: httpx.AsyncClient | None = None
_SMS_HTTP_LOOP = None


def _sms_http() -> httpx.AsyncClient:
    """The shared client, rebuilt if the event loop changed or it was closed (a client is bound to one loop)."""
    global _SMS_HTTP, _SMS_HTTP_LOOP
    loop = asyncio.get_running_loop()
    if _SMS_HTTP is None or _SMS_HTTP.is_closed or _SMS_HTTP_LOOP is not loop:
        _SMS_HTTP = httpx.AsyncClient(
            timeout=_SMS_TIMEOUT,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10, keepalive_expiry=30.0))
        _SMS_HTTP_LOOP = loop
    return _SMS_HTTP


async def _close_sms_http() -> None:
    global _SMS_HTTP
    if _SMS_HTTP is not None and not _SMS_HTTP.is_closed:
        try:
            await _SMS_HTTP.aclose()
        except Exception:
            logger.debug("closing the SMS HTTP client failed", exc_info=True)
    _SMS_HTTP = None


async def send_sms_via_mambosms(to_number: str, message_text: str) -> bool:
    """Fallback OTP provider, used only when EgoSMS fails. Returns True only on a genuine send success —
    Mambo's API returns HTTP 200 even for some failures (e.g. a suspended
    account), so success is read from the `success` field in the body, not
    just the status code. See https://mambosms.com/api for the full contract.
    """
    try:
        clean_number = to_number.replace("+", "").strip()
        payload = {
            "message": message_text,
            "recipients": clean_number,
            "message_category": MAMBOSMS_MESSAGE_CATEGORY,
            "sender_id": MAMBOSMS_SENDER_ID,
        }
        headers = {"Authorization": MAMBOSMS_API_KEY or "", "Content-Type": "application/json"}
        response = await _sms_http().post(
            "https://api-mongolia.mambosms.com/v1/send-sms",
            json=payload,
            headers=headers,
            timeout=_SMS_TIMEOUT,
        )
        body = response.json()
        logger.info(f"MamboSMS Result: {body}")
        return bool(body.get("success"))
    except Exception as e:
        logger.error(f"MamboSMS Connection Error: {e}")
        return False


async def send_sms_via_egosms(to_number: str, message_text: str) -> str:
    """Primary OTP provider. See send_sms_status(). Returns "ok", "failed" (definitely not sent) or
    "ambiguous" (the request may have been accepted: timeout / connection dropped after sending)."""
    try:
        clean_number = to_number.replace("+", "").strip()
        params = {
            "username": EGOSMS_USER,
            "password": EGOSMS_PASS,
            "number": clean_number,
            "message": message_text,
            "sender": EGOSMS_SENDER_ID
        }
        response = await _sms_http().get(
            "https://comms.egosms.co/api/v1/plain/",
            params=params,
            timeout=_SMS_TIMEOUT
        )
        resp_text = response.text.strip()
        logger.info(f"EgoSMS Result: {resp_text}")
        return "ok" if "OK" in resp_text.upper() else "failed"
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.RemoteProtocolError) as e:
        logger.error(f"EgoSMS ambiguous result ({type(e).__name__}): {e}")
        return "ambiguous"
    except Exception as e:
        logger.error(f"EgoSMS Connection Error: {e}")
        return "failed"


async def _safe_count_sms(org_id, kind: str):
    try:
        await count_sms(org_id, kind)
    except Exception as e:                      # accounting must never block a voter's code
        logger.error(f"sms usage count failed: {e}")


# kind="otp" is the only time-priority category (a voter is actively waiting on the code).
# Everything else (admin, notice, test, vetting, ...) is non-priority: MamboSMS is cheap but
# slow, which is fine for messages nobody is staring at their phone for.
PRIORITY_SMS_KINDS = {"otp"}

# ── SMS routing (superadmin-adjustable per org, Security tab -> "SMS delivery") ──────────────
# A route decides which provider(s) a message may use and in what order:
#   default        the original behaviour: OTP -> EgoSMS then MamboSMS; everything else -> MamboSMS then EgoSMS
#   egosms_first   EgoSMS, falling back to MamboSMS on a definite failure
#   mambosms_first MamboSMS, falling back to EgoSMS on a failure
#   egosms_only    EgoSMS only - never touches MamboSMS
#   mambosms_only  MamboSMS only - never touches EgoSMS
SMS_PROVIDERS = ("egosms", "mambosms")
SMS_ROUTES = ("default", "egosms_first", "mambosms_first", "egosms_only", "mambosms_only")
_SMS_PROVIDER_LABEL = {"egosms": "EgoSMS", "mambosms": "MamboSMS"}


def sms_route_group(kind: str) -> str:
    """Which routing setting a message kind follows: 'otp' (voter codes) or 'other' (everything else)."""
    return "otp" if kind in PRIORITY_SMS_KINDS else "other"


def sms_provider_order(route: str, kind: str) -> list[str]:
    """Ordered provider list for a route. Unknown routes behave like 'default'."""
    if route == "egosms_only":
        return ["egosms"]
    if route == "mambosms_only":
        return ["mambosms"]
    if route == "egosms_first":
        return ["egosms", "mambosms"]
    if route == "mambosms_first":
        return ["mambosms", "egosms"]
    return ["egosms", "mambosms"] if kind in PRIORITY_SMS_KINDS else ["mambosms", "egosms"]


async def _sms_try_provider(provider: str, to_number: str, message_text: str) -> str:
    """One provider attempt -> "ok" | "failed" | "ambiguous" (only EgoSMS can report ambiguous)."""
    if provider == "egosms":
        return await send_sms_via_egosms(to_number, message_text)
    return "ok" if await send_sms_via_mambosms(to_number, message_text) else "failed"


async def _send_sms_routed(to_number: str, message_text: str, org, kind: str) -> str:
    """Send following the org's routing setting for this kind of message.

    Every attempt that was accepted OR may have been accepted (ambiguous) is counted toward the SMS
    budget. After an AMBIGUOUS result (timeout: the message may already have been delivered and billed)
    the next provider is only tried if the org's sms_fallback_on_timeout setting is on, to avoid
    double-sending a voter's code.
    """
    try:
        sec = await security_settings_for(org)
    except Exception as e:                      # settings read must never block a voter's code
        logger.error(f"sms routing settings read failed, using defaults: {e}")
        sec = dict(_SEC_DEFAULTS)
    route = sec.get(f"sms_route_{sms_route_group(kind)}") or "default"
    order = sms_provider_order(route, kind)

    last = "failed"
    for i, provider in enumerate(order):
        last = await _sms_try_provider(provider, to_number, message_text)
        if last in ("ok", "ambiguous"):
            await _safe_count_sms(org, kind)    # ambiguous may have been billed
        if last == "ok":
            return "ok"
        has_next = i + 1 < len(order)
        if last == "ambiguous" and not (has_next and sec.get("sms_fallback_on_timeout")):
            if has_next:
                await log_action("sms_ambiguous_no_fallback", "system", {"primary": provider}, org_id=org)
            return "ambiguous"
        if has_next:
            nxt = order[i + 1]
            logger.warning(f"{_SMS_PROVIDER_LABEL[provider]} failed for {to_number}, falling back to {_SMS_PROVIDER_LABEL[nxt]}.")
            await log_action("sms_provider_fallback", "system", {"primary": provider, "fallback": nxt, "route": route}, org_id=org)

    # Every provider this route allows failed. For "otp" this is the silent-failure case: a voter is
    # sitting on the OTP screen and nothing ever arrives. Tier 1 for otp, warning for anything else.
    names = " and ".join(_SMS_PROVIDER_LABEL[p] for p in order)
    level = "critical" if kind == "otp" else "warning"
    await send_alert(
        f"SMS send failed ({kind})",
        f"{names} failed sending to {to_number} (route: {route}). Org: {org}. Kind: {kind}.",
        level=level,
    )
    return "failed"


async def send_sms_status(to_number: str, message_text: str, request: Request | None = None,
                          kind: str = "otp", org_id: str | None = None) -> str:
    """Single entrypoint every route should call to send an SMS. Returns "ok", "failed" or "ambiguous".

    Provider order comes from the org's SMS routing setting (see SMS_ROUTES / sms_provider_order),
    which defaults to the original behaviour. Every provider send is counted toward the election budget.
    """
    org = request.state.org_id if request is not None else org_id
    if org and await _demo_active(org):
        return await _demo_capture(org, to_number, message_text, kind)
    if DEBUG_MODE:
        # Local/load-testing only: never hit either real API. Log the message (which contains the OTP)
        # so Locust or a manual tester can read it back, and report success.
        logger.info(f"[DEBUG_MODE] SMS to {to_number}: {message_text}")
        await _safe_count_sms(org, kind)
        return "ok"

    return await _send_sms_routed(to_number, message_text, org, kind)


async def send_sms(to_number: str, message_text: str, request: Request | None = None,
                   kind: str = "otp", org_id: str | None = None) -> bool:
    """Boolean wrapper over send_sms_status(): True only on a confirmed send."""
    return await send_sms_status(to_number, message_text, request, kind, org_id) == "ok"


# =============================================================================
# PASSWORD HELPERS
# =============================================================================

def generate_temp_password() -> str:
    """12 chars from an unambiguous alphabet (no 0/O/1/I/l), ~62 bits of entropy.
    The previous 6 digits (1e6 possibilities, no expiry) were guessable by an
    online brute force against /admin/login well within LOGIN_MAX_ATTEMPTS's
    15-minute lockout window resetting per attempt cycle."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return ''.join(secrets.choice(alphabet) for _ in range(12))


# A temp password used to be permanent: if nobody ever logged in with it, it worked forever.
TEMP_PASSWORD_EXPIRE_HOURS = int(os.getenv("TEMP_PASSWORD_EXPIRE_HOURS", "24"))
# The superadmin can reset elections, force-approve applications, and read every tenant —
# a shorter session than the other roles limits how long a stolen superadmin token is useful.
SUPERADMIN_JWT_EXPIRE_MINUTES = int(os.getenv("SUPERADMIN_JWT_EXPIRE_MINUTES", "60"))

# Guide 6.4 / 6.6 (P5): what a panel token may reach. Panel tokens are blocked from every
# admin area except the panel's own routes; route guards still apply inside those.
from auth import JWT_EXPIRE_MINUTES as _JWT_MINUTES
PANEL_GUARDED_PREFIXES = ("/admin/", "/commission/", "/overseer/", "/superadmin/", "/it-admin/", "/financial-controller/")
PANEL_ALLOWED_PREFIXES = ("/admin/applications", "/admin/vetting-", "/admin/approval-policy",
                          "/admin/switch-hat", "/admin/set-password", "/admin/logout")
# Guide 6.4 rule 5: externals must accept this notice before anything else. Bump the version to re-ask.
CONFIDENTIALITY_VERSION = "2026-10-v1"
# /admin/set-password must be here: a temp-password token is scoped to set-password only, so without it an
# external could neither change the password (blocked by this gate) nor accept the notice (blocked by the scope).
CONFIDENTIALITY_ALLOWED_PATHS = {"/admin/vetting-me", "/admin/vetting-confidentiality/accept", "/admin/logout",
                                 "/admin/set-password"}
CONFIDENTIALITY_NOTICE = (
    "You are serving on the Vetting Panel as a non-member. Everything you see here is confidential: "
    "applicant details, votes, panel discussion and the reasons behind decisions. Do not share or copy it. "
    "Your access ends automatically at the time shown below.")
OVERSEER_PAUSED_ALLOWED_PATHS = {"/admin/switch-hat", "/admin/panel-link", "/admin/set-password", "/admin/logout"}
SCOPE_PASSWORD_CHANGE_ONLY = "password_change_only"
PASSWORD_CHANGE_ONLY_ALLOWED_PATHS = {"/admin/set-password", "/admin/logout"}


def _login_token_for(voter: dict, role: str, must_change_field: str, org_id: str | None,
                     expires_at: datetime | None = None) -> str:
    """A temp-password login (must_change_field still true) gets a token that the guard
    will accept ONLY for /admin/set-password and /admin/logout — so an intercepted temp
    password's token can't be used to touch anything else even if the client is buggy or
    the person never opens the change-password screen."""
    must_change = voter.get(must_change_field, True)
    # Panel members are keyed by panel_member_id, not student_id (guide 6.3/6.6). A MEMBER's panel
    # record also carries a student_id (its link to the voter row); preferring that gave the token a
    # subject the guard could not resolve, so every member panelist who logged in directly was
    # rejected on every request. Voter documents have no panel_member_id, so they are unaffected.
    subject = voter.get("panel_member_id") or voter.get("student_id")
    return create_access_token(
        subject=subject, role=role, org_id=org_id,
        full_name=voter.get("full_name", ""),
        scope=SCOPE_PASSWORD_CHANGE_ONLY if must_change else "full",
        # Guide 6.4 rule 6: a panel token never outlives the access end.
        expire_minutes=(max(1, min(_JWT_MINUTES, int((expires_at - datetime.utcnow()).total_seconds() // 60)))
                        if expires_at else None),
    )


async def _invalidate_sessions(voter_id) -> dict:
    """Stamp used in an update_one's $set: any token issued before this moment for this
    account stops working at the NEXT request (checked in auth_guard_middleware), even
    though the JWT itself hasn't expired yet. Call this whenever a password is set/reset
    or a role is revoked."""
    return {"sessions_valid_after": datetime.utcnow()}

def hash_password(plain_password: str) -> str:
    # bcrypt silently truncates at 72 bytes; reject rather than truncate so a
    # long passphrase can never be shortened into a weaker one without notice.
    encoded = plain_password.encode()
    if len(encoded) > 72:
        raise HTTPException(400, "Password must be 72 bytes or fewer.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()


MIN_PASSWORD_LENGTH = 10


def _assert_password_strength(password: str):
    """These accounts control an election. A 6-character minimum was well
    inside offline-cracking range for anyone who ever got a dump of the
    hashes."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    if classes < 3:
        raise HTTPException(
            400,
            "Password must combine at least three of: lowercase, uppercase, numbers, symbols.",
        )

# =============================================================================
# MULTI-TENANCY HELPERS
# =============================================================================

async def generate_unique_org_slug(name: str) -> str:
    """Slugify an org name and guarantee uniqueness against existing orgs."""
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    if not base:
        base = "org"
    slug = base
    suffix = 1
    while await db.organizations.find_one({"slug": slug}):
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug

def require_org(org_id) -> str:
    """Return org_id, or refuse. There is no unscoped / "legacy default tenant" mode: a missing tenant
    is a 400, never a filter-less query that would match every client's documents."""
    if not org_id:
        raise HTTPException(400, "X-Org-Slug header is required.")
    return str(org_id)

def org_query(request: Request, extra: dict = None) -> dict:
    """
    Merge tenant scoping into a query filter. Fails closed: if the request has no resolved
    organization it raises (400) instead of returning an unscoped filter.
    """
    q = dict(extra) if extra else {}
    q["org_id"] = require_org(getattr(request.state, "org_id", None))
    return q

def org_stamp(request: Request, doc: dict) -> dict:
    """Stamp a new document with the current org_id. Refuses to write an ownerless (org_id=None) doc."""
    doc = dict(doc)
    doc["org_id"] = require_org(getattr(request.state, "org_id", None))
    return doc

async def get_vote_counts(request: Request) -> dict[str, int]:
    """
    Aggregate vote_events into per-candidate counts, scoped to the current
    org. Replaces reads of the old candidates.votes counter now that writes
    go to vote_events instead (see /vote, /vote-bulk). Candidates with zero
    votes won't have a group row at all, so callers use
    counts.get(str(candidate_id), 0) rather than indexing directly.
    """
    counts: dict[str, int] = {}
    async for row in tdb(request).vote_events.aggregate([
        {"$match": org_query(request)},
        {"$group": {"_id": "$candidate_id", "count": {"$sum": 1}}}
    ]):
        counts[str(row["_id"])] = row["count"]
    return counts

# ── Ballot secrecy against an insider (SEC audit, "Open" item 3) ─────────────────────────────────
# vote_events deliberately holds no voter id. But a precise cast_at plus a time-ordered ObjectId _id let
# someone with DB or backup access sort ballots into the exact order voters appeared in audit_log
# ("vote_cast", a few ms apart) and pair each voter to a ballot. So:
#   * cast_at is rounded DOWN to a coarse bucket (default 10 minutes),
#   * the _id's timestamp is the bucket's END and the other 8 bytes are random, so _id order is
#     bucket order and random inside a bucket (it still sorts the hash chain deterministically),
#   * the "vote_cast" audit entry is stamped with the same bucket start instead of the exact instant.
# Anyone can still tell WHICH bucket a voter and a ballot fell in, but not which ballot is whose.
# Turnout analytics (hourly / daily) are unaffected. Existing events keep their old precise values and
# still verify, because the chain hashes whatever cast_at / _id is stored.
VOTE_TIME_BUCKET_SECONDS = max(60, int(os.getenv("VOTE_TIME_BUCKET_SECONDS", "600")))
# A bucket is only folded into a checkpoint once it ended this long ago, so a transaction still in
# flight can never land behind a checkpoint's to_id (it would be skipped by every later checkpoint).
CHECKPOINT_SEAL_GRACE_SECONDS = 60


def _vote_bucket_start(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    epoch = calendar.timegm(now.utctimetuple())
    return datetime.utcfromtimestamp(epoch - (epoch % VOTE_TIME_BUCKET_SECONDS))


def _new_vote_event_stamp(now: datetime | None = None) -> tuple[ObjectId, datetime]:
    """(_id, cast_at) for one ballot event: coarse time, unordered inside its bucket."""
    start = _vote_bucket_start(now)
    end_epoch = calendar.timegm(start.utctimetuple()) + VOTE_TIME_BUCKET_SECONDS
    return ObjectId(struct.pack(">I", end_epoch) + os.urandom(8)), start


async def _publish_checkpoint_externally(checkpoint: dict) -> None:
    """
    Uploads the checkpoint to Backblaze B2 with Object Lock in compliance
    mode, retained for 10 years — nobody, including whoever holds these B2
    credentials, can delete or modify this object before then. This is what
    makes the audit chain resistant to tampering by someone with the Mongo
    connection string, not just accidental overwrites.

    boto3 is synchronous, so this runs in FastAPI's threadpool rather than
    blocking the event loop. If the upload fails (B2 down, bad credentials),
    the checkpoint still exists in Mongo — this failure is logged but never
    raised, since a missed external anchor shouldn't break checkpoint
    creation for callers.
    """
    key = f"{checkpoint['org_id']}/{checkpoint['to_id']}.json"

    if b2_client is None:
        logging.error(f"B2 checkpoint anchor skipped for {key}: B2 client not configured")
        await log_action("audit_checkpoint_anchor_failed", "system", {
            "checkpoint_id": str(checkpoint.get("_id", "")),
            "error": "B2 client not configured (see startup logs)",
        }, org_id=checkpoint.get("org_id"))
        return

    body = json.dumps({
        "org_id": checkpoint["org_id"],
        "from_id": str(checkpoint["from_id"]) if checkpoint["from_id"] else None,
        "to_id": str(checkpoint["to_id"]),
        "event_count": checkpoint["event_count"],
        "prev_chain_hash": checkpoint["prev_chain_hash"],
        "chain_hash": checkpoint["chain_hash"],
        "roster_ledger_seq": checkpoint.get("roster_ledger_seq", 0),
        "roster_ledger_head": checkpoint.get("roster_ledger_head"),
        "created_at": checkpoint["created_at"].isoformat(),
    }, indent=2)

    retain_until = datetime.utcnow() + timedelta(days=3650)

    try:
        await run_in_threadpool(
            b2_client.put_object,
            Bucket=B2_BUCKET_NAME,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
        )
    except Exception as e:
        logging.error(f"B2 checkpoint anchor failed for {key}: {e}")
        await log_action("audit_checkpoint_anchor_failed", "system", {
            "checkpoint_id": str(checkpoint.get("_id", "")),
            "error": str(e),
        }, org_id=checkpoint.get("org_id"))


async def create_audit_checkpoint(request: Request) -> dict | None:
    """
    Folds every vote_event since the last checkpoint into a hash chain and
    records one new audit_checkpoints document. Returns None if there are no
    new events to checkpoint, or if a concurrent call already claimed this
    range (see the from_id unique index in lifespan()). Deliberately
    excludes voter_id from the hash input (vote_events never stores it —
    see /vote) so the chain itself carries no voter-identity risk.
    """
    org_id = require_org(request.state.org_id)
    await anchor_roster_ledger(request)   # ledger head goes to B2 Object Lock even when there are no new ballots
    ledger_head = await tdb(request).roster_ledger.find_one({"org_id": org_id}, sort=[("seq", -1)])
    last = await db.audit_checkpoints.find_one(
        org_query(request), sort=[("to_id", -1)]
    )
    prev_hash = last["chain_hash"] if last else "GENESIS"

    match: dict = org_query(request)
    if last:
        match["_id"] = {"$gt": last["to_id"]}
    # Only buckets that ended more than the grace period ago. Event _ids are bucket-ordered, so every
    # event left out here sorts AFTER every event folded in, and a later checkpoint picks it up.
    sealed_before = _vote_bucket_start(datetime.utcnow() - timedelta(seconds=CHECKPOINT_SEAL_GRACE_SECONDS))
    match["cast_at"] = {"$lt": sealed_before}
    events = await tdb(request).vote_events.find(match).sort("_id", 1).to_list(length=None)
    if not events:
        return None

    chain_hash = prev_hash
    for ev in events:
        payload = f"{chain_hash}|{ev['_id']}|{ev['candidate_id']}|{ev['cast_at'].isoformat()}"
        chain_hash = hashlib.sha256(payload.encode()).hexdigest()

    checkpoint = org_stamp(request, {
        "from_id": last["to_id"] if last else None,
        "to_id": events[-1]["_id"],
        "event_count": len(events),
        "prev_chain_hash": prev_hash,
        "chain_hash": chain_hash,
        "roster_ledger_seq": ledger_head["seq"] if ledger_head else 0,
        "roster_ledger_head": ledger_head["hash"] if ledger_head else None,
        "created_at": datetime.utcnow(),
    })

    try:
        await db.audit_checkpoints.insert_one(checkpoint)
    except DuplicateKeyError:
        # Another call (cron + manual trigger overlapping, or a double-fired
        # scheduler tick) already checkpointed this range. Not an error —
        # the loser's events get picked up by whichever checkpoint runs next.
        return None

    await _publish_checkpoint_externally(checkpoint)
    await log_action("audit_checkpoint_created", current_actor(request), {
        "event_count": len(events),
        "chain_hash": chain_hash,
    }, org_id=org_id)
    return checkpoint


async def verify_audit_chain(request: Request) -> dict:
    """
    Independent re-derivation of the entire chain straight from vote_events
    — doesn't trust the stored chain_hash values, recomputes every one of
    them and compares. This is what makes the chain actually auditable
    rather than decorative: run this and the checkpoints either match the
    raw event log or they don't.
    """
    checkpoints = await db.audit_checkpoints.find(
        org_query(request)
    ).sort("to_id", 1).to_list(length=None)

    chain_hash = "GENESIS"
    for cp in checkpoints:
        match: dict = org_query(request, {
            "_id": {"$gt": cp["from_id"], "$lte": cp["to_id"]} if cp["from_id"]
                   else {"$lte": cp["to_id"]}
        })
        events = await tdb(request).vote_events.find(match).sort("_id", 1).to_list(length=None)

        recomputed = chain_hash
        for ev in events:
            payload = f"{recomputed}|{ev['_id']}|{ev['candidate_id']}|{ev['cast_at'].isoformat()}"
            recomputed = hashlib.sha256(payload.encode()).hexdigest()

        if recomputed != cp["chain_hash"]:
            return {
                "valid": False,
                "first_mismatch_checkpoint_id": str(cp["_id"]),
                "expected": cp["chain_hash"],
                "recomputed": recomputed,
            }
        chain_hash = cp["chain_hash"]

    return {"valid": True, "checkpoints_verified": len(checkpoints), "head_hash": chain_hash}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except Exception:
        return False


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """bcrypt takes roughly 100-250 ms of pure CPU; run on the event loop it stalls every other request
    (voters included) for that long on each login. Handlers call this instead of verify_password."""
    return await run_in_threadpool(verify_password, plain_password, hashed_password)


# Fixed bcrypt hash of an arbitrary, unused password — used only to burn a
# realistic amount of CPU time on the "no matching account" path in
# /verify-admin, so that path can't be distinguished from a real
# wrong-password check by response timing. See the SECURITY comment at its
# call site.
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode().encode()

async def send_temp_password_sms(voter: dict, role_label: str, temp_password: str) -> bool:
    phone_list = voter.get("phone_numbers", [])
    if not phone_list:
        return False

    # Was unscoped ({"name": "branding"} with no org filter) — in a
    # multi-tenant deployment this could read a DIFFERENT org's branding
    # doc and quote the wrong organization's name in this voter's SMS.
    # voter["org_id"] is the source of truth for which org this voter
    # belongs to (set at import time), not the caller's request context,
    # since some callers here run outside a request (e.g. scripts).
    branding_doc = (await tdb_for(voter["org_id"]).settings.find_one({"name": "branding"})
                    if voter.get("org_id") else None)
    sms_org_name = (branding_doc or {}).get("org_name", "Election")

    message = (
        f"Hello {voter.get('full_name', 'User')}, your temporary {role_label} login code "
        f"for the {sms_org_name} Election Portal is {temp_password}. "
        f"You will be asked to set a new password on first login. "
        f"Do not share this code with anyone."
    )
    return await send_sms(phone_list[0], message, kind="admin", org_id=voter.get("org_id"))

# --- Application consensus helpers ---

@app.get("/admin/approval-policy")
async def get_approval_policy(request: Request,
                               admin: dict = Depends(require_role("commission", "vetting"))):
    """Read-only view of the active policy. The majority is taken over the Vetting Panel (guide 7, item 2);
    the commissioner count is shown to commissioners for oversight only."""
    sec = await security_settings_for(request.state.org_id)
    panel = await get_panel_count(request.state.org_id)
    out = {
        "policy": sec["approval_policy"],
        "panel_count": panel,
        "required_for_majority_total": (panel // 2) + 1,
    }
    if admin.get("role") == "commission":
        out["total_commissioners"] = await get_commissioner_count(request.state.org_id)
    return out


async def get_commissioner_count(org_id: str) -> int:
    q = {"is_commissioner": True, "org_id": require_org(org_id)}
    return await tdb_for(org_id).voters.count_documents(q)

async def _resolve_position_title(position_id: str, org_id: str) -> tuple[str, int]:
    """Returns (title, order) for a position id, with safe fallbacks."""
    org_id = require_org(org_id)      # outside the try: a missing tenant must not be swallowed
    try:
        q = {"_id": ObjectId(position_id), "org_id": org_id}
        pos = await tdb_for(org_id).positions.find_one(q)
        if pos:
            return pos.get("title", position_id), pos.get("order", 0)
    except Exception:
        pass
    return position_id, 0

async def _create_candidate_from_application(app_doc: dict, org_id: str):
    org_id = require_org(org_id)
    title, order = await _resolve_position_title(app_doc.get("position_id", ""), org_id)
    # Same fallback _issue_certificate uses. This runs AFTER the status flip to "approved", so a KeyError here
    # would leave an approved application with no candidate and no way to retry.
    await tdb_for(org_id).candidates.insert_one({
        "name": app_doc.get("full_name")
                or (app_doc.get("application_snapshot") or {}).get("full_name", ""),
        "position": title,
        "image_url": app_doc.get("image_url", ""),
        "order": order,
        "votes": 0,
        "application_id": str(app_doc["_id"]),
        "org_id": org_id,
        "is_demo": bool(app_doc.get("is_demo")),
    })

async def _position_fee(position_id: str, org_id: str) -> int:
    """Nomination fee (UGX) configured on a position; 0 when none/unknown."""
    org_id = require_org(org_id)
    try:
        q = {"_id": ObjectId(position_id), "org_id": org_id}
        pos = await tdb_for(org_id).positions.find_one(q)
        return int((pos or {}).get("application_fee") or 0)
    except Exception:
        return 0


def fmt_ugx(n) -> str:
    return f"UGX {int(n or 0):,}"


async def _notify_applicant(app_doc: dict, org_id: str, text_for) -> str:
    """Best-effort SMS to the applicant's first registered number. `text_for(org_name, position_title)` -> str.
    Never raises and never blocks the decision that triggered it. Returns 'sent' | 'failed' | 'no_phone'."""
    try:
        voter = await tdb_for(org_id).voters.find_one({**get_forgiving_filter(app_doc.get("student_id", "")), "org_id": org_id})
        phones = (voter or {}).get("phone_numbers") or []
        if not phones:
            return "no_phone"
        b = await tdb_for(org_id).settings.find_one({"name": "branding", "org_id": org_id}) or {}
        title, _ = await _resolve_position_title(app_doc.get("position_id", ""), org_id)
        text = text_for(b.get("org_name") or "the election", title)
        ok = await send_sms(phones[0], text, None, kind="notice", org_id=org_id)
        return "sent" if ok else "failed"
    except Exception as e:
        logger.error(f"applicant SMS failed: {e}")
        return "failed"


def _vote_key(student_id: str) -> str:
    """One canonical key per commissioner (bind_identity normalizes, the old key did not)."""
    return normalize_student_id(student_id).replace(".", "_").replace("/", "_").replace("$", "_")


def _dedupe_votes(votes: dict) -> dict:
    return {_vote_key(k): v for k, v in (votes or {}).items()}


def _tally_outcome(policy: str, total: int, approve: int, deny: int) -> str | None:
    """Returns 'approve', 'deny', or None (still undecided) for the given
    policy and vote counts. Pure function — no DB access — so it's easy to
    unit-test independently of the Mongo write/atomic-guard dance around it."""
    if total == 0:
        return None
    cast = approve + deny

    if policy == "unanimous":
        if approve == total:
            return "approve"
        if deny == total:
            return "deny"
        return None

    if policy == "majority_cast":
        if cast < total:
            return None  # not everyone has voted yet
        if approve > deny:
            return "approve"
        if deny > approve:
            return "deny"
        return None  # exact tie — left pending, see _flag_tie_for_chief

    # default / "majority_total"
    required = (total // 2) + 1
    if approve >= required:
        return "approve"
    if deny >= required:
        return "deny"
    return None


async def _flag_tie_for_chief(app_id: str, org_id: str):
    """Flag a tie (name kept for data compatibility, guide 7.2). Logged once per tie, not on every re-check."""
    result = await tdb_for(org_id).applications.update_one(
        {"_id": ObjectId(app_id), "tied_pending_chief": {"$ne": True}},
        {"$set": {"tied_pending_chief": True}}
    )
    if result.matched_count:
        await log_action("application_vote_tied", "vetting", {"app_id": app_id}, org_id=org_id)


async def _issue_certificate(app_doc: dict, org_id: str = None):
    """
    Called at the moment an application is approved (commission vote or
    superadmin force-approve) — candidate-portal-spec §3.5. Inserts a
    minimal, public-safe row into `certificates` (never a copy of the full
    `applications` doc) and stamps `certificate_id`/`certificate_issued_at`
    back onto the application. This row *is* the snapshot: nothing else is
    rendered or stored server-side, the frontend prints the certificate
    component from these fields plus branding.
    """
    title, _ = await _resolve_position_title(app_doc.get("position_id", ""), org_id)
    b = await tdb_for(org_id).settings.find_one({"name": "branding", "org_id": org_id}) or {}
    certificate_id = f"CERT-{secrets.token_hex(6).upper()}"   # 48 bits, unambiguous charset
    issued_at = datetime.utcnow()
    await tdb_for(org_id).certificates.insert_one({
        "certificate_id": certificate_id,
        "org_id": org_id,
        "candidate_name": app_doc.get("full_name")
                          or (app_doc.get("application_snapshot") or {}).get("full_name", ""),
        "position_title": title,
        "org_name": b.get("org_name", ""),
        "issued_at": issued_at,
        "revoked": False,
        "is_demo": bool(app_doc.get("is_demo")),
    })
    await tdb_for(org_id).applications.update_one(
        {"_id": ObjectId(str(app_doc["_id"]))},
        {"$set": {"certificate_id": certificate_id, "certificate_issued_at": issued_at}}
    )


async def _record_denial_snapshot(app_doc: dict, org_id: str, *, finance_reason: str | None = None):
    """
    Called at the moment an application is denied, from any of the three
    denial paths (commission vote, finance rejection, superadmin
    force-deny) — candidate-portal-spec §3.5. A standard denial: no reason is
    recorded or shown. Freezes the fields the plain denial-notice renders; a later correction to the
    candidate's live record never changes what already "printed".
    """
    title, _ = await _resolve_position_title(app_doc.get("position_id", ""), org_id)
    decided_at = datetime.utcnow()
    await tdb_for(org_id).applications.update_one(
        {"_id": ObjectId(str(app_doc["_id"]))},
        {"$set": {
            "denial_snapshot": {
                "full_name": app_doc.get("full_name", ""),
                "position_title": title,
                "decided_at": decided_at,
                # Only a Financial Controller rejection carries these: the candidate's portal shows the
                # reason and tells them to contact Finance. A commission denial leaves them out.
                **({"denied_by": "Financial Controller", "reason": finance_reason} if finance_reason else {}),
            },
        }}
    )


async def _revoke_certificate_for_application(app_doc: dict, org_id: str = None):
    """
    Called when an approved candidate is removed (commission removal-vote
    majority or superadmin force-removal) — candidate-portal-spec §3.7. The
    certificate row is never deleted, only flipped to revoked, so a stale
    printed copy still resolves at /verify/{certificate_id} but correctly
    shows as no longer valid rather than disappearing or still confirming.
    """
    certificate_id = app_doc.get("certificate_id")
    if not certificate_id:
        return
    await tdb_for(org_id).certificates.update_one(
        {"certificate_id": certificate_id, "org_id": org_id},
        {"$set": {"revoked": True}}
    )


RESOLVED_STATUSES = ("approved", "denied", "removed")
_HIDDEN_APPLICATION_FIELDS = ("votes", "removal_votes", "revert_history", "tied_pending_chief", "tie_break")
# Data minimisation (SEC audit, "Open" item 5): payment details exist so the Financial Controller can
# clear or reject a payment. No other role's screen reads them, so they are not sent to any other role.
# The booleans (finance_cleared / finance_rejected) and fee_required stay: the vetting and overseer
# dashboards use them to show whether voting can open.
_FINANCE_ONLY_APPLICATION_FIELDS = ("payment_method", "payment_proof_url", "finance_clear_note",
                                    "finance_rejection_reason", "finance_history")
PANEL_HIDDEN_AUDIT_ACTIONS = ("application_vote_tied", "application_tie_broken")


async def _live_panelists(org_id: str = None) -> list:
    """Active panelists whose access has not ended. Expired externals are dropped from the approval
    denominator and from the counted votes, otherwise unanimous / majority-of-total policies can never
    resolve once an external's access ends mid-vote. Read live, so extending a phase restores them."""
    doc = await cached_setting(org_id, "election_phases")
    phases = (doc or {}).get("phases", {}) or {}
    now = datetime.utcnow()
    live = []
    async for p in tdb_for(org_id).panel_members.find({"active": True}):
        ends = []
        if p.get("access_expires_at"):
            ends.append(naive_utc(p["access_expires_at"]))
        phase_end = (phases.get(p.get("expires_with_phase")) or {}).get("end") if p.get("expires_with_phase") else None
        if phase_end:
            ends.append(naive_utc(phase_end))
        if ends and now >= min(ends):
            continue
        live.append(p)
    return live


async def get_panel_count(org_id: str = None) -> int:
    """Active, unexpired Vetting Panel members: the approval denominator (guide 7, item 1)."""
    return len(await _live_panelists(org_id))


def _panel_vote_key(p: dict) -> str:
    """Members vote under their student_id, so migrated votes still map to the same person (guide 8.1).
    Externals have no voter row and vote under their PM- id."""
    if p.get("is_member") and p.get("student_id"):
        return _vote_key(p["student_id"])
    return _vote_key(p["panel_member_id"])


async def _active_panel_keys(org_id: str = None) -> set:
    return {_panel_vote_key(p) for p in await _live_panelists(org_id)}


async def _has_live_application(request: Request, student_id: str) -> bool:
    """Guide 6.5: an applicant (not yet denied or removed) cannot sit on the panel."""
    return bool(await tdb(request).applications.find_one({
        "student_id": normalize_student_id(student_id),
        "status": {"$nin": ["denied", "removed"]}}))


async def _panel_access_end(request: Request, p: dict) -> datetime | None:
    """Guide 6.4 rule 6: the earlier of a fixed date and the end of the chosen timeline phase.
    Read live, so extending the phase extends access. None means no end is set."""
    ends = []
    if p.get("access_expires_at"):
        ends.append(naive_utc(p["access_expires_at"]))
    phase = p.get("expires_with_phase")
    if phase:
        end = (await get_phase_schedule(request))["phases"].get(phase, {}).get("end")
        if end:
            ends.append(naive_utc(end))
    return min(ends) if ends else None


async def _panel_access_ended(request: Request, p: dict) -> bool:
    end = await _panel_access_end(request, p)
    return bool(end) and datetime.utcnow() >= end


async def _external_has_no_end(request: Request, p: dict) -> bool:
    """True for a non-member whose access end cannot be resolved right now (guide 6.4 rule 6 makes the
    end mandatory for externals). Happens when only a timeline phase was chosen and that phase has no end
    date, so nothing would ever close the account. Used to refuse NEW logins, fail-closed."""
    return (not p.get("is_member")) and (await _panel_access_end(request, p)) is None


_PANEL_LOGIN_EMAIL_FIELDS = ("it_admin_email", "financial_controller_email", "overseer_email",
                             "commissioner_email")


async def _panel_email_conflict(request: Request, email: str, exclude_pm_id: str | None = None) -> str | None:
    """verify-admin tries each role in turn and the panel branch comes before the commissioner branch,
    so a panel email equal to someone's commissioner (or any other role) email would silently capture
    that person's login and lock them out of their own role. Panel emails must therefore be unique
    across the panel AND across every other role's login email. Returns the message, or None if free."""
    pattern = {"$regex": f"^{re.escape(email)}$", "$options": "i"}
    q = {"email": pattern}
    if exclude_pm_id:
        q["panel_member_id"] = {"$ne": exclude_pm_id}
    if await tdb(request).panel_members.find_one(q, {"_id": 1}):
        return "A panel member with this email already exists."
    if await tdb(request).voters.find_one({"$or": [{f: pattern} for f in _PANEL_LOGIN_EMAIL_FIELDS]},
                                {"_id": 1}):
        return ("This email is already the login email of another admin role. Use a different email so "
                "each login resolves to exactly one role.")
    return None


async def _acting_panelist(request: Request, admin: dict) -> dict:
    """The signed-in panel account, or 403. Checked on every vetting action."""
    p = await tdb(request).panel_members.find_one({"panel_member_id": admin.get("sub"), "active": True})
    if not p:
        raise HTTPException(403, "You are not an active member of the Vetting Panel.")
    if await _panel_access_ended(request, p):
        raise HTTPException(403, "Your panel access has ended.")
    return p


async def _panel_actor_context(request: Request) -> tuple:
    """(vote key, is Chair) for a signed-in panelist; (None, False) for every other role."""
    if current_role(request) != "vetting":
        return None, False
    p = await tdb(request).panel_members.find_one({"panel_member_id": current_actor(request), "active": True})
    if not p:
        return None, False
    is_chair = False
    if p.get("is_member") and p.get("student_id"):
        is_chair = bool(await tdb(request).voters.find_one({
            **get_forgiving_filter(p["student_id"]), "is_chief_commissioner": True}))
    return _panel_vote_key(p), is_chair


def _is_tied(policy: str, panel_total: int, approve: int, deny: int) -> bool:
    """Guide 7.2: an even split once every active panelist has voted, under a policy that can tie."""
    return (policy in ("majority_cast", "majority_total") and panel_total > 0
            and approve + deny == panel_total and approve == deny)


def _shape_nomination_fields(out: dict) -> None:
    """N3: replace the stored `nomination_form` metadata with flat flags. Only the filename is shown; the upload id,
    storage key and any link stay server-side and are reachable only through the audited read-back route."""
    nf = out.pop("nomination_form", None)
    has = isinstance(nf, dict) and bool(nf.get("upload_id"))
    out["has_nomination_form"] = has
    out["nomination_form_filename"] = nf.get("filename") if has else None
    out["nomination_form_required"] = bool(out.get("nomination_form_required"))   # absent on older applications


# Visibility tiers for applications. Tier 1 = the stage only (no vote information); only the Vetting Panel
# (and the superadmin, for diagnosis) see vote counts. Every other role is held to tier 1 below.
STAGE_LABELS = {
    "finance_pending":  "Pending financial approval",
    "finance_rejected": "Payment rejected",
    "with_panel":       "With the Vetting Panel",
    "approved":         "Approved",
    "denied":           "Denied",
    "removed":          "Removed",
}


def application_stage(app: dict) -> str:
    """One stage code per application, derived from existing fields (nothing is stored). Deliberately coarse:
    'with_panel' also covers 'all votes in' and 'tied, waiting for the chair', so it never hints at voting."""
    status = app.get("status", "pending")
    if status in RESOLVED_STATUSES:
        return status
    if (app.get("fee_required") or 0) > 0 and not app.get("finance_cleared"):
        return "finance_rejected" if app.get("finance_rejected") else "finance_pending"
    return "with_panel"


_IT_ADMIN_APPLICATION_FIELDS = ("_id", "student_id", "full_name", "position_id", "position_title",
                                "position_order", "submitted_at", "status")


def shape_application_for_role(app: dict, role: str, *, actor_key: str | None = None,
                               active_keys=frozenset(), panel_count: int = 0,
                               is_chair_panelist: bool = False) -> dict:
    """Guide 7.1: the one place that decides what each role may see of an application.
    Returns a copy. Only the superadmin receives the raw vote maps."""
    out = dict(app)
    stage = application_stage(app)
    if role == "it_admin":
        # Whitelist, not blacklist: a field added to applications later never reaches this role by accident.
        shaped = {f: out[f] for f in _IT_ADMIN_APPLICATION_FIELDS if f in out}
        shaped["stage"], shaped["stage_label"] = stage, STAGE_LABELS[stage]
        return shaped
    _shape_nomination_fields(out)       # every role, superadmin included: the browser never gets an upload id
    raw = _dedupe_votes(app.get("votes", {}))
    votes = {k: v for k, v in raw.items() if k in active_keys}
    approve = sum(1 for v in votes.values() if v == "approve")
    deny = sum(1 for v in votes.values() if v == "deny")
    cast = len(votes)
    resolved = app.get("status", "pending") in RESOLVED_STATUSES
    awaiting = (not resolved) and panel_count > 0 and cast == panel_count
    tied = (not resolved) and bool(app.get("tied_pending_chief"))

    out["stage"], out["stage_label"] = stage, STAGE_LABELS[stage]
    if role == "superadmin":
        out["progress"] = {"cast": cast, "panel_count": panel_count}
        out["awaiting_final_decision"] = awaiting
        if resolved:
            out["final_split"] = {"approve": approve, "deny": deny}
        return out

    for field in _HIDDEN_APPLICATION_FIELDS:
        out.pop(field, None)
    if role != "financial_controller":
        for field in _FINANCE_ONLY_APPLICATION_FIELDS:
            out.pop(field, None)
    out.pop("decided_by_tie_break", None)
    out.pop("final_reason", None)

    if role == "vetting":   # vote counts: Vetting Panel only (everyone else is tier 1)
        out["progress"] = {"cast": cast, "panel_count": panel_count}
        out["awaiting_final_decision"] = awaiting
        if resolved:
            out["final_split"] = {"approve": approve, "deny": deny}
            out["decided_by_tie_break"] = bool(app.get("decided_by_tie_break"))
    if role == "vetting":
        out["my_vote"] = votes.get(actor_key) if actor_key else None
        out["tie_break_available"] = bool(is_chair_panelist and tied and awaiting)
    if role in ("vetting", "overseer", "commission") and resolved:
        out["final_reason"] = app.get("final_reason")
    return out


_AUDIT_SID_RE = re.compile(r"[A-Za-z0-9\-]+(?:/[A-Za-z0-9\-]+){2,}")   # registration-number shape: 3+ segments split by "/"
_AUDIT_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")


def _scrub_audit_text(text: str) -> str:
    """Mask registration numbers and email addresses typed into free text (e.g. an admin's `reason`)."""
    text = _AUDIT_EMAIL_RE.sub(lambda m: _mask_email(m.group(0)), text)
    # Needs a letter somewhere, so plain dates such as 12/05/2026 in a reason are left alone.
    return _AUDIT_SID_RE.sub(lambda m: _mask_student_id(m.group(0)) if re.search(r"[A-Za-z]", m.group(0)) else m.group(0), text)


def _mask_audit_identifiers(entry: dict) -> None:
    """Extra masking for every admin role except the superadmin (activity-log transparency without
    broadcasting full student IDs, emails or uploaded-file names). Mutates `entry` in place."""
    actor = entry.get("actor")
    if isinstance(actor, str):
        if "@" in actor:
            entry["actor"] = _mask_email(actor)
        elif _AUDIT_SID_RE.fullmatch(actor):
            entry["actor"] = _mask_student_id(actor)
    details = entry.get("details")
    if not isinstance(details, dict):
        return
    details.pop("nomination_form", None)   # uploaded file names often contain a real name
    for key, val in list(details.items()):
        if not isinstance(val, str):
            continue
        if key == "student_id":
            details[key] = _mask_student_id(val)
        else:
            details[key] = _scrub_audit_text(val)


def _redact_panel_audit(entry: dict, role: str | None = None):
    """Non-superadmin view of audit entries that would reveal who voted how, or the split (guide 8.1)."""
    action = entry.get("action")
    details = dict(entry.get("details") or {})
    if action == "application_vote_cast":
        entry["actor"] = "redacted"
        entry["details"] = {"app_id": details.get("app_id")}
    elif action in ("application_approved", "application_denied"):
        for k in ("approve_count", "deny_count", "panel_count", "total_commissioners"):
            details.pop(k, None)
        # A tie-break resolution is logged under the Chair's panel id with tie_break=True. Neither the
        # Chair's identity nor the marker may reach roles outside vetting (guide 7.1 / 7.2). The
        # overseer may learn THAT it was decided by tie-break, never who decided it.
        if details.get("tie_break"):
            entry["actor"] = "vetting"
            if role != "overseer":
                details.pop("tie_break", None)
        entry["details"] = details


async def _apply_application_outcome(app_id: str, app_doc: dict, org_id: str, outcome: str, *,
                                     actor: str, details: dict, extra_set: dict | None = None) -> bool:
    """The single resolution path for votes, the Chair's tie-break and re-evaluation (guide 8.1).
    The status flip is the atomic guard: a caller that loses the race changes nothing."""
    new_status = "approved" if outcome == "approve" else "denied"
    result = await tdb_for(org_id).applications.update_one(
        {"_id": ObjectId(app_id), "status": {"$nin": list(RESOLVED_STATUSES)}},
        {"$set": {"status": new_status, **(extra_set or {})}, "$unset": {"tied_pending_chief": ""}}
    )
    if result.matched_count == 0:
        return False
    if outcome == "approve":
        try:
            await _create_candidate_from_application(app_doc, org_id)
            await _issue_certificate(app_doc, org_id)
        except Exception:
            # Compensating rollback: the status flip above is already committed, so a failure here would
            # leave an approved application with no candidate. Undo what may have been written and put
            # the application back to its prior open state so the next vote / resweep retries it.
            logger.exception(f"Approval side effects failed for application {app_id}; rolling back.")
            try:
                await tdb_for(org_id).candidates.delete_many({"application_id": str(app_doc["_id"])})
                await _revoke_certificate_for_application(app_doc, org_id)
            except Exception:
                logger.exception(f"Rollback cleanup failed for application {app_id}.")
            await tdb_for(org_id).applications.update_one(
                {"_id": ObjectId(app_id), "status": "approved"},
                {"$set": {"status": app_doc.get("status") or "pending"}})
            raise
        await log_action("application_approved", actor, {"app_id": app_id, **details}, org_id=org_id)
        await _notify_applicant(app_doc, org_id, lambda org, pos: (
            f"{org}: Congratulations! Your nomination for {pos} has been approved. "
            f"Your name will appear on the ballot."))
    else:
        await _record_denial_snapshot(app_doc, org_id)
        await log_action("application_denied", actor, {"app_id": app_id, **details}, org_id=org_id)
        await _notify_applicant(app_doc, org_id, lambda org, pos: (
            f"{org}: Your nomination for {pos} was not approved by the Electoral Commission."))
    return True


async def _resolve_application(app_id: str, app_doc: dict, org_id: str = None):
    """Called after every panel vote and after panel or policy changes. The denominator is the
    active panel (guide 7, item 1), and only active panelists' votes count."""
    panel_total = await get_panel_count(org_id)
    if panel_total == 0:
        return
    policy = (await security_settings_for(org_id))["approval_policy"]
    active = await _active_panel_keys(org_id)
    votes = {k: v for k, v in _dedupe_votes(app_doc.get("votes", {})).items() if k in active}
    approve_count = sum(1 for v in votes.values() if v == "approve")
    deny_count = sum(1 for v in votes.values() if v == "deny")

    outcome = _tally_outcome(policy, panel_total, approve_count, deny_count)
    if outcome:
        applied = await _apply_application_outcome(
            app_id, app_doc, org_id, outcome, actor="vetting",
            details={"approve_count": approve_count, "deny_count": deny_count,
                     "panel_count": panel_total, "policy": policy})
        if applied:
            word = "approved" if outcome == "approve" else "denied"
            logger.info(f"Application {app_id} {word} by vetting panel ({approve_count}/{deny_count} of {panel_total}, policy={policy}).")
        return

    if _is_tied(policy, panel_total, approve_count, deny_count):
        await _flag_tie_for_chief(app_id, org_id)
    else:
        # Re-evaluation found no tie (panel change, expiry or policy change): clear a stale flag (guide 7.2).
        await tdb_for(org_id).applications.update_one(
            {"_id": ObjectId(app_id), "status": {"$nin": list(RESOLVED_STATUSES)}},
            {"$unset": {"tied_pending_chief": ""}})


async def _resolve_removal(app_id: str, app_doc: dict, org_id: str = None):
    """
    Called after every removal vote. Same per-org approval_policy governs
    whether the candidate is removed — see _tally_outcome. A "deny" outcome
    (or no outcome yet) just means the candidate stays, same as before.
    """
    total = await get_commissioner_count(org_id)
    if total == 0:
        return
    policy = (await security_settings_for(org_id))["approval_policy"]

    removal_votes = _dedupe_votes(app_doc.get("removal_votes", {}))
    approve_removals = sum(1 for v in removal_votes.values() if v == "approve")
    deny_removals    = sum(1 for v in removal_votes.values() if v == "deny")

    outcome = _tally_outcome(policy, total, approve_removals, deny_removals)

    if outcome == "approve":
        # Same atomic-guard pattern as _resolve_application: only the caller
        # whose update actually flips status to "removed" proceeds to delete
        # the candidate and log it, so two commissioners racing to cast the
        # deciding removal vote can't both fire the delete/log side effects.
        result = await tdb_for(org_id).applications.update_one(
            {"_id": ObjectId(app_id), "status": "approved"},
            {"$set": {"status": "removed", "removal_votes": {}}, "$unset": {"tied_pending_chief": ""}}
        )
        if result.matched_count == 0:
            return
        cand = await tdb_for(org_id).candidates.find_one({"application_id": app_id})
        await tdb_for(org_id).candidates.delete_one({"application_id": app_id})
        await _revoke_certificate_for_application(app_doc, org_id)
        # Was only logger.info'd — a candidate removed by commission majority
        # never showed up in the Activity Log at all, unlike a superadmin's
        # forced removal (candidate_removed, logged in
        # superadmin_remove_candidate). Same action, same log entry, whoever
        # did it.
        await log_action("candidate_removed", "commission", {
            "name": (cand or {}).get("name"), "position": (cand or {}).get("position"),
            "approve_removals": approve_removals, "total_commissioners": total, "policy": policy,
        }, org_id=org_id)
        logger.info(f"Candidate from application {app_id} removed by commission ({approve_removals}/{total}, policy={policy}).")
    elif outcome == "deny":
        # "deny" here means "keep" — no status change needed, but clear a
        # stale tie flag if this vote broke a previous tie the other way.
        await tdb_for(org_id).applications.update_one({"_id": ObjectId(app_id)}, {"$unset": {"tied_pending_chief": ""}})
    elif policy == "majority_cast" and (approve_removals + deny_removals) == total and approve_removals == deny_removals:
        await _flag_tie_for_chief(app_id, org_id)


async def _safe_resweep(org_id: str, include_removals: bool = True):
    """Panel-membership endpoints (add/link/activate/deactivate a panelist) trigger a resweep purely as
    a side effect of the active-panel count changing, NOT as the thing the caller actually asked for.
    Run as a background task (added via BackgroundTasks.add_task at each call site) so it can't make an
    already-successful "add this panelist" response slow, and wrapped here so a failure inside it — an
    SMS send or certificate generation for some unrelated pending application — can't surface as a
    failure of the panel-membership change that already committed before this runs. Logged, not raised:
    there's no caller left listening by the time this executes, so the only thing an exception here would
    accomplish is an unhandled-task warning in the server log, which this replaces with a clearer one."""
    try:
        await _resweep_pending_after_policy_change(org_id, include_removals=include_removals)
    except Exception:
        logger.exception(f"Resweep of pending applications after a panel change failed for org {org_id}.")


async def _resweep_pending_after_policy_change(org_id: str, include_removals: bool = True):
    """
    Called right after approval_policy changes. Re-evaluates every
    still-open application/removal against the NEW policy immediately,
    instead of waiting for the next vote to land on each one — so a
    switch to a stricter or looser policy takes effect at once, even for
    applications that would already have resolved under the new rule.

    Deliberately opt-in (§9 of the original guide left this out): a
    tighten-mid-round change can flip an outcome with no new commissioner
    action, which is a real behavior change worth being explicit about.
    """
    async for app_doc in tdb_for(org_id).applications.find({"status": "pending"}):
        await _resolve_application(str(app_doc["_id"]), app_doc, org_id)

    if not include_removals:
        return
    async for app_doc in tdb_for(org_id).applications.find({
        "status": "approved", "removal_votes": {"$exists": True, "$ne": {}},
    }):
        await _resolve_removal(str(app_doc["_id"]), app_doc, org_id)

#--IT Administration Helpers---

async def _validate_voter_attrs(org_id: str, attrs: dict | None) -> dict:
    """Validate/normalize only fields enabled for this organisation."""
    attrs = attrs or {}
    fields = await get_voter_fields_for_org(org_id)
    enabled = {f["key"] for f in fields if f.get("enabled")}
    unknown = sorted(set(attrs) - enabled)
    if unknown:
        raise HTTPException(400, f"Unknown or disabled voter field: {unknown[0]}")
    return {k: normalize_attr_value(v) for k, v in attrs.items() if normalize_attr_value(v)}


async def get_voter_fields_for_org(org_id: str) -> list[dict]:
    doc = await tdb_for(org_id).settings.find_one({"org_id": org_id, "name": "voter_fields"}) or {}
    return merge_voter_fields(doc.get("fields"))


async def _execute_student_change(change_doc: dict, org_id: str = None):
    if change_doc["change_type"] == "add":
        # Accept both the new multi-number "phones" list and the older
        # single "phone" field, for any change docs left over from before
        # this became a list.
        raw_phones = change_doc.get("phones") or ([change_doc["phone"]] if change_doc.get("phone") else [])
        phones = []
        for raw in raw_phones:
            if not str(raw or "").strip():
                continue
            clean = normalize_phone_number(raw)
            if clean not in phones:
                phones.append(clean)
        sid = normalize_student_id(change_doc["student_id"])
        q = {"student_id": sid, "org_id": require_org(org_id)}
        if await tdb_for(org_id).voters.find_one(q, {"_id": 1}):
            raise HTTPException(409, "Already registered, use Edit Student.")
        attrs = await _validate_voter_attrs(org_id, change_doc.get("attrs"))
        set_doc = {
            "full_name":       change_doc["full_name"],
            "phone_numbers":   phones,
            "added_by_it":     True,
            "added_by":        change_doc.get("requested_by", ""),
            "org_id":          org_id,
            "student_id":      sid
        }
        set_doc.update(attr_set_paths(attrs))
        await tdb_for(org_id).voters.update_one(
            q,
            {"$set": set_doc,
            # Defaults ONLY on insert: for an existing ID, $set here used to flip has_voted back to
            # False (a double-vote path) and wipe every role flag.
            "$setOnInsert": {
                "is_commissioner": False,
                "is_it_admin":     False,
                "has_voted":       False,
                "last_status":     "idle",
            }},
            upsert=True
        )
    elif change_doc["change_type"] == "remove":
        q = get_forgiving_filter(change_doc["student_id"])
        q["org_id"] = require_org(org_id)
        await tdb_for(org_id).voters.delete_one(q)

async def log_action(action: str, actor: str, details: dict | None = None, org_id: str = None,
                     timestamp: datetime | None = None):
    details = dict(details or {})
    if org_id and isinstance(actor, str) and actor.startswith("PM-") and "is_member" not in details:
        pm = await tdb_for(org_id).panel_members.find_one({"panel_member_id": actor}, {"is_member": 1})
        if pm:
            details["is_member"] = bool(pm.get("is_member"))
    # details defaults to None, not {} — a mutable default argument is shared
    # across every call site in the process, so one accidental mutation would
    # leak into unrelated log entries.
    entry = {
        "action":    action,
        "actor":     actor,
        "details":   details or {},
        "org_id":    org_id,
        # Ballot-secrecy callers pass a coarse time (see _vote_bucket_start); everyone else gets "now".
        "timestamp": timestamp or datetime.utcnow()
    }
    if not org_id:
        # Genuinely tenant-less events (organization created, unauthenticated 401s). Marked so the
        # superadmin "Legacy data" check does not mistake them for leftover pre-multi-tenancy rows.
        entry["scope"] = "system"
        await cross_tenant(db).audit_log.insert_one(entry)   # deliberate: no tenant to scope to
    else:
        await tdb_for(org_id).audit_log.insert_one(entry)


# =============================================================================
# ACTOR ATTRIBUTION
# =============================================================================
# Every log_action call on an authenticated route must record WHO actually
# made the request, taken from the verified JWT — never a hardcoded string and
# never a value the client supplied in the body.

def current_actor(request: Request) -> str:
    admin = getattr(request.state, "admin", None)
    if not admin:
        return "unknown"
    return admin.get("sub") or "unknown"


def current_role(request: Request) -> str:
    admin = getattr(request.state, "admin", None)
    return (admin or {}).get("role", "")


def bind_identity(request: Request, claimed_id: str, label: str = "account") -> str:
    """
    Reject a request whose body claims to act as a different person than the
    token says it is.

    Several endpoints take a `commissioner_id` / `financial_controller_id` /
    `requested_by` straight from the request body and used to trust it. Any
    valid admin token — including a read-only Overseer's — could therefore
    cast a Commission vote, finance-clear an application, or decide a student
    change *in someone else's name*. The token subject is the only identity
    the server actually verified, so it is the one that has to match.

    Superadmin is exempt: it legitimately acts on behalf of any role through
    the documented override endpoints.
    """
    admin = getattr(request.state, "admin", None) or {}
    if admin.get("role") == "superadmin":
        return claimed_id
    subject = admin.get("sub") or ""
    if normalize_student_id(claimed_id) != normalize_student_id(subject):
        raise HTTPException(
            status_code=403,
            detail=f"You can only act as your own {label}.",
        )
    return claimed_id


async def require_payment_controller(request: Request, claimed_id: str, verb: str) -> dict:
    """
    Gate for clearing / rejecting a CANDIDATE's payment. Only the Financial Controller may do it.

    Candidate payments used to be cleared by a commissioner holding "finance-clearing power", who then
    also voted on the same application, so one person confirmed the money and judged the candidate.
    This gate keeps the two apart:
      * the token must be a Financial Controller session (a superadmin uses the logged
        /superadmin/applications/{id}/force-finance-clear override instead),
      * the body's id must be the token's own id (bind_identity),
      * the voter must still hold is_financial_controller.
    One person MAY hold both roles (e.g. a small commission). Each role has its own login and portal, so
    the session's role says which system is acting; clearing payments needs the Financial Controller
    session, voting needs the Commission session. Returns the voter document.
    """
    if current_role(request) != "financial_controller":
        raise HTTPException(403, f"Only the Financial Controller can {verb} a candidate's payment.")
    bind_identity(request, claimed_id, "Financial Controller account")
    fc = await tdb(request).voters.find_one({
        **get_forgiving_filter(claimed_id),
        "is_financial_controller": True,
    })
    if not fc:
        raise HTTPException(403, "Not a registered Financial Controller.")
    return fc


def _payment_audit(app_doc: dict, fc: dict | None = None) -> dict:
    """Receipt details copied into the audit entry, so the log alone shows what the decision rested on."""
    d = {
        "student_id":        app_doc.get("student_id", ""),
        "position_id":       app_doc.get("position_id", ""),
        "fee_required":      app_doc.get("fee_required") or 0,
        "payment_method":    app_doc.get("payment_method", ""),
        "payment_proof_url": app_doc.get("payment_proof_url", ""),
    }
    if fc and fc.get("is_commissioner"):
        d["decider_also_commissioner"] = True     # allowed, but visible in the log
    return d


async def _is_chief_or_deputy(request: Request, admin: dict) -> bool:
    """Superadmin, or the commissioner flagged is_chief_commissioner or is_deputy_chief_commissioner."""
    if admin.get("role") == "superadmin":
        return True
    if admin.get("role") != "commission":
        return False
    voter = await tdb(request).voters.find_one({
        **get_forgiving_filter(admin.get("sub", "")),
        "is_commissioner": True,
        "$or": [{"is_chief_commissioner": True}, {"is_deputy_chief_commissioner": True}],
    })
    return bool(voter)


async def require_chief_commissioner(request: Request) -> dict:
    """Superadmin, or the commissioner flagged is_chief_commissioner or
    is_deputy_chief_commissioner. The Deputy Chairperson stands in for the
    Chief on every action gated behind this check (exception grants,
    certification) — there's no separate, narrower deputy tier."""
    admin = getattr(request.state, "admin", None) or {}
    if not await _is_chief_or_deputy(request, admin):
        raise HTTPException(403, "Chief Commissioner access required.")
    return admin


async def require_superadmin_state(request: Request) -> dict:
    admin = getattr(request.state, "admin", None) or {}
    if admin.get("role") != "superadmin":
        raise HTTPException(403, "Superadmin access required.")
    return admin


# =============================================================================
# ELECTION PHASES  (applications / campaign / voting / results)
# =============================================================================
# Previously only ONE window existed (voting), and /apply had no time gate at
# all — a candidacy application could be submitted at any moment, including
# after voting closed. Phases are stored on a single settings document per org
# so a phase read is one query, and each carries its own enforced flag.

PHASE_NAMES = ("applications", "vetting", "campaign", "voting", "results")
DEFAULT_ROUND_ID = "round-1"
# Times are STORED as UTC. The election timezone is the zone admins think in when they type a start/end,
# and the one every screen shows them in — so a laptop set to another timezone can't start an election early/late.
DEFAULT_ELECTION_TZ = os.getenv("ELECTION_DEFAULT_TIMEZONE", "Africa/Kampala")


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise HTTPException(400, f"'{name}' is not a valid IANA timezone (e.g. Africa/Kampala).")
    return name


class PhaseWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    enforced: bool = True


class PhaseScheduleUpdate(BaseModel):
    phases: dict[str, PhaseWindow]
    round_id: str = DEFAULT_ROUND_ID
    timezone: str | None = None      # IANA name; omitted = keep the current one
    reason: str | None = None        # required only when this edit ends a live voting window right now


class Milestone(BaseModel):
    """One row of a client-supplied election roadmap (e.g. ASK-Table-EC.pdf).
    Purely informational — doesn't gate anything, unlike PhaseWindow above.

    Dates are structured: `start_date` (YYYY-MM-DD) is the event day, and
    `end_date` is set only for a multi-day range (omitted/null = single-day
    event). The public timeline derives the printed date text, the "● Today"
    highlight (any day within start..end inclusive) and the automatic
    "Week N" grouping from these. `date_label` is a legacy free-text field
    kept only so rows saved before the date picker existed still render; it's
    ignored whenever `start_date` is present."""
    start_date: str | None = None
    end_date: str | None = None
    date_label: str = ""
    activities: list[str] = []

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _iso_date(cls, v):
        if v in (None, ""):
            return None
        try:
            return datetime.strptime(str(v), "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise ValueError("Dates must be in YYYY-MM-DD format.")

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        start = info.data.get("start_date")
        if v and not start:
            raise ValueError("An end date requires a start date.")
        if v and start and v < start:
            raise ValueError("The end date must not be before the start date.")
        if v and v == start:
            return None  # same day = single-day event
        return v


class RoadmapUpdate(BaseModel):
    milestones: list[Milestone] = []
    # First day of the week for the auto-computed week numbers on the public
    # timeline. JS convention: 0 = Sunday ... 6 = Saturday. Week 1 always
    # starts on the earliest event date (even mid-week); later weeks begin on
    # this weekday. Default Monday.
    week_start_day: int = Field(1, ge=0, le=6)


class ExceptionGrantCreate(BaseModel):
    student_id: str
    phase: str
    reason: str
    expires_at: datetime | None = None


class ElectionToggle(BaseModel):
    """Optional body for /admin/toggle-election. `reason` is only required when stopping the
    election while an enforced voting window is still live (an early stop)."""
    reason: str | None = None


EARLY_STOP_MIN_REASON = 5


def iso_utc(dt: datetime | None) -> str | None:
    """Naive-UTC datetime -> ISO string with a Z, so browsers read it as UTC instead of local time."""
    dt = naive_utc(dt)
    return dt.isoformat() + "Z" if dt else None


def naive_utc(dt: datetime | None) -> datetime | None:
    """Pydantic hands us aware datetimes; everything stored/compared here is naive UTC."""
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def voting_window_state(schedule: dict, now: datetime) -> dict:
    """Where the enforced voting window stands right now — one place, used by the toggle route."""
    w = schedule["phases"]["voting"]
    start, end = w.get("start"), w.get("end")
    enforced = bool(w.get("enforced"))
    return {
        "enforced": enforced,
        # live = enforced, has a definite end, and we are inside [start, end]
        "live": enforced and end is not None and _phase_is_open(w, now),
        "ended": enforced and end is not None and now > end,
        "not_started": enforced and start is not None and now < start,
        "start": start,
        "end": end,
    }


async def _write_phase_schedule(org_id: str, phases: dict, timezone_name: str, round_id: str = DEFAULT_ROUND_ID) -> None:
    """Single persistence seam for phase windows. Demo phase-jumps reuse this helper so they do not
    invoke the real schedule route (whose early-end / panel validations are intentionally stricter)."""
    org_id = require_org(org_id)
    doc = {
        "name": "election_phases",
        "phases": phases,
        "round_id": round_id or DEFAULT_ROUND_ID,
        "timezone": timezone_name or DEFAULT_ELECTION_TZ,
        "updated_at": datetime.utcnow(),
    }
    await tdb_for(org_id).settings.update_one(
        {"name": "election_phases"},
        {"$set": {**doc, "org_id": org_id}},
        upsert=True,
    )
    invalidate_settings(org_id, "election_phases")


async def get_phase_schedule(request: Request) -> dict:
    doc = await cached_setting(request.state.org_id, "election_phases")
    phases = (doc or {}).get("phases", {})
    return {
        "round_id": (doc or {}).get("round_id", DEFAULT_ROUND_ID),
        "timezone": (doc or {}).get("timezone") or DEFAULT_ELECTION_TZ,
        "phases": {
            name: {
                "start": (phases.get(name) or {}).get("start"),
                "end": (phases.get(name) or {}).get("end"),
                # Unconfigured phases are NOT enforced — an org that never sets
                # a phase schedule keeps today's behaviour exactly.
                "enforced": (phases.get(name) or {}).get("enforced", False),
            }
            for name in PHASE_NAMES
        },
    }


def _phase_is_open(window: dict, now: datetime) -> bool:
    if not window.get("enforced"):
        return True
    start, end = window.get("start"), window.get("end")
    if not start and not end:
        return True
    if start and now < start:
        return False
    if end and now > end:
        return False
    return True


async def has_exception_grant(request: Request, student_id: str, phase: str) -> dict | None:
    now = datetime.utcnow()
    return await tdb(request).exception_grants.find_one({
        "student_id": normalize_student_id(student_id),
        "phase": phase,
        "revoked": {"$ne": True},
        "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
    })


async def assert_phase_open(request: Request, phase: str, student_id: str | None = None):
    """
    Auto-block by default: a closed, enforced phase rejects the action
    outright. The only way through is a named, logged, time-bound exception
    grant issued by the Chief Commissioner for one specific student — never a
    blanket reopen, so the decision record survives in the audit log.
    """
    schedule = await get_phase_schedule(request)
    window = schedule["phases"].get(phase, {})
    if _phase_is_open(window, datetime.utcnow()):
        return
    if student_id:
        grant = await has_exception_grant(request, student_id, phase)
        if grant:
            await log_action("phase_exception_used", normalize_student_id(student_id), {
                "phase": phase, "grant_id": str(grant["_id"]),
            }, org_id=request.state.org_id)
            return
    label = phase.replace("_", " ")
    now = datetime.utcnow()
    tz_name = schedule.get("timezone") or DEFAULT_ELECTION_TZ

    def _when(dt: datetime) -> str:
        try:
            z = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            z = ZoneInfo("UTC")
        local = dt.replace(tzinfo=timezone.utc).astimezone(z)
        return f"{local.day} {local:%b %Y}, {local:%H:%M} {local.tzname()}"

    start, end = window.get("start"), window.get("end")
    if start and now < start:
        detail = f"The {label} period has not opened yet. It opens on {_when(start)}."
        analytics.set_reason(request, "phase_not_open")
    elif end and now > end:
        detail = (f"The {label} period has ended. It closed on {_when(end)}. "
                  "Contact the Electoral Commission if you believe this is an error.")
        analytics.set_reason(request, "phase_ended")
    else:
        detail = f"The {label} period is currently closed. Contact the Electoral Commission if you believe this is an error."
        analytics.set_reason(request, "phase_closed")
    raise HTTPException(status_code=403, detail=detail)


async def current_round_id(request: Request) -> str:
    schedule = await get_phase_schedule(request)
    return schedule.get("round_id") or DEFAULT_ROUND_ID


def parse_oid(raw_id: str, label: str = "id") -> ObjectId:
    """
    Path-param IDs come straight from the URL, so a malformed value (wrong
    length, non-hex, stray characters) used to hit ObjectId() unguarded and
    raise bson.errors.InvalidId — an unhandled exception that surfaces to the
    caller as a raw 500 instead of a clean 4xx. /vote, /vote-bulk, and
    /positions/{id} already did this defensively; this makes that the norm
    for every route that takes an id from the path.
    """
    try:
        return ObjectId(raw_id)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {label}.")


async def assert_voting_allowed(request: Request, student_id: str):
    """
    /verify-identity checks is_open/schedule once, before the OTP is even
    sent — but nothing re-checked either that or the "voting" phase window
    at the moment a ballot is actually cast. A voter who authenticated while
    the election was open could still POST /vote after a superadmin closed
    it, certified results, or after a scheduled/enforced voting window
    ended, since /vote only ever checked has_voted + last_status. Re-check
    both gates here, at the point of casting, not just at OTP-send time.
    """
    config = await cached_setting(request.state.org_id, "election_config")
    if config and not config.get("is_open", True):
        raise HTTPException(status_code=403, detail="Election is closed.")
    if config and config.get("is_certified"):
        raise HTTPException(status_code=403, detail="Results have been certified; voting is closed.")
    await assert_phase_open(request, "voting", student_id)

# =============================================================================
# ADMIN LOGIN RATE LIMITING
# =============================================================================
# Mongo-backed (not in-memory) on purpose: this guards the highest-privilege
# accounts in the system, so it needs to survive a backend restart and work
# correctly even if this ever runs behind multiple instances — unlike the
# best-effort in-memory limiter on the public upload endpoint, where the
# stakes of a reset-on-restart are much lower.

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
# A superadmin can reset elections, force-approve applications, and read every tenant, so
# it's the single highest-value account in the system — it must never be the one account an
# attacker can fully deny access to just by typing its (publicly-known) email wrong 5 times.
# Its lockout is short and capped rather than the normal 15 minutes, however many failures
# pile up. Combined with (email, IP) keying below, an attacker spamming one IP no longer
# blocks the same person's real login attempt from a different IP either.
SUPERADMIN_LOCKOUT_SECONDS_CAP = int(os.getenv("SUPERADMIN_LOCKOUT_SECONDS_CAP", "60"))


# Per-EMAIL ceiling across every IP (SEC audit, "Open" item 4). The (email, IP) counter below stops one
# address hammering an account, but an attacker rotating IPs gets LOGIN_MAX_ATTEMPTS fresh guesses per IP.
# This second counter is keyed on the email alone, so total guesses against one account are bounded
# no matter how many addresses they come from. It is higher than the per-IP limit so a real user who
# mistypes a few times (or a shared campus NAT) is not caught by it.
LOGIN_EMAIL_MAX_ATTEMPTS = int(os.getenv("LOGIN_EMAIL_MAX_ATTEMPTS", "20"))


def _login_attempt_key(email: str, org_id: str | None, ip: str) -> str:
    return f"{org_id or 'default'}:{email}:{ip}"


def _login_email_key(email: str, org_id: str | None) -> str:
    # "*" can never be a real IP, so this cannot collide with an (email, IP) key.
    return f"{org_id or 'default'}:{email}:*"


def _login_lock_for(email: str, attempts: int, threshold: int) -> timedelta:
    if _is_superadmin_email(email):
        # Same short, capped backoff as the per-IP lock: the publicly-known superadmin email must never
        # be lockable for long by a stranger typing it wrong.
        return timedelta(seconds=min(SUPERADMIN_LOCKOUT_SECONDS_CAP, 5 * (2 ** (attempts - threshold))))
    return timedelta(minutes=LOGIN_LOCKOUT_MINUTES)


def _is_superadmin_email(email: str) -> bool:
    return email.strip().lower() == SUPER_ADMIN_ID.strip().lower()


async def enforce_login_rate_limit(email: str, org_id: str | None, ip: str):
    # Check the per-IP record and the per-email record; whichever lock runs longer decides the message.
    longest = None
    for key in (_login_attempt_key(email, org_id, ip), _login_email_key(email, org_id)):
        record = await db.login_attempts.find_one({"key": key})
        locked_until = (record or {}).get("locked_until")
        if locked_until and locked_until > datetime.utcnow() and (longest is None or locked_until > longest):
            longest = locked_until
    if longest:
        remaining_s = int((longest - datetime.utcnow()).total_seconds())
        remaining_min = max(1, remaining_s // 60 + (1 if remaining_s % 60 else 0))
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {remaining_min} minute(s)."
        )


async def record_failed_login(email: str, org_id: str | None, ip: str):
    key = _login_attempt_key(email, org_id, ip)
    # CONCURRENCY: was find_one() then a separate update_one() — two failed
    # logins arriving at nearly the same instant (a script hammering one
    # account from parallel connections) could both read the same "attempts"
    # count before either write landed, undercounting by a request or more
    # and pushing the real lockout threshold a little past LOGIN_MAX_ATTEMPTS.
    # $inc via find_one_and_update is atomic — every failure is counted
    # exactly once no matter how many arrive concurrently.
    doc = await db.login_attempts.find_one_and_update(
        {"key": key},
        {"$inc": {"attempts": 1}, "$set": {"last_attempt": datetime.utcnow()}},
        upsert=True,
        return_document=True,
    )
    attempts = doc.get("attempts", 1)
    if attempts >= LOGIN_MAX_ATTEMPTS:
        lock_for = _login_lock_for(email, attempts, LOGIN_MAX_ATTEMPTS)
        await db.login_attempts.update_one(
            {"key": key}, {"$set": {"locked_until": datetime.utcnow() + lock_for}}
        )
        await log_action("admin_login_locked", email, {"attempts": attempts, "ip": ip}, org_id=org_id)

    # Per-email counter, same atomic $inc, shared by every IP.
    email_key = _login_email_key(email, org_id)
    edoc = await db.login_attempts.find_one_and_update(
        {"key": email_key},
        {"$inc": {"attempts": 1}, "$set": {"last_attempt": datetime.utcnow()}},
        upsert=True,
        return_document=True,
    )
    email_attempts = edoc.get("attempts", 1)
    if email_attempts >= LOGIN_EMAIL_MAX_ATTEMPTS:
        lock_for = _login_lock_for(email, email_attempts, LOGIN_EMAIL_MAX_ATTEMPTS)
        await db.login_attempts.update_one(
            {"key": email_key}, {"$set": {"locked_until": datetime.utcnow() + lock_for}}
        )
        await log_action("admin_login_locked", email,
                         {"attempts": email_attempts, "scope": "email"}, org_id=org_id)   # no IP: it spans many


async def clear_login_attempts(email: str, org_id: str | None, ip: str):
    await db.login_attempts.delete_many({"key": {"$in": [_login_attempt_key(email, org_id, ip),
                                                         _login_email_key(email, org_id)]}})

# =============================================================================
# OTP THROTTLING, SMS-BUDGET PROTECTION & ROSTER CONTROL  (OTP_SMS_Design_v2)
# =============================================================================
# Pure maths (ladder, guess bucket, attack detection) lives in otp_limits.py;
# everything that touches Mongo lives here. Rollout flags (design section 15):
# OTP_LIMITER_MODE=legacy|new, ROSTER_FREEZE_ENABLED, CONTACT_CHANGE_REQUIRED.

OTP_LIMITER_MODE = os.getenv("OTP_LIMITER_MODE", "new").strip().lower()
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET")
SMS_BUDGET_DEFAULT_MULTIPLIER = ol.env_float("SMS_BUDGET_DEFAULT_MULTIPLIER", 2.5)

CONTACT_EVIDENCE_TYPES = (
    "id_card_in_person", "registrar_record", "student_portal_record",
    "commission_verified_by_call", "other_documented",
)
CONTACT_CHANGE_TYPES = ("phone_change", "phone_add", "phone_remove", "registration_number_change")
RESET_REASONS = ("sms_delayed", "victim_of_lockout", "wrong_details_fixed", "test")

def _env_sms_route(name: str) -> str:
    v = os.getenv(name, "default").strip().lower()
    return v if v in SMS_ROUTES else "default"


# Per-org overrides live in db.settings {name: "security_settings"}; these are the fallbacks.
_SEC_DEFAULTS = {
    "roster_freeze_at": None,
    "roster_freeze_enabled": ol.env_bool("ROSTER_FREEZE_ENABLED", True),
    "contact_change_required": ol.env_bool("CONTACT_CHANGE_REQUIRED", True),
    "otp_target_risk": ol.TARGET_RISK,
    "turnstile_mode": os.getenv("TURNSTILE_MODE", "off").strip().lower(),
    "public_results_mode": os.getenv("PUBLIC_RESULTS_MODE", "live").strip().lower(),
    "sms_fallback_on_timeout": ol.env_bool("SMS_FALLBACK_ON_TIMEOUT", False),
    # Which provider(s) carry voter OTPs vs everything else (see SMS_ROUTES). Env vars only set the default.
    "sms_route_otp": _env_sms_route("SMS_ROUTE_OTP"),
    "sms_route_other": _env_sms_route("SMS_ROUTE_OTHER"),
    "sms_budget_total": None,
    "sms_budget_enforce": ol.env_bool("SMS_BUDGET_ENFORCE", False),  # monitor-only until the dry run passes
    "sms_balance_floor_ugx": ol.env_int("SMS_BALANCE_FLOOR_UGX", 0) or None,
    "sms_mode": "normal",                                             # normal | conservation
    "contact_change_ttl_hours": ol.env_int("CONTACT_CHANGE_TTL_HOURS", 6),
    "contact_change_max_per_voter": ol.env_int("CONTACT_CHANGE_MAX_PER_VOTER", 2),
    "approver_daily_cap": ol.env_int("CONTACT_CHANGE_APPROVER_DAILY_CAP", 30),
    "quota_alert_pct": ol.env_float("CONTACT_CHANGE_ALERT_PCT", 2),
    "quota_hard_cap_pct": ol.env_float("CONTACT_CHANGE_HARD_CAP_PCT", 5),
    "superadmin_breakglass": ol.env_bool("CONTACT_CHANGE_SUPERADMIN_BREAKGLASS", False),
    "reset_admin_hourly_alert": ol.env_int("OTP_RESET_PER_ADMIN_HOURLY_ALERT", 50),
    "reset_admin_hourly_hard_cap": ol.env_int(
        "OTP_RESET_PER_ADMIN_HOURLY_HARD_CAP", ol.env_int("ADMIN_RESET_HARD_CAP", 150)),
    "reset_per_voter_daily": ol.env_int("OTP_RESET_PER_VOTER_DAILY", 3),
    "reset_per_voter_election": ol.env_int("OTP_RESET_PER_VOTER_ELECTION", 10),
    "freeze_lifted_at": None,   # set by reset-election / new round
    "epoch_at": None,           # counters (caps, quotas) only look at events after this
    "cap_overrides": {},        # {"approver_daily": {sid: cap}, "reset_hourly": {sid: cap}} (chief commissioner)
    "approval_policy": os.getenv("DEFAULT_APPROVAL_POLICY", "majority_total"),
    # one of: "unanimous" | "majority_total" | "majority_cast"
}

VALID_APPROVAL_POLICIES = {"unanimous", "majority_total", "majority_cast"}


# -----------------------------------------------------------------------------------------------
# Short-TTL cache of the RAW settings documents read on every public hit (/election-status and the
# security settings read by /verify-identity). Raw documents, not computed responses: the phase
# position depends on "now", so the response itself must always be recomputed.
#
# Every handler that WRITES election_config / election_phases / security_settings calls
# invalidate_settings(org_id) after the write, so an admin's change is visible at once on that
# instance; other instances catch up within the TTL. Casting a ballot deliberately does NOT use this
# cache (assert_voting_open reads the DB directly), so closing/certifying takes effect immediately
# for votes. SETTINGS_CACHE_TTL_S=0 disables the cache (tests do this unless they test the cache).
# -----------------------------------------------------------------------------------------------
_SETTINGS_TTL = float(os.getenv("SETTINGS_CACHE_TTL_S", "5"))
_SETTINGS_CACHE: dict = {}


async def cached_setting(org_id, name: str):
    """find_one({"name": name, org scope}) with a short TTL. Returns a private copy (callers may mutate)."""
    key = (str(org_id), name)
    if _SETTINGS_TTL > 0:
        hit = _SETTINGS_CACHE.get(key)
        if hit and hit[0] > time.monotonic():
            return copy.deepcopy(hit[1])
    doc = await tdb_for(org_id).settings.find_one({"name": name})
    if _SETTINGS_TTL > 0:
        _SETTINGS_CACHE[key] = (time.monotonic() + _SETTINGS_TTL, copy.deepcopy(doc))
    return doc


# Public results payload, per organisation: every open results page polls /election-results, and without
# this each poll recounted turnout and re-aggregated every vote event (performance audit P1-2). The key
# includes `results_released`, so a gated visitor can never be served a payload built for a released one.
_RESULTS_TTL = float(os.getenv("RESULTS_CACHE_TTL_S", "5"))
_RESULTS_CACHE: dict[tuple, tuple[float, dict]] = {}


def _invalidate_results(org_id=None) -> None:
    for k in [k for k in _RESULTS_CACHE if org_id is None or k[0] == str(org_id)]:
        _RESULTS_CACHE.pop(k, None)


def invalidate_settings(org_id=None, name: str | None = None) -> None:
    """Drop cached settings for one org (optionally one name). org_id=None drops everything.
    Also drops that org's cached results, since opening, closing or certifying changes what they show."""
    _invalidate_results(org_id)
    if org_id is None and name is None:
        _SETTINGS_CACHE.clear()
        return
    for k in [k for k in _SETTINGS_CACHE if (org_id is None or k[0] == str(org_id)) and (name is None or k[1] == name)]:
        _SETTINGS_CACHE.pop(k, None)


def _oq(org_id, extra: dict | None = None) -> dict:
    """org_query for code that has an org_id but no request (same fail-closed semantics)."""
    q = dict(extra) if extra else {}
    q["org_id"] = require_org(org_id)
    return q


def tdb(request: Request):
    """Tenant-scoped database handle for this request (see tenant_db.py). 400 if there is no tenant.
    `db` is resolved at call time so tests can swap main.db."""
    return _tenant_scoped_db(db, request)

def tdb_for(org_id):
    """Same, for code that has an org_id but no request."""
    return _tenant_scoped_db_for(db, org_id)


class ApiError(Exception):
    """HTTP error that carries machine-readable fields (reason, retry_after, ...) next to `detail`."""

    def __init__(self, status_code: int, detail: str, reason: str | None = None,
                 retry_after: int | None = None, **extra):
        self.status_code, self.detail, self.reason = status_code, detail, reason
        self.retry_after, self.extra = retry_after, extra


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    analytics.set_reason(request, exc.reason)
    body = {"detail": exc.detail}
    if exc.reason:
        body["reason"] = exc.reason
    if exc.retry_after is not None:
        body["retry_after"] = int(exc.retry_after)
    body.update(exc.extra)
    headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


# Tier 1 catch-all: any unhandled exception on a write/critical path becomes an
# immediate email instead of a silent 500 that only shows up in Render logs.
# HTTPException/ApiError are handled above and never reach here, so this only
# fires for genuine bugs/outages (DB down, unexpected driver errors, etc).
CRITICAL_ALERT_PATHS = (
    "/vote", "/vote-bulk", "/verify-identity", "/admin/reset-election",
    "/admin/certify", "/apply", "/admin/schedule",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    path = request.url.path
    if any(path.startswith(p) for p in CRITICAL_ALERT_PATHS):
        await alert_critical(
            f"Unhandled error on {path}",
            f"{type(exc).__name__}: {exc}\n\nMethod: {request.method}\n"
            f"Org: {getattr(request.state, 'org_id', None)}",
        )
    else:
        await alert_warning(
            f"Unhandled error on {path}",
            f"{type(exc).__name__}: {exc}\n\nMethod: {request.method}\n"
            f"Org: {getattr(request.state, 'org_id', None)}",
        )
    logger.exception("Unhandled exception on %s %s", request.method, path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


async def security_settings_for(org_id) -> dict:
    doc = await cached_setting(org_id, "security_settings") or {}
    out = dict(_SEC_DEFAULTS)
    out.update({k: doc[k] for k in _SEC_DEFAULTS if doc.get(k) is not None})
    if not isinstance(out.get("cap_overrides"), dict):
        out["cap_overrides"] = {}
    return out


async def get_security_settings(request: Request) -> dict:
    return await security_settings_for(request.state.org_id)


def _epoch(sec: dict) -> datetime:
    return sec.get("epoch_at") or datetime(1970, 1, 1)


def _client_ip(request: Request) -> str:
    return real_client_ip(request)


def _otp_key_for(org_id, student_id: str) -> str:
    return f"{org_id or 'default'}:otp:{normalize_student_id(student_id)}"


def _otp_key(request: Request, student_id: str) -> str:
    return _otp_key_for(request.state.org_id, student_id)


# ── Election window -> guess-bucket parameters ──────────────────────────────

async def guess_params(request: Request, sec: dict | None = None) -> dict:
    sec = sec or await get_security_settings(request)
    schedule = await get_phase_schedule(request)
    v = schedule["phases"]["voting"]
    w, is_default = ol.window_seconds(v.get("start"), v.get("end"), v.get("enforced"))
    risk = float(sec["otp_target_risk"])
    return {
        "window_s": w, "window_is_default": is_default,
        "budget": ol.guess_budget(risk), "interval": ol.refill_interval(w, risk),
    }


# ── Part A: atomic send reservation (ladder + 24 h ceiling) ─────────────────

async def reserve_send(request: Request, student_id: str) -> dict:
    """Reserve the voter's next SMS slot or raise 429. Optimistic-concurrency on `version`, so
    20 parallel Resend taps produce exactly one reservation. Returns {"snapshot", "wait"}."""
    key = _otp_key(request, student_id)
    for _ in range(3):
        now = datetime.utcnow()
        doc = await db.otp_send_state.find_one({"key": key})
        if doc is None:
            wait = ol.next_wait(1)
            try:
                await db.otp_send_state.insert_one({
                    "key": key, "send_count": 1, "last_send_at": now,
                    "next_send_at": now + timedelta(seconds=wait), "sends_24h": [now], "version": 0,
                })
            except DuplicateKeyError:
                continue                       # someone else won the insert; re-read
            return {"snapshot": None, "wait": wait}

        count = doc.get("send_count", 0)
        if now - doc["last_send_at"] > timedelta(seconds=ol.LADDER_RESET_S):
            count = 0                          # ladder forgets after idle time
        nxt = doc.get("next_send_at")
        if nxt and nxt > now:
            secs = max(1, math.ceil((nxt - now).total_seconds()))
            raise ApiError(429, f"Please wait {ol.fmt_wait(secs)} before requesting another code. "
                                f"Your last code is still valid.", "cooldown", secs)
        recent = ol.prune_24h(doc.get("sends_24h", []), now)
        if len(recent) >= ol.DAILY_SEND_CEILING:
            secs = max(1, math.ceil((min(recent) + timedelta(hours=24) - now).total_seconds()))
            raise ApiError(429, "You have reached today's limit for codes. Please try again later.",
                           "daily_ceiling", secs)
        new_count = count + 1
        wait = ol.next_wait(new_count)
        res = await db.otp_send_state.update_one(
            {"key": key, "version": doc.get("version", 0)},
            {"$set": {"send_count": new_count, "last_send_at": now,
                      "next_send_at": now + timedelta(seconds=wait), "sends_24h": recent + [now]},
             "$inc": {"version": 1}},
        )
        if res.modified_count == 1:
            return {"snapshot": doc, "wait": wait}
    raise ApiError(429, "Too many requests at once. Please wait a moment and try again.", "cooldown", 2)


async def rollback_send(request: Request, student_id: str, snapshot: dict | None):
    """Gateway failure is free: give the reserved slot back."""
    key = _otp_key(request, student_id)
    if snapshot is None:
        await db.otp_send_state.delete_one({"key": key})
        return
    await db.otp_send_state.update_one(
        {"key": key},
        {"$set": {f: snapshot[f] for f in ("send_count", "last_send_at", "next_send_at", "sends_24h") if f in snapshot},
         "$inc": {"version": 1}},
    )


# ── Part B: guess token bucket ──────────────────────────────────────────────

async def peek_guess(request: Request, student_id: str, params: dict) -> tuple[float, int]:
    """(tokens, retry_after) without consuming. Used to refuse SMS sends while the bucket is empty."""
    doc = await db.otp_guess_state.find_one({"key": _otp_key(request, student_id)})
    if not doc:
        return float(ol.FREE_GUESSES), 0
    tokens = ol.refill(doc["tokens"], (datetime.utcnow() - doc["updated_at"]).total_seconds(),
                       params["interval"])
    return tokens, (ol.retry_after(tokens, params["interval"]) if tokens < 1 else 0)


async def consume_guess(request: Request, student_id: str, params: dict) -> tuple[bool, float, int]:
    """Atomically pay one token BEFORE comparing the code (so parallel guesses can't overdraw).
    Returns (allowed, tokens_after, retry_after)."""
    key = _otp_key(request, student_id)
    interval = params["interval"]
    for _ in range(4):
        now = datetime.utcnow()
        doc = await db.otp_guess_state.find_one({"key": key})
        if doc is None:
            try:
                await db.otp_guess_state.insert_one(
                    {"key": key, "tokens": ol.FREE_GUESSES - 1.0, "updated_at": now, "v": 0})
            except DuplicateKeyError:
                continue
            return True, ol.FREE_GUESSES - 1.0, 0
        tokens = ol.refill(doc["tokens"], (now - doc["updated_at"]).total_seconds(), interval)
        if tokens < 1:
            return False, tokens, ol.retry_after(tokens, interval)
        res = await db.otp_guess_state.update_one(
            {"key": key, "v": doc.get("v", 0)},
            {"$set": {"tokens": tokens - 1.0, "updated_at": now}, "$inc": {"v": 1}},
        )
        if res.modified_count == 1:
            return True, tokens - 1.0, 0
    return False, 0.0, 1


async def clear_otp_limit_state(org_id, student_ids):
    """Forget send + guess state for these voters. Never touches or creates a code."""
    for sid in {normalize_student_id(s) for s in student_ids if s}:
        key = _otp_key_for(org_id, sid)
        await db.otp_send_state.delete_one({"key": key})
        await db.otp_guess_state.delete_one({"key": key})


async def reset_voter_otp_state(org_id, student_ids):
    """Approved correction: also delete any live code so it can't reach the OLD number's owner."""
    await clear_otp_limit_state(org_id, student_ids)
    for sid in {normalize_student_id(s) for s in student_ids if s}:
        q = _oq(org_id, {"student_id": sid})
        await tdb_for(org_id).otps.delete_many(q)
        await db.admin_otps.delete_many(q)


# ── Part C: SMS budget, usage counters, bot check ───────────────────────────

async def sms_usage_doc(org_id) -> dict:
    return await db.sms_usage.find_one({"org_key": org_id or "default"}) or {}


async def _budget_alerts(org_id, usage: dict):
    sec = await security_settings_for(org_id)
    total = sec["sms_budget_total"]
    if total:
        left_frac = (total - usage.get("sent_total", 0)) / total
        for threshold in (0.5, 0.25, 0.10):
            if left_frac <= threshold:
                r = await db.sms_usage.update_one(
                    {"org_key": org_id or "default", "alerts_fired": {"$ne": threshold}},
                    {"$addToSet": {"alerts_fired": threshold}})
                if r.modified_count:
                    await log_action("sms_budget_alert", "system", {
                        "threshold_pct": int(threshold * 100), "sent": usage.get("sent_total", 0),
                        "budget": total}, org_id=org_id)
                    # 10% left is the one that can actually block voters mid-election
                    # (see sms_budget_gate below), so it's critical; 50/25% are early
                    # warnings to top up before that happens.
                    level = "critical" if threshold <= 0.10 else "warning"
                    await send_alert(
                        f"SMS budget at {int(threshold * 100)}% remaining",
                        f"Org: {org_id or 'default'}. Sent {usage.get('sent_total', 0)} of {total} "
                        f"budgeted SMS. Top up or raise sms_budget_total before voters start being blocked.",
                        level=level,
                    )
    # Independent of whether a unit budget is even configured — the floor is
    # a currency check, and this is the safety net over sms_budget_total's
    # own accuracy, so it shouldn't be gated behind that setting existing.
    await _cross_check_live_balance(org_id, sec, usage)


async def count_sms(org_id, kind: str = "otp"):
    """Count one billable SMS toward the election budget (OTP, notice, or a provider fallback)."""
    now = datetime.utcnow()
    upd: dict = {"$inc": {"sent_total": 1, f"sent_{kind}": 1}, "$set": {"updated_at": now}}
    if kind == "otp":
        upd["$push"] = {"recent_sends": {"$each": [now], "$slice": -300}}
    key = org_id or "default"
    try:
        doc = await db.sms_usage.find_one_and_update({"org_key": key}, upd, upsert=True, return_document=True)
    except DuplicateKeyError:
        doc = await db.sms_usage.find_one_and_update({"org_key": key}, upd, upsert=True, return_document=True)
    await _budget_alerts(org_id, doc or {})


async def count_verified(org_id):
    now = datetime.utcnow()
    upd = {"$inc": {"verified_total": 1},
           "$push": {"recent_verifies": {"$each": [now], "$slice": -300}}, "$set": {"updated_at": now}}
    try:
        await db.sms_usage.update_one({"org_key": org_id or "default"}, upd, upsert=True)
    except DuplicateKeyError:
        await db.sms_usage.update_one({"org_key": org_id or "default"}, upd, upsert=True)


def current_sms_mode(sec: dict, usage: dict) -> str:
    if ol.under_attack(usage.get("recent_sends", []), usage.get("recent_verifies", []), datetime.utcnow()):
        return "under_attack"
    return "conservation" if sec.get("sms_mode") == "conservation" else "normal"


async def sms_budget_gate(request: Request, sec: dict, usage: dict, student: dict):
    """Hard stop when the budget is spent; conservation keeps the remaining credit for first codes.
    Both are monitor-only (counted + alerted, never enforced) until sms_budget_enforce is on."""
    total = sec["sms_budget_total"]
    if not total or not sec["sms_budget_enforce"]:
        return
    left = total - usage.get("sent_total", 0)
    msg = "Verification codes are temporarily unavailable. Please contact support."
    if left <= 0:
        raise ApiError(429, msg, "budget")
    if sec["sms_mode"] == "conservation" and (student.get("sms_sends_total") or 0) > 0:
        reserve = await tdb(request).voters.count_documents({
            "has_voted": {"$ne": True}, "sms_sends_total": {"$not": {"$gt": 0}}})
        if left <= reserve * 1.2:
            raise ApiError(429, "Codes are limited right now so that everyone can receive their first one. "
                                "Please try again later or contact support.", "budget")


async def ip_record(request: Request, field: str):
    """field: sends | verifies | fails. Feeds the per-IP challenge guard (never a hard block)."""
    now = datetime.utcnow()
    upd = {"$push": {field: {"$each": [now], "$slice": -120}}, "$set": {"updated_at": now}}
    for _ in range(2):
        try:
            await db.ip_send_stats.update_one({"key": _client_ip(request)}, upd, upsert=True)
            return
        except DuplicateKeyError:
            continue


async def ip_flagged(request: Request) -> bool:
    d = await db.ip_send_stats.find_one({"key": _client_ip(request)}) or {}
    return ol.ip_needs_captcha(d.get("sends", []), d.get("verifies", []), d.get("fails", []), datetime.utcnow())


async def _turnstile_verify(token: str, ip: str | None):
    """True = passed, False = rejected, None = Cloudflare unreachable / not configured (caller decides)."""
    if not TURNSTILE_SECRET:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                                  data={"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip or ""})
        return bool(r.json().get("success"))
    except Exception:
        return None


async def enforce_turnstile(request: Request, token: str | None, sec: dict, mode_now: str, flagged: bool):
    """Modes: off | adaptive (challenge flagged IPs / under attack) | on. Fails OPEN if Cloudflare is
    unreachable (voters first), except under_attack, which fails closed."""
    mode, attack = sec["turnstile_mode"], mode_now == "under_attack"
    if not (mode == "on" or attack or (mode == "adaptive" and flagged)):
        return
    if not token:
        raise ApiError(429, "Please complete the security check, then try again.", "captcha_required")
    ok = await _turnstile_verify(token, _client_ip(request))
    if ok is True:
        return
    if ok is False:
        raise ApiError(429, "The security check failed. Please try again.", "captcha_required")
    # Turnstile unreachable: outside under_attack this fails OPEN, i.e. captcha
    # protection silently stops working with nothing visible to a voter — the
    # exact kind of failure that's invisible unless someone's watching logs.
    # 60s cooldown matches the previous log-only behavior's own throttle.
    await alert_warning(
        "Turnstile (Cloudflare captcha) unreachable",
        f"configured={bool(TURNSTILE_SECRET)} mode={mode} failing_closed={attack and bool(TURNSTILE_SECRET)} "
        f"org={request.state.org_id}",
        cooldown_s=60,
    )
    await log_action("turnstile_unavailable", "system", {
        "configured": bool(TURNSTILE_SECRET), "mode": mode, "failing_closed": attack and bool(TURNSTILE_SECRET),
    }, org_id=request.state.org_id)
    if attack and TURNSTILE_SECRET:
        raise ApiError(503, "The security check is temporarily unavailable. Please try again shortly.",
                       "captcha_required", 30)


# ── Roster freeze (Part D) ──────────────────────────────────────────────────

async def roster_status(request: Request, sec: dict | None = None) -> dict:
    """phase: pre_freeze | voting_frozen | closed.
    - pre_freeze: everything allowed (audit-logged).
    - voting_frozen: no add/remove/import; phone & registration-number edits need approval.
    - closed (voting ended, no live exception grant): still no add/remove/import until a new round;
      contact edits are audit-only again because no OTP can be issued."""
    sec = sec or await get_security_settings(request)
    v = (await get_phase_schedule(request))["phases"]["voting"]
    now = datetime.utcnow()
    freeze_at = sec["roster_freeze_at"] or v.get("start")
    lifted = sec.get("freeze_lifted_at")
    base = {"freeze_at": freeze_at, "freeze_enabled": sec["roster_freeze_enabled"]}
    if (not sec["roster_freeze_enabled"] or freeze_at is None or now < freeze_at
            or (lifted and lifted >= freeze_at)):
        return {**base, "phase": "pre_freeze", "frozen": False, "contact_change_required": False}
    end = v.get("end")
    live_grant = await tdb(request).exception_grants.count_documents({
        "phase": "voting", "revoked": {"$ne": True},
        "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]})
    if end and now > end and not live_grant:
        return {**base, "phase": "closed", "frozen": True, "contact_change_required": False}
    return {**base, "phase": "voting_frozen", "frozen": True,
            "contact_change_required": bool(sec["contact_change_required"])}


async def _expire_pending_at_freeze(request: Request):
    await tdb(request).student_changes.update_many(
        {"status": "pending"},
        {"$set": {"status": "expired_at_freeze", "resolved_at": datetime.utcnow()}})


async def assert_roster_unfrozen(request: Request):
    """Call at the top of every add / remove / import route."""
    st = await roster_status(request)
    if st["frozen"]:
        await _expire_pending_at_freeze(request)
        raise ApiError(409, "The voter roster is frozen for this election: voters can no longer be added, "
                            "removed or imported. Contact changes go through the commission.", "roster_frozen")


# ── Tamper-evident roster ledger (Part D 7.6) ───────────────────────────────

def _ledger_hash(prev: str, seq: int, event: str, ref_id: str, actor: str, role: str,
                 ts: datetime, details: dict) -> str:
    payload = "|".join([prev, str(seq), event, ref_id or "", actor or "", role or "", ts.isoformat(),
                        json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)])
    return hashlib.sha256(payload.encode()).hexdigest()


async def append_ledger(org_id, event: str, ref_id: str, actor: str, role: str, details: dict | None = None):
    """Append-only SHA-256 chain per org. Best effort: a ledger failure is logged, never fatal."""
    details = {k: v for k, v in (details or {}).items()}
    for _ in range(6):
        last = await tdb_for(org_id).roster_ledger.find_one({"org_id": org_id}, sort=[("seq", -1)])
        seq = (last["seq"] if last else 0) + 1
        prev = last["hash"] if last else "GENESIS"
        now = datetime.utcnow()
        ts = now.replace(microsecond=(now.microsecond // 1000) * 1000)   # Mongo keeps milliseconds
        doc = {"org_id": org_id, "seq": seq, "event": event, "ref_id": ref_id, "actor": actor, "role": role,
               "ts": ts, "details": details, "prev_hash": prev,
               "hash": _ledger_hash(prev, seq, event, ref_id, actor, role, ts, details)}
        try:
            await tdb_for(org_id).roster_ledger.insert_one(doc)
            return doc
        except DuplicateKeyError:
            continue
        except Exception as e:
            logger.error(f"roster_ledger append failed ({event}): {e}")
            return None
    logger.error(f"roster_ledger append lost the race 6 times ({event})")
    return None


async def verify_roster_ledger(org_id) -> dict:
    prev, n, bad = "GENESIS", 0, None
    async for e in tdb_for(org_id).roster_ledger.find({"org_id": org_id}).sort("seq", 1):
        n += 1
        expect_seq = n
        if (e["seq"] != expect_seq or e["prev_hash"] != prev
                or e["hash"] != _ledger_hash(prev, e["seq"], e["event"], e["ref_id"], e["actor"], e["role"],
                                             e["ts"], e.get("details", {}))):
            bad = e["seq"]
            break
        prev = e["hash"]
    return {"valid": bad is None, "entries": n, "head_hash": prev if n else None, "first_bad_seq": bad}


async def anchor_roster_ledger(request: Request):
    """Publish the ledger head to B2 Object Lock (same trust anchor as the ballot chain)."""
    org_id = require_org(request.state.org_id)
    head = await tdb(request).roster_ledger.find_one({"org_id": org_id}, sort=[("seq", -1)])
    if not head:
        return
    marker = await tdb(request).settings.find_one({"name": "roster_ledger_anchor"}) or {}
    if marker.get("seq", 0) >= head["seq"]:
        return
    key = f"{org_id or 'default'}/roster-ledger-{head['seq']:08d}.json"
    body = json.dumps({"org_id": org_id, "seq": head["seq"], "head_hash": head["hash"],
                       "anchored_at": datetime.utcnow().isoformat()}, indent=2)
    try:
        if b2_client is None:
            raise RuntimeError("B2 client not configured (see startup logs)")
        await run_in_threadpool(
            b2_client.put_object, Bucket=B2_BUCKET_NAME, Key=key, Body=body.encode("utf-8"),
            ContentType="application/json", ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=datetime.utcnow() + timedelta(days=3650))
    except Exception as e:
        logging.error(f"B2 roster-ledger anchor failed for {key}: {e}")
        await log_action("audit_checkpoint_anchor_failed", "system", {"ledger_seq": head["seq"], "error": str(e)},
                         org_id=org_id)
        return
    await tdb(request).settings.update_one({"name": "roster_ledger_anchor"},
                                 {"$set": org_stamp(request, {"name": "roster_ledger_anchor", "seq": head["seq"],
                                                              "head_hash": head["hash"], "at": datetime.utcnow()})},
                                 upsert=True)


# =============================================================================
# SYSTEM & HEALTH
# =============================================================================

@app.get("/")
def read_root():
    # Boot probe for the frontend splash (App.jsx BOOT_PROBE_PATH). "/" rather than /health because
    # iPhone/Brave content blockers can block monitoring-style paths. No DB call, no provider details.
    return {"status": "Online"}

@app.get("/health")
async def health_check():
    try:
        await db.command("ping")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        # DB loss is Tier 1 by definition (nothing else works if this fails),
        # but this endpoint gets polled often (uptime monitors, the external
        # backup scheduler), so alert_critical's cooldown is what keeps a
        # sustained outage to one email every few minutes instead of one per
        # poll.
        await alert_critical("Database health check failing", f"{type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

@app.get("/election-status")
async def get_status(request: Request):
    status_doc = await cached_setting(request.state.org_id, "election_config")
    schedule = await get_phase_schedule(request)
    voting_phase_open = _phase_is_open(schedule["phases"]["voting"], datetime.utcnow())
    sec = await get_security_settings(request)
    turnstile_mode = sec["turnstile_mode"]   # off | adaptive | on
    approval_policy = sec["approval_policy"]  # unanimous | majority_total | majority_cast — public copy only, no vote counts here

    # Extra, additive fields so every screen can show the SAME "closed" notice for the same
    # situation (master switch off vs. scheduled window) instead of a notice in one place and an
    # error dialog in another. Existing fields below are unchanged.
    now = datetime.utcnow()

    def _position(window: dict) -> str:
        """'open' | 'not_started' | 'ended' — tells "too early" apart from "too late"."""
        if _phase_is_open(window, now):
            return "open"
        start = window.get("start")
        return "not_started" if start and now < start else "ended"

    vwin, awin, vetwin = schedule["phases"]["voting"], schedule["phases"]["applications"], schedule["phases"]["vetting"]
    voting_phase, applications_phase, vetting_phase = _position(vwin), _position(awin), _position(vetwin)
    phase_info = {
        # Same reading the Timeline cards use (admin /admin/schedule): a window is "scheduled" when it has a
        # start or an end, and "active" when now sits inside it. Lets the public header say "Applications Open"
        # while voting has no schedule of its own, instead of falling back on the master switch alone.
        "voting_scheduled": bool(vwin.get("start") or vwin.get("end")),
        "applications_active": bool(
            (awin.get("start") or awin.get("end"))
            and not (awin.get("start") and now < awin["start"])
            and not (awin.get("end") and now > awin["end"])
        ),
        "voting_phase": voting_phase,
        "voting_opens_at": vwin["start"].isoformat() if voting_phase == "not_started" else None,
        "applications_phase": applications_phase,
        "applications_opens_at": awin["start"].isoformat() if applications_phase == "not_started" else None,
        "applications_closes_at": awin["end"].isoformat() if awin.get("end") else None,
        "voting_closes_at": vwin["end"].isoformat() if vwin.get("end") else None,
        "applications_phase_open": applications_phase == "open",
        # Vetting = when commissioners may cast an approve/deny vote on an application (see
        # /admin/applications/{id}/vote). Finance clearance is deliberately NOT gated by this —
        # the Finance Commissioner can clear payment status any time, so clearance backs up ready
        # to go the moment the vetting window opens.
        "vetting_phase": vetting_phase,
        "vetting_phase_open": vetting_phase == "open",
        "vetting_opens_at": vetwin["start"].isoformat() if vetting_phase == "not_started" else None,
        "vetting_closes_at": vetwin["end"].isoformat() if vetwin.get("end") else None,
        "timezone": schedule["timezone"],
    }

    if not status_doc:
        return {"is_open": True, "is_certified": False, "start": None, "end": None,
                "voting_phase_open": voting_phase_open, "turnstile_mode": turnstile_mode,
                "approval_policy": approval_policy, **phase_info}
    return {
        **phase_info,
        "turnstile_mode": turnstile_mode,
        "approval_policy": approval_policy,
        "is_open": status_doc.get("is_open", True),
        "is_certified": status_doc.get("is_certified", False),
        "start": status_doc.get("start_time"),
        "end": status_doc.get("end_time"),
        # Whether the "voting" phase (Timeline tab) currently allows casting a
        # ballot, independent of the is_open master switch. Public/unauthenticated
        # so pre-login screens (the Sample Ballot preview) can hide themselves once
        # voting is no longer live, instead of indefinitely advertising a guide for
        # something that's no longer happening.
        "voting_phase_open": voting_phase_open,
    }

# =============================================================================
# VOTER ROUTES  (unchanged)
# =============================================================================

@app.post("/verify-identity")
async def verify_identity(data: IdentityCheck, request: Request):
    """Order (design section 10): election open -> identity/name -> bot check -> SMS budget -> guess
    bucket -> reserve send slot -> send (re-using a live code) -> count -> roll back on gateway failure."""
    now = datetime.utcnow()
    legacy = OTP_LIMITER_MODE == "legacy"
    status_doc = await cached_setting(request.state.org_id, "election_config")

    if status_doc and not status_doc.get("is_open", True):
        analytics.set_reason(request, "closed")
        raise HTTPException(status_code=403, detail="Election is closed.")

    # Timing is governed entirely by the "voting" phase schedule (see PHASE_NAMES / assert_phase_open).
    await assert_phase_open(request, "voting", data.student_id)

    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        await ip_record(request, "fails")
        analytics.set_reason(request, "not_on_roll")
        raise HTTPException(status_code=404, detail="Student ID not found.")

    # LEGACY (OTP_LIMITER_MODE=legacy only): permanent 3-send cap. The new limiter never reads otp_count.
    if legacy and student.get("otp_count", 0) >= 3:
        analytics.set_reason(request, "legacy_cap")
        raise HTTPException(
            status_code=403,
            detail="Too many attempts. Please check the official register for your details."
        )

    if student.get("has_voted"):
        analytics.set_reason(request, "already_voted")
        raise HTTPException(status_code=400, detail="Already voted.")

    if not names_match(student.get("full_name", ""), data.full_name):
        await ip_record(request, "fails")
        logger.warning(f"Name Match Fail: Reg({student.get('full_name','')}) vs Input({data.full_name})")
        analytics.set_reason(request, "name_mismatch")
        raise HTTPException(status_code=400, detail="Name mismatch. Please provide your full registered names.")

    phone_list = student.get("phone_numbers", [])
    if not phone_list:
        analytics.set_reason(request, "no_phone")
        raise HTTPException(status_code=400, detail="No phone found.")

    if len(phone_list) > 1 and data.phone_index is None:
        analytics.set_reason(request, "phone_choice")  # 200, but no code was sent yet
        return {"status": "needs_selection", "masked_numbers": [f"{p[:6]}****{p[-2:]}" for p in phone_list]}

    idx = data.phone_index if data.phone_index is not None else 0
    if not 0 <= idx < len(phone_list):
        analytics.set_reason(request, "bad_phone_choice")
        raise HTTPException(status_code=400, detail="Invalid phone selection.")
    raw_phone = phone_list[idx]
    sid = student["student_id"]

    reservation = None
    if not legacy:
        sec = await get_security_settings(request)
        usage = await sms_usage_doc(request.state.org_id)
        mode = current_sms_mode(sec, usage)
        await enforce_turnstile(request, data.turnstile_token, sec, mode, await ip_flagged(request))
        await sms_budget_gate(request, sec, usage, student)
        tokens, retry = await peek_guess(request, sid, await guess_params(request, sec))
        if tokens < 1:      # a fresh code is useless while no guess is allowed
            raise ApiError(429, f"Too many incorrect codes. You can try again in {ol.fmt_wait(retry)}. "
                                f"You do not need to do anything.", "guess_lock", retry)
        reservation = await reserve_send(request, sid)

    # Re-send the SAME code while it is still valid, so a late first SMS never becomes a wrong guess.
    existing = None if legacy else await tdb(request).otps.find_one({"student_id": sid})
    live = bool(existing and existing.get("created_at")
                and now - existing["created_at"] < timedelta(minutes=ol.CODE_TTL_MINUTES))
    otp = existing["code"] if live else str(secrets.randbelow(900000) + 100000)

    first_name = student.get("full_name", "Voter").split()[0].capitalize()
    branding_doc = await cached_setting(request.state.org_id, "branding")
    sms_org_name = (branding_doc or {}).get("org_name", "Election")

    message = (
        f"Hello {first_name}, your {sms_org_name} voting code is {otp}. "
        f"Your vote is secret. Do not share this code with anyone. Your voice, your power!"
    )

    outcome = await send_sms_status(raw_phone, message, request)
    if outcome == "failed":
        if reservation:
            await rollback_send(request, sid, reservation["snapshot"])      # gateway failure is free
        analytics.set_reason(request, "sms_failed")
        raise HTTPException(status_code=500, detail="SMS delivery failed.")

    # "ok" or "ambiguous": the SMS may well be on its way, so the code must be valid and the cooldown must hold.
    if not live:
        await tdb(request).otps.update_one(
            {"student_id": sid},
            {"$set": org_stamp(request, {"code": otp, "created_at": now,
                                      "is_demo": bool(await _demo_active(request.state.org_id))})},
            upsert=True
        )
    await tdb(request).voters.update_one(
        {"student_id": sid},
        {"$set": {"last_status": "otp_sent"}, "$inc": {"otp_count": 1, "sms_sends_total": 1},
         "$min": {"first_sms_at": now}}
    )
    await ip_record(request, "sends")
    resp = {"status": "success", "phone": f"{raw_phone[:6]}****{raw_phone[-2:]}",
            "next_send_in": reservation["wait"] if reservation else 60}
    if outcome == "ambiguous":
        resp["delivery"] = "unconfirmed"
    return resp


OTP_EXPIRY_MINUTES = ol.CODE_TTL_MINUTES


# LEGACY limiter (OTP_LIMITER_MODE=legacy): fixed 5 guesses -> fixed 15 min lock. Kept only as a rollback path.
OTP_MAX_VERIFY_ATTEMPTS = 5
OTP_VERIFY_LOCKOUT_MINUTES = 15



async def _enforce_otp_attempt_limit(request: Request, student_id: str):
    """
    A 6-digit OTP is only 1,000,000 possibilities — with unlimited guesses it
    falls in minutes to a script. There was NO attempt cap on this endpoint at
    all: /verify-identity capped how many codes could be SENT, but nothing
    capped how many could be TRIED. Mongo-backed so it survives a restart and
    works across multiple instances.
    """
    key = f"{request.state.org_id or 'default'}:otp:{normalize_student_id(student_id)}"
    record = await db.otp_attempts.find_one({"key": key})
    locked_until = (record or {}).get("locked_until")
    if locked_until and locked_until > datetime.utcnow():
        raise HTTPException(429, "Too many incorrect codes. Please wait before trying again.")


async def _record_otp_failure(request: Request, student_id: str):
    key = f"{request.state.org_id or 'default'}:otp:{normalize_student_id(student_id)}"
    # CONCURRENCY: same fix as record_failed_login above — atomic $inc
    # instead of read-then-write, so concurrent guesses against one
    # student_id can't undercount past the real attempt cap.
    doc = await db.otp_attempts.find_one_and_update(
        {"key": key},
        {"$inc": {"attempts": 1}, "$set": {"last_attempt": datetime.utcnow()}},
        upsert=True,
        return_document=True,
    )
    attempts = doc.get("attempts", 1)
    if attempts >= OTP_MAX_VERIFY_ATTEMPTS:
        await db.otp_attempts.update_one(
            {"key": key},
            {"$set": {
                "locked_until": datetime.utcnow() + timedelta(minutes=OTP_VERIFY_LOCKOUT_MINUTES),
                "attempts": 0,
            }}
        )
        await log_action("otp_verify_locked", normalize_student_id(student_id), {
            "attempts": OTP_MAX_VERIFY_ATTEMPTS
        }, org_id=request.state.org_id)


async def _clear_otp_attempts(request: Request, student_id: str):
    key = f"{request.state.org_id or 'default'}:otp:{normalize_student_id(student_id)}"
    await db.otp_attempts.delete_one({"key": key})


async def _verify_otp_legacy(data: OTPCheck, request: Request):
    await _enforce_otp_attempt_limit(request, data.student_id)

    search = org_query(request, get_forgiving_filter(data.student_id))
    voter  = await tdb(request).voters.find_one(search)
    if not voter:
        analytics.set_reason(request, "voter_not_found")
        raise HTTPException(status_code=404, detail="Voter not found.")

    record = await tdb(request).otps.find_one(search) or await db.admin_otps.find_one(search)

    if record:
        created_at = record.get("created_at")
        is_expired = (
            created_at is None
            or datetime.utcnow() - created_at > timedelta(minutes=OTP_EXPIRY_MINUTES)
        )
        if is_expired:
            await tdb(request).otps.delete_one(search)
            analytics.set_reason(request, "no_live_code")
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

        # Constant-time compare so response timing can't leak how many
        # leading digits of a guess were correct.
        if secrets.compare_digest(str(record.get("code", "")), str(data.code)):
            voter_token, vote_jti = create_voter_token(
                student_id=normalize_student_id(voter["student_id"]), org_id=request.state.org_id)
            await tdb(request).voters.update_one(search, {"$set": {
                "last_status": "authenticated", "otp_count": 0, "vote_jti": vote_jti,
                "authenticated_at": datetime.utcnow()}})
            await tdb(request).otps.delete_one(search)
            await _clear_otp_attempts(request, data.student_id)
            # Failure (otp_verify_locked) was already logged; success never
            # was, so the log couldn't show a complete authentication
            # lifecycle for a voter — only that they'd been locked out, never
            # that they got in.
            await log_action("otp_verified", normalize_student_id(data.student_id), {}, org_id=request.state.org_id)
            return {"status": "success", "voter_token": voter_token}

    await _record_otp_failure(request, data.student_id)
    analytics.set_reason(request, "wrong_code")
    raise HTTPException(status_code=400, detail="Invalid OTP. Please check your messages and try again.")


@app.post("/verify-otp")
async def verify_otp(data: OTPCheck, request: Request):
    if OTP_LIMITER_MODE == "legacy":
        return await _verify_otp_legacy(data, request)

    search = org_query(request, get_forgiving_filter(data.student_id))
    voter = await tdb(request).voters.find_one(search)
    if not voter:
        analytics.set_reason(request, "voter_not_found")
        raise HTTPException(status_code=404, detail="Voter not found.")
    sid = voter["student_id"]

    record = await tdb(request).otps.find_one(search) or await db.admin_otps.find_one(search)
    created_at = (record or {}).get("created_at")
    live = bool(record and created_at
                and datetime.utcnow() - created_at <= timedelta(minutes=ol.CODE_TTL_MINUTES))
    if not live:
        # No live code: a guess cannot succeed, so it must NOT cost the voter a token (otherwise anyone
        # could lock any voter out for free). Limited only by the per-IP guard.
        if record:
            await tdb(request).otps.delete_one(search)
        await ip_record(request, "fails")
        raise ApiError(400, "This code has expired. Please request a new one." if record
                       else "Please request a new code first.", "no_live_code")

    params = await guess_params(request)
    allowed, tokens_after, retry = await consume_guess(request, sid, params)   # pay BEFORE comparing
    if not allowed:
        raise ApiError(429, f"Too many incorrect codes. You can try again in {ol.fmt_wait(retry)}. "
                            f"You do not need to do anything.", "guess_lock", retry, attempts_remaining=0)

    # Constant-time compare so response timing can't leak how many leading digits were correct.
    if secrets.compare_digest(str(record.get("code", "")), str(data.code)):
        voter_token, vote_jti = create_voter_token(
            student_id=normalize_student_id(sid), org_id=request.state.org_id)
        await tdb(request).voters.update_one(search, {"$set": {
            "last_status": "authenticated", "otp_count": 0, "vote_jti": vote_jti,
            "authenticated_at": datetime.utcnow()}})
        await tdb(request).otps.delete_one(search)
        await db.otp_guess_state.delete_one({"key": _otp_key(request, sid)})   # success forgives the bucket
        await count_verified(request.state.org_id)
        await ip_record(request, "verifies")
        await log_action("otp_verified", sid, {}, org_id=request.state.org_id)
        return {"status": "success", "voter_token": voter_token}

    await ip_record(request, "fails")
    remaining = int(tokens_after + 1e-9)
    if remaining <= 0:
        wait = ol.retry_after(tokens_after, params["interval"])
        await log_action("otp_verify_locked", sid, {
            "window_s": int(params["window_s"]), "refill_interval_s": int(params["interval"]),
            "retry_after_s": wait}, org_id=request.state.org_id)
        raise ApiError(429, f"Too many incorrect codes. You can try again in {ol.fmt_wait(wait)}. "
                            f"You do not need to do anything.", "guess_lock", wait, attempts_remaining=0)
    raise ApiError(400, f"That code is not correct. {remaining} {'try' if remaining == 1 else 'tries'} left.",
                   "wrong_code", attempts_remaining=remaining)


def _assert_voter_session(request: Request, student: dict):
    """Bind the ballot to whoever just passed OTP. auth.verify_voter_token checks signature,
    expiry, role, student and tenant; the jti must also match the one stored at the LATEST
    OTP verification, so a newer login (or a used token) invalidates older tokens. A 401 here
    is what BallotBox.jsx turns into 'session expired, verify again'."""
    try:
        payload = verify_voter_token(request, normalize_student_id(student.get("student_id", "")), request.state.org_id)
    except HTTPException:
        analytics.set_reason(request, "session_expired")
        raise
    if not student.get("vote_jti") or not secrets.compare_digest(str(payload["jti"]), str(student["vote_jti"])):
        analytics.set_reason(request, "session_expired")
        raise HTTPException(status_code=401, detail="Your voting session has expired. Please verify your identity again.")


@app.post("/vote")
async def cast_vote(data: VoteRequest, request: Request):
    try:
        candidate_oid = ObjectId(data.candidate_id)
    except Exception:
        analytics.set_reason(request, "invalid_candidate")
        raise HTTPException(status_code=400, detail="Invalid candidate.")

    # Wrapped in a transaction: "mark voter as having voted" and "increment
    # the candidate's tally" are all-or-nothing. Uses with_transaction()
    # rather than a bare start_transaction() context manager because it
    # auto-retries on transient write conflicts — expected when many voters
    # hit the same popular candidate's document concurrently on election
    # day — instead of surfacing those as hard errors to the voter.
    # HTTPException raised inside the callback isn't a PyMongoError, so
    # with_transaction lets it propagate immediately rather than retrying it.
    candidate_exists = await tdb(request).candidates.count_documents(
        {"_id": candidate_oid}
    )
    if not candidate_exists:
        analytics.set_reason(request, "candidate_missing")
        raise HTTPException(status_code=404, detail="Candidate not found.")

    await assert_voting_allowed(request, data.student_id)

    async def _do_vote(session):
        student = await tdb(request).voters.find_one(
            get_forgiving_filter(data.student_id), session=session
        )
        if not student or student.get("has_voted"):
            analytics.set_reason(request, "ineligible")
            raise HTTPException(status_code=400, detail="Ineligible voter.")
        if student.get("last_status") != "authenticated":
            analytics.set_reason(request, "otp_required")
            raise HTTPException(status_code=403, detail="OTP verification required before voting.")
        _assert_voter_session(request, student)

        candidate_still_exists = await tdb(request).candidates.count_documents(
            {"_id": candidate_oid}, session=session
        )
        if not candidate_still_exists:
            analytics.set_reason(request, "candidate_missing")
            raise HTTPException(status_code=404, detail="Candidate not found.")

        claimed = await tdb(request).voters.update_one(
            {"_id": student["_id"], "has_voted": {"$ne": True}},
            {"$set": {"has_voted": True, "last_status": "completed"}, "$unset": {"vote_jti": ""}},
            session=session
        )
        if claimed.matched_count != 1:
            analytics.set_reason(request, "ineligible")
            raise HTTPException(status_code=400, detail="Ineligible voter.")
        # Append-only insert — no shared document for concurrent voters to
        # lock against, unlike the $inc this replaces. No voter_id is stored:
        # has_voted (on the voter doc) and this event are deliberately
        # decoupled so nothing in the DB links a voter to their choice.
        _ev_id, _ev_at = _new_vote_event_stamp()
        await tdb(request).vote_events.insert_one(
            {
                "_id": _ev_id,
                "candidate_id": candidate_oid,
                "cast_at": _ev_at,
                "is_demo": bool(await _demo_active(request.state.org_id)),
            },
            session=session
        )

    try:
        async with await client.start_session() as session:
            await session.with_transaction(_do_vote)
    except HTTPException:
        raise  # expected rejections (ineligible, wrong phase, etc.) — not an alert
    except Exception as e:
        await alert_critical(
            "Vote transaction failed",
            f"A vote transaction raised {type(e).__name__}: {e}\n"
            f"Org: {request.state.org_id} | candidate: {data.candidate_id}",
        )
        raise

    # Logged under the voter's own id, with no candidate/choice attached —
    # same secrecy boundary vote_events already keeps (see comment above).
    # This only records THAT a ballot was cast, so the activity log has a
    # complete picture of every state change, not just the admin-side ones.
    await log_action("vote_cast", normalize_student_id(data.student_id), {}, org_id=request.state.org_id,
                     timestamp=_vote_bucket_start())

    return {"status": "success"}


@app.get("/vote-status")
async def vote_status(student_id: str, request: Request, response: Response):
    """"Did my vote count?" for a voter whose /vote-bulk response was lost (guide 4.8 #2).

    Authenticated by the voter's own token — signature, expiry, tenant and student are checked, but the
    one-time jti is deliberately NOT compared: a successful vote clears vote_jti, so the very token that cast
    the ballot must still be able to ask. Only reveals whether THIS voter has voted; never choices."""
    sid = normalize_student_id(student_id)
    verify_voter_token(request, sid, request.state.org_id)
    student = await tdb(request).voters.find_one(get_forgiving_filter(sid), {"has_voted": 1})
    if not student:
        raise HTTPException(status_code=404, detail="Voter not found.")
    response.headers["Cache-Control"] = "no-store"
    return {"has_voted": bool(student.get("has_voted"))}


@app.post("/vote-bulk")
async def cast_bulk_vote(data: BulkVoteRequest, request: Request):
    try:
        candidate_oids = [ObjectId(c_id) for c_id in data.candidate_ids]
    except Exception:
        analytics.set_reason(request, "invalid_candidate")
        raise HTTPException(status_code=400, detail="One or more candidate IDs are invalid.")

    # Same id submitted twice used to slip through: the existence check only
    # compared distinct ids, but insert_many below looped over the raw list
    # — so a repeated id got inserted as two separate vote_events, double
    # counting that one candidate. Reject outright instead of silently
    # de-duping, since a client sending duplicates is either buggy or
    # tampering with the ballot.
    if len(candidate_oids) != len(set(candidate_oids)):
        analytics.set_reason(request, "duplicate_pick")
        raise HTTPException(status_code=400, detail="Duplicate candidate selected.")

    await assert_voting_allowed(request, data.student_id)

    # with_transaction auto-retries transient write conflicts — expected
    # under concurrent load when many voters hit the same popular
    # candidate's document at once — instead of surfacing them as hard
    # errors to the voter. See /vote for the same pattern.
    async def _do_bulk_vote(session):
        student = await tdb(request).voters.find_one(
            get_forgiving_filter(data.student_id), session=session
        )
        if not student:
            analytics.set_reason(request, "voter_not_found")
            raise HTTPException(status_code=404, detail="Voter not found.")
        if student.get("has_voted"):
            analytics.set_reason(request, "already_voted")
            raise HTTPException(status_code=400, detail="You have already cast your vote.")
        if student.get("last_status") != "authenticated":
            analytics.set_reason(request, "otp_required")
            raise HTTPException(status_code=403, detail="OTP verification required before voting.")
        _assert_voter_session(request, student)

        # Validate every candidate exists BEFORE writing anything. The old
        # version incremented whichever candidates happened to resolve and
        # silently swallowed failures for the rest — a voter could end up
        # marked as voted with some of their choices never counted. Now
        # it's genuinely all-or-nothing: either every choice is recorded,
        # or none are and the voter can retry.
        candidates = await tdb(request).candidates.find(
            {"_id": {"$in": candidate_oids}}, session=session
        ).to_list(length=None)
        if len(candidates) != len(set(candidate_oids)):
            analytics.set_reason(request, "candidate_missing")
            raise HTTPException(status_code=404, detail="One or more selected candidates could not be found.")

        # Nothing previously stopped two candidates for the SAME position
        # both being submitted — a voter (or a crafted request bypassing the
        # UI) could cast two ballots for President in one go. One candidate
        # per position, same as a real ballot.
        positions = [c.get("position") for c in candidates]
        if len(positions) != len(set(positions)):
            analytics.set_reason(request, "duplicate_pick")
            raise HTTPException(status_code=400, detail="Only one candidate can be selected per position.")

        claimed = await tdb(request).voters.update_one(
            {"_id": student["_id"], "has_voted": {"$ne": True}},
            {"$set": {"has_voted": True, "last_status": "completed"}, "$unset": {"vote_jti": ""}},
            session=session
        )
        if claimed.matched_count != 1:
            analytics.set_reason(request, "already_voted")
            raise HTTPException(status_code=400, detail="You have already cast your vote.")
        # Same append-only pattern as /vote, batched as one insert_many so a
        # multi-position ballot is still a single round trip inside the
        # transaction (still all-or-nothing with the has_voted update above).
        cast_at = _vote_bucket_start()
        demo_flag = bool(await _demo_active(request.state.org_id))
        await tdb(request).vote_events.insert_many(
            [org_stamp(request, {"_id": _new_vote_event_stamp()[0], "candidate_id": c_oid, "cast_at": cast_at,
                                 "is_demo": demo_flag}) for c_oid in candidate_oids],
            session=session
        )

    try:
        async with await client.start_session() as session:
            await session.with_transaction(_do_bulk_vote)
    except HTTPException:
        raise  # expected rejections — not an alert
    except Exception as e:
        await alert_critical(
            "Bulk vote transaction failed",
            f"A bulk vote transaction raised {type(e).__name__}: {e}\n"
            f"Org: {request.state.org_id} | candidates: {data.candidate_ids}",
        )
        raise

    await log_action("vote_cast", normalize_student_id(data.student_id), {"positions": len(candidate_oids)},
                     org_id=request.state.org_id, timestamp=_vote_bucket_start())

    return {"status": "success", "message": "Ballot cast successfully."}


@app.get("/candidates")
async def get_candidates(request: Request):
    # Public candidate list — feeds both the real ballot (BallotBox) and the
    # unauthenticated Sample Ballot preview, AND every admin dashboard's own
    # candidate-management screen (Superadmin, plain Admin) reuses this same
    # route rather than a separate authenticated one. So the voting-closed
    # block below only applies to unauthenticated (voter-facing) callers —
    # an authenticated admin of any role must always be able to see/manage
    # candidates, including right after voting closes, to prep for
    # certification or the next cycle. The Sample Ballot link already hides
    # itself client-side (App.jsx's showSampleBallot); this closes the same
    # gap server-side for anyone hitting the route directly, without
    # touching admin access.
    is_admin_caller = False
    try:
        await require_admin(request)
        is_admin_caller = True
    except HTTPException:
        pass

    if not is_admin_caller:
        schedule = await get_phase_schedule(request)
        voting_window = schedule["phases"]["voting"]
        if voting_window.get("enforced") and voting_window.get("end") and datetime.utcnow() > voting_window["end"]:
            raise HTTPException(status_code=403, detail="Voting has closed. The candidate list is no longer available.")

    candidates = []
    async for cand in tdb(request).candidates.find({}).sort("order", 1):
        cand["_id"] = str(cand["_id"])
        candidates.append(cand)
    return candidates

# =============================================================================
# PUBLIC ROUTES
# =============================================================================

@app.get("/public/bootstrap")
async def public_bootstrap(request: Request, response: Response):
    """E1: one request for what the public pages need at startup - branding, election status, positions.
    Each part is produced by the SAME handler the individual endpoint uses, so the shapes cannot drift, every
    query stays org-scoped, and only already-public fields can appear. The old endpoints keep working."""
    response.headers["Vary"] = "Origin, X-Org-Slug, Authorization"
    response.headers["Cache-Control"] = "no-store" if request.headers.get("Authorization") else "public, max-age=15, stale-while-revalidate=30"
    return {
        "branding": await get_branding(request),
        "status": await get_status(request),
        "positions": await get_positions(request, Response()),
    }


@app.get("/positions")
async def get_positions(request: Request, response: Response):
    # Near-static and public, so let browsers/CDNs reuse it briefly. Vary on X-Org-Slug is REQUIRED — the tenant
    # comes from that header, and without it one organisation's positions could be served to another.
    # Authenticated (admin) callers just edited something and must see it at once, so they get no-store.
    if request.headers.get("Authorization"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "public, max-age=15, stale-while-revalidate=30"
    response.headers["Vary"] = "Origin, X-Org-Slug, Authorization"
    positions = []
    async for p in tdb(request).positions.find({}).sort("order", 1):
        p["_id"] = str(p["_id"])
        positions.append(p)
    return positions

# Simple in-memory per-IP rate limit for the one unauthenticated upload
# Mongo-backed (not in-memory) so it (a) survives a restart, (b) works
# correctly across multiple instances behind a load balancer — the same
# reasoning that already applies to the admin login limiter above — and
# (c) increments atomically via a single find_one_and_update, so a burst of
# concurrent requests from one IP can't all read the same "under the limit"
# count before any of them write (the in-memory read-then-write version this
# replaced had exactly that race). Client IP is resolved via
# ProxyHeadersMiddleware (see near the bottom of this file) so this counts
# the real visitor, not the platform's reverse proxy, as long as
# TRUSTED_PROXY_HOSTS is configured correctly for your deployment.
async def _check_rate_limit(request: Request, *, bucket: str, limit: int, window_s: int, message: str):
    ip = real_client_ip(request)
    key = f"{bucket}:{ip}"
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_s)

    doc = await db.ip_rate_limits.find_one_and_update(
        {"key": key},
        {
            "$push": {"hits": {"$each": [now], "$slice": -(limit + 1)}},
            "$set": {"last_hit": now},
        },
        upsert=True,
        return_document=True,
    )
    recent_hits = [h for h in doc.get("hits", []) if h > window_start]
    if len(recent_hits) > limit:
        raise HTTPException(status_code=429, detail=message)


UPLOAD_RATE_LIMIT = 8       # max uploads
UPLOAD_RATE_WINDOW_S = 600  # per 10 minutes, per IP


async def _check_upload_rate_limit(request: Request):
    await _check_rate_limit(
        request, bucket="upload", limit=UPLOAD_RATE_LIMIT, window_s=UPLOAD_RATE_WINDOW_S,
        message="Too many uploads. Please try again in a few minutes.",
    )


async def _check_document_upload_rate_limit(request: Request):
    # Nomination forms have their own bucket: a third applicant upload must not
    # consume the same 8/10-minute budget used by the photo/receipt endpoint.
    await _check_rate_limit(
        request, bucket="upload_doc", limit=UPLOAD_RATE_LIMIT, window_s=UPLOAD_RATE_WINDOW_S,
        message="Too many form uploads. Please try again in a few minutes.",
    )


REGISTER_RATE_LIMIT = 10
REGISTER_RATE_WINDOW_S = 60


async def _check_register_rate_limit(request: Request):
    await _check_rate_limit(
        request, bucket="register", limit=REGISTER_RATE_LIMIT, window_s=REGISTER_RATE_WINDOW_S,
        message="Too many requests. Please try again shortly.",
    )


APPLY_RATE_LIMIT = 120        # eligibility checks per IP per window (a campus NAT shares one IP)
APPLY_SUBMIT_RATE_LIMIT = 60  # application submissions per IP per window
APPLY_RATE_WINDOW_S = 600


async def _check_apply_rate_limit(request: Request, *, submit: bool = False):
    """/apply/check-eligibility tells a caller whether an ID is on the roll and whether a name matches it,
    and was unthrottled, so the register could be enumerated during the applications phase. Generous
    limits: legitimate applicants make a handful of calls, and the upload limiter already bounds them."""
    await _check_rate_limit(
        request, bucket="apply_submit" if submit else "apply_check",
        limit=APPLY_SUBMIT_RATE_LIMIT if submit else APPLY_RATE_LIMIT, window_s=APPLY_RATE_WINDOW_S,
        message="Too many requests. Please try again in a few minutes.")


VOTER_REGISTER_PAGE_SIZE = 25

@app.get("/voter-register")
async def search_voter_register(request: Request, q: str = "", page: int = 1):
    await _check_register_rate_limit(request)
    page = min(max(page, 1), 2000)  # cap: an unbounded skip is a cheap DoS
    skip = (page - 1) * VOTER_REGISTER_PAGE_SIZE
    query = org_query(request)
    if q:
        # The raw query string used to be interpolated straight into a Mongo
        # $regex. On an unauthenticated endpoint that is both a regex
        # injection and a ReDoS lever — a crafted pattern can pin the database
        # CPU. Escape it, and cap the length.
        safe_q = re.escape(q.strip()[:80])
        query["$or"] = [
            {"full_name": {"$regex": safe_q, "$options": "i"}},
            {"student_id": {"$regex": re.escape(normalize_student_id(q)[:80]), "$options": "i"}},
        ]
    total = await tdb(request).voters.count_documents(query)
    cursor = tdb(request).voters.find(
        query, {"_id": 0, "full_name": 1, "student_id": 1, "phone_numbers": 1}
    ).sort("full_name", 1).skip(skip).limit(VOTER_REGISTER_PAGE_SIZE)
    results = [
        {
            "full_name": _mask_name(v["full_name"]),
            "student_id": _mask_student_id(v["student_id"]),
            "phone_on_file": bool(v.get("phone_numbers")),
        }
        async for v in cursor
    ]
    return {"results": results, "total": total, "page": page, "page_size": VOTER_REGISTER_PAGE_SIZE}


@app.post("/voter-register/check-number")
async def check_registered_number(data: ApplicationEligibilityCheck, request: Request):
    await _check_register_rate_limit(request)
    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(status_code=404, detail="Not found in the register.")
    if not names_match(student.get("full_name", ""), data.full_name):
        raise HTTPException(status_code=400, detail="Name does not match our records.")
    phones = student.get("phone_numbers", [])
    if not phones:
        return {"phone_on_file": False}
    return {"phone_on_file": True, "masked_phone": _mask_phone(phones[0])}


# Content-Type is attacker-controlled — a client can label anything
# "image/png". Sniff the real signature so only actual images reach
# Cloudinary (and, via the returned URL, every visitor's browser).
_IMAGE_MAGIC = (
    b"\xff\xd8\xff",          # JPEG
    b"\x89PNG\r\n\x1a\n",     # PNG
    b"GIF87a", b"GIF89a",      # GIF
)


def _assert_real_image(content: bytes):
    if content[:3] in (m[:3] for m in (_IMAGE_MAGIC[0],)) and content.startswith(_IMAGE_MAGIC[0]):
        return
    if content.startswith(_IMAGE_MAGIC[1]):
        return
    if content.startswith(_IMAGE_MAGIC[2]) or content.startswith(_IMAGE_MAGIC[3]):
        return
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return
    raise HTTPException(status_code=400, detail="That file is not a valid JPEG, PNG, WEBP or GIF image.")


@app.post("/apply/upload-image")
async def apply_upload_image(request: Request, file: UploadFile = File(...)):
    """Public upload used for candidate photos and payment proof during
    application submission. Applicants have no login, so this can't require
    an admin token — but it still keeps the Cloudinary secret server-side,
    validates file type/size, and rate-limits per IP, none of which the old
    unsigned-preset upload did.
    """
    await _check_upload_rate_limit(request)
    await assert_phase_open(request, "applications")

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        analytics.set_reason(request, "bad_file_type")
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP, or GIF images are allowed.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)   # never buffer an unbounded body
    if len(content) > MAX_UPLOAD_BYTES:
        analytics.set_reason(request, "too_large")
        raise HTTPException(status_code=400, detail="Image must be under 5MB.")
    _assert_real_image(content)

    try:
        result = cloudinary.uploader.upload(content, folder="ballotbox/applicants", resource_type="image")
    except Exception as e:
        logger.error(f"Cloudinary applicant upload failed: {e}")
        await alert_critical(
            "Cloudinary upload failing (applicant)",
            f"{type(e).__name__}: {e}\nOrg: {getattr(request.state, 'org_id', None)}",
        )
        analytics.set_reason(request, "upload_failed")
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    return {"secure_url": result["secure_url"]}


async def _applicant_phone_to_save(cfg: dict, raw: str, student: dict, request: Request) -> str | None:
    """Phone-number step of the application form (org setting `collect_phone`, off by default).

    Returns the normalised number to write onto the voter record, or None when nothing should be written.
    Safety rules, because this is a PUBLIC endpoint and the voter's phone is where their voting OTP is sent:
      * a voter who already has a phone on file is never changed or added to here (that goes through the
        contact-change flow, which has review), so nobody can attach their own number to someone else's record;
      * a number already registered to a different voter is refused."""
    if not cfg.get("collect_phone"):
        return None
    if student.get("phone_numbers"):
        return None
    if not (raw or "").strip():
        raise HTTPException(400, "Please enter your phone number. Your record has none on file.")
    num = normalize_phone_number(raw)
    if await tdb(request).voters.count_documents({"phone_numbers": num, "student_id": {"$ne": student["student_id"]}}):
        raise HTTPException(400, "That phone number is already registered to another student. "
                                 "Enter your own number, or contact IT support.")
    return num


@app.post("/apply/check-eligibility")
async def check_application_eligibility(data: ApplicationEligibilityCheck, request: Request):
    await _check_apply_rate_limit(request)
    await assert_phase_open(request, "applications", data.student_id)
    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        analytics.set_reason(request, "not_on_roll")
        raise HTTPException(
            status_code=404,
            detail=f"Your {await id_noun(request.state.org_id)} was not found on the voter register. Please contact IT support if you believe this is an error."
        )
    if not names_match(student.get("full_name", ""), data.full_name):
        analytics.set_reason(request, "name_mismatch")
        raise HTTPException(
            status_code=400,
            detail=f"The name entered doesn't match our records for this {await id_noun(request.state.org_id)}. Please enter your full registered name."
        )
    # Fail on a missing / malformed / taken phone number now, before the applicant spends time on uploads.
    await _applicant_phone_to_save(await get_nomination_form(request.state.org_id), data.phone, student, request)
    return {"status": "eligible"}

@app.post("/apply")
async def submit_application(data: ApplicationSubmit, request: Request):
    await _check_apply_rate_limit(request, submit=True)
    # Applications had NO time gating anywhere — a candidacy could be filed
    # after voting had already closed.
    await assert_phase_open(request, "applications", data.student_id)
    # These URLs are attacker-supplied on a public endpoint and are later opened by the Financial Controller
    # and the panel, so they must be https links (the superadmin edit route already enforces this).
    for _field, _val in (("image_url", data.image_url), ("payment_proof_url", data.payment_proof_url)):
        if _val and not _val.startswith("https://"):
            raise HTTPException(400, f"{_field} must be an https:// link (or empty).")
    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        analytics.set_reason(request, "not_on_roll")
        raise HTTPException(
            status_code=404,
            detail=f"Your {await id_noun(request.state.org_id)} was not found on the voter register. Please contact IT support if you believe this is an error."
        )
    if not names_match(student.get("full_name", ""), data.full_name):
        analytics.set_reason(request, "name_mismatch")
        raise HTTPException(
            status_code=400,
            detail=f"The name entered doesn't match our records for this {await id_noun(request.state.org_id)}."
        )
    data.full_name = normalize_name(data.full_name)
    if await tdb(request).panel_members.find_one({"student_id": student["student_id"], "active": True}):
        raise HTTPException(403, "You are serving on the Vetting Panel and cannot apply. Ask the superadmin to remove you from the panel first.")
    data.student_id = student["student_id"]     # canonical stored form, whatever the applicant typed

    existing = await tdb(request).applications.find_one({
        "student_id": data.student_id,
        "position_id": data.position_id
    })
    if existing:
        analytics.set_reason(request, "already_applied")
        raise HTTPException(400, "You have already applied for this position.")

    round_id = await current_round_id(request)
    org_id = require_org(request.state.org_id)
    position_title, _ = await _resolve_position_title(data.position_id, org_id)

    # N2: the signed nomination form. Checked before anything is stored so a missing form never leaves a
    # half-created application behind.
    nomination_cfg = await get_nomination_form(org_id)
    phone_to_save = await _applicant_phone_to_save(nomination_cfg, data.phone, student, request)   # may raise 400, before any upload is claimed
    claimed_upload = None
    if nomination_cfg["enabled"]:
        upload_id = (data.nomination_upload_id or "").strip()
        if not upload_id and nomination_cfg["required"]:
            raise HTTPException(400, "Please upload the signed nomination form before submitting your application.")
        if upload_id:
            claimed_upload = await _claim_nomination_upload(request, upload_id, data.student_id, data.position_id)

    # candidate-portal-spec §2/§4.1: a copy of the submitted fields, captured
    # once here. The printable "Application Snapshot" view always renders
    # this, never the live application doc, so a later IT-admin correction
    # doesn't change what was already "printed".
    application_snapshot = {
        "student_id":     data.student_id,
        "full_name":      data.full_name,
        "position_title": position_title,
        "manifesto":      data.manifesto,
        "image_url":      data.image_url,
        "submitted_at":   datetime.utcnow(),
    }

    try:
        inserted = await tdb(request).applications.insert_one({
        **data.dict(exclude={"nomination_upload_id", "phone"}),
        # Metadata only. The storage key and any link stay in nomination_uploads / behind a presigned URL.
        "nomination_form": ({"upload_id": claimed_upload["upload_id"], "filename": claimed_upload["filename"],
                             "kind": claimed_upload["kind"], "bytes": claimed_upload["bytes"]}
                            if claimed_upload else None),
        # Snapshot at submit time, like fee_required: a later change to the setting never rewrites history (N3).
        "nomination_form_required": bool(nomination_cfg["enabled"] and nomination_cfg["required"]),
        # round_id is written now so multi-round support later is a feature
        # addition, not a breaking data migration.
        "round_id": round_id,
        "status": "pending",
        "votes": {},          # { commissioner_student_id: "approve" | "deny" }
        "removal_votes": {},  # same structure, used after approval
        "fee_required": await _position_fee(data.position_id, request.state.org_id),  # what the applicant was told to pay
        "finance_cleared": False,      # gate: Finance Commissioner must clear before voting opens
        "finance_cleared_by": None,
        "finance_cleared_at": None,
        "submitted_at": datetime.utcnow(),
        "application_snapshot": application_snapshot,
        "denial_snapshot": None,
        "certificate_id": None,
        "certificate_issued_at": None,
        "is_demo": bool(await _demo_active(org_id)),
        })
    except Exception:
        if claimed_upload:     # give the file back so the applicant can retry with the same upload
            await tdb(request).nomination_uploads.update_one(
                {"upload_id": claimed_upload["upload_id"], "status": "attached"},
                {"$set": {"status": "pending", "created_at": claimed_upload.get("created_at") or claimed_upload.get("uploaded_at") or datetime.utcnow()},
                 "$unset": {"student_id": "", "position_id": "", "attached_at": ""}})
        raise
    if claimed_upload:
        await tdb(request).nomination_uploads.update_one(
            {"upload_id": claimed_upload["upload_id"]}, {"$set": {"application_id": str(inserted.inserted_id)}})
    if phone_to_save:
        try:
            # Guarded write: only if the record STILL has no phone (it may have been filled since we read it).
            res = await tdb(request).voters.update_one(
                {"_id": student["_id"], "$or": [{"phone_numbers": {"$exists": False}}, {"phone_numbers": {"$size": 0}}]},
                {"$set": {"phone_numbers": [phone_to_save], "updated_at": datetime.utcnow()}})
            if res.modified_count:
                student["phone_numbers"] = [phone_to_save]          # so the status-link SMS below goes to it
                await log_action("applicant_phone_registered", data.student_id,
                                 {"phone": _mask_phone(phone_to_save)}, org_id=org_id)
        except Exception:
            logger.exception("Could not save the applicant's phone number (application itself was saved)")
    await log_action("application_submitted", data.student_id, {
    "position_id": data.position_id,
    "full_name":   data.full_name,
    "nomination_form_required": bool(nomination_cfg["enabled"] and nomination_cfg["required"]),
    **({"nomination_form": claimed_upload["filename"]} if claimed_upload else {}),
    }, org_id=request.state.org_id)

    # candidate-portal-spec §3.1: one live status link per student per round,
    # created on first application and reused for every later one. The SMS is
    # only sent when a link is newly created (not on later applications).
    had_live_link = False
    async for t in tdb(request).candidate_tokens.find({"student_id": data.student_id, "round_id": round_id, "org_id": org_id}):
        if not _status_link_expired(t):
            had_live_link = True
            break
    if not had_live_link:
        token_doc = await _get_or_create_status_token(data.student_id, round_id, org_id)
        phones = student.get("phone_numbers") or []
        if phones:
            # "candidate_status_link" deliberately isn't in PRIORITY_SMS_KINDS —
            # this rides the cheap/slow non-priority tier (§3.1): nobody is
            # staring at their phone waiting for it the way an OTP recipient is.
            await send_sms(
                phones[0],
                f"Application received. Check status: {await frontend_url_for(request)}/status/{token_doc['token']}",
                request, kind="candidate_status_link",
            )
    return {"status": "submitted"}

# =============================================================================
# CANDIDATE STATUS PORTAL  (public, token-linked, read-only — candidate-portal-spec)
# =============================================================================

async def _candidacy_results_band(position_title: str, candidate_id: str, org_id: str, request: Request) -> dict | None:
    """
    §3.3: rank/of/trend for one candidate, reusing the same aggregation the
    Commission/Overseer "Candidate Results" tab already uses
    (get_vote_counts), gated the same way /election-results gates the public
    breakdown — never raw vote counts or opponent names, only the band.
    """
    cfg = await tdb(request).settings.find_one({"name": "election_config"}) or {}
    schedule = await get_phase_schedule(request)
    voting_open = _phase_is_open(schedule["phases"].get("voting", {}), datetime.utcnow())
    voting_closed_certified = cfg.get("is_certified", False)
    if not (voting_open or voting_closed_certified):
        return None

    vote_counts = await get_vote_counts(request)
    peers = [c async for c in tdb(request).candidates.find({"position": position_title})]
    if not peers:
        return None
    ranked = sorted(peers, key=lambda c: vote_counts.get(str(c["_id"]), 0), reverse=True)
    of = len(ranked)
    rank = next((i + 1 for i, c in enumerate(ranked) if str(c["_id"]) == candidate_id), None)
    if rank is None:
        return None
    trend = "leading" if rank == 1 else ("tied" if of > 1 and vote_counts.get(str(ranked[0]["_id"]), 0) == vote_counts.get(candidate_id, 0) else "trailing")
    return {"rank": rank, "of": of, "trend": trend}


@app.get("/candidates/status/{token}")
async def get_candidate_status(token: str, request: Request):
    """
    Public, no auth, no org_query/org_stamp — the token itself scopes the
    lookup (§3.2). One link covers every position a student applied for in
    a round, so this returns one entry per matching `applications` row.
    """
    # Public + unauthenticated: the token is the only credential, so cap guessing per IP.
    # Limit is generous because the portal polls every 20s and campus users share NAT'd IPs.
    await _check_rate_limit(request, bucket="cand_status", limit=120, window_s=60,
                            message="Too many requests. Please try again shortly.")
    # The one deliberately cross-tenant read: the token itself identifies the tenant.
    token_doc = await cross_tenant(db).candidate_tokens.find_one({"token": token})
    if not token_doc or not token_doc.get("org_id"):
        raise HTTPException(404, "Status link not found.")
    if _status_link_expired(token_doc):
        raise HTTPException(410, "This status link has expired or was withdrawn. Contact the IT administrators for a new one.")

    org_id = token_doc.get("org_id")
    # Every downstream helper here (org_query/org_stamp/get_phase_schedule/
    # get_vote_counts) reads tenant scope off request.state.org_id — set it
    # from the token's stored org_id rather than duplicating each helper.
    request.state.org_id = org_id

    # If the org shows public results from the start ("live"), results are already on
    # display for everyone, so the candidate-specific results band is redundant.
    public_results_live = (await get_security_settings(request))["public_results_mode"] == "live"

    apps = tdb_for(org_id).applications.find({
        "student_id": token_doc["student_id"],
        "round_id": token_doc["round_id"],
    })

    # Branding is scoped by the token's org here, so the portal never depends on
    # a tenant header that a bare status link doesn't carry.
    b = await tdb_for(org_id).settings.find_one({"name": "branding"}) or {}
    branding = {k: b.get(k, "") for k in
                ("logo_url", "org_name", "university_name", "university_logo_url")}

    candidacies = []
    async for app_doc in apps:
        title, _ = await _resolve_position_title(app_doc.get("position_id", ""), org_id)
        entry = {
            "position_title": title,
            "status": app_doc.get("status", "pending"),
            "application_snapshot": app_doc.get("application_snapshot"),   # always the ORIGINAL submission
        }
        # Public-safe edit marker: when, and the printed content after each correction. Never who or why.
        edits = [{"at": h.get("at"), "snapshot": h.get("after")} for h in _application_edit_history(app_doc)]
        if edits and app_doc.get("application_snapshot"):
            entry["edits"] = edits
        if app_doc.get("status") == "denied" and app_doc.get("denial_snapshot"):
            entry["denial_snapshot"] = app_doc["denial_snapshot"]
        if app_doc.get("certificate_id"):
            cert = await tdb_for(org_id).certificates.find_one({"certificate_id": app_doc["certificate_id"]})
            if cert and not cert.get("revoked"):
                entry["certificate_id"] = app_doc["certificate_id"]
                entry["certificate"] = {
                    "candidate_name": cert.get("candidate_name")
                        or (app_doc.get("application_snapshot") or {}).get("full_name")
                        or app_doc.get("full_name", ""),
                    "org_name": cert.get("org_name") or branding["org_name"],
                }
        if not public_results_live and app_doc.get("status") in ("approved", "removed"):
            cand = await tdb_for(org_id).candidates.find_one({"application_id": str(app_doc["_id"])})
            if cand:
                results = await _candidacy_results_band(
                    title, str(cand["_id"]), org_id, request)
                if results:
                    entry["results"] = results
        candidacies.append(entry)

    return {"candidacies": candidacies, "public_results_live": public_results_live,
            "branding": branding}


@app.get("/verify/{certificate_id}")
async def verify_certificate(certificate_id: str, request: Request):
    """
    Public. Looks up `certificates` only, never `applications` (§3.4) — what
    a certificate's QR code points to.
    """
    await _check_rate_limit(request, bucket="verify_cert", limit=30, window_s=60,
                            message="Too many requests. Please try again shortly.")
    # The one deliberately cross-tenant read: the certificate id identifies the issuing tenant.
    cert = await cross_tenant(db).certificates.find_one({"certificate_id": certificate_id})
    if not cert:
        raise HTTPException(404, "Certificate not found.")
    if cert.get("revoked"):
        return {"verified": False, "revoked": True}
    # Certificates issued before the organisation name was configured stored it
    # empty; fall back to the org's current branding (name only, nothing else).
    org_name = cert.get("org_name", "")
    if not org_name and cert.get("org_id"):
        b = await tdb_for(cert["org_id"]).settings.find_one({"name": "branding"}) or {}
        org_name = b.get("org_name", "")
    return {
        "verified": True,
        "candidate_name": cert.get("candidate_name", ""),
        "position_title": cert.get("position_title", ""),
        "org_name": org_name,
        "issued_at": cert.get("issued_at"),
    }


@app.post("/superadmin/candidates/{student_id:path}/resend-status-link")
async def resend_candidate_status_link(student_id: str, request: Request):
    """
    §3.8. Placed under /superadmin (rather than the /admin path the spec
    prose names) so the codebase's existing auth_guard_middleware — which
    already gates every /superadmin/* path to the superadmin role — covers
    it for free, consistent with every other force-approve/force-deny-tier
    action in this file.
    """
    round_id = await current_round_id(request)
    # candidate_tokens.student_id is written verbatim in submit_application —
    # try an exact match first, then the app's usual forgiving/normalized
    # comparison for a student_id typed differently than it was stored.
    student_id_canon = normalize_student_id(student_id)
    any_token = (
        await tdb(request).candidate_tokens.find_one({"round_id": round_id, "student_id": student_id})
        or await tdb(request).candidate_tokens.find_one({
            "round_id": round_id,
            "student_id": {"$regex": f"^{re.escape(student_id_canon)}$", "$options": "i"},
        })
    )
    if not any_token:
        raise HTTPException(404, "This student has no candidacy this round.")

    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    phones = (voter or {}).get("phone_numbers") or []
    if not phones:
        raise HTTPException(400, "This student has no phone number on file.")

    # A still-valid link is re-sent as is (and its expiry extended); an expired or
    # revoked one is replaced with a fresh link.
    token_doc = await _get_or_create_status_token(any_token["student_id"], round_id, request.state.org_id)
    await tdb(request).candidate_tokens.update_one(
        {"token": token_doc["token"]},
        {"$set": {"expires_at": datetime.utcnow() + timedelta(days=STATUS_LINK_TTL_DAYS)}})
    await send_sms(
        phones[0],
        f"Application received. Check status: {await frontend_url_for(request)}/status/{token_doc['token']}",
        request, kind="candidate_status_link",
    )
    await log_action("candidate_status_link_resent", current_actor(request),
                      {"student_id": student_id}, org_id=request.state.org_id)
    return {"status": "resent"}


@app.post("/superadmin/candidates/{student_id:path}/revoke-status-link")
async def revoke_candidate_status_link(student_id: str, request: Request):
    """Kills every status link for this student this round (e.g. a link shared by mistake).
    Under /superadmin, so the auth guard already restricts it to superadmins. A new link
    is issued the next time "Resend status link" is used."""
    round_id = await current_round_id(request)
    student_id_canon = normalize_student_id(student_id)
    res = await tdb(request).candidate_tokens.update_many(
        {"round_id": round_id, "student_id": {"$regex": f"^{re.escape(student_id_canon)}$", "$options": "i"}},
        {"$set": {"revoked": True}})
    if res.matched_count == 0:
        raise HTTPException(404, "This student has no status link this round.")
    await log_action("candidate_status_link_revoked", current_actor(request),
                     {"student_id": student_id}, org_id=request.state.org_id)
    return {"status": "revoked"}


# =============================================================================
# ADMIN ROUTES  (election control — accessible to both superadmin & commission)
# =============================================================================

@app.post("/verify-admin")
async def verify_admin(data: AdminLoginCheck, request: Request):
    email_key = data.email.strip().lower()
    org_id = require_org(request.state.org_id)
    ip = real_client_ip(request)

    await enforce_login_rate_limit(email_key, org_id, ip)

    try:
        result = await _verify_admin_credentials(data, request)
    except HTTPException as exc:
        if exc.status_code in (401, 404):
            await record_failed_login(email_key, org_id, ip)
        raise
    else:
        await clear_login_attempts(email_key, org_id, ip)
        return result


async def _verify_admin_credentials(data: AdminLoginCheck, request: Request):
    # ── Superadmin ── (env var based, no hashing needed — this is you)
    # compare_digest instead of == so a wrong password can't be narrowed down
    # character-by-character from response timing.
    if (secrets.compare_digest(data.email.encode(), SUPER_ADMIN_ID.encode())
            and secrets.compare_digest(data.password.encode(), SUPER_ADMIN_PASSWORD.encode())):
        if SUPERADMIN_TOTP_SECRET:
            if not data.totp_code:
                # Distinct status code from "wrong code" on purpose: this is
                # the signal the frontend uses to reveal the TOTP field only
                # once email+password have actually matched superadmin —
                # never shown for a wrong password, or for any other role.
                raise HTTPException(status_code=428, detail="totp_required")
            if not pyotp.TOTP(SUPERADMIN_TOTP_SECRET).verify(data.totp_code, valid_window=1):
                raise HTTPException(status_code=401, detail="Invalid authenticator code.")
        token = create_access_token(subject="superadmin", role="superadmin", org_id=request.state.org_id,
                             expire_minutes=SUPERADMIN_JWT_EXPIRE_MINUTES)
        return {
            "status": "success",
            "bypass": True,
            "role": "superadmin",
            "access_token": token,
            "message": "Superadmin bypass active."
        }

    # Every role below belongs to exactly one organization. Only the superadmin (above) may sign in
    # without X-Org-Slug; without this, a header-less login would search every client's staff.
    require_org(request.state.org_id)

    # ── IT Admin ──
    it_admin = await tdb(request).voters.find_one({
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    })
    if it_admin:
        stored_hash = it_admin.get("it_admin_password_hash", "")
        if not await verify_password_async(data.password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        expires = it_admin.get("it_admin_temp_password_expires")
        if expires and datetime.utcnow() > expires and it_admin.get("it_admin_must_change_password"):
            raise HTTPException(status_code=401, detail="Your temporary password has expired. Ask the superadmin for a new one.")
        await log_action("it_admin_login", it_admin["student_id"], {"email": data.email}, org_id=request.state.org_id)
        token = _login_token_for(it_admin, "it_admin", "it_admin_must_change_password", request.state.org_id)
        return {
            "status":              "success",
            "bypass":              True,
            "role":                "it_admin",
            "access_token":        token,
            "it_admin_id":         it_admin["student_id"],
            "full_name":           it_admin.get("full_name", ""),
            "must_change_password": it_admin.get("it_admin_must_change_password", True)
        }

    # ── Financial Controller ──
    financial_controller = await tdb(request).voters.find_one({
        "financial_controller_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_financial_controller": True
    })
    if financial_controller:
        stored_hash = financial_controller.get("financial_controller_password_hash", "")
        if not await verify_password_async(data.password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        expires = financial_controller.get("financial_controller_temp_password_expires")
        if expires and datetime.utcnow() > expires and financial_controller.get("financial_controller_must_change_password"):
            raise HTTPException(status_code=401, detail="Your temporary password has expired. Ask the superadmin for a new one.")
        await log_action("financial_controller_login", financial_controller["student_id"], {"email": data.email}, org_id=request.state.org_id)
        token = _login_token_for(financial_controller, "financial_controller",
                                  "financial_controller_must_change_password", request.state.org_id)
        return {
            "status":              "success",
            "bypass":              True,
            "role":                "financial_controller",
            "access_token":        token,
            "financial_controller_id": financial_controller["student_id"],
            "full_name":           financial_controller.get("full_name", ""),
            "must_change_password": financial_controller.get("financial_controller_must_change_password", True)
        }

    # ── Overseer ──
    overseer = await tdb(request).voters.find_one({
        "overseer_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_overseer": True
    })
    if overseer:
        stored_hash = overseer.get("overseer_password_hash", "")
        if not await verify_password_async(data.password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        expires = overseer.get("overseer_temp_password_expires")
        if expires and datetime.utcnow() > expires and overseer.get("overseer_must_change_password"):
            raise HTTPException(status_code=401, detail="Your temporary password has expired. Ask the superadmin for a new one.")
        await log_action("overseer_login", overseer["student_id"], {"email": data.email}, org_id=request.state.org_id)
        token = _login_token_for(overseer, "overseer", "overseer_must_change_password", request.state.org_id)
        return {
            "status":              "success",
            "bypass":              True,
            "role":                "overseer",
            "access_token":        token,
            "overseer_id":         overseer["student_id"],
            "full_name":           overseer.get("full_name", ""),
            "must_change_password": overseer.get("overseer_must_change_password", True)
        }

    # ── Vetting Panel ──
    # Panel members live in panel_members (not voters), so externals (non-members)
    # can log in here without a voter row. Same timing-safe shape as the others.
    panelist = await tdb(request).panel_members.find_one({
        "email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "active": True,
    })
    if panelist:
        stored_hash = panelist.get("password_hash", "")
        if not await verify_password_async(data.password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        expires = panelist.get("temp_password_expires")
        if expires and datetime.utcnow() > expires and panelist.get("must_change_password"):
            raise HTTPException(status_code=401, detail="Your temporary password has expired. Ask the superadmin for a new one.")
        if await _panel_access_ended(request, panelist):
            raise HTTPException(status_code=401, detail="Your panel access has ended.")
        if await _external_has_no_end(request, panelist):
            raise HTTPException(status_code=401, detail="Your panel access has no end date set yet. "
                                                        "Ask the superadmin to set one.")
        await log_action("vetting_panel_login", panelist["panel_member_id"],
                         {"email": data.email, "is_member": panelist.get("is_member", False)},
                         org_id=request.state.org_id)
        token = _login_token_for(panelist, "vetting", "must_change_password", request.state.org_id,
                                 expires_at=await _panel_access_end(request, panelist))
        return {
            "status":              "success",
            "bypass":              True,
            "role":                "vetting",
            "access_token":        token,
            "panel_member_id":     panelist["panel_member_id"],
            "full_name":           panelist.get("full_name", ""),
            "is_member":           panelist.get("is_member", False),
            "must_change_password": panelist.get("must_change_password", True),
        }

    # ── Commissioner ──
    commissioner = await tdb(request).voters.find_one({
        "commissioner_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_commissioner": True
    })
    if not commissioner:
        # SECURITY: this used to be a 404 while every other "wrong
        # credentials" branch above returns 401 — a status-code oracle that
        # let an attacker learn "this email belongs to *some* admin
        # account" without a password, just from which code came back.
        # Also run a dummy bcrypt comparison so a no-account-found request
        # takes roughly the same time as one that found an account and
        # checked its password — bcrypt is the only slow step in this
        # function, so skipping it entirely on the "not found" path is a
        # timing oracle for the same information. _DUMMY_BCRYPT_HASH is a
        # fixed, valid bcrypt hash of no real password; its value doesn't
        # matter, only that checkpw does real work against it.
        await run_in_threadpool(bcrypt.checkpw, data.password.encode()[:72], _DUMMY_BCRYPT_HASH)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    stored_hash = commissioner.get("commissioner_password_hash", "")
    if not await verify_password_async(data.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    expires = commissioner.get("commissioner_temp_password_expires")
    if expires and datetime.utcnow() > expires and commissioner.get("commissioner_must_change_password"):
        raise HTTPException(status_code=401, detail="Your temporary password has expired. Ask the superadmin for a new one.")

    await log_action("commissioner_login", commissioner["student_id"], {"email": data.email}, org_id=request.state.org_id)
    token = _login_token_for(commissioner, "commission", "commissioner_must_change_password", request.state.org_id)
    return {
        "status":              "success",
        "bypass":              True,
        "role":                "commission",
        "access_token":        token,
        "commissioner_id":     commissioner["student_id"],
        "full_name":           commissioner.get("full_name", ""),
        "must_change_password": commissioner.get("commissioner_must_change_password", True)
    }


@app.post("/admin/logout")
async def admin_logout(request: Request):
    """Revoke the current session token immediately, rather than leaving it
    valid until its natural 8h expiry. Any admin role can call this on
    themselves; there's no separate 'revoke someone else's session' endpoint
    yet — see the superadmin org-reset / password-reset flows for dealing
    with a compromised non-superadmin account in the meantime."""
    admin = request.state.admin  # set by auth_guard_middleware
    await db.revoked_tokens.insert_one({"jti": admin.get("jti"), "revoked_at": datetime.utcnow()})
    await log_action("admin_logout", admin.get("sub", "unknown"), {}, org_id=admin.get("org_id"))
    return {"status": "success"}


@app.post("/admin/toggle-election")
async def toggle_election(request: Request, data: ElectionToggle | None = None,
                          admin: dict = Depends(require_role("superadmin"))):
    current    = await tdb(request).settings.find_one({"name": "election_config"})
    new_status = not (current.get("is_open", True) if current else True)
    now        = datetime.utcnow()
    schedule   = await get_phase_schedule(request)
    vw         = voting_window_state(schedule, now)
    reason     = ((data.reason if data else None) or "").strip()

    # Starting (re-opening) an election while its results are still certified would leave a
    # "FINAL and BINDING" stamp on a live election. Certification is chief-commissioner-only, so
    # it is not silently cleared here (that would let a superadmin bypass that sign-off) — the
    # certification has to be revoked first, same rule as the election reset below.
    if new_status and (current or {}).get("is_certified"):
        raise HTTPException(400, "Results are certified. Revoke certification before starting the election.")

    # A roster freeze with no resolvable timestamp is a no-op: roster_status() only ever
    # freezes once `now >= freeze_at`, and with freeze_at None it never does, regardless of
    # roster_freeze_enabled. That silently left "voters can be added/removed all the way
    # through voting" as the default whenever nobody had set an explicit freeze time or a
    # voting-phase start. Block opening in that state (unless the org explicitly disabled
    # roster freeze protection) rather than let it open unprotected by omission.
    if new_status:
        sec = await get_security_settings(request)
        if sec["roster_freeze_enabled"]:
            voting_start = (await get_phase_schedule(request))["phases"]["voting"].get("start")
            if not sec["roster_freeze_at"] and not voting_start:
                raise HTTPException(400, {
                    "code": "no_roster_freeze_time",
                    "message": ("Roster freeze is enabled but has no time to freeze at. Set a roster freeze "
                                "time or a voting start time before opening the election, or explicitly "
                                "disable roster freeze if this election doesn't need it."),
                })

    # Stopping while an enforced voting window is still live ends voting before the published
    # deadline. That is sometimes necessary (security incident), but it must be deliberate and on
    # the record — same principle as phase exception grants. 409 (not 400) so the UI can tell
    # "ask for a reason" apart from a real validation failure.
    early_stop = (not new_status) and vw["live"]
    if early_stop and len(reason) < EARLY_STOP_MIN_REASON:
        raise HTTPException(409, {
            "code": "early_stop_reason_required",
            "message": "The voting window is still open. Stopping now ends voting early — a reason is required.",
            "voting_ends_at": vw["end"].isoformat(),
            "timezone": schedule["timezone"],
        })

    await tdb(request).settings.update_one(
        {"name": "election_config"},
        {"$set": org_stamp(request, {"is_open": new_status, "name": "election_config"})},
        upsert=True
    )
    invalidate_settings(request.state.org_id)
    # Was hardcoded actor="superadmin" — this route sits under /admin/*, so
    # ANY admin role could trigger it and the log would still name superadmin.
    details = {"is_open": new_status, "role": current_role(request)}
    if early_stop:
        details.update({
            "early_stop": True,
            "reason": reason[:500],
            "voting_window_end_utc": vw["end"].isoformat(),
        })
    await log_action("election_toggled", current_actor(request), details, org_id=request.state.org_id)
    logger.info(f" Election toggled to: {'OPEN' if new_status else 'CLOSED'}" + (" (EARLY STOP)" if early_stop else ""))

    # Tell the UI what "started" actually means: is_open is only the master switch, voting still
    # needs the enforced window to be live.
    return {
        "is_open": new_status,
        "early_stop": early_stop,
        "voting_phase_open": _phase_is_open(schedule["phases"]["voting"], now),
        "voting_window_ended": vw["ended"],
        "voting_opens_at": vw["start"].isoformat() if vw["not_started"] else None,
        "timezone": schedule["timezone"],
    }


# NOTE: /admin/schedule-election and /admin/clear-schedule (a standalone
# start_time/end_time window on election_config) were retired in favor of
# the phase schedule (PHASE_NAMES / assert_phase_open / POST
# /admin/schedule/phases) — see the "voting" phase, which /verify-identity,
# /vote and /vote-bulk all now check consistently instead of two disconnected
# timers. The historical election_scheduled / election_schedule_cleared
# action labels stay in the frontend's Activity Log formatter so old log
# entries still render human-readably.


@app.post("/admin/reset-election")
async def reset_election(request: Request, admin: dict = Depends(require_role("superadmin"))):
    # Refuse to wipe a certified election. The UI already disables the button
    # when is_certified is true, but a disabled button is not an access
    # control — the endpoint has to enforce it too.
    config = await tdb(request).settings.find_one({"name": "election_config"})
    if (config or {}).get("is_certified"):
        raise HTTPException(400, "Certified results cannot be reset. Revoke certification first.")
    # Safety snapshot BEFORE anything is deleted. If it cannot be uploaded to B2 the
    # reset aborts — it never continues without a backup. A reset only ever touches the caller's
    # own tenant: a missing X-Org-Slug is rejected, there is no "reset every tenant" mode.
    org_id = require_org(request.state.org_id)
    try:
        await backup.snapshot_before_destructive(db, org_id, "reset-election")
    except Exception as e:
        logger.error(f"reset-election aborted: pre-reset snapshot failed: {e}")
        await backup.send_alert(
            "[BallotBox] Reset ABORTED: pre-reset backup failed",
            f"An election reset was requested by {current_actor(request)} but the safety snapshot "
            f"could not be uploaded, so nothing was deleted.\n\nError: {e}")
        raise HTTPException(503, "Reset aborted: the safety backup could not be uploaded, so nothing was deleted.")
    await tdb(request).otps.delete_many({})
    # New limiter state belongs to this election run only (the roster_ledger is append-only and is kept).
    _kf = {"key": {"$regex": f"^{re.escape(org_id)}:otp:"}}
    await db.otp_send_state.delete_many(_kf)
    await db.otp_guess_state.delete_many(_kf)
    await db.sms_usage.delete_many({"org_key": org_id})
    await db.ip_send_stats.delete_many({})
    await tdb(request).contact_changes.delete_many({})
    await _save_security(request, {"freeze_lifted_at": datetime.utcnow(), "epoch_at": datetime.utcnow()})
    await append_ledger(request.state.org_id, "election_reset", "election", current_actor(request),
                        current_role(request), {"note": "roster freeze lifted; caps and quotas restart"})
    await tdb(request).voters.update_many({}, {"$set": {"has_voted": False, "last_status": "idle"}})
    await tdb(request).candidates.update_many({}, {"$set": {"votes": 0}})
    # votes now live in vote_events, not candidates.votes — without this, a
    # reset (used for testing/re-runs) would leave stale events behind and
    # the next election's tally would include last time's votes.
    await tdb(request).vote_events.delete_many({})
    # If this election was ever checkpointed, those checkpoints now
    # reference _id ranges that no longer exist — verify_audit_chain would
    # report the chain permanently invalid, a false alarm, not real
    # tampering. Resetting means "this election's data doesn't count," so
    # its audit trail is wiped too. Any checkpoint already anchored to B2
    # (diff #4) stays locked there regardless — Object Lock doesn't care
    # what Mongo does, it just becomes an orphaned record with no local
    # reference, which is harmless.
    await db.audit_checkpoints.delete_many(org_query(request))
    await log_action("election_reset", current_actor(request), {
        "role": current_role(request)
    }, org_id=request.state.org_id)
    return {"status": "success"}


@app.post("/admin/toggle-certification")
async def toggle_certification(request: Request, admin: dict = Depends(require_chief_commissioner)):
    current    = await tdb(request).settings.find_one({"name": "election_config"})
    new_status = not (current.get("is_certified", False) if current else False)
    # "Stop the election before certifying" used to live only in the dashboards. Certified results
    # also block voting (assert_voting_allowed), so certifying an open election was a way to end
    # voting early with no reason on record. Enforce it here; revoking is always allowed.
    if new_status and (current.get("is_open", True) if current else True):
        raise HTTPException(400, "Stop the election before certifying results.")
    await tdb(request).settings.update_one(
        {"name": "election_config"},
        {"$set": {"is_certified": new_status}},
        upsert=True
    )
    invalidate_settings(request.state.org_id)
    # Was hardcoded actor="superadmin". Certification is the single most
    # consequential action in the system; it has to name the real signer.
    await log_action("results_certified", current_actor(request), {
        "is_certified": new_status, "role": current_role(request)
    }, org_id=request.state.org_id)
    return {"is_certified": new_status}


async def get_egosms_balance() -> dict:
    """EgoSMS's balance check lives on a different, JSON-only endpoint than
    the plain-text one used for sending. Sending already works against
    comms.egosms.co, so that's tried first — www.egosms.co appears to be a
    separate account provisioning and can 400 with "user does not exist"
    even for a username that's valid on comms.egosms.co."""
    if not (EGOSMS_USER and EGOSMS_PASS):
        return {"balance": None, "currency": "UGX", "error": "EGOSMS_USERNAME/PASSWORD not configured."}
    payload = {"method": "Balance", "userdata": {"username": EGOSMS_USER, "password": EGOSMS_PASS}}
    last_error = None
    for host in ("https://comms.egosms.co/api/v1/json/", "https://www.egosms.co/api/v1/json/"):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(host, json=payload, timeout=15.0)
                body = response.json()
            if str(body.get("Status", "")).upper() == "OK":
                return {"balance": body.get("Balance"), "currency": "UGX", "provider": "egosms"}
            # "user does not exist" on one host just means try the other
            # host's account — only report the error once both are tried.
            last_error = body.get("Message") or "Unknown error"
        except Exception as e:
            logger.error(f"EgoSMS balance check failed against {host}: {e}")
            last_error = "Could not reach EgoSMS."
    return {"balance": None, "currency": "UGX", "error": last_error}


async def _fetch_and_check_provider_balances() -> dict:
    """Shared by /admin/sms-balance and the periodic cross-check below: fetch
    both providers concurrently, and alert if either can't be read at all."""
    egosms, mambosms = await asyncio.gather(get_egosms_balance(), _get_mambosms_balance())
    # Either provider silently running dry mid-election is a Tier-1-adjacent
    # risk (it just degrades to "the other provider carries all traffic"
    # rather than an outright outage), so this doubles as the check: a
    # superadmin manually hitting the endpoint, or the periodic cross-check,
    # gets an alert the moment either balance can't be read at all.
    for name, result in (("EgoSMS", egosms), ("MamboSMS", mambosms)):
        if result.get("error"):
            await alert_warning(f"{name} balance check failed", result["error"], cooldown_s=3600)
    return {"egosms": egosms, "mambosms": mambosms}


@app.get("/admin/sms-balance")
async def get_sms_balance(admin: dict = Depends(require_role("superadmin"))):
    """Live balance for both SMS providers — restricted to superadmin since
    both calls hit billable third-party accounts."""
    return await _fetch_and_check_provider_balances()


# Cross-check safety net: sms_budget_total/sms_usage is an admin-set *unit*
# counter, tracked internally and never verified against what's actually
# funded on either provider's account. This periodically pulls the real
# currency balance and warns if it's low even though the internal counter
# thinks there's plenty left — catches a stale/wrong sms_budget_total rather
# than replacing it (that's the simpler, lower-risk option vs. switching
# gating itself to live currency, which would need a cost-per-SMS figure and
# a caching layer to avoid a provider call on every vote).
_LAST_BALANCE_CROSSCHECK: dict[str, float] = {}
_BALANCE_CROSSCHECK_INTERVAL_S = 15 * 60


async def _cross_check_live_balance(org_id, sec: dict, usage: dict) -> None:
    floor = sec.get("sms_balance_floor_ugx")
    if not floor:
        return
    key = org_id or "default"
    now = time.time()
    if now - _LAST_BALANCE_CROSSCHECK.get(key, 0) < _BALANCE_CROSSCHECK_INTERVAL_S:
        return
    _LAST_BALANCE_CROSSCHECK[key] = now

    balances = await _fetch_and_check_provider_balances()
    numeric = []
    for result in balances.values():
        try:
            numeric.append(float(result["balance"]))
        except (TypeError, ValueError, KeyError):
            pass  # provider errored or returned a non-numeric balance; already alerted above
    if not numeric:
        return  # both providers unreadable right now — already covered by the per-provider alert
    total_live = sum(numeric)
    if total_live >= floor:
        return

    budget_total = sec.get("sms_budget_total")
    counter_left = (budget_total - usage.get("sent_total", 0)) if budget_total else None
    await send_alert(
        "Live SMS balance below configured floor",
        f"Org: {key}. Combined live balance across providers is {total_live:.0f} UGX, "
        f"below the configured floor of {floor} UGX.\n"
        f"EgoSMS: {balances['egosms'].get('balance')} | MamboSMS: {balances['mambosms'].get('balance')}\n"
        + (f"Internal budget counter currently shows {counter_left} SMS remaining of {budget_total} — "
           f"that number may be stale or based on the wrong per-SMS cost."
           if counter_left is not None else
           "No internal sms_budget_total is set, so this is the only signal you have on remaining runway."),
        level="critical" if total_live <= floor * 0.5 else "warning",
    )


async def _get_mambosms_balance() -> dict:
    if not MAMBOSMS_API_KEY:
        return {"balance": None, "currency": "UGX", "error": "MAMBOSMS_API_KEY not configured."}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api-mongolia.mambosms.com/v1/accounts/balance",
                headers={"Authorization": MAMBOSMS_API_KEY},
                timeout=15.0,
            )
            body = response.json()
            if body.get("success"):
                return {"balance": body["data"]["balance"], "currency": "UGX", "provider": "mambosms"}
            return {"balance": None, "currency": "UGX", "error": (body.get("messages") or ["Unknown error"])[0]}
    except Exception as e:
        logger.error(f"MamboSMS balance check failed: {e}")
        return {"balance": None, "currency": "UGX", "error": "Could not reach MamboSMS."}


@app.post("/admin/test-connection")
async def test_sms_connection(data: AdminTestSMS, request: Request, admin: dict = Depends(require_role("superadmin"))):
    # Restricted to superadmin: this sends a real, billable SMS to an
    # arbitrary number supplied in the body. Under "any admin token" it was a
    # free SMS relay for every provisioned role. With no `provider` it goes through the same
    # routing as real OTPs, so the test reflects what a voter would actually experience; with a
    # `provider` it checks that one account directly (ignoring routing and fallback).
    if data.provider is not None and data.provider not in SMS_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider must be 'egosms' or 'mambosms'.")
    await log_action("sms_test_sent", current_actor(request),
                     {"phone": _mask_phone(data.phone), "provider": data.provider or "routing"}, org_id=request.state.org_id)
    text = "SMS Connection Verified for BallotBox!"
    if data.provider:
        label = _SMS_PROVIDER_LABEL[data.provider]
        if DEBUG_MODE:
            success = await send_sms(data.phone, text, request, kind="test")
        else:
            outcome = await _sms_try_provider(data.provider, data.phone, text)
            if outcome in ("ok", "ambiguous"):
                await _safe_count_sms(request.state.org_id, "test")
            success = outcome == "ok"
            if outcome == "ambiguous":
                raise HTTPException(status_code=400, detail=f"{label} did not answer in time. The test message may still arrive.")
        if success:
            return {"status": "success", "message": f"Test message sent via {label} to {data.phone}"}
        raise HTTPException(status_code=400, detail=f"{label} rejected the request. Check server logs for the reason.")
    success = await send_sms(data.phone, text, request, kind="test")
    if success:
        return {"status": "success", "message": f"Test message delivered to {data.phone}"}
    raise HTTPException(status_code=400, detail="Every provider allowed by the current routing rejected the request. Check server logs for the reason.")


# Applied to student_id and full_name from an imported CSV. Generous enough
# for any real name/ID, but a hard ceiling against an accidentally (or
# deliberately) malformed file stuffing an unbounded string into a field
# that later gets re-rendered in the voter register, official report, and
# analytics screens.
IMPORT_FIELD_MAX_LEN = 200

# A normalized Ugandan MSISDN is "256" + 9 digits = 12 digits total. This
# isn't a hard validity check (real numbers can vary) — it's a heuristic so
# an obviously mistyped phone number (a stray extra/missing digit) can be
# flagged back to the importing admin instead of silently being saved as a
# different, still-plausible-looking number and only discovered when that
# voter never receives an OTP.
_UGANDA_MSISDN_RE = re.compile(r"^256\d{9}$")


def _normalize_phone_field(raw_phone_field: str, sid: str, row_num: int, warnings: list) -> list:
    formatted = []
    for num in raw_phone_field.split('/'):
        clean = re.sub(r'\D', '', num.strip())
        if not clean:
            continue
        if clean.startswith('0'):
            clean = '256' + clean[1:]
        elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
            clean = '256' + clean
        if not _UGANDA_MSISDN_RE.match(clean):
            # Kept, just surfaced — the importing admin can judge one flagged row.
            warnings.append(
                f"Row {row_num} ({sid}): phone \"{num.strip()}\" normalized to \"{clean}\", "
                f"which doesn't look like a standard Ugandan number — please double-check it.")
        if clean not in formatted:
            formatted.append(clean)
    return formatted


async def get_voter_fields(request: Request) -> dict:
    """Per-org optional voter attributes (gender, programme, any custom field), each switchable.
    {"fields": [{key,label,standard,enabled,public}], "min_group_size": int}."""
    doc = await tdb(request).settings.find_one({"name": "voter_fields"}) or {}
    lo, hi = MIN_GROUP_RANGE
    k = doc.get("min_group_size")
    return {"fields": merge_voter_fields(doc.get("fields")),
            "min_group_size": k if isinstance(k, int) and lo <= k <= hi else DEFAULT_MIN_GROUP}


DEFAULT_ID_NOUN = "registration number"


def _id_noun_from(branding) -> str:
    """How this org names the voter ID inside a sentence ("student number"); the original wording if unset."""
    label = ((branding or {}).get("id_label") or "").strip()
    return label.lower() if label else DEFAULT_ID_NOUN


async def id_noun(org_id) -> str:
    """Same, looked up (cached) for an org. Only called on error / message paths, never per normal request."""
    return _id_noun_from(await cached_setting(org_id, "branding"))


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _parse_voter_table(table, header_row: int, mapping: dict, fields: list[dict] | None = None, roster_ids=(),
                       noun: str = DEFAULT_ID_NOUN) -> dict:
    """Shared by preview, the legacy endpoint and the column-mapping flow. Last row wins for a repeated ID
    (warned). mapping: {target: [column index, ...]} from tabular_import — student_id / full_name / phone plus
    any enabled voter field. Several columns for full_name or phone are joined (First + Surname, Phone 1 / 2).
    Row numbers in warnings are the row numbers in the uploaded file. roster_ids: the org's existing
    registration numbers, used as the reference for the registration-number format check (warn-only)."""
    enabled = {f["key"] for f in (fields or []) if f.get("enabled")}
    attr_keys = [k for k in mapping if k not in CORE_KEYS and k in enabled]
    rows: dict[str, dict] = {}
    row_nums: dict[str, int] = {}
    warnings: list[str] = []
    skipped = 0
    if table.truncated:
        warnings.append(f"File truncated at {MAX_CSV_ROWS} rows.")
    if not (mapping.get("student_id") and mapping.get("full_name")):
        return {"rows": {}, "warnings": [f"No {noun} / full name column was found."],
                "skipped": 0, "attr_fields": []}
    if not mapping.get("phone"):
        warnings.append("No phone column is mapped: voters imported this way have no number to receive an OTP on.")

    def cell(cells, i):
        return cells[i] if i < len(cells) else ""

    for row_num, cells in table.data_rows(header_row):
        if row_num - header_row > MAX_CSV_ROWS:
            warnings.append(f"File truncated at {MAX_CSV_ROWS} rows.")
            break
        sid   = normalize_student_id(cell(cells, mapping["student_id"][0]))
        name  = normalize_name(" ".join(p for p in (cell(cells, i).strip() for i in mapping["full_name"]) if p))
        if not (sid and name):
            skipped += 1
            continue
        if len(sid) > IMPORT_FIELD_MAX_LEN or len(name) > IMPORT_FIELD_MAX_LEN:
            skipped += 1
            warnings.append(f"Row {row_num}: Student ID or full name exceeds {IMPORT_FIELD_MAX_LEN} characters — skipped.")
            continue
        if sid in rows:
            warnings.append(f"Row {row_num} ({sid}): {noun} appears more than once in the file — the later row is used.")
        raw_phone = "/".join(p for p in (cell(cells, i).strip() for i in mapping.get("phone", [])) if p)
        attrs = {}
        for k in attr_keys:
            v = normalize_attr_value(cell(cells, mapping[k][0]))
            if v:
                attrs[k] = v
        rows[sid] = {
            "student_id": sid, "full_name": name,
            # A cell like "0772123456, 0701234567" is two numbers, not one long one.
            "phone_numbers": _normalize_phone_field(re.sub(r"[,;\n]+", "/", raw_phone), sid, row_num, warnings),
            "attrs": attrs,
        }
        row_nums[sid] = row_num
    # Format check runs on the already-normalized IDs. Warn only: nothing is skipped or blocked.
    shape = shape_warnings(check_id_shapes(rows.keys(), roster_ids), len(rows), row_nums, noun=noun)
    return {"rows": rows, "warnings": shape + warnings, "skipped": skipped, "attr_fields": attr_keys}


def _load_table(content: bytes, filename: str | None, sheet: str | None = None):
    try:
        return read_table(content, filename or "", sheet)
    except TableError as e:
        raise HTTPException(400, str(e))


def _parse_voter_csv(content: bytes, fields: list[dict] | None = None, roster_ids=(), filename: str = "") -> dict:
    """No manual mapping: the header row and columns are guessed from the file itself (CSV/TSV/XLSX).
    Used by the legacy one-shot endpoint and by /preview when the client sends no mapping."""
    table = _load_table(content, filename)
    header_row = guess_header_row(table.rows, fields)
    mapping = suggest_mapping(table.headers(header_row), fields)
    return _parse_voter_table(table, header_row, mapping, fields, roster_ids)


async def _roster_ids(request: Request) -> list[str]:
    return [normalize_student_id(i) for i in await tdb(request).voters.distinct("student_id", org_query(request)) if i]


_NEW_VOTER_DEFAULTS = {
    "is_commissioner": False, "has_voted": False, "last_active": None, "last_status": "idle", "otp_count": 0,
}
_STAFF_ROLE_FLAGS = ("is_commissioner", "is_it_admin", "is_financial_controller", "is_overseer")
_STAFF_FLAGS = (
    ("has_voted", "Has already voted"),
    ("is_commissioner", "Commissioner"),
    ("is_it_admin", "IT admin"),
    ("is_financial_controller", "Financial controller"),
    ("is_overseer", "Overseer"),
)


async def _diff_roster(request: Request, rows: dict, enabled_keys=frozenset()) -> dict:
    """Compares parsed CSV rows against the live roster (matched on canonical registration number).
    Voter attributes (enabled_keys only): filling an EMPTY value is never a "change" (returned in
    attr_fills, applied automatically); only overwriting a different existing value shows up as changed."""
    existing = {}
    async for v in tdb(request).voters.find({}):
        existing[normalize_student_id(v.get("student_id", ""))] = v
    applicants = set(await tdb(request).applications.distinct("student_id", org_query(request)))

    new, changed, unchanged, missing, attr_fills = [], [], 0, [], []
    for sid, r in rows.items():
        attrs = {k: x for k, x in (r.get("attrs") or {}).items() if k in enabled_keys}
        v = existing.get(sid)
        if not v:
            new.append({**r, "attrs": attrs})
            continue
        old_name   = v.get("full_name", "")
        old_phones = v.get("phone_numbers") or []
        name_changed   = normalize_name(old_name) != r["full_name"]
        phones_changed = set(old_phones) != set(r["phone_numbers"])
        fills, overwrites = diff_attrs(v.get("attrs"), attrs, enabled_keys)
        if fills:
            attr_fills.append({"actual_id": v["student_id"], "attrs": fills})
        if name_changed or phones_changed or overwrites:
            changed.append({
                "student_id": sid, "actual_id": v["student_id"],
                # Admin/commissioner accounts receive their OTPs on these numbers.
                "staff": any(v.get(f) for f in _STAFF_ROLE_FLAGS),
                "name_changed": name_changed, "phones_changed": phones_changed, "attrs_changed": overwrites,
                "old_name": old_name, "new_name": r["full_name"],
                "old_phones": old_phones, "new_phones": r["phone_numbers"],
            })
        else:
            unchanged += 1
    for sid, v in existing.items():
        if sid in rows:
            continue
        reasons = [label for flag, label in _STAFF_FLAGS if v.get(flag)]
        if v.get("student_id") in applicants or sid in applicants:
            reasons.append("Has an application / candidacy")
        missing.append({
            "student_id": sid, "actual_id": v["student_id"], "full_name": v.get("full_name", ""),
            "protected": bool(reasons), "protected_reasons": reasons,
        })
    return {"new": new, "changed": changed, "unchanged": unchanged, "missing": missing, "attr_fills": attr_fills}


def _public_diff(diff: dict) -> dict:
    """Phones are masked for display; full numbers never leave the server via preview."""
    return {
        "new": [{"student_id": r["student_id"], "full_name": r["full_name"],
                 "phones": [_mask_phone(p) for p in r["phone_numbers"]], "attrs": r.get("attrs") or {}} for r in diff["new"]],
        "changed": [{
            "student_id": c["student_id"], "name_changed": c["name_changed"], "phones_changed": c["phones_changed"],
            "staff": c["staff"], "attrs_changed": c["attrs_changed"],
            "old_name": c["old_name"], "new_name": c["new_name"],
            "old_phones": [_mask_phone(p) for p in c["old_phones"]],
            "new_phones": [_mask_phone(p) for p in c["new_phones"]],
        } for c in diff["changed"]],
        "missing": [{k: m[k] for k in ("student_id", "full_name", "protected", "protected_reasons")} for m in diff["missing"]],
        "unchanged": diff["unchanged"],
        "attr_fills": len(diff["attr_fills"]),
    }


@app.post("/admin/import-voters/inspect")
async def import_voters_inspect(request: Request, file: UploadFile = File(...),
                                sheet: str | None = Form(None), header_row: int | None = Form(None),
                                admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Step 0 of a roster update ("Match columns"): reads the file and returns its sheets, a raw view of
    the top rows, the header row it picked (or the one asked for), the columns and a suggested
    mapping. Nothing is stored. The client re-calls this when the admin changes sheet or header row."""
    await assert_roster_unfrozen(request)
    vf = (await get_voter_fields(request))["fields"]
    table = _load_table(await _read_csv_upload(file), file.filename, sheet)
    try:
        out = describe_table(table, header_row, vf)
        label = ((await cached_setting(request.state.org_id, "branding")) or {}).get("id_label", "").strip()
        if label:
            for t in out["targets"]:
                if t["key"] == "student_id":
                    t["label"] = label
        return out
    except TableError as e:
        raise HTTPException(400, str(e))


@app.post("/admin/import-voters/preview")
async def import_voters_preview(request: Request, file: UploadFile = File(...),
                                mapping: str | None = Form(None), sheet: str | None = Form(None),
                                header_row: int | None = Form(None),
                                admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Step 1 of a roster update: nothing is written to the roster. Returns what the file would
    add, change and leave behind so the admin can choose an action for each group.
    mapping (optional JSON {field: [column index, ...]}) + sheet + header_row come from the Match columns
    step; without them the header row and columns are guessed, which is what plain CSV clients rely on."""
    await assert_roster_unfrozen(request)
    vf = (await get_voter_fields(request))["fields"]
    enabled = {f["key"] for f in vf if f["enabled"]}
    content = await _read_csv_upload(file)
    if mapping is None or not mapping.strip():
        parsed = _parse_voter_csv(content, vf, await _roster_ids(request), file.filename or "")
    else:
        try:
            chosen = validate_mapping(json.loads(mapping), enabled)
        except (ValueError, TypeError) as e:      # json errors and TableError are both ValueErrors
            raise HTTPException(400, str(e) if isinstance(e, TableError) else "The column mapping is not valid.")
        table = _load_table(content, file.filename, sheet)
        hr = header_row or guess_header_row(table.rows, vf)
        if not 1 <= hr <= len(table.rows):
            raise HTTPException(400, f"Row {hr} is not in the file.")
        noun = await id_noun(request.state.org_id)
        parsed = _parse_voter_table(table, hr, chosen, vf, await _roster_ids(request), noun=noun)
    if not parsed["rows"]:
        raise HTTPException(400, f"No valid rows found. Each row needs a {noun} and a full name; "
                                 "check the columns you matched and the header row.")
    diff = await _diff_roster(request, parsed["rows"], enabled)
    preview_id = secrets.token_urlsafe(16)
    await tdb(request).voter_import_previews.insert_one({
        "preview_id": preview_id, "org_id": request.state.org_id, "created_by": current_actor(request),
        "created_at": datetime.utcnow(), "rows": list(parsed["rows"].values()),
    })
    return {
        "preview_id": preview_id,
        "summary": {"file_rows": len(parsed["rows"]), "new": len(diff["new"]), "changed": len(diff["changed"]),
                    "unchanged": diff["unchanged"], "missing": len(diff["missing"]),
                    "skipped_rows": parsed["skipped"], "warning_count": len(parsed["warnings"]),
                    "attr_fills": len(diff["attr_fills"]),
                    "fields_in_file": [{"key": f["key"], "label": f["label"]} for f in vf if f["key"] in parsed["attr_fields"]]},
        "warnings": parsed["warnings"][:50],
        **_public_diff(diff),
    }


class VoterImportApply(BaseModel):
    preview_id: str
    new_action: str = "add"            # add | skip
    changed_default: str = "apply"     # apply | skip
    changed_overrides: dict[str, str] = {}   # student_id -> apply | skip
    phone_mode: str = "replace"        # replace | merge (keep old numbers, add the new ones)
    missing_default: str = "keep"      # keep | remove
    missing_overrides: dict[str, str] = {}   # student_id -> keep | remove
    id_label: str = ""                 # optional: what the org calls the voter ID (saved to branding)


@app.post("/admin/import-voters/apply")
async def import_voters_apply(data: VoterImportApply, request: Request,
                              admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Step 2. The diff is recomputed against the roster as it is NOW (it may have changed since the
    preview). Only name/phones are ever touched on existing voters — never has_voted, roles or
    credentials — and voters with a vote, a staff role or an application can never be removed."""
    await assert_roster_unfrozen(request)
    if (data.new_action not in ("add", "skip") or data.changed_default not in ("apply", "skip")
            or data.phone_mode not in ("replace", "merge") or data.missing_default not in ("keep", "remove")
            or any(v not in ("apply", "skip") for v in data.changed_overrides.values())
            or any(v not in ("keep", "remove") for v in data.missing_overrides.values())):
        raise HTTPException(400, "Invalid import action.")
    org_id = require_org(request.state.org_id)
    # Only the admin who uploaded the file can apply its preview.
    prev = await tdb(request).voter_import_previews.find_one(
        {"preview_id": data.preview_id, "org_id": org_id, "created_by": current_actor(request)})
    if not prev:
        raise HTTPException(404, "This import preview expired. Upload the file again.")
    rows = {r["student_id"]: r for r in prev["rows"]}
    # Fields switched off since the preview are ignored, so nothing is stored for a disabled field.
    enabled = {f["key"] for f in (await get_voter_fields(request))["fields"] if f["enabled"]}
    diff = await _diff_roster(request, rows, enabled)
    now = datetime.utcnow()
    ops: list[UpdateOne] = []

    added = 0
    if data.new_action == "add":
        for r in diff["new"]:
            ops.append(UpdateOne(
                org_query(request, {"student_id": r["student_id"]}),
                {"$set": org_stamp(request, {"full_name": r["full_name"], "phone_numbers": r["phone_numbers"], "updated_at": now,
                                             **attr_set_paths(r.get("attrs"))}),
                 "$setOnInsert": dict(_NEW_VOTER_DEFAULTS)},
                upsert=True))
            added += 1

    updated = skipped_changed = staff_skipped = 0
    is_superadmin = (admin or {}).get("role") == "superadmin"
    for c in diff["changed"]:
        if data.changed_overrides.get(c["student_id"], data.changed_default) != "apply":
            skipped_changed += 1
            continue
        if c["staff"] and not is_superadmin:
            # An IT admin must not be able to repoint a commissioner's/admin's OTP
            # number via bulk import; those changes need a superadmin.
            staff_skipped += 1
            continue
        phones = c["new_phones"]
        if data.phone_mode == "merge":
            phones = c["old_phones"] + [p for p in c["new_phones"] if p not in c["old_phones"]]
        ops.append(UpdateOne(
            org_query(request, {"student_id": c["actual_id"]}),
            {"$set": {"full_name": c["new_name"], "phone_numbers": phones, "updated_at": now,
                      **attr_set_paths({k: o["new"] for k, o in c["attrs_changed"].items()})}}))
        updated += 1

    # Empty -> value for gender/programme/etc. is additive, so it is applied without review.
    attrs_filled = 0
    for fl in diff["attr_fills"]:
        ops.append(UpdateOne(org_query(request, {"student_id": fl["actual_id"]}),
                             {"$set": {**attr_set_paths(fl["attrs"]), "updated_at": now}}))
        attrs_filled += 1

    to_remove, blocked = [], []
    for m in diff["missing"]:
        if data.missing_overrides.get(m["student_id"], data.missing_default) != "remove":
            continue
        if m["protected"]:
            blocked.append({"student_id": m["student_id"], "reasons": m["protected_reasons"]})
        else:
            to_remove.append(m["actual_id"])

    if ops:
        await tdb(request).voters.bulk_write(ops, ordered=False)
    removed = 0
    if to_remove:
        res = await tdb(request).voters.delete_many({"student_id": {"$in": to_remove}, "has_voted": {"$ne": True}})
        removed = res.deleted_count
    await tdb(request).voter_import_previews.delete_one({"preview_id": data.preview_id})

    # The label chosen on the import screen ("Student Number"): only this one branding field is touched.
    new_label = (data.id_label or "").strip()[:60]
    label_saved = ""
    if new_label:
        await tdb(request).settings.update_one(
            {"name": "branding"},
            {"$set": org_stamp(request, {"name": "branding", "id_label": new_label})},
            upsert=True)
        invalidate_settings(org_id, "branding")
        label_saved = new_label
        await log_action("id_label_set_by_import", current_actor(request), {"id_label": new_label}, org_id=org_id)

    summary = {"added": added, "updated": updated, "skipped_changes": skipped_changed, "removed": removed,
               "blocked_removals": len(blocked), "staff_changes_skipped": staff_skipped, "phone_mode": data.phone_mode,
               "attrs_filled": attrs_filled}
    await log_action("voters_import_applied", current_actor(request), summary, org_id=org_id)
    await append_ledger(org_id, "voters_import_applied", "roster", current_actor(request),
                        (admin or {}).get("role", "admin"), summary)
    return {"status": "success", **summary, "blocked": blocked, "id_label": label_saved}


@app.post("/admin/import-voters")
async def import_voters(request: Request, file: UploadFile = File(...), admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Legacy one-shot upsert (add new + refresh name/phone), kept for API compatibility. The
    dashboards use /preview + /apply instead. Existing voters' status/roles are never reset here."""
    await assert_roster_unfrozen(request)
    vf = (await get_voter_fields(request))["fields"]
    parsed = _parse_voter_csv(await _read_csv_upload(file), vf, await _roster_ids(request), file.filename or "")
    now = datetime.utcnow()
    ops = [UpdateOne(
        org_query(request, {"student_id": r["student_id"]}),
        {"$set": org_stamp(request, {"full_name": r["full_name"], "phone_numbers": r["phone_numbers"], "updated_at": now,
                                     **attr_set_paths(r.get("attrs"))}),
         "$setOnInsert": dict(_NEW_VOTER_DEFAULTS)},
        upsert=True) for r in parsed["rows"].values()]
    if ops:
        await tdb(request).voters.bulk_write(ops, ordered=False)
    await log_action("voters_imported", current_actor(request), {
        "count": len(ops), "skipped": parsed["skipped"], "warning_count": len(parsed["warnings"])
    }, org_id=request.state.org_id)
    return {"status": "success", "imported_count": len(ops), "skipped_rows": parsed["skipped"],
            "warnings": parsed["warnings"][:50], "warning_count": len(parsed["warnings"])}


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 50000


async def _read_csv_upload(file: UploadFile) -> bytes:
    content = await file.read(MAX_CSV_BYTES + 1)   # never buffers an unbounded upload
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(400, "File is too large (limit 5MB).")
    return content


@app.post("/admin/upload-image")
async def admin_upload_image(request: Request, file: UploadFile = File(...), admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Signed, server-side Cloudinary upload for candidate photos etc.
    Replaces the old unsigned-preset upload that ran directly from the
    browser. Protected automatically by auth_guard_middleware (any admin
    role) since this path starts with /admin.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP, or GIF images are allowed.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)   # never buffer an unbounded body
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Image must be under 5MB.")
    _assert_real_image(content)

    try:
        result = cloudinary.uploader.upload(content, folder="ballotbox/admin", resource_type="image")
    except Exception as e:
        logger.error(f"Cloudinary admin upload failed: {e}")
        await alert_warning(
            "Cloudinary upload failing (admin)",
            f"{type(e).__name__}: {e}\nOrg: {getattr(request.state, 'org_id', None)}",
        )
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    # Deliberately not logging the URL here. This upload is used for candidate
    # photos and payment-proof evidence, and the resulting link already gets
    # surfaced properly — via ReceiptLink — on the specific application/
    # roster-change record, to only the roles that review it (Commission,
    # Financial Controller, SuperAdmin). The activity log, by contrast, is
    # visible to every admin role via /admin/audit-log with no per-record
    # gating — logging the raw link there would let any role (e.g. Overseer,
    # IT Admin) open someone else's payment proof straight from the log,
    # bypassing that access control. Keep provenance (who, when, how big)
    # without the direct link.
    await log_action("admin_image_uploaded", current_actor(request), {
        "bytes": len(content)
    }, org_id=request.state.org_id)
    return {"secure_url": result["secure_url"]}


@app.get("/admin/voter-fields")
async def admin_get_voter_fields(request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    fields = await get_voter_fields(request)
    return [{"key": f["key"], "label": f["label"]} for f in fields["fields"] if f.get("enabled")]


def _admin_voter_projection(role: str) -> dict:
    projection = {"_id": 0, "full_name": 1, "student_id": 1, "phone_numbers": 1, "attrs": 1}
    if role == "superadmin":
        projection["has_voted"] = 1
        projection["last_status"] = 1
    return projection


@app.get("/admin/voters/list")
async def list_admin_voters(request: Request, q: str = "", page: int = 1, page_size: int = 25,
                            missing_phone: bool = False, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    role = admin.get("role", "")
    page_size = min(max(page_size, 1), 50)
    page = max(page, 1)
    q = q.strip()[:80]
    query = org_query(request)
    clauses = []
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        clauses.append({"$or": [{"student_id": rx}, {"full_name": rx}]})
    if missing_phone:
        clauses.append({"$or": [{"phone_numbers": {"$exists": False}}, {"phone_numbers": {"$size": 0}}]})
    if clauses:
        query["$and"] = clauses
    total = await tdb(request).voters.count_documents(query)
    skip = (page - 1) * page_size
    if skip >= total and total:
        page = max(1, math.ceil(total / page_size))
        skip = (page - 1) * page_size
    fields = await get_voter_fields(request)
    enabled = {f["key"] for f in fields["fields"] if f.get("enabled")}
    results = []
    projection = _admin_voter_projection(role)
    async for v in tdb(request).voters.find(query, projection).sort([("full_name", 1), ("student_id", 1)]).skip(skip).limit(page_size):
        attrs = {k: v.get("attrs", {}).get(k, "") for k in enabled if v.get("attrs", {}).get(k, "") != ""}
        row = {"full_name": v.get("full_name", ""), "student_id": v.get("student_id", ""),
               "phone_numbers": [_mask_phone(p) for p in v.get("phone_numbers", [])], "attrs": attrs}
        if role == "superadmin":
            row["has_voted"] = bool(v.get("has_voted"))
            row["last_status"] = v.get("last_status", "idle")
        results.append(row)
    return {"results": results, "total": total, "page": page, "page_size": page_size}


@app.get("/admin/voters")
async def get_all_voters(request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    # Kept for legacy callers. Never expose stored fields wholesale.
    role = admin.get("role", "")
    projection = _admin_voter_projection(role)
    fields = await get_voter_fields(request)
    enabled = {f["key"] for f in fields["fields"] if f.get("enabled")}
    voters = []
    async for v in tdb(request).voters.find({}, projection):
        row = {"full_name": v.get("full_name", ""), "student_id": v.get("student_id", ""),
               "phone_numbers": [_mask_phone(p) for p in v.get("phone_numbers", [])],
               "attrs": {k: v.get("attrs", {}).get(k, "") for k in enabled if v.get("attrs", {}).get(k, "") != ""}}
        if role == "superadmin":
            row["has_voted"] = bool(v.get("has_voted"))
            row["last_status"] = v.get("last_status", "idle")
        voters.append(row)
    return voters

@app.post("/admin/set-password")
async def set_new_password(data: SetNewPassword, request: Request):
    # Was gated to superadmin only, which made the forced first-login password
    # change impossible for every role that needs it. The endpoint verifies
    # old_password against the stored hash before changing anything, so it is
    # safe as self-service — but an admin may only change their OWN password.
    admin = getattr(request.state, "admin", None) or {}

    def _assert_self(account: dict):
        if admin.get("role") == "superadmin":
            return
        if normalize_student_id(account.get("student_id", "")) != normalize_student_id(admin.get("sub", "")):
            raise HTTPException(403, "You can only change your own password.")

    # Try IT admin first
    it_admin = await tdb(request).voters.find_one({
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    })
    if it_admin:
        _assert_self(it_admin)
        if not await verify_password_async(data.old_password, it_admin.get("it_admin_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await tdb(request).voters.update_one(
            {"_id": it_admin["_id"]},
            {"$set": {
                "it_admin_password_hash":        hash_password(data.new_password),
                "it_admin_must_change_password": False,
                **(await _invalidate_sessions(it_admin["_id"])),
              },
              "$unset": {"it_admin_temp_password_expires": ""}}
        )
        await log_action("it_admin_password_changed", it_admin["student_id"], {}, org_id=request.state.org_id)
        return {"status": "password_updated"}

    # Try Financial Controller
    financial_controller = await tdb(request).voters.find_one({
        "financial_controller_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_financial_controller": True
    })
    if financial_controller:
        _assert_self(financial_controller)
        if not await verify_password_async(data.old_password, financial_controller.get("financial_controller_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await tdb(request).voters.update_one(
            {"_id": financial_controller["_id"]},
            {"$set": {
                "financial_controller_password_hash":        hash_password(data.new_password),
                "financial_controller_must_change_password": False,
                **(await _invalidate_sessions(financial_controller["_id"])),
              },
              "$unset": {"financial_controller_temp_password_expires": ""}}
        )
        await log_action("financial_controller_password_changed", financial_controller["student_id"], {}, org_id=request.state.org_id)
        return {"status": "password_updated"}

    # Try Overseer
    overseer = await tdb(request).voters.find_one({
        "overseer_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_overseer": True
    })
    if overseer:
        _assert_self(overseer)
        if not await verify_password_async(data.old_password, overseer.get("overseer_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await tdb(request).voters.update_one(
            {"_id": overseer["_id"]},
            {"$set": {
                "overseer_password_hash":        hash_password(data.new_password),
                "overseer_must_change_password": False,
                **(await _invalidate_sessions(overseer["_id"])),
              },
              "$unset": {"overseer_temp_password_expires": ""}}
        )
        await log_action("overseer_password_changed", overseer["student_id"], {}, org_id=request.state.org_id)
        return {"status": "password_updated"}

    # Try Vetting Panel member (panel_members; no voter row for externals)
    panelist = await tdb(request).panel_members.find_one({
        "email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "active": True,
    })
    if panelist:
        # Same self-only rule as _assert_self, keyed by panel_member_id (no student_id here).
        if admin.get("role") != "superadmin" and panelist["panel_member_id"] != admin.get("sub"):
            raise HTTPException(403, "You can only change your own password.")
        if not await verify_password_async(data.old_password, panelist.get("password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await tdb(request).panel_members.update_one(
            {"_id": panelist["_id"]},
            {"$set": {
                "password_hash": hash_password(data.new_password),
                "must_change_password": False,
                **(await _invalidate_sessions(panelist["_id"])),
            },
             "$unset": {"temp_password_expires": ""}}
        )
        await log_action("vetting_panel_password_changed", panelist["panel_member_id"],
                         {"is_member": panelist.get("is_member", False)}, org_id=request.state.org_id)
        return {"status": "password_updated"}

    # Try commissioner
    commissioner = await tdb(request).voters.find_one({
        "commissioner_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_commissioner": True
    })
    if commissioner:
        _assert_self(commissioner)
        if not await verify_password_async(data.old_password, commissioner.get("commissioner_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await tdb(request).voters.update_one(
            {"_id": commissioner["_id"]},
            {"$set": {
                "commissioner_password_hash":        hash_password(data.new_password),
                "commissioner_must_change_password": False,
                **(await _invalidate_sessions(commissioner["_id"])),
              },
              "$unset": {"commissioner_temp_password_expires": ""}}
        )
        await log_action("commissioner_password_changed", commissioner["student_id"], {}, org_id=request.state.org_id)
        return {"status": "password_updated"}

    raise HTTPException(404, "Account not found.")

# --- Candidates (superadmin can add/edit/delete freely; commission does not touch these) ---

@app.post("/candidates")
async def add_candidate(candidate: CandidateCreate, request: Request, admin: dict = Depends(require_role("superadmin"))):
    candidate.name = normalize_name(candidate.name)
    result = await tdb(request).candidates.insert_one(candidate.dict())
    await log_action("candidate_added", current_actor(request), {
        "name": candidate.name, "position": candidate.position
    }, org_id=request.state.org_id)
    return {"id": str(result.inserted_id)}


@app.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, data: dict, request: Request, admin: dict = Depends(require_role("superadmin"))):
    oid = parse_oid(candidate_id, "candidate id")
    upd = {
        "name":     normalize_name(data["name"]) if isinstance(data.get("name"), str) else data.get("name"),
        "position": data.get("position"),
        "order":    int(data.get("order", 0))
    }
    if data.get("image_url"):
        upd["image_url"] = data["image_url"]
    await tdb(request).candidates.update_one({"_id": oid}, {"$set": upd})
    await log_action("candidate_updated", current_actor(request), {
        "candidate_id": candidate_id, "name": upd.get("name"), "position": upd.get("position")
    }, org_id=request.state.org_id)
    return {"status": "success"}


@app.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, request: Request, admin: dict = Depends(require_role("superadmin"))):
    oid = parse_oid(candidate_id, "candidate id")
    doomed = await tdb(request).candidates.find_one({"_id": oid})
    await tdb(request).candidates.delete_one({"_id": oid})
    await log_action("candidate_deleted", current_actor(request), {
        "candidate_id": candidate_id,
        "name": (doomed or {}).get("name", ""),
        "position": (doomed or {}).get("position", ""),
    }, org_id=request.state.org_id)
    return {"status": "deleted"}


# --- Applications list (shared: both superadmin and commission can read) ---

@app.get("/admin/applications")
async def list_applications(request: Request, status: str = None):
    role = current_role(request)
    org_id = require_org(request.state.org_id)
    query = org_query(request)
    if status:
        query["status"] = status
    if role == "commission":
        # Commissioners not on the panel see the outcome, never pending applications (guide 5.2).
        if status and status not in RESOLVED_STATUSES:
            return []
        if not status:
            query["status"] = {"$in": list(RESOLVED_STATUSES)}
    actor_key, is_chair = await _panel_actor_context(request)
    active_keys = await _active_panel_keys(org_id)
    panel_count = await get_panel_count(org_id)
    apps = []
    async for a in tdb(request).applications.find(query).sort("submitted_at", -1):
        a["_id"] = str(a["_id"])
        a["edit_history"] = _application_edit_history(a)   # one shape for old and new corrections
        a.pop("reg_no_history", None)
        if a.get("position_id"):
            title, order = await _resolve_position_title(a["position_id"], org_id)
            a["position_title"] = title
            a["position_order"] = order
        else:
            a["position_order"] = 0
        apps.append(shape_application_for_role(
            a, role, actor_key=actor_key, active_keys=active_keys,
            panel_count=panel_count, is_chair_panelist=is_chair))
    apps.sort(key=lambda x: (x.get("position_order", 0), -x["submitted_at"].timestamp() if x.get("submitted_at") else 0))
    return apps

@app.get("/admin/applications/{app_id}/nomination-form")
async def get_application_nomination_form(
        app_id: str, request: Request,
        admin: dict = Depends(require_role("vetting", "superadmin", "overseer", "commission"))):
    """N3: a short-lived signed link to the applicant's signed nomination form. The panel needs it to vet;
    commissioners only once the application is resolved (same rule as list_applications). Every issued link is
    audited, because panelists are told their views are confidential. Nothing here returns a storage key."""
    role = current_role(request)
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if role == "commission" and app_doc.get("status", "pending") not in RESOLVED_STATUSES:
        raise HTTPException(403, "Not authorized for this action.")
    nf = app_doc.get("nomination_form")
    if not isinstance(nf, dict) or not nf.get("upload_id"):
        raise HTTPException(404, "No nomination form was submitted with this application.")
    rec = await tdb(request).nomination_uploads.find_one({"upload_id": nf["upload_id"], "status": "attached"})
    if not rec:
        raise HTTPException(404, "The nomination form file could not be found.")
    if not nomination_storage.is_configured():
        await alert_critical("Nomination form storage not configured",
                             f"Staff read-back failed. Missing: {', '.join(nomination_storage.missing_settings())}\n"
                             f"Org: {request.state.org_id}")
        raise HTTPException(503, "Form viewing is temporarily unavailable. Please try again later.")
    try:
        url = await run_in_threadpool(nomination_storage.presigned_get_url, rec["key"], rec.get("filename", ""))
    except Exception as e:
        logger.error(f"Nomination form link failed: {type(e).__name__}: {e}")
        await alert_critical("Nomination form storage failing", f"{type(e).__name__}: {e}\nOrg: {request.state.org_id}")
        raise HTTPException(502, "Could not open the form. Please try again.")
    viewer = (getattr(request.state, "admin", None) or {})
    await log_action("nomination_form_viewed", current_actor(request), {
        "application_id": app_id, "role": role,
        **({"viewed_by_superadmin": viewer.get("viewer")} if viewer.get("view_only") else {}),
    }, org_id=request.state.org_id)
    return JSONResponse(
        content={"url": url, "filename": rec.get("filename", "nomination-form"), "kind": rec.get("kind"),
                 "bytes": rec.get("bytes"), "expires_in": nomination_storage.PRESIGN_SECONDS},
        headers={"Cache-Control": "no-store"})


# =============================================================================
# COMMISSION ROUTES  (voting — requires commission login)
# =============================================================================

@app.get("/admin/vetting-me")
async def vetting_me(request: Request, admin: dict = Depends(require_role("vetting"))):
    """The signed-in panelist's own status: access end and the confidentiality gate (guide 6.4)."""
    p = await tdb(request).panel_members.find_one({"panel_member_id": admin.get("sub"), "active": True})
    if not p:
        raise HTTPException(403, "You are not an active member of the Vetting Panel.")
    end = await _panel_access_end(request, p)
    return {
        "panel_member_id": p["panel_member_id"],
        "full_name": p.get("full_name", ""),
        "is_member": bool(p.get("is_member")),
        "affiliation": p.get("affiliation", ""),
        "access_ends_at": iso_utc(end),
        "confidentiality_required": not p.get("is_member") and not admin.get("view_only"),
        "confidentiality_accepted": p.get("confidentiality_version") == CONFIDENTIALITY_VERSION,
        "confidentiality_notice": CONFIDENTIALITY_NOTICE,
    }


@app.post("/admin/vetting-confidentiality/accept")
async def accept_confidentiality(request: Request, admin: dict = Depends(require_role("vetting"))):
    p = await tdb(request).panel_members.find_one({"panel_member_id": admin.get("sub"), "active": True})
    if not p:
        raise HTTPException(403, "You are not an active member of the Vetting Panel.")
    await tdb(request).panel_members.update_one({"_id": p["_id"]}, {"$set": {
        "confidentiality_accepted_at": datetime.utcnow(),
        "confidentiality_version": CONFIDENTIALITY_VERSION}})
    await log_action("vetting_confidentiality_accepted", p["panel_member_id"],
                     {"version": CONFIDENTIALITY_VERSION}, org_id=request.state.org_id)
    return {"status": "accepted", "confidentiality_version": CONFIDENTIALITY_VERSION}


@app.get("/admin/vetting-outcomes")
async def vetting_outcomes(request: Request, admin: dict = Depends(require_role("commission"))):
    """Guide 5.2 / 8.1: what a commissioner may see of the Vetting Panel's work. Final decisions
    and the final stated reason only. Never pending applications, votes, tallies or the split."""
    def iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    rows = []
    async for a in tdb(request).applications.find({"status": {"$in": list(RESOLVED_STATUSES)}}).sort("submitted_at", -1):
        title = ""
        if a.get("position_id"):
            title, _ = await _resolve_position_title(a["position_id"], request.state.org_id)
        rows.append({
            "id": str(a["_id"]),
            "full_name": a.get("full_name", ""),
            "student_id": a.get("student_id", ""),
            "position_title": title,
            "status": a.get("status"),
            "decided_at": iso(a.get("decided_at")),
            "final_reason": a.get("final_reason"),
            "superadmin_override": bool(a.get("superadmin_override")),
        })
    return rows


@app.post("/admin/applications/{app_id}/vote")
async def commissioner_vote(app_id: str, data: CommissionerVote, request: Request,
                            admin: dict = Depends(require_role("vetting"))):
    """A Vetting Panel member casts an approve/deny vote on a pending application (guide 8.1).
    Commissioners cannot vote unless they sit on the panel, and then only through the panel hat."""
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "Vote must be 'approve' or 'deny'.")

    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in RESOLVED_STATUSES:
        raise HTTPException(400, "This application is already resolved.")
    if not app_doc.get("finance_cleared"):
        raise HTTPException(400, "Awaiting Financial Controller clearance before voting can open.")
    await assert_phase_open(request, "vetting")

    panelist = await _acting_panelist(request, admin)
    if panelist.get("student_id") and app_doc.get("student_id") and \
            normalize_student_id(panelist["student_id"]) == normalize_student_id(app_doc["student_id"]):
        raise HTTPException(403, "You cannot vote on your own application.")
    key = _panel_vote_key(panelist)
    claimed = (data.commissioner_id or "").strip()
    allowed = {_vote_key(x) for x in (panelist.get("student_id"), panelist["panel_member_id"]) if x}
    if claimed and _vote_key(claimed) not in allowed:
        raise HTTPException(403, "The vote does not match your panel account.")
    # The panel screen promises "your vote is final and cannot be changed"; enforce it here too. Otherwise a
    # panelist could flip a vote by calling the API after a tie was flagged and sidestep the Chairperson.
    if key in _dedupe_votes(app_doc.get("votes")):
        raise HTTPException(409, "You have already voted on this application. Votes are final.")

    is_also_commissioner = False
    if panelist.get("student_id"):
        is_also_commissioner = bool(await tdb(request).voters.find_one({
            **get_forgiving_filter(panelist["student_id"]), "is_commissioner": True}))

    # Atomic: only record the vote while the application is still open and this panelist has not voted. A
    # concurrent resolution or a double submit changes nothing and is reported, instead of writing a vote
    # onto a resolved application. The audit row is written only once the vote is actually stored.
    written = await tdb(request).applications.update_one(
        {"_id": oid, "status": {"$nin": list(RESOLVED_STATUSES)},
                            f"votes.{key}": {"$exists": False}},
        {"$set": {f"votes.{key}": data.vote}}
    )
    if written.matched_count == 0:
        raise HTTPException(409, "This application was just resolved or you have already voted. Please refresh.")
    await log_action("application_vote_cast", panelist["panel_member_id"], {
        "app_id": app_id, "vote": data.vote, "reason": data.reason,
        "is_member": bool(panelist.get("is_member")), "also_commissioner": is_also_commissioner,
    }, org_id=request.state.org_id)
    updated = await tdb(request).applications.find_one({"_id": oid})
    await _resolve_application(app_id, updated, request.state.org_id)

    final = await tdb(request).applications.find_one({"_id": oid})
    shaped = shape_application_for_role(
        final, "vetting", actor_key=key, active_keys=await _active_panel_keys(request.state.org_id),
        panel_count=await get_panel_count(request.state.org_id))
    return {"status": "vote_recorded", "my_vote": data.vote, "progress": shaped["progress"]}


@app.post("/admin/applications/{app_id}/tie-break")
async def panel_tie_break(app_id: str, data: TieBreakDecision, request: Request,
                          admin: dict = Depends(require_role("vetting"))):
    """Guide 7.2: the Chair, acting in the panel hat and only as an active panelist, breaks a tie.
    The casting decision is not written into votes, so each member keeps exactly one vote."""
    if data.decision not in ("approve", "deny"):
        raise HTTPException(400, "Decision must be 'approve' or 'deny'.")
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")

    panelist = await _acting_panelist(request, admin)
    chair = None
    if panelist.get("student_id"):
        chair = await tdb(request).voters.find_one({
            **get_forgiving_filter(panelist["student_id"]), "is_chief_commissioner": True})
    if not chair:
        raise HTTPException(403, "Only the Chairperson can break a tie.")
    if panelist.get("student_id") and normalize_student_id(panelist["student_id"]) == normalize_student_id(app_doc.get("student_id") or ""):
        raise HTTPException(403, "The Chairperson cannot break a tie on their own application.")

    org_id = require_org(request.state.org_id)
    await assert_phase_open(request, "vetting")
    if app_doc.get("status") in RESOLVED_STATUSES or not app_doc.get("finance_cleared"):
        raise HTTPException(409, "This application is not waiting for a tie-break.")
    policy = (await security_settings_for(org_id))["approval_policy"]
    active = await _active_panel_keys(org_id)
    panel_total = await get_panel_count(org_id)
    votes = {k: v for k, v in _dedupe_votes(app_doc.get("votes", {})).items() if k in active}
    approve_count = sum(1 for v in votes.values() if v == "approve")
    deny_count = sum(1 for v in votes.values() if v == "deny")
    if not (app_doc.get("tied_pending_chief") and _is_tied(policy, panel_total, approve_count, deny_count)):
        raise HTTPException(409, "This application is not waiting for a tie-break.")

    extra = {
        "tie_break": {"by": chair["student_id"], "decision": data.decision, "at": datetime.utcnow()},
        "decided_by_tie_break": True,
    }
    reason = (data.reason or "").strip()
    if data.decision == "deny" and reason:
        extra["final_reason"] = reason
    applied = await _apply_application_outcome(
        app_id, app_doc, org_id, data.decision, actor=admin.get("sub", "unknown"),
        details={"tie_break": True, "approve_count": approve_count, "deny_count": deny_count,
                 "panel_count": panel_total, "policy": policy},
        extra_set=extra)
    if not applied:
        raise HTTPException(409, "This application was just resolved by someone else. Please refresh.")
    await log_action("application_tie_broken", admin.get("sub", "unknown"),
                     {"app_id": app_id, "decision": data.decision}, org_id=org_id)
    return {"status": "tie_broken", "decision": data.decision}


@app.post("/superadmin/applications/{app_id}/final-reason")
async def superadmin_set_final_reason(app_id: str, data: FinalReasonUpdate, request: Request,
                                      admin: dict = Depends(require_role("superadmin"))):
    """Guide 13.2 (H2): an optional reason on a denied or removed application. Shown to commissioners
    in the outcome feed; per-panelist comments are never shown."""
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") not in ("denied", "removed"):
        raise HTTPException(409, "A final reason applies to denied or removed applications.")
    reason = (data.reason or "").strip() or None
    await tdb(request).applications.update_one({"_id": oid}, {"$set": {"final_reason": reason}})
    await log_action("application_final_reason_set", current_actor(request), {"app_id": app_id},
                     org_id=request.state.org_id)
    return {"status": "saved", "final_reason": reason}


@app.post("/admin/applications/{app_id}/vote-remove")
async def commissioner_vote_remove(app_id: str, data: CommissionerVote, request: Request):
    """A commissioner votes to remove an already-approved candidate.

    ON HOLD: deliberately not wired into any frontend (no button in CommissionDashboard
    calls this route). It was pulled from the UI earlier because it confused commissioners,
    and we're still deciding whether it's worth bringing back before re-exposing it. Leave
    this endpoint as-is until that's settled — don't add UI for it without checking first.
    """
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "Vote must be 'approve' (remove) or 'deny' (keep).")

    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") != "approved":
        raise HTTPException(400, "Can only vote to remove an approved candidate.")

    bind_identity(request, data.commissioner_id, "commissioner account")

    commissioner = await tdb(request).voters.find_one({
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    })
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    await log_action("candidate_removal_vote", current_actor(request), {
        "app_id": app_id, "vote": data.vote
    }, org_id=request.state.org_id)

    safe_key = _vote_key(data.commissioner_id)
    await tdb(request).applications.update_one(
        {"_id": oid},
        {"$set": {f"removal_votes.{safe_key}": data.vote}}
    )

    updated = await tdb(request).applications.find_one({"_id": oid})
    await _resolve_removal(app_id, updated, request.state.org_id)

    return {"status": "removal_vote_recorded"}


async def _finance_clear_application_core(app_id: str, data: FinanceClear, request: Request, fc: dict) -> dict:
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared.")

    fc_id = fc["student_id"]
    note = data.reason.strip()
    result = await tdb(request).applications.update_one(
        {
            "_id": oid,
            "finance_cleared": {"$ne": True},
            "status": {"$nin": ["approved", "denied", "removed"]},
        },
        {"$set": {
            "finance_cleared": True,
            "finance_cleared_by": fc_id,
            "finance_cleared_at": datetime.utcnow(),
            **({"finance_clear_note": note} if note else {}),
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(400, "This application was already resolved or finance-cleared by someone else.")
    await log_action("application_finance_cleared", fc_id,
                     {"app_id": app_id, **_payment_audit(app_doc, fc), **({"reason": note} if note else {})},
                     org_id=request.state.org_id)

    schedule = await get_phase_schedule(request)
    vetting_start = schedule["phases"]["vetting"]["start"]
    when = None
    if vetting_start:
        tz_name = schedule.get("timezone") or DEFAULT_ELECTION_TZ
        try:
            z = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            z = ZoneInfo("UTC")
        local = vetting_start.replace(tzinfo=timezone.utc).astimezone(z)
        when = f"{local.day} {local:%b %Y}"
    await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
        f"{org}: Your payment has been confirmed. You are invited for nomination/vetting for {pos}"
        + (f" on {when}." if when else " — the date will be communicated once the timeline is set.")))
    logger.info(f"Application {app_id} finance-cleared by {fc_id}.")
    return {"status": "finance_cleared"}


@app.post("/admin/applications/{app_id}/finance-clear")
async def finance_clear_application(app_id: str, data: FinanceClear, request: Request):
    """The Financial Controller verifies payment; the demo uses this same core business path."""
    fc = await require_payment_controller(request, data.financial_controller_id, "clear")
    return await _finance_clear_application_core(app_id, data, request, fc)


@app.post("/admin/applications/{app_id}/finance-reject")
async def finance_reject_application(app_id: str, data: FinanceReject, request: Request):
    """
    The Financial Controller rejects the candidate's payment/receipt with a
    required reason. This resolves the application as denied, mirroring the
    commission's deny flow but for the finance gate specifically.
    """
    if not data.reason.strip():
        raise HTTPException(400, "A reason is required to reject an application.")

    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared and can no longer be finance-rejected.")

    fc = await require_payment_controller(request, data.financial_controller_id, "reject")
    fc_id = fc["student_id"]

    # Same atomic-guard pattern as finance_clear_application: fold the
    # "not already cleared / not already resolved" check into the update
    # filter itself so a double-click or race can't double-write.
    result = await tdb(request).applications.update_one(
        {
            "_id": oid,
            "finance_cleared": {"$ne": True},
            "status": {"$nin": ["approved", "denied", "removed"]},
        },
        {"$set": {
            "status": "denied",
            "finance_rejected": True,
            "finance_rejected_by": fc_id,
            "finance_rejected_at": datetime.utcnow(),
            "finance_rejection_reason": data.reason.strip(),
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(400, "This application was already resolved or cleared by someone else.")

    # Finance rejection is a separate code path from a commissioner-vote
    # denial, so it records the denial snapshot itself — otherwise the
    # candidate's status page would have no decision notice for it.
    # The reason is stored on the snapshot so the candidate's status page shows it
    # ("denied by the Financial Controller, contact Finance if this is an error").
    await _record_denial_snapshot(app_doc, request.state.org_id, finance_reason=data.reason.strip())

    await log_action("application_finance_rejected", fc_id,
                      {"app_id": app_id, "reason": data.reason.strip(), **_payment_audit(app_doc, fc)},
                      org_id=request.state.org_id)
    fee = app_doc.get("fee_required") or 0
    reason = data.reason.strip()[:80]
    await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
        f"{org}: Your nomination for {pos} was rejected because of your payment: {reason}."
        + (f" The required amount is {fmt_ugx(fee)}; incomplete payments are not accepted." if fee else "")
        + " If you think this is a mistake, contact the Finance office."))
    logger.info(f"Application {app_id} finance-rejected by {fc_id}.")
    return {"status": "denied"}


@app.post("/admin/applications/{app_id}/finance-reverse")
async def finance_reverse_clearance(app_id: str, data: FinanceReverse, request: Request):
    """
    The Financial Controller takes back a clearance they gave in error (short payment, forged receipt).
    The application returns to "awaiting clearance": the Vetting Panel can no longer vote on it.

    Only possible while the application is still pending. Once the panel has approved or denied it, the
    decision is no longer Finance's to undo (the superadmin can revert an override; see revert-to-pending).
    Any votes already cast are set aside, since they were cast on a payment that is no longer valid; they
    are kept in revert_history (superadmin-only) and the panel votes again after re-clearance.
    """
    reason = _clean_reason(data.reason)
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in RESOLVED_STATUSES:
        raise HTTPException(409, "The Vetting Panel has already decided this application, so Finance can no "
                                 "longer reverse the clearance. Ask the superadmin.")
    if not app_doc.get("finance_cleared"):
        raise HTTPException(400, "This payment is not currently cleared.")

    fc = await require_payment_controller(request, data.financial_controller_id, "reverse")
    fc_id = fc["student_id"]
    now = datetime.utcnow()
    prior_votes = dict(app_doc.get("votes") or {})

    result = await tdb(request).applications.update_one(
        {"_id": oid, "finance_cleared": True,
                            "status": {"$nin": list(RESOLVED_STATUSES)}},
        {"$set": {"finance_cleared": False, "votes": {}},
         "$unset": {"finance_cleared_by": "", "finance_cleared_at": "", "finance_clear_note": "",
                    "tied_pending_chief": ""},
         "$push": {
             "finance_history": {"at": now, "by": fc_id, "action": "clearance_reversed", "reason": reason},
             **({"revert_history": {"at": now, "by": fc_id, "from_status": "pending",
                                    "reason": f"Finance reversed payment clearance: {reason}",
                                    "prior_votes": prior_votes}} if prior_votes else {}),
         }}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just changed by someone else. Please refresh.")

    await log_action("application_finance_reversed", fc_id,
                     {"app_id": app_id, "reason": reason, "votes_set_aside": len(prior_votes),
                      **_payment_audit(app_doc, fc)},
                     org_id=request.state.org_id)
    await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
        f"{org}: The payment confirmation for your {pos} nomination has been withdrawn while Finance "
        f"reviews it. Please contact the Finance office."))
    logger.info(f"Application {app_id} finance clearance reversed by {fc_id}.")
    return {"status": "pending", "votes_set_aside": len(prior_votes)}


@app.post("/admin/applications/{app_id}/finance-reinstate")
async def finance_reinstate_application(app_id: str, data: FinanceReinstate, request: Request):
    """
    Move an application the Financial Controller rejected back into play once the candidate has sorted
    things out with Finance. target="pending" returns it to the awaiting-clearance queue; target="cleared"
    confirms the payment in the same step so the Vetting Panel can vote.

    Only a finance rejection can be reinstated here. A commission denial or a superadmin override cannot.
    """
    if data.target not in ("pending", "cleared"):
        raise HTTPException(400, "Target must be 'pending' or 'cleared'.")
    reason = _clean_reason(data.reason)
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") != "denied" or not app_doc.get("finance_rejected"):
        raise HTTPException(400, "Only an application rejected by Finance can be reinstated here.")
    if app_doc.get("superadmin_override"):
        raise HTTPException(400, "This denial was a superadmin override, so Finance can't reinstate it.")

    fc = await require_payment_controller(request, data.financial_controller_id, "reinstate")
    fc_id = fc["student_id"]
    now = datetime.utcnow()
    cleared = data.target == "cleared"

    set_fields = {"status": "pending", "finance_rejected": False, "denial_snapshot": None,
                  "finance_cleared": cleared}
    if cleared:
        set_fields.update({"finance_cleared_by": fc_id, "finance_cleared_at": now, "finance_clear_note": reason})
    result = await tdb(request).applications.update_one(
        {"_id": oid, "status": "denied", "finance_rejected": True,
                            "superadmin_override": {"$ne": True}},
        {"$set": set_fields,
         "$unset": {"finance_rejected_by": "", "finance_rejected_at": "", "finance_rejection_reason": "",
                    "decided_at": ""},
         "$push": {"finance_history": {
             "at": now, "by": fc_id, "action": f"reinstated_to_{data.target}", "reason": reason,
             "previous_rejection_reason": app_doc.get("finance_rejection_reason", "")}}}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just changed by someone else. Please refresh.")

    await log_action("application_finance_reinstated", fc_id,
                     {"app_id": app_id, "target": data.target, "reason": reason,
                      "previous_rejection_reason": app_doc.get("finance_rejection_reason", ""),
                      **_payment_audit(app_doc, fc)},
                     org_id=request.state.org_id)
    if cleared:
        await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
            f"{org}: Your payment issue is resolved and your nomination for {pos} is back under review."))
    else:
        await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
            f"{org}: Your nomination for {pos} has been reopened and is awaiting payment confirmation "
            f"from Finance."))
    logger.info(f"Application {app_id} reinstated to {data.target} by {fc_id}.")
    return {"status": "pending", "finance_cleared": cleared}


@app.get("/admin/commissioners")
async def list_commissioners_for_admins(request: Request):
    """
    Commission roster, readable by any admin role.

    CommissionDashboard has always called this path; only the superadmin-only
    /superadmin/commissioners existed, so the call 403'd, was swallowed by
    .catch(), and the dashboard could never tell who the Chief Commissioner
    was. Deliberately narrower than the superadmin version: no email
    addresses, since the roster is being widened to every admin role.
    """
    result = []
    async for v in tdb(request).voters.find(
        {"is_commissioner": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1,
         "is_deputy_chief_commissioner": 1, "commissioner_role": 1},
    ):
        result.append(v)
    return result


@app.get("/commission/results/detailed")
async def get_commission_detailed_results(request: Request):
    """
    Detailed, per-position results view for the Commission portal so
    commissioners can monitor and announce standings themselves. Built from
    an aggregation over `vote_events` — no voter identity is ever stored in
    that collection, so this view carries no anonymity risk; it's the same
    anonymous data /election-results already exposes publicly, just grouped
    and enriched for commission use.
    """
    total_voters = await tdb(request).voters.count_documents({})
    voted_count = await tdb(request).voters.count_documents({"has_voted": True})
    vote_counts = await get_vote_counts(request)
    positions_by_id = {}
    async for pos in tdb(request).positions.find({}).sort("order", 1):
        positions_by_id[str(pos["_id"])] = pos
    grouped: dict = {}
    async for cand in tdb(request).candidates.find({}).sort("order", 1):
        position_title = cand.get("position", "Unknown Position")
        grouped.setdefault(position_title, []).append(cand)

    detailed = []
    for position_title, candidates in grouped.items():
        position_total_votes = sum(vote_counts.get(str(c["_id"]), 0) for c in candidates)
        candidate_rows = []
        for c in sorted(candidates, key=lambda x: vote_counts.get(str(x["_id"]), 0), reverse=True):
            votes = vote_counts.get(str(c["_id"]), 0)
            candidate_rows.append({
                "id": str(c["_id"]),
                "name": c["name"],
                "votes": votes,
                "pct_of_position": round((votes / position_total_votes) * 100, 1) if position_total_votes else 0,
                "unopposed": len(candidates) == 1
            })
        detailed.append({
            "position": position_title,
            "total_votes": position_total_votes,
            "candidates": candidate_rows
        })

    return {
        "voter_turnout": {
            "total_voters": total_voters,
            "voted_count":  voted_count,
            "turnout_pct":  round((voted_count / total_voters) * 100, 1) if total_voters else 0
        },
        "positions": detailed,
        "generated_at": datetime.utcnow()
    }


# =============================================================================
# SUPERADMIN — MFA BOOTSTRAP
# =============================================================================

@app.get("/superadmin/mfa/generate")
async def generate_superadmin_mfa_secret(request: Request):
    """One-time bootstrap: call this once while logged in as superadmin
    (works pre-MFA — plain email+password gets you in to run this).

    To use MFA from BOTH your phone and your laptop: call this endpoint
    ONCE, then enroll that SAME secret into an authenticator app on each
    device (scan provisioning_uri as a QR code on your phone; on Linux,
    paste the raw `secret` into KeePassXC's TOTP field, the GNOME
    "Authenticator" app, or run `oathtool --totp -b <secret>` from a
    terminal). One secret, multiple apps — they'll all produce the same
    code at the same moment since it's derived from the secret + the
    current time, not tied to any one device.

    Refuses to run again once SUPERADMIN_TOTP_SECRET is already set —
    generating a second secret would silently invalidate every device
    you've already enrolled the moment it's deployed, locking you out
    until you reset the env var by hand on Render. To rotate the secret
    on purpose, unset SUPERADMIN_TOTP_SECRET, redeploy, call this again,
    re-enroll every device, THEN set the new secret and redeploy again —
    never skip straight to a new secret while the old one is still live.

    Copy the returned secret into SUPERADMIN_TOTP_SECRET in Render's env
    vars and redeploy. MFA becomes mandatory on the NEXT login after that —
    this endpoint alone doesn't turn it on.
    """
    if SUPERADMIN_TOTP_SECRET:
        raise HTTPException(
            status_code=409,
            detail=(
                "MFA is already configured. Generating a new secret now would invalidate "
                "every device already enrolled and could lock you out. To rotate it: unset "
                "SUPERADMIN_TOTP_SECRET, redeploy, call this endpoint again, re-enroll every "
                "device with the new secret, THEN set it and redeploy."
            )
        )
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=SUPER_ADMIN_ID, issuer_name="BallotBox Superadmin")
    # The secret itself is deliberately NOT logged — only the fact that a
    # bootstrap happened, and when.
    await log_action("superadmin_mfa_secret_generated", current_actor(request), {}, org_id=request.state.org_id)
    return {"secret": secret, "provisioning_uri": uri}


# =============================================================================
# SUPERADMIN — ORGANIZATION MANAGEMENT (multi-tenancy)
# =============================================================================
# One platform-wide Superadmin (George) provisions orgs here. The returned
# `slug` is what gets set as VITE_ORG_SLUG in that org's frontend deployment.

@app.post("/superadmin/orgs")
async def create_organization(data: OrganizationCreate, request: Request):
    slug = data.slug.strip().lower() if data.slug.strip() else await generate_unique_org_slug(data.name)
    if data.slug.strip():
        existing = await db.organizations.find_one({"slug": slug})
        if existing:
            raise HTTPException(400, f"Slug '{slug}' is already taken.")

    org_doc = {
        "name":              data.name,
        "slug":              slug,
        "frontend_url":      normalize_frontend_url(data.frontend_url),
        "created_at":        datetime.utcnow(),
        "branding_defaults": {
            "org_name": data.name
        }
    }
    result = await db.organizations.insert_one(org_doc)
    _invalidate_org_cache(slug)
    await log_action("organization_created", current_actor(request), {
        "org_id": str(result.inserted_id), "name": data.name, "slug": slug
    })
    logger.info(f"Organization '{data.name}' provisioned with slug '{slug}'.")
    return {
        "org_id": str(result.inserted_id),
        "name":   data.name,
        "slug":   slug,
        "frontend_url": org_doc["frontend_url"],
    }


@app.put("/superadmin/orgs/{slug}/frontend-url")
async def set_organization_frontend_url(slug: str, data: OrganizationFrontendUrl, request: Request):
    """Sets (or clears, with a blank value) the site address used in links this org's SMS messages carry."""
    url = normalize_frontend_url(data.frontend_url)
    res = await db.organizations.update_one({"slug": slug.strip().lower()}, {"$set": {"frontend_url": url}})
    if not res.matched_count:
        raise HTTPException(404, "Organisation not found.")
    _invalidate_org_cache(slug.strip().lower())
    await log_action("organization_frontend_url_set", current_actor(request),
                     {"slug": slug, "frontend_url": url})
    return {"slug": slug, "frontend_url": url}


@app.get("/superadmin/orgs")
async def list_organizations():
    orgs = []
    async for o in db.organizations.find({}).sort("created_at", -1):
        o["_id"] = str(o["_id"])
        orgs.append(o)
    return orgs


# =============================================================================
# LEGACY (NO-TENANT) DATA CHECK  — superadmin only
# =============================================================================
# The app no longer creates or reads documents without an org_id. This finds any that still exist (from
# before multi-tenancy) so the superadmin can assign them to the right organization or remove them.
# It is the only code that deliberately queries for a missing org, and it never exposes their contents.
# {"org_id": None} matches both a null and a missing field.
LEGACY_TENANT_COLLECTIONS = [
    "voters", "applications", "candidates", "positions", "settings", "student_changes", "contact_changes",
    "exception_grants", "student_edit_audit", "audit_log", "candidate_tokens", "certificates",
    "panel_members", "otps", "admin_otps", "nomination_uploads",
    # Hash-chained / anchored with the org id: removable, but NEVER re-assigned (that would break verification).
    "vote_events", "audit_checkpoints", "roster_ledger",
]
LEGACY_NO_ASSIGN = {"vote_events", "audit_checkpoints", "roster_ledger"}
LEGACY_DELETE_CONFIRM = "DELETE LEGACY DATA"


def _legacy_targets() -> dict:
    """name -> (filter, assignable). The 'default' keys are what the old org-less code wrote for SMS counters
    and OTP limiter state."""
    t = {n: ({"org_id": None}, n not in LEGACY_NO_ASSIGN) for n in LEGACY_TENANT_COLLECTIONS}
    t["audit_log"] = ({"org_id": None, "scope": {"$ne": "system"}}, True)   # system events are not legacy
    t["sms_usage"] = ({"org_key": "default"}, True)
    t["otp_send_state"] = ({"key": {"$regex": "^default:otp:"}}, False)    # expires on its own (48 h)
    t["otp_guess_state"] = ({"key": {"$regex": "^default:otp:"}}, False)   # expires on its own (7 d)
    return t


async def _legacy_counts() -> list[dict]:
    out = []
    for name, (flt, assignable) in _legacy_targets().items():
        n = await cross_tenant(db)[name].count_documents(flt)      # deliberately cross-tenant: finds ownerless rows
        out.append({"name": name, "count": n, "assignable": assignable})
    return out


class LegacyAssign(BaseModel):
    org_id: str
    collections: list[str] = Field(default_factory=list)


class LegacyDelete(BaseModel):
    collections: list[str] = Field(default_factory=list)
    confirm: str = ""


def _legacy_pick(requested: list[str], counts: list[dict], *, assigning: bool) -> list[str]:
    by_name = {c["name"]: c for c in counts}
    unknown = [n for n in requested if n not in by_name]
    if unknown:
        raise HTTPException(400, f"Unknown collection(s): {', '.join(unknown)}")
    picked = [n for n in requested if by_name[n]["count"] > 0]
    if assigning:
        blocked = [n for n in picked if not by_name[n]["assignable"]]
        if blocked:
            raise HTTPException(400, f"Cannot be assigned to an organization (remove instead): {', '.join(blocked)}")
    if not picked:
        raise HTTPException(400, "Nothing selected: choose at least one collection that has legacy data.")
    return picked


@app.get("/superadmin/legacy-data")
async def legacy_data_check(request: Request, admin: dict = Depends(require_role("superadmin"))):
    counts = await _legacy_counts()
    return {"total": sum(c["count"] for c in counts), "collections": counts}


@app.post("/superadmin/legacy-data/assign")
async def legacy_data_assign(data: LegacyAssign, request: Request,
                             admin: dict = Depends(require_role("superadmin"))):
    try:
        oid = ObjectId(data.org_id)
    except Exception:
        raise HTTPException(400, "Invalid organization id.")
    org = await db.organizations.find_one({"_id": oid}, {"slug": 1, "name": 1})
    if not org:
        raise HTTPException(404, "Organization not found.")
    org_id = str(org["_id"])
    counts = await _legacy_counts()
    picked = _legacy_pick(data.collections, counts, assigning=True)
    targets = _legacy_targets()
    results = []
    for name in picked:
        flt = targets[name][0]
        try:
            if name == "sms_usage":
                if await db.sms_usage.find_one({"org_key": org_id}, {"_id": 1}):
                    raise DuplicateKeyError("target organization already has SMS usage counters")
                r = await db.sms_usage.update_many(flt, {"$set": {"org_key": org_id}})
            else:
                r = await cross_tenant(db)[name].update_many(flt, {"$set": {"org_id": org_id}})   # claims ownerless rows
            results.append({"name": name, "moved": r.modified_count})
        except DuplicateKeyError as e:
            # Some documents may already have moved before the clash; a re-check shows what is left.
            results.append({"name": name, "moved": 0, "error":
                            f"Clashes with data the organization already has ({str(e)[:120]}). Remove these instead, or fix the clash."})
        except Exception as e:
            logger.error(f"legacy assign {name} failed: {e}")
            results.append({"name": name, "moved": 0, "error": "Could not be assigned (see server log)."})
    invalidate_settings()
    _invalidate_results()
    moved = {r["name"]: r["moved"] for r in results if r["moved"]}
    await log_action("legacy_data_assigned", current_actor(request),
                     {"org_slug": org.get("slug"), "moved": moved,
                      "failed": [r["name"] for r in results if r.get("error")]}, org_id=org_id)
    return {"org_id": org_id, "results": results, "remaining": sum(c["count"] for c in await _legacy_counts())}


@app.post("/superadmin/legacy-data/delete")
async def legacy_data_delete(data: LegacyDelete, request: Request,
                             admin: dict = Depends(require_role("superadmin"))):
    if data.confirm != LEGACY_DELETE_CONFIRM:
        raise HTTPException(400, f'Type "{LEGACY_DELETE_CONFIRM}" to confirm.')
    counts = await _legacy_counts()
    picked = _legacy_pick(data.collections, counts, assigning=False)
    backed_up = set(backup.FULL_COLLECTIONS) | set(backup.APPEND_ONLY)
    snapshot = None
    if any(n in backed_up for n in picked):
        # Same rule as reset-election: never delete without a safety copy; a failed upload aborts.
        try:
            snapshot = await backup.snapshot_legacy_data(db, "legacy-delete")
        except Exception as e:
            logger.error(f"legacy-data delete aborted: pre-delete snapshot failed: {e}")
            raise HTTPException(503, "Delete aborted: the safety backup could not be uploaded, so nothing was deleted.")
    targets = _legacy_targets()
    deleted = {}
    for name in picked:
        r = await cross_tenant(db)[name].delete_many(targets[name][0])   # removes ownerless rows only
        deleted[name] = r.deleted_count
    invalidate_settings()
    _invalidate_results()
    # Deliberately not written to audit_log: an entry with no org would itself be new legacy data.
    logger.warning(f"legacy data removed by {current_actor(request)}: {deleted}; safety snapshot: "
                   f"{(snapshot or {}).get('prefix')}")
    return {"deleted": deleted, "snapshot": (snapshot or {}).get("prefix"),
            "remaining": sum(c["count"] for c in await _legacy_counts())}


# =============================================================================
# SUPERADMIN ROUTES  (instant overrides — no voting required)
# =============================================================================

# --- Branding ---

_ID_WORDING_DEFAULTS = {"id_label": "", "id_examples": [], "name_examples": [], "id_format_hint": ""}


def _clean_id_wording(data) -> dict:
    """Trims and bounds the voter-login wording so a pasted essay can't end up in a placeholder."""
    def lst(items):
        return [str(x).strip()[:80] for x in (items or []) if str(x).strip()][:8]
    return {
        "id_label": (data.id_label or "").strip()[:60],
        "id_examples": lst(data.id_examples),
        "name_examples": lst(data.name_examples),
        "id_format_hint": (data.id_format_hint or "").strip()[:200],
    }


@app.get("/superadmin/branding")
async def get_branding(request: Request):
    doc = await tdb(request).settings.find_one({"name": "branding"})
    if not doc:
        return {
            "logo_url":            "",
            "primary_color":       "#003366",
            "accent_color":        "#f1c40f",
            "org_name":            "",
            "university_name":     "",
            "university_logo_url": "",
            "support_phone":       "",
            "support_contacts":    [],
            "cc_list":             [],
            **_ID_WORDING_DEFAULTS,
        }
        
    # This endpoint is unauthenticated by design (App.jsx and Results.jsx fetch it for
    # every visitor before anyone logs in), so only return fields meant for a public
    # visitor. cc_list (officials' email addresses) and org_id have no business here.
    PUBLIC_BRANDING_FIELDS = (
        "logo_url", "primary_color", "accent_color", "org_name", "university_name",
        "university_logo_url", "support_phone", "id_label", "id_format_hint",
    )
    out = {k: doc.get(k, "") for k in PUBLIC_BRANDING_FIELDS}
    out["support_contacts"] = doc.get("support_contacts") or []
    out["id_examples"] = doc.get("id_examples") or []
    out["name_examples"] = doc.get("name_examples") or []
    return out


# The public endpoint above deliberately strips cc_list/signatories for
# unauthenticated visitors. The SuperAdmin settings form needs those back to
# edit them without wiping them on every save, hence this authenticated twin.
@app.get("/superadmin/branding-full")
async def get_branding_full(request: Request, admin: dict = Depends(require_role("superadmin"))):
    doc = await tdb(request).settings.find_one({"name": "branding"}) or {}
    defaults = {
        "logo_url": "", "primary_color": "#003366", "accent_color": "#f1c40f",
        "org_name": "", "university_name": "", "university_logo_url": "",
        "support_phone": "", "support_contacts": [],
        "cc_list": [], "signatories": [], **_ID_WORDING_DEFAULTS,
    }
    return {**defaults, **{k: doc.get(k, v) for k, v in defaults.items()}}


_WHATSAPP_HOSTS = {"wa.me", "api.whatsapp.com", "chat.whatsapp.com", "whatsapp.com", "www.whatsapp.com"}


def _clean_support_contacts(groups: list[dict]) -> list[dict]:
    """Each group is {reason, contacts: [{name, link}]}: link is a WhatsApp number (digits, country
    code) or an https WhatsApp link. Anything else is rejected so the voter Help menu can never be
    pointed elsewhere. A reason with one contact is a direct link in the Help menu; more than one
    shows a small submenu of names for the voter to pick from — see HelpPanel.jsx."""
    out = []
    for g in (groups or [])[:12]:
        reason = str((g or {}).get("reason", "")).strip()[:80]
        contacts = []
        for c in (g or {}).get("contacts", [])[:6]:
            name = str((c or {}).get("name", "")).strip()[:60]
            link = str((c or {}).get("link", "")).strip()[:300]
            if not name and not link:
                continue
            if not link:
                raise HTTPException(400, f"'{reason or '(reason)'}': every contact needs a WhatsApp number or link.")
            if link.lower().startswith("https://"):
                host = (urlparse(link).hostname or "").lower()
                if host not in _WHATSAPP_HOSTS:
                    raise HTTPException(400, f"'{reason or '(reason)'}': only WhatsApp links (wa.me, chat.whatsapp.com) are allowed.")
            else:
                digits = re.sub(r"\D", "", link)
                if not 9 <= len(digits) <= 15:
                    raise HTTPException(400, f"'{reason or '(reason)'}': enter digits with the country code (e.g. 256745707723) or a full WhatsApp link.")
                link = digits
            contacts.append({"name": name, "link": link})
        if not reason and not contacts:
            continue
        if not reason or not contacts:
            raise HTTPException(400, "Each support reason needs a label and at least one contact.")
        out.append({"reason": reason, "contacts": contacts})
    return out


@app.post("/superadmin/branding")
async def save_branding(data: BrandingUpdate, request: Request):
    doc = data.dict()
    doc["support_contacts"] = _clean_support_contacts(data.support_contacts)
    doc.update(_clean_id_wording(data))
    await tdb(request).settings.update_one(
        {"name": "branding"},
        {"$set": org_stamp(request, {**doc, "name": "branding"})},
        upsert=True
    )
    invalidate_settings(request.state.org_id, "branding")    # the SMS text reads it through the cache
    # Branding drives the org name, the commissioner name printed on the
    # official declaration, and the cc list — all of which appear on the
    # certified report. Changes to it belong in the audit trail.
    await log_action("branding_updated", current_actor(request), {
        "org_name": data.org_name,
        "cc_count": len(data.cc_list),
        "signatory_count": len(data.signatories),
    }, org_id=request.state.org_id)
    return {"status": "saved"}


# --- Positions ---

@app.post("/positions")
async def add_position(data: PositionCreate, request: Request, admin: dict = Depends(require_role("superadmin"))):
    # Was reachable by ANY admin token (the path doesn't start with
    # /superadmin) — an Overseer could create or delete ballot positions.
    result = await tdb(request).positions.insert_one(data.dict())
    await log_action("position_added", current_actor(request), {"title": data.title}, org_id=request.state.org_id)
    return {"id": str(result.inserted_id)}


@app.patch("/positions/{position_id}")
async def update_position(position_id: str, data: PositionUpdate, request: Request,
                          admin: dict = Depends(require_role("superadmin"))):
    oid = parse_oid(position_id, "position id")
    changes = {k: v for k, v in data.dict().items() if v is not None}
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(400, "Position title cannot be empty.")
    if not changes:
        raise HTTPException(400, "Nothing to update.")
    res = await tdb(request).positions.update_one({"_id": oid}, {"$set": changes})
    if res.matched_count == 0:
        raise HTTPException(404, "Position not found.")
    await log_action("position_updated", current_actor(request), {"position_id": position_id, **changes},
                     org_id=request.state.org_id)
    return {"status": "updated"}


@app.delete("/positions/{position_id}")
async def delete_position(position_id: str, request: Request, admin: dict = Depends(require_role("superadmin"))):
    try:
        oid = ObjectId(position_id)
    except Exception:
        raise HTTPException(400, "Invalid position id.")
    await tdb(request).positions.delete_one({"_id": oid})
    await log_action("position_deleted", current_actor(request), {"position_id": position_id}, org_id=request.state.org_id)
    return {"status": "deleted"}


# --- Commissioner management ---

@app.get("/superadmin/commissioners")
async def list_commissioners(request: Request):
    result = []
    async for v in tdb(request).voters.find(
        {"is_commissioner": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1, "is_deputy_chief_commissioner": 1, "commissioner_role": 1, "commissioner_email": 1}
    ):
        result.append(v)
    return result
    
@app.get("/superadmin/panel-eligible-admins")
async def list_panel_eligible_admins(request: Request):
    """Everyone who holds any admin role (commissioner, IT admin, overseer, financial controller), each
    with the labels of the roles they hold, for the Vetting Panel quick-pick. Any of them can be linked
    to the panel (no extra login) and reach it from their own dashboard via /admin/switch-hat."""
    proj = {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1,
            **{f: 1 for f in HAT_ROLE_FLAGS.values()}}
    result = []
    async for v in tdb(request).voters.find({"$or": [{f: True} for f in HAT_ROLE_FLAGS.values()]}, proj):
        result.append({
            "student_id": v["student_id"], "full_name": v.get("full_name", ""),
            "is_chief_commissioner": bool(v.get("is_chief_commissioner")),
            "roles": [HAT_ROLE_LABELS[r] for r in _held_hat_roles(v)],
        })
    result.sort(key=lambda r: (r["full_name"] or "").lower())
    return result


@app.post("/superadmin/commissioners/{student_id:path}/set-chief")
async def set_chief_commissioner(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await tdb(request).voters.update_many({}, {"$set": {"is_chief_commissioner": False}})
    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_chief_commissioner": True}}
    )
    # Arguably the most sensitive action in the system — this is who can
    # certify results and grant phase exceptions. It was logging nothing.
    await log_action("chief_commissioner_set", current_actor(request), {
        "student_id": voter["student_id"], "full_name": voter.get("full_name", "")
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_chief_commissioner": True}


@app.post("/superadmin/commissioners/{student_id:path}/clear-chief")
async def clear_chief_commissioner(student_id: str, request: Request):
    await tdb(request).voters.update_one(
        get_forgiving_filter(student_id),
        {"$set": {"is_chief_commissioner": False}}
    )
    await log_action("chief_commissioner_cleared", current_actor(request), {
        "student_id": normalize_student_id(student_id)
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_chief_commissioner": False}


@app.post("/superadmin/commissioners/{student_id:path}/set-deputy-chief")
async def set_deputy_chief_commissioner(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await tdb(request).voters.update_many({}, {"$set": {"is_deputy_chief_commissioner": False}})
    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_deputy_chief_commissioner": True}}
    )
    # Deputy has the same standing as the Chief for exception grants and
    # signing — see isChief usage on the frontend, which now checks either
    # flag. Logged for the same reason set-chief is logged.
    await log_action("deputy_chief_commissioner_set", current_actor(request), {
        "student_id": voter["student_id"], "full_name": voter.get("full_name", "")
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_deputy_chief_commissioner": True}


@app.post("/superadmin/commissioners/{student_id:path}/clear-deputy-chief")
async def clear_deputy_chief_commissioner(student_id: str, request: Request):
    await tdb(request).voters.update_one(
        get_forgiving_filter(student_id),
        {"$set": {"is_deputy_chief_commissioner": False}}
    )
    await log_action("deputy_chief_commissioner_cleared", current_actor(request), {
        "student_id": normalize_student_id(student_id)
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_deputy_chief_commissioner": False}


@app.get("/superadmin/chief-commissioner")
async def get_chief_commissioner(request: Request):
    chief = await tdb(request).voters.find_one(
        {"is_chief_commissioner": True},
        {"_id": 0, "student_id": 1, "full_name": 1}
    )
    if not chief:
        return {"full_name": None}
    return chief


@app.post("/superadmin/commissioners/{student_id:path}/set-finance-commissioner")
async def set_finance_commissioner(student_id: str, request: Request):
    """RETIRED. Candidate payments are cleared by the Financial Controller, so commissioners can no
    longer be given finance-clearing power (they vote on the same applications). Grant the
    Financial Controller role instead: /superadmin/financial-controllers/{student_id}/toggle."""
    raise HTTPException(410, "Commissioners can no longer clear payments. Make this person a Financial "
                             "Controller instead (a different person from the commissioners).")


@app.post("/superadmin/commissioners/{student_id:path}/clear-finance-commissioner")
async def clear_finance_commissioner(student_id: str, request: Request):
    await tdb(request).voters.update_one(
        get_forgiving_filter(student_id),
        {"$set": {"is_finance_commissioner": False}}
    )
    await log_action("finance_commissioner_cleared", current_actor(request), {"student_id": student_id}, org_id=request.state.org_id)
    return {"student_id": student_id, "is_finance_commissioner": False}


@app.get("/superadmin/finance-commissioner")
async def get_finance_commissioner(request: Request):
    """LEGACY: lists anyone still carrying the retired is_finance_commissioner flag (it no longer grants
    anything). Empty once migrate_retire_finance_commissioner.py --apply has been run."""
    result = []
    async for fc in tdb(request).voters.find(
        {"is_finance_commissioner": True},
        {"_id": 0, "student_id": 1, "full_name": 1}
    ):
        result.append(fc)
    return result


@app.post("/superadmin/commissioners/{student_id:path}/set-role")
async def set_commissioner_role(student_id: str, data: CommissionerRoleUpdate, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"commissioner_role": data.role_label}}
    )
    await log_action("commissioner_role_set", current_actor(request), {
        "student_id": student_id, "role_label": data.role_label
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "commissioner_role": data.role_label}

@app.post("/superadmin/commissioners/{student_id:path}/toggle")
async def toggle_commissioner(student_id: str, request: Request):
    """Grant or revoke commissioner status for any voter."""
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_commissioner", False)
    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_commissioner": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("commissioner_toggled", current_actor(request), {
    "student_id": student_id, "is_commissioner": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_commissioner": new_val}

@app.post("/superadmin/it-admins/{student_id:path}/set-credentials")
async def set_it_admin_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_it_admin"):
        raise HTTPException(400, "This person is not an IT admin.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "it_admin_email":                data.email,
            "it_admin_password_hash":        hashed,
            "it_admin_must_change_password": True,
            "it_admin_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "IT Admin", temp_password)
    await log_action("it_admin_credentials_set", current_actor(request), {
        "student_id": student_id, "email": data.email, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "credentials_set", "sms_notified": sms_sent}
    
# --- Application overrides ---

@app.post("/superadmin/applications/{app_id}/force-approve")
async def superadmin_force_approve(app_id: str, request: Request):
    """Approve an application instantly, bypassing vetting panel voting."""
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") == "approved":
        raise HTTPException(400, "Already approved.")

    # Atomic guard, same pattern as _resolve_application: claim the
    # not-yet-approved document via the update filter so this can't race a
    # commission majority vote (or a concurrent duplicate click) into
    # creating two candidates for the same application.
    result = await tdb(request).applications.update_one(
        {"_id": oid, "status": {"$ne": "approved"}},
        {"$set": {
            "status": "approved",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        },
        "$unset": {"tied_pending_chief": ""}}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just approved by someone else. Please refresh.")
    await _create_candidate_from_application(app_doc, request.state.org_id)
    await _issue_certificate(app_doc, request.state.org_id)
    await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
        f"{org}: Congratulations! Your nomination for {pos} has been approved. "
        f"Your name will appear on the ballot."))
    await log_action("application_force_approved", current_actor(request), {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f" Superadmin force-approved application {app_id}.")
    return {"status": "force_approved"}


@app.post("/superadmin/applications/{app_id}/force-deny")
async def superadmin_force_deny(app_id: str, request: Request):
    """Deny an application instantly, bypassing vetting panel voting."""
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("denied", "removed"):
        raise HTTPException(400, "Application is already denied or removed.")

    result = await tdb(request).applications.update_one(
        {"_id": oid, "status": {"$nin": ["denied", "removed"]}},
        {"$set": {
            "status": "denied",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        },
        "$unset": {"tied_pending_chief": ""}}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just resolved by someone else. Please refresh.")
    await _record_denial_snapshot(app_doc, request.state.org_id)
    await log_action("application_force_denied", current_actor(request), {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f" Superadmin force-denied application {app_id}.")
    return {"status": "force_denied"}


class ApplicationRevertRequest(BaseModel):
    reason: str


class ApplicationEditRequest(BaseModel):
    """Any subset of the application's fields; only the ones sent (and actually different) are changed."""
    student_id:        str | None = None
    full_name:         str | None = None
    position_id:       str | None = None
    manifesto:         str | None = Field(None, max_length=MANIFESTO_MAX_CHARS)
    image_url:         str | None = None
    payment_method:    str | None = None
    payment_proof_url: str | None = None
    reason:            str


# Fields an application correction may touch, and which of them appear on the printed application.
APPLICATION_EDITABLE_FIELDS = ("student_id", "full_name", "position_id", "manifesto", "image_url",
                               "payment_method", "payment_proof_url")
APPLICATION_PRINTED_FIELDS = ("student_id", "full_name", "position_title", "manifesto", "image_url")


def _application_edit_history(app_doc: dict) -> list[dict]:
    """Normalised correction history, oldest first: [{at, by, reason, changes{field:{old,new}}, after{...}}].
    `after` is the printed content of the application right after that correction. Older records that
    only have `reg_no_history` (registration-number-only edits) are converted on the fly."""
    snap = app_doc.get("application_snapshot") or {}
    out = []
    for h in app_doc.get("reg_no_history") or []:
        out.append({"at": h.get("at"), "by": h.get("by"), "reason": h.get("reason"),
                    "changes": {"student_id": {"old": h.get("old"), "new": h.get("new")}},
                    "after": {**{k: snap.get(k) for k in APPLICATION_PRINTED_FIELDS}, "student_id": h.get("new"),
                              "submitted_at": snap.get("submitted_at")}})
    out.extend(app_doc.get("edit_history") or [])
    return out


def _clean_reason(raw: str) -> str:
    reason = (raw or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason (at least 3 characters) is required.")
    if len(reason) > 500:
        raise HTTPException(400, "Reason must be 500 characters or fewer.")
    return reason


@app.post("/superadmin/applications/{app_id}/revert-to-pending")
async def superadmin_revert_application_to_pending(app_id: str, data: ApplicationRevertRequest, request: Request):
    """Undo a force-approve or force-deny: the application goes back to `pending` so the commission
    can decide it normally (or the superadmin can override again). A reason is mandatory and is written
    to the audit log. Commission-decided applications are deliberately not reversible here.

    Reverting a force-approve also takes the candidate off the ballot and revokes the certificate, and is
    refused once votes have been cast for that candidate (those votes would be orphaned)."""
    reason = _clean_reason(data.reason)
    oid = parse_oid(app_id, "application id")
    org_id = require_org(request.state.org_id)
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    from_status = app_doc.get("status")
    if from_status not in ("approved", "denied"):
        raise HTTPException(400, "Only an approved or denied application can be sent back to pending.")
    if not app_doc.get("superadmin_override"):
        raise HTTPException(400, "This decision was made by the commission, not by a superadmin override, "
                                 "so it can't be reverted here.")

    cand = None
    if from_status == "approved":
        cand = await tdb(request).candidates.find_one({"application_id": app_id})
        if cand:
            votes_cast = await tdb(request).vote_events.count_documents({"candidate_id": cand["_id"]})
            if votes_cast:
                raise HTTPException(409, f"{votes_cast} vote(s) have already been cast for this candidate, "
                                         "so the approval can't be reverted. Use Remove from Ballot instead.")

    now = datetime.utcnow()
    prior_votes = dict(app_doc.get("votes") or {})
    # Atomic claim on the exact state we inspected, so a racing commission vote / second click can't double-apply.
    result = await tdb(request).applications.update_one(
        {"_id": oid, "status": from_status, "superadmin_override": True},
        {"$set": {"status": "pending", "votes": {}, "removal_votes": {},
                  "denial_snapshot": None, "certificate_id": None, "certificate_issued_at": None},
         "$unset": {"superadmin_override": "", "decided_at": "", "tied_pending_chief": ""},
         "$push": {"revert_history": {"at": now, "by": current_actor(request), "from_status": from_status,
                                      "reason": reason, "prior_votes": prior_votes}}}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just changed by someone else. Please refresh.")

    if cand:
        await tdb(request).candidates.delete_one({"_id": cand["_id"]})
    if from_status == "approved":
        await _revoke_certificate_for_application(app_doc, org_id)

    await log_action("application_reverted_to_pending", current_actor(request), {
        "app_id": app_id, "from_status": from_status, "reason": reason,
        "candidate_removed_from_ballot": bool(cand), "certificate_revoked": bool(app_doc.get("certificate_id")),
    }, org_id=org_id)
    logger.info(f"Superadmin reverted application {app_id} from {from_status} to pending.")
    return {"status": "pending", "from_status": from_status}


@app.post("/superadmin/applications/{app_id}/edit")
async def superadmin_edit_application(app_id: str, data: ApplicationEditRequest, request: Request):
    """Correct an application: registration number, name, position, manifesto, photo or payment details.
    A reason is mandatory. The original submission snapshot is never touched; each correction is appended
    to `edit_history` (who, when, why, old -> new, and the printed content afterwards), which drives the
    EDITED mark and the extra pages of the application PDF, and it is written to the audit log.
    A changed registration number must exist on the voter register under the same name; the applicant's
    old status links are revoked (they may have gone to a different student's phone)."""
    reason = _clean_reason(data.reason)
    oid = parse_oid(app_id, "application id")
    org_id = require_org(request.state.org_id)
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")

    requested = {k: getattr(data, k) for k in APPLICATION_EDITABLE_FIELDS if getattr(data, k) is not None}
    new_vals: dict = {}
    if "student_id" in requested:
        sid = normalize_student_id(requested["student_id"])
        if not re.fullmatch(r"[^\s\x00-\x1f]{1,64}", sid):
            raise HTTPException(400, f"{_cap(await id_noun(request.state.org_id))} must be 1-64 characters with no spaces.")
        new_vals["student_id"] = sid
    if "full_name" in requested:
        name = normalize_name(requested["full_name"])
        if not name or len(name) > 120:
            raise HTTPException(400, "Name must be 1-120 characters.")
        new_vals["full_name"] = name
    if "position_id" in requested:
        pid = requested["position_id"].strip()
        try:
            pos = await tdb(request).positions.find_one({"_id": ObjectId(pid), "org_id": org_id})
        except Exception:
            pos = None
        if not pos:
            raise HTTPException(400, "That position does not exist.")
        new_vals["position_id"] = pid
    if "manifesto" in requested:
        new_vals["manifesto"] = requested["manifesto"].strip()
    for url_field in ("image_url", "payment_proof_url"):
        if url_field in requested:
            u = requested[url_field].strip()
            if u and not (u.startswith("https://") and len(u) <= 2000):
                raise HTTPException(400, f"{url_field} must be an https:// link (or empty).")
            new_vals[url_field] = u
    if "payment_method" in requested:
        pm = requested["payment_method"].strip()
        if len(pm) > 60:
            raise HTTPException(400, "Payment method is too long.")
        new_vals["payment_method"] = pm

    # Only genuinely different values count as changes.
    changes = {}
    for k, v in new_vals.items():
        old = app_doc.get(k, "")
        if k == "student_id":
            same = normalize_student_id(old or "") == v
        else:
            same = (old or "") == v
        if not same:
            changes[k] = {"old": old, "new": v}
    if not changes:
        raise HTTPException(400, "No changes to save.")

    final = {k: changes[k]["new"] if k in changes else app_doc.get(k, "")
             for k in ("student_id", "full_name", "position_id")}
    set_doc = {k: c["new"] for k, c in changes.items()}

    if "student_id" in changes or "full_name" in changes:
        voter = await tdb(request).voters.find_one({"student_id": final["student_id"]})
        if not voter:
            raise HTTPException(404, f"That {await id_noun(request.state.org_id)} is not on the voter register.")
        if not names_match(voter.get("full_name", ""), final["full_name"]):
            raise HTTPException(400, f"The name on the voter register for that {await id_noun(request.state.org_id)} doesn't match "
                                     "the name on this application.")
        final["student_id"] = voter["student_id"]
        if "student_id" in changes:
            changes["student_id"]["new"] = set_doc["student_id"] = voter["student_id"]

    if {"student_id", "position_id"} & set(changes):
        clash = await tdb(request).applications.find_one({
            "student_id": final["student_id"], "position_id": final["position_id"], "_id": {"$ne": oid}})
        if clash:
            raise HTTPException(409, "That student already has an application for this position.")

    cand = None
    if app_doc.get("status") == "approved":
        cand = await tdb(request).candidates.find_one({"application_id": app_id})
        if cand and "position_id" in changes:
            if await tdb(request).vote_events.count_documents({"candidate_id": cand["_id"]}):
                raise HTTPException(409, "Votes have already been cast for this candidate, so their position "
                                         "can't be changed.")

    position_title, position_order = await _resolve_position_title(final["position_id"], org_id)
    history = _application_edit_history(app_doc)
    prev_after = history[-1]["after"] if history else (app_doc.get("application_snapshot") or {})
    after = {
        "student_id": final["student_id"], "full_name": final["full_name"], "position_title": position_title,
        "manifesto": changes.get("manifesto", {}).get("new", prev_after.get("manifesto", app_doc.get("manifesto", ""))),
        "image_url": changes.get("image_url", {}).get("new", prev_after.get("image_url", app_doc.get("image_url", ""))),
        "submitted_at": (app_doc.get("application_snapshot") or {}).get("submitted_at"),
    }
    now = datetime.utcnow()
    entry = {"at": now, "by": current_actor(request), "reason": reason, "changes": changes, "after": after}

    guard = {"_id": oid, "student_id": app_doc.get("student_id"), "status": app_doc.get("status")}
    result = await tdb(request).applications.update_one(
        guard, {"$set": set_doc, "$push": {"edit_history": entry}})
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just changed by someone else. Please refresh.")

    if cand:   # keep the ballot entry in step with the corrected application
        cand_set = {}
        if "full_name" in changes: cand_set["name"] = changes["full_name"]["new"]
        if "image_url" in changes: cand_set["image_url"] = changes["image_url"]["new"]
        if "position_id" in changes: cand_set.update({"position": position_title, "order": position_order})
        if cand_set:
            await tdb(request).candidates.update_one({"_id": cand["_id"]}, {"$set": cand_set})

    links_revoked = 0
    if "student_id" in changes:
        moved = await tdb(request).candidate_tokens.update_many(
            {"org_id": org_id, "student_id": changes["student_id"]["old"]},
            {"$set": {"student_id": final["student_id"], "revoked": True}})
        links_revoked = moved.modified_count

    def _short(v):
        v = "" if v is None else str(v)
        return v if len(v) <= 120 else v[:117] + "..."
    await log_action("application_edited", current_actor(request), {
        "app_id": app_id, "reason": reason, "fields": sorted(changes),
        "changes": {k: {"old": _short(c["old"]), "new": _short(c["new"])} for k, c in changes.items()},
        "status_links_revoked": links_revoked,
    }, org_id=org_id)
    logger.info(f"Superadmin corrected application {app_id}: {sorted(changes)}.")
    return {"status": "edited", "fields": sorted(changes), "status_links_revoked": links_revoked,
            "ballot_updated": bool(cand)}


class ReconcileEditsRequest(BaseModel):
    dry_run: bool = True


@app.post("/superadmin/maintenance/reconcile-application-edits")
async def superadmin_reconcile_application_edits(data: ReconcileEditsRequest, request: Request,
                                                 admin: dict = Depends(require_role("superadmin"))):
    """Record pre-tracking edits (live fields differ from the snapshot with no edit_history)."""
    dry_run = data.dry_run
    from edit_reconcile import run_edit_reconcile
    report = await run_edit_reconcile(db, _resolve_position_title, _application_edit_history,
                                      org_id=request.state.org_id, actor=current_actor(request), dry_run=dry_run)
    if not dry_run and report["recorded"]:
        await log_action("application_edits_reconciled", current_actor(request),
                         {"recorded": report["recorded"], "apps": [i["app_id"] for i in report["items"]]},
                         org_id=request.state.org_id)
    return report


@app.post("/superadmin/applications/{app_id}/force-finance-clear")
async def superadmin_force_finance_clear(app_id: str, request: Request):
    """Bypass the Finance Commissioner gate — for cases where no Finance
    Commissioner is currently assigned. Voting can proceed after this."""
    oid = parse_oid(app_id, "application id")
    app_doc = await tdb(request).applications.find_one({"_id": oid})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared.")

    result = await tdb(request).applications.update_one(
        {"_id": oid, "finance_cleared": {"$ne": True}},
        {"$set": {
            "finance_cleared": True,
            "finance_cleared_by": "superadmin_override",
            "finance_cleared_at": datetime.utcnow()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just finance-cleared by someone else. Please refresh.")
    await log_action("application_force_finance_cleared", current_actor(request), {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f"Superadmin force-cleared finance gate for application {app_id}.")
    return {"status": "force_finance_cleared"}


@app.post("/superadmin/candidates/{candidate_id}/remove")
async def superadmin_remove_candidate(candidate_id: str, request: Request):
    """Remove an approved candidate from the ballot instantly."""
    oid = parse_oid(candidate_id, "candidate id")
    cand = await tdb(request).candidates.find_one({"_id": oid})
    if not cand:
        raise HTTPException(404, "Candidate not found.")

    await tdb(request).candidates.delete_one({"_id": oid})
    await log_action("candidate_removed", current_actor(request), {
    "name": cand.get("name"), "position": cand.get("position")
    }, org_id=request.state.org_id)
    
    # If the candidate came from an application, mark it removed
    if cand.get("application_id"):
        app_oid = parse_oid(cand["application_id"], "application id")
        await tdb(request).applications.update_one(
            {"_id": app_oid},
            {"$set": {
                "status": "removed",
                "superadmin_override": True,
                "removed_at": datetime.utcnow()
            }}
        )
        # Same as a commission-majority removal (§3.7): stop the certificate
        # from confirming, don't just unlink it, so a copy printed before
        # removal can't keep validating forever.
        removed_app_doc = await tdb(request).applications.find_one({"_id": app_oid})
        if removed_app_doc:
            await _revoke_certificate_for_application(removed_app_doc, request.state.org_id)

    logger.info(f"Superadmin removed candidate {candidate_id}.")
    return {"status": "removed"}


# =============================================================================
# RESULTS
# =============================================================================

# live (default: what Results.jsx does today) | closed | certified. "live" publishes running tallies
# to anyone during voting; together with the public has_voted roll a watcher can correlate a tally
# tick with a known voter finishing. Set closed/certified to withhold until then (admins always see).
@app.get("/election-results")
async def get_election_results(request: Request):
    # Per-org, not process-wide: each tenant's own security_settings doc can
    # override this; PUBLIC_RESULTS_MODE (env) is only the fallback default
    # for orgs that haven't set their own (see _SEC_DEFAULTS).
    #
    # Turnout (how many people voted) is NEVER gated by this setting — it's
    # participation data, not "who's winning," and hiding it too just breaks
    # the public page instead of protecting anything. Only the per-candidate
    # vote breakdown is withheld until results are released. A gated request
    # gets a 200 with results_released=false and an empty results list, not
    # a 403 — so the turnout figure and voter-roll section on the public page
    # keep working even while the breakdown itself stays hidden.
    results_mode = (await get_security_settings(request))["public_results_mode"]
    results_released = True
    if results_mode != "live":
        try:
            await require_admin(request)
        except HTTPException:
            cfg = await tdb(request).settings.find_one({"name": "election_config"}) or {}
            results_released = cfg.get("is_certified", False) or (
                results_mode == "closed" and not cfg.get("is_open", True))
    cache_key = (str(request.state.org_id), bool(results_released))
    if _RESULTS_TTL > 0:
        hit = _RESULTS_CACHE.get(cache_key)
        if hit and hit[0] > time.monotonic():
            return copy.deepcopy(hit[1])
    voter_turnout = await tdb(request).voters.count_documents({"has_voted": True})
    results = []
    if results_released:
        vote_counts = await get_vote_counts(request)
        async for cand in tdb(request).candidates.find({}).sort("order", 1):
            results.append({
                "id": str(cand["_id"]),
                "name": cand["name"],
                "position": cand["position"],
                "votes": vote_counts.get(str(cand["_id"]), 0),
                "order": cand.get("order", 0)
            })
    payload = {"voter_turnout": voter_turnout, "results": results, "results_released": results_released}
    if _RESULTS_TTL > 0:
        _RESULTS_CACHE[cache_key] = (time.monotonic() + _RESULTS_TTL, copy.deepcopy(payload))
    return payload

# =============================================================================
# OVERSEER ROUTES  (read-only, platform-wide, anonymized)
# =============================================================================

@app.get("/overseer/dashboard")
async def get_overseer_dashboard(request: Request, admin: dict = Depends(require_role("overseer", "superadmin"))):
    """
    Platform-wide read-only view for the Overseer. Deliberately strips the
    per-commissioner votes map from every application — the Overseer can see
    aggregate counts and outcomes, but never which commissioner voted which way.
    """
    status_doc = await tdb(request).settings.find_one({"name": "election_config"})
    election_status = {
        "is_open":      (status_doc or {}).get("is_open", True),
        "is_certified": (status_doc or {}).get("is_certified", False),
        "start":        (status_doc or {}).get("start_time"),
        "end":          (status_doc or {}).get("end_time")
    }

    total_voters   = await tdb(request).voters.count_documents({})
    voted_count    = await tdb(request).voters.count_documents({"has_voted": True})
    total_commissioners = await get_commissioner_count(request.state.org_id)

    applications_summary = []
    overseer_keys = await _active_panel_keys(request.state.org_id)
    panel_count = await get_panel_count(request.state.org_id)
    async for a in tdb(request).applications.find({}).sort("submitted_at", -1):
        shaped = shape_application_for_role(a, "overseer", active_keys=overseer_keys, panel_count=panel_count)
        row = {
            "id":                 str(a["_id"]),
            "full_name":          a.get("full_name", ""),
            "position_id":        a.get("position_id", ""),
            "status":             a.get("status", "pending"),
            "finance_cleared":    a.get("finance_cleared", False),
            "stage":              shaped["stage"],
            "stage_label":        shaped["stage_label"],
            "submitted_at":       a.get("submitted_at"),
            # Tier 1: the stage only. No vote counts, split or tie-break marker (only the Vetting Panel sees those).
        }
        applications_summary.append(row)

    student_changes_summary = []
    async for c in tdb(request).student_changes.find({}).sort("requested_at", -1):
        student_changes_summary.append({
            "id":            str(c["_id"]),
            "change_type":   c.get("change_type", ""),
            "student_id":    c.get("student_id", ""),
            "full_name":     c.get("full_name", ""),
            "status":        c.get("status", "pending"),
            "requested_by":  c.get("requested_by", ""),
            "decided_by":    c.get("decided_by"),
            "requested_at":  c.get("requested_at"),
            "reason":        c.get("reason")
        })

    vote_counts = await get_vote_counts(request)
    candidates_results = []
    async for cand in tdb(request).candidates.find({}).sort("order", 1):
        candidates_results.append({
            "name": cand["name"],
            "position": cand["position"],
            "votes": vote_counts.get(str(cand["_id"]), 0)
        })

    return {
        "election_status":       election_status,
        "voter_turnout": {
            "total_voters": total_voters,
            "voted_count":  voted_count,
            "turnout_pct":  round((voted_count / total_voters) * 100, 1) if total_voters else 0
        },
        "total_commissioners":   total_commissioners,
        "panel_count":           panel_count,
        "applications":          applications_summary,
        "student_changes":       student_changes_summary,
        "candidate_results":     candidates_results
    }


# =============================================================================
# IT ADMIN ROUTES
# =============================================================================

@app.post("/it-admin/students/request-add")
async def request_add_student(data: ITAdminStudentAdd, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    await assert_roster_unfrozen(request)
    if not any(str(p or "").strip() for p in data.phones):
        raise HTTPException(400, "At least one phone number is required.")
    # A request attributed to someone else would make the audit trail lie
    # about who asked for a voter to be added to the register.
    bind_identity(request, data.requested_by, "IT Admin account")
    data.full_name = normalize_name(data.full_name)
    data.student_id = normalize_student_id(data.student_id)
    data.attrs = await _validate_voter_attrs(request.state.org_id, data.attrs)
    if await tdb(request).voters.find_one({"student_id": data.student_id}, {"_id": 1}):
        raise HTTPException(409, "Already registered, use Edit Student.")
    bypass = await upload_bypass_enabled(request)
    if not bypass and not data.reason.strip():
        raise HTTPException(400, "A reason is required.")
    if bypass:
        # Superadmin has switched the upload bypass on: no reason / proof of payment needed and no
        # Financial Controller approval step. The voter is added straight away, and the request is
        # still recorded (approved, flagged bypass) plus audit-logged and written to the roster ledger.
        now = datetime.utcnow()
        reason = data.reason.strip() or "Fully paid, receipt issued (upload bypass)"
        doc = {**data.dict(), "reason": reason, "change_type": "add", "status": "approved",
               "requested_at": now, "resolved_at": now, "decided_by": "upload_bypass",
               "decision_reason": "Superadmin upload bypass was enabled", "bypass": True}
        result = await tdb(request).student_changes.insert_one(dict(doc))
        await _execute_student_change(doc, request.state.org_id)
        summary = {"student_id": data.student_id, "full_name": data.full_name, "reason": reason, "bypass": True}
        await log_action("student_added_via_upload_bypass", current_actor(request), summary, org_id=request.state.org_id)
        await append_ledger(request.state.org_id, "student_added_via_upload_bypass", str(result.inserted_id),
                            current_actor(request), current_role(request) or "it_admin", summary)
        return {"status": "added", "id": str(result.inserted_id), "bypass": True}
    # Prevent duplicate pending requests for same student
    existing = await tdb(request).student_changes.find_one({
        "student_id":  data.student_id,
        "change_type": "add",
        "status":      "pending"
    })
    if existing:
        raise HTTPException(400, "A pending add request already exists for this student.")

    result = await tdb(request).student_changes.insert_one({
        **data.dict(),
        "change_type":  "add",
        "status":       "pending",
        "requested_at": datetime.utcnow()
    })
    await log_action("student_add_requested", data.requested_by, {
        "student_id": data.student_id,
        "full_name":  data.full_name,
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "requested", "id": str(result.inserted_id)}

@app.post("/superadmin/it-admins/{student_id:path}/reset-password")
async def reset_it_admin_password(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter or not voter.get("is_it_admin"):
        raise HTTPException(404, "IT admin not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "it_admin_password_hash":        hashed,
            "it_admin_must_change_password": True,
            "it_admin_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "IT Admin", temp_password)
    await log_action("it_admin_password_reset", current_actor(request), {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}


@app.post("/superadmin/commissioners/{student_id:path}/reset-password")
async def reset_commissioner_password(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter or not voter.get("is_commissioner"):
        raise HTTPException(404, "Commissioner not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "commissioner_password_hash":        hashed,
            "commissioner_must_change_password": True,
            "commissioner_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Commissioner", temp_password)
    await log_action("commissioner_password_reset", current_actor(request), {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}

@app.post("/it-admin/students/request-remove")
async def request_remove_student(data: ITAdminStudentRemove, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    await assert_roster_unfrozen(request)
    bind_identity(request, data.requested_by, "IT Admin account")
    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(404, "Student not found in voter register.")

    existing = await tdb(request).student_changes.find_one({
        "student_id":  data.student_id,
        "change_type": "remove",
        "status":      "pending"
    })
    if existing:
        raise HTTPException(400, "A pending removal request already exists for this student.")

    result = await tdb(request).student_changes.insert_one({
        **data.dict(),
        "full_name":    student.get("full_name", ""),
        "change_type":  "remove",
        "status":       "pending",
        "requested_at": datetime.utcnow()
    })
    await log_action("student_remove_requested", data.requested_by, {
        "student_id": data.student_id,
        "full_name":  student.get("full_name", ""),
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "requested", "id": str(result.inserted_id)}


@app.post("/it-admin/students/requests/{change_id}/cancel")
async def cancel_student_change(change_id: str, data: StudentChangeCancelRequest, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    oid = parse_oid(change_id, "change id")
    change = await tdb(request).student_changes.find_one({"_id": oid})
    if not change:
        raise HTTPException(404, "Request not found.")
    bind_identity(request, data.requested_by, "IT Admin account")
    if change.get("requested_by") != data.requested_by:
        raise HTTPException(403, "You can only cancel your own requests.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"Cannot cancel a request that is already {change.get('status')}.")

    await tdb(request).student_changes.update_one(
        {"_id": oid},
        {"$set": {
            "status":            "cancelled",
            "cancelled_at":      datetime.utcnow(),
            "cancelled_reason":  data.cancelled_reason
        }}
    )
    await log_action("student_change_cancelled", data.requested_by, {
        "change_id":        change_id,
        "change_type":      change.get("change_type"),
        "student_id":       change.get("student_id"),
        "original_reason":  change.get("reason"),
        "cancel_reason":    data.cancelled_reason
    }, org_id=request.state.org_id)
    return {"status": "cancelled"}


@app.get("/it-admin/applications")
async def it_admin_applications(request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Applicant list with stages for the people who answer applicants' questions. Stage only (tier 1)."""
    org_id = require_org(request.state.org_id)
    rows = []
    async for a in tdb(request).applications.find(org_query(request)).sort("submitted_at", -1):
        a["_id"] = str(a["_id"])
        if a.get("position_id"):
            a["position_title"], a["position_order"] = await _resolve_position_title(a["position_id"], org_id)
        rows.append(shape_application_for_role(a, "it_admin"))
    return rows


@app.get("/it-admin/students/my-requests/{it_admin_id}")
async def get_my_requests(it_admin_id: str, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    bind_identity(request, it_admin_id, "IT Admin account")
    changes = []
    async for c in tdb(request).student_changes.find(
        {"requested_by": it_admin_id}
    ).sort("requested_at", -1):
        c["_id"] = str(c["_id"])
        changes.append(c)
    return changes


# =============================================================================
# COMMISSION — STUDENT CHANGES
# =============================================================================

@app.get("/admin/student-changes")
async def list_student_changes(request: Request, status: str = None):
    if (await roster_status(request))["frozen"]:
        await _expire_pending_at_freeze(request)
    query = org_query(request)
    if status:
        query["status"] = status
    else:
        # Default: exclude cancelled so commission doesn't see withdrawn requests
        query["status"] = {"$nin": ["cancelled"]}
    changes = []
    async for c in tdb(request).student_changes.find(query).sort("requested_at", -1):
        c["_id"] = str(c["_id"])
        changes.append(c)
    return changes


@app.post("/admin/student-changes/{change_id}/decide")
async def financial_controller_decide_student_change(change_id: str, data: FinancialControllerDecision, request: Request):
    """
    The Financial Controller verifies payment status and makes the final call on
    an IT Admin's student-register change. Single-approver decision — this is
    completely separate from Commission voting on candidates.
    """
    await assert_roster_unfrozen(request)
    if data.decision not in ("approve", "deny"):
        raise HTTPException(400, "Decision must be 'approve' or 'deny'.")
    if data.decision == "deny" and not data.reason.strip():
        raise HTTPException(400, "A reason is required to deny a request.")

    oid = parse_oid(change_id, "change id")
    change = await tdb(request).student_changes.find_one({"_id": oid})
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"This request is already {change.get('status')}.")

    bind_identity(request, data.financial_controller_id, "Financial Controller account")

    financial_controller = await tdb(request).voters.find_one({
        **get_forgiving_filter(data.financial_controller_id),
        "is_financial_controller": True
    })
    if not financial_controller:
        raise HTTPException(403, "Not a registered Financial Controller.")

    # Atomic guard: claim the "pending" document via the update filter
    # itself, not the read above. Two near-simultaneous decide calls (a
    # double-click, or a decide racing a superadmin force-approve/deny on
    # the same change) would otherwise both pass the read-based check and
    # both execute _execute_student_change / log a decision. Whoever's
    # update actually matches a still-pending document is the one who goes
    # on to execute the change; the other gets a clean 409, not a silent
    # double-apply.
    status_value = "approved" if data.decision == "approve" else "denied"
    claim = await tdb(request).student_changes.update_one(
        {"_id": oid, "status": "pending"},
        {"$set": {
            "status":          status_value,
            "decided_by":      data.financial_controller_id,
            "decision_reason": data.reason,
            "resolved_at":     datetime.utcnow()
        }}
    )
    if claim.matched_count == 0:
        raise HTTPException(409, "This request was just decided by someone else. Please refresh.")

    if data.decision == "approve":
        await _execute_student_change(change, request.state.org_id)
        await log_action("student_change_approved", data.financial_controller_id, {
            "change_type": change["change_type"],
            "student_id":  change["student_id"],
            "requested_by": change.get("requested_by", "")
        }, org_id=request.state.org_id)
    else:
        await log_action("student_change_denied", data.financial_controller_id, {
            "change_type": change["change_type"],
            "student_id":  change["student_id"],
            "requested_by": change.get("requested_by", "")
        }, org_id=request.state.org_id)

    return {"status": "decision_recorded", "decision": data.decision}


# =============================================================================
# SUPERADMIN — IT ADMIN MANAGEMENT + STUDENT CHANGE OVERRIDES
# =============================================================================

def _login_state(v: dict, prefix: str) -> str:
    """Where a staff member is in first-login set-up, without exposing any credential data.
    no_credentials -> none sent yet; awaiting -> temp password sent, not yet replaced;
    expired -> temp password lapsed before it was replaced; active -> they set their own password."""
    if not v.get(f"{prefix}_password_hash"):
        return "no_credentials"
    if not v.get(f"{prefix}_must_change_password", True):
        return "active"
    expires = v.get(f"{prefix}_temp_password_expires")
    if expires and datetime.utcnow() > expires:
        return "expired"
    return "awaiting"


@app.get("/superadmin/it-admins")
async def list_it_admins(request: Request):
    result = []
    async for v in tdb(request).voters.find(
        {"is_it_admin": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "it_admin_email": 1, "it_admin_export_mode": 1,
         "it_admin_password_hash": 1, "it_admin_must_change_password": 1, "it_admin_temp_password_expires": 1}
    ):
        v["it_admin_export_mode"] = normalize_export_mode(v.get("it_admin_export_mode"))
        v["login_state"] = _login_state(v, "it_admin")
        for k in ("it_admin_password_hash", "it_admin_must_change_password", "it_admin_temp_password_expires"):
            v.pop(k, None)
        result.append(v)
    return result


@app.post("/superadmin/it-admins/{student_id:path}/toggle")
async def toggle_it_admin(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_it_admin", False)
    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_it_admin": new_val, **(await _invalidate_sessions(voter["_id"]))},
         "$unset": {"it_admin_export_mode": "", "it_admin_export_mode_set_by": "", "it_admin_export_mode_set_at": ""}}
    )
    await log_action("it_admin_toggled", current_actor(request), {
        "student_id": student_id, "is_it_admin": new_val
    }, org_id=request.state.org_id)

    return {"student_id": student_id, "is_it_admin": new_val}


# ── IT admin voter-register export ───────────────────────────────────────────
EXPORT_MODES = ("none", "redacted", "full")
EXPORT_MAX_ROWS = int(os.getenv("VOTER_EXPORT_MAX_ROWS", "50000"))
EXPORT_RATE_LIMIT = 6
EXPORT_RATE_WINDOW_S = 600
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")   # spreadsheet formula-injection triggers


def normalize_export_mode(raw) -> str:
    """Fail closed: anything other than exactly 'redacted' or 'full' is 'none'."""
    return raw if raw in ("redacted", "full") else "none"


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection: a cell that would be read as a formula gets a leading '."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def _export_row(v: dict, mode: str, enabled_fields: list[dict], max_phones: int) -> list[str]:
    if mode not in ("redacted", "full"):          # explicit raise, not assert (asserts vanish under python -O)
        raise ValueError("export mode must be redacted or full")
    phones = [str(p) for p in (v.get("phone_numbers") or [])]
    if mode == "redacted":
        phones = [_mask_phone(p) for p in phones]   # SAME function the on-screen list uses
    phones += [""] * (max_phones - len(phones))
    attrs = v.get("attrs") or {}
    return [str(v.get("student_id", "")).upper(), v.get("full_name", "") or "", *phones,
            *[attrs.get(f["key"], "") for f in enabled_fields]]


async def _it_admin_export_mode(request: Request, admin: dict) -> str:
    """Read the caller's mode from the DB on EVERY call. Never from the JWT, never cached."""
    doc = await tdb(request).voters.find_one(
        {"student_id": admin.get("sub"), "is_it_admin": True},
        {"_id": 0, "it_admin_export_mode": 1})
    return normalize_export_mode((doc or {}).get("it_admin_export_mode"))


class ExportModeUpdate(BaseModel):
    mode: str


@app.put("/superadmin/it-admins/{student_id:path}/export-mode")
async def set_it_admin_export_mode(student_id: str, data: ExportModeUpdate, request: Request,
                                   admin: dict = Depends(require_role("superadmin"))):
    if data.mode not in EXPORT_MODES:
        raise HTTPException(400, "Mode must be none, redacted or full.")
    voter = await tdb(request).voters.find_one({**get_forgiving_filter(student_id), "is_it_admin": True})
    if not voter:
        raise HTTPException(404, "That person is not an IT admin.")
    old = normalize_export_mode(voter.get("it_admin_export_mode"))
    if data.mode == old:
        return {"student_id": voter["student_id"], "it_admin_export_mode": old, "changed": False}
    await tdb(request).voters.update_one({"_id": voter["_id"]}, {"$set": {
        "it_admin_export_mode": data.mode,
        "it_admin_export_mode_set_by": current_actor(request),
        "it_admin_export_mode_set_at": datetime.utcnow()}})
    await log_action("it_admin_export_mode_changed", current_actor(request),
                     {"student_id": voter["student_id"], "old": old, "new": data.mode},
                     org_id=request.state.org_id)
    return {"student_id": voter["student_id"], "it_admin_export_mode": data.mode, "changed": True}


@app.get("/admin/voters/export/permission")
async def voter_export_permission(request: Request, admin: dict = Depends(require_role("it_admin"))):
    mode = await _it_admin_export_mode(request, admin)
    return {"mode": mode, "formats": ["xlsx", "csv"] if mode != "none" else [], "max_rows": EXPORT_MAX_ROWS}


class VoterExportRequest(BaseModel):
    format: str = "xlsx"


@app.post("/admin/voters/export")
async def export_voter_register(data: VoterExportRequest, request: Request,
                                admin: dict = Depends(require_role("it_admin"))):
    org_id, actor = request.state.org_id, current_actor(request)
    fmt = (data.format or "").strip().lower()
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(400, "Format must be csv or xlsx.")

    mode = await _it_admin_export_mode(request, admin)           # fresh DB read, every call
    if mode == "none":
        await log_action("voter_register_export_denied", actor, {"reason": "mode_none"}, org_id=org_id)
        raise HTTPException(403, "Voter register export is not enabled for your account. Ask the superadmin to enable it.")

    await _check_rate_limit(request, bucket=f"voter_export:{actor}", limit=EXPORT_RATE_LIMIT,
                            window_s=EXPORT_RATE_WINDOW_S,
                            message="Too many exports. Please wait a few minutes and try again.")

    query = org_query(request)                                   # tenant scope: mandatory
    if await tdb(request).voters.count_documents(query) > EXPORT_MAX_ROWS:
        await log_action("voter_register_export_denied", actor, {"reason": "too_many_rows"}, org_id=org_id)
        raise HTTPException(413, f"The register is larger than the {EXPORT_MAX_ROWS:,}-row export limit.")

    fields = await get_voter_fields(request)
    enabled = [f for f in fields["fields"] if f.get("enabled")]
    projection = {"_id": 0, "full_name": 1, "student_id": 1, "phone_numbers": 1, "attrs": 1}   # allowlist
    voters = [v async for v in tdb(request).voters.find(query, projection).sort([("full_name", 1), ("student_id", 1)])]

    max_phones = max([1] + [len(v.get("phone_numbers") or []) for v in voters])
    _b = await cached_setting(org_id, "branding") or {}
    id_header = (_b.get("id_label") or "").strip() or "Registration Number"   # the org's own name for the ID
    header = [id_header, "Full Name", *[f"Phone {i}" for i in range(1, max_phones + 1)],
              *[f["label"] for f in enabled]]
    rows = [_export_row(v, mode, enabled, max_phones) for v in voters]

    if fmt == "csv":
        buf = io.StringIO(newline="")
        w = csv.writer(buf)
        w.writerow([_csv_safe(h) for h in header])
        for r in rows:
            w.writerow([_csv_safe(c) for c in r])
        body = buf.getvalue().encode("utf-8-sig")                # BOM so Excel reads UTF-8 names correctly
        media = "text/csv; charset=utf-8"
    else:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Voter register")

        def _text_row(values):
            cells = []
            for x in values:
                c = WriteOnlyCell(ws, value="" if x is None else str(x))
                c.data_type = "s"                                # force TEXT: never a formula, never a number
                cells.append(c)
            return cells
        ws.append(_text_row(header))
        for r in rows:
            ws.append(_text_row(r))
        bio = io.BytesIO()
        wb.save(bio)
        body = bio.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Audit BEFORE releasing data. No names/phones/reg numbers/search text: this log is readable by every admin role.
    await log_action("voter_register_export", actor, {"mode": mode, "format": fmt, "rows": len(rows)}, org_id=org_id)

    slug = re.sub(r"[^a-z0-9-]", "", (getattr(request.state, "org_slug", "") or "org").lower()) or "org"
    filename = f"voter-register-{slug}-{mode}-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.{fmt}"
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Export-Mode": mode, "X-Export-Rows": str(len(rows)),
    })


@app.post("/superadmin/commissioners/{student_id:path}/set-credentials")
async def set_commissioner_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "commissioner_email":                data.email,
            "commissioner_password_hash":        hashed,
            "commissioner_must_change_password": True,
            "commissioner_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Commissioner", temp_password)
    await log_action("commissioner_credentials_set", current_actor(request), {
        "student_id": student_id, "email": data.email, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "credentials_set", "sms_notified": sms_sent}



# =============================================================================
# SUPERADMIN — VETTING PANEL MANAGEMENT (guide P1)
# =============================================================================
# Panel members are separate from voters. Only the superadmin creates or removes
# them. Externals (is_member False) have no voter row and can never vote.

def _panel_public(p: dict) -> dict:
    """Shape a panel record for the API. Never returns hashes or temp passwords."""
    return {
        "panel_member_id": p.get("panel_member_id"),
        "full_name":       p.get("full_name", ""),
        "email":           p.get("email", ""),
        "is_member":       p.get("is_member", False),
        "student_id":      p.get("student_id"),
        "affiliation":     p.get("affiliation", ""),
        "appointment_reason": p.get("appointment_reason", ""),
        "active":          p.get("active", False),
        "access_expires_at": iso_utc(p.get("access_expires_at")),
        "expires_with_phase": p.get("expires_with_phase"),
        "confidentiality_accepted_at": (p["confidentiality_accepted_at"].isoformat()
                                        if p.get("confidentiality_accepted_at") else None),
    }


async def _panel_open_guard(request: Request):
    """Guide 7 item 4: the panel is frozen while the vetting window is open, so
    thresholds cannot move under people mid-vote. Changes are allowed before it
    opens and after it closes."""
    schedule = await get_phase_schedule(request)
    window = schedule["phases"].get("vetting", {})
    # _phase_is_open treats an UNENFORCED phase as open (it never blocks). For the freeze we
    # need the opposite: only an enforced window that is currently inside its dates freezes
    # the panel. An org that never set a timeline must still be able to appoint panelists.
    if window.get("enforced") and _phase_is_open(window, datetime.utcnow()):
        raise HTTPException(409, "The Vetting Panel is frozen while vetting is open. "
                                 "Changes are allowed before it opens and after it closes.")


@app.get("/superadmin/vetting-panel")
async def superadmin_list_panel(request: Request):
    raw = [p async for p in tdb(request).panel_members.find(
        {}, {"_id": 0, "password_hash": 0, "temp_password_expires": 0})]
    rows = []
    for p in raw:
        row = _panel_public(p)
        # The real end, resolved live from the timeline (earlier of fixed date and phase end).
        row["access_ends_at"] = iso_utc(await _panel_access_end(request, p))
        rows.append(row)
    sched = await get_phase_schedule(request)
    phase_schedule = {n: {"start": iso_utc(w.get("start")), "end": iso_utc(w.get("end")),
                          "enforced": bool(w.get("enforced"))} for n, w in sched["phases"].items()}
    active_rows = [r for r in rows if r["active"]]
    panel_count = len(active_rows)
    # Guide 7.2 tie_risk: ties only happen on an even panel; the Chair (live check) can break them.
    chair_active = False
    for r in rows:
        r["is_chair"] = False
        if r.get("student_id") and await tdb(request).voters.find_one({
                **get_forgiving_filter(r["student_id"]), "is_chief_commissioner": True}):
            r["is_chair"] = True
            if r["active"]:
                chair_active = True
    if panel_count % 2 == 1:
        tie_risk = "none"
    elif chair_active:
        tie_risk = "chair_resolves"
    else:
        tie_risk = "superadmin_only"
    frozen = False
    try:
        await _panel_open_guard(request)
    except HTTPException:
        frozen = True
    return {"panel": rows, "count": panel_count, "panel_count": panel_count, "tie_risk": tie_risk,
            "frozen": frozen, "min_panel": 3, "phase_schedule": phase_schedule,
            "timezone": sched["timezone"]}


@app.post("/superadmin/vetting-panel")
async def superadmin_add_panelist(data: PanelMemberCreate, request: Request, background_tasks: BackgroundTasks):
    await _panel_open_guard(request)

    if not data.appointment_reason.strip():
        raise HTTPException(400, "An appointment reason is required.")
    if not data.full_name.strip() or not data.email.strip() or not data.phone.strip():
        raise HTTPException(400, "Name, email and phone are required.")
    if data.is_member and not data.student_id:
        raise HTTPException(400, "A member panelist must be linked to a student_id.")
    if not data.is_member and not (data.access_expires_at or data.expires_with_phase):
        raise HTTPException(400, "An external panelist needs an access end: a date or a timeline phase.")
    if data.expires_with_phase and data.expires_with_phase not in PHASE_NAMES:
        raise HTTPException(400, "Unknown timeline phase for access expiry.")

    email = data.email.strip().lower()
    conflict = await _panel_email_conflict(request, email)
    if conflict:
        raise HTTPException(409, conflict)
    if not data.is_member and not data.access_expires_at and data.expires_with_phase:
        phase_end = (await get_phase_schedule(request))["phases"].get(data.expires_with_phase, {}).get("end")
        if not phase_end:
            raise HTTPException(400, "That timeline phase has no end date yet, so it cannot close an external's "
                                     "access. Set a fixed access end, or schedule the phase first.")

    if data.is_member:
        voter = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
        if not voter:
            raise HTTPException(404, "Member not found on the voter roll.")
        if await _has_live_application(request, voter["student_id"]):
            raise HTTPException(409, "This member has an application in progress and cannot sit on the Vetting Panel.")
        # A second record for the same person would count twice in the approval denominator (get_panel_count)
        # but vote under one key (_panel_vote_key), so unanimous / majority-of-cast outcomes could never be
        # reached. link-commissioner already refuses this; the direct-login route must too.
        if await tdb(request).panel_members.find_one({
                "student_id": normalize_student_id(voter["student_id"])}, {"_id": 1}):
            raise HTTPException(409, "This member is already on the panel list. Edit, re-issue credentials for, "
                                     "or activate the existing record instead of adding another.")

    panel_member_id = f"PM-{secrets.token_hex(6).upper()}"
    temp_password = generate_temp_password()
    now = datetime.utcnow()
    doc = {
        "org_id":            request.state.org_id,
        "panel_member_id":   panel_member_id,
        "full_name":         data.full_name.strip(),
        "email":             email,
        "phone_numbers":     [data.phone.strip()],
        "is_member":         data.is_member,
        "appointment_reason": data.appointment_reason.strip(),
        "affiliation":       data.affiliation.strip(),
        "student_id":        normalize_student_id(data.student_id) if data.is_member else None,
        # The frontend sends toISOString() ("...Z"), which pydantic parses as an AWARE datetime; everything
        # else here compares against naive utcnow(), so store it naive (as the schedule routes already do).
        "access_expires_at": naive_utc(data.access_expires_at),
        "expires_with_phase": data.expires_with_phase,
        "confidentiality_accepted_at": None,
        "confidentiality_version": None,
        "active":            True,
        "password_hash":     hash_password(temp_password),
        "must_change_password": True,
        "temp_password_expires": now + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
        "added_by":          current_actor(request),
        "added_at":          now,
        "removed_at":        None,
    }
    await tdb(request).panel_members.insert_one(doc)
    background_tasks.add_task(_safe_resweep, request.state.org_id, include_removals=False)
    sms_sent = await send_temp_password_sms(
        {"phone_numbers": doc["phone_numbers"], "full_name": doc["full_name"],
         "org_id": doc["org_id"]}, "Vetting Panel", temp_password)
    await log_action("vetting_panel_member_added", current_actor(request), {
        "panel_member_id": panel_member_id, "is_member": data.is_member,
        "reason": doc["appointment_reason"], "sms_notified": sms_sent,
    }, org_id=request.state.org_id)
    return {"status": "added", "panel_member_id": panel_member_id, "sms_notified": sms_sent}


@app.post("/superadmin/vetting-panel/link-commissioner")
async def superadmin_link_commissioner(data: PanelCommissionerLink, request: Request, background_tasks: BackgroundTasks):
    """Guide 5.2: any admin (commissioner, IT admin, overseer or financial controller) sits on the panel as
    an extension of their own screens. The record is linked by student_id and carries NO password and NO
    email, so nothing is texted and there is nothing to log in with: they reach the panel through
    /admin/switch-hat from their own dashboard. The appointment reason is required and goes into the
    audit trail like any other appointment. (Route name kept for compatibility.)"""
    await _panel_open_guard(request)
    reason = data.appointment_reason.strip()
    if not reason:
        raise HTTPException(400, "An appointment reason is required.")
    voter = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    held = _held_hat_roles(voter)
    if not held:
        raise HTTPException(404, "That person does not hold an admin role.")
    sid = normalize_student_id(voter["student_id"])
    existing = await tdb(request).panel_members.find_one({"student_id": sid})
    if existing:
        raise HTTPException(409, "This person is already on the panel list."
                                 + ("" if existing.get("active") else " They are inactive: use Activate."))
    if await _has_live_application(request, voter["student_id"]):
        raise HTTPException(409, "This member has an application in progress and cannot sit on the Vetting Panel.")

    panel_member_id = f"PM-{secrets.token_hex(6).upper()}"
    now = datetime.utcnow()
    await tdb(request).panel_members.insert_one({
        "org_id":            request.state.org_id,
        "panel_member_id":   panel_member_id,
        "full_name":         voter.get("full_name", ""),
        "email":             "",
        "phone_numbers":     voter.get("phone_numbers", []),
        "is_member":         True,
        "appointment_reason": reason,
        "affiliation":       "",
        "student_id":        sid,
        "access_expires_at": None,
        "expires_with_phase": None,
        "confidentiality_accepted_at": None,
        "confidentiality_version": None,
        "active":            True,
        "password_hash":     "",          # no direct login: verify_password() rejects an empty hash
        "must_change_password": True,
        "temp_password_expires": None,
        "added_by":          current_actor(request),
        "added_at":          now,
        "removed_at":        None,
    })
    background_tasks.add_task(_safe_resweep, request.state.org_id, include_removals=False)
    await log_action("vetting_panel_member_added", current_actor(request), {
        "panel_member_id": panel_member_id, "is_member": True, "linked_commissioner": True, "linked_roles": held,
        "reason": reason, "sms_notified": False,
    }, org_id=request.state.org_id)
    return {"status": "added", "panel_member_id": panel_member_id, "sms_notified": False}


@app.patch("/superadmin/vetting-panel/{panel_member_id}")
async def superadmin_update_panelist(panel_member_id: str, data: PanelMemberUpdate, request: Request):
    p = await tdb(request).panel_members.find_one({"panel_member_id": panel_member_id})
    if not p:
        raise HTTPException(404, "Panel member not found.")
    update: dict = {}
    if data.affiliation is not None:
        update["affiliation"] = data.affiliation.strip()
    if data.phone is not None:
        if not data.phone.strip():
            raise HTTPException(400, "Phone cannot be empty.")
        update["phone_numbers"] = [data.phone.strip()]
    if data.expires_with_phase and data.expires_with_phase not in PHASE_NAMES:
        raise HTTPException(400, "Unknown timeline phase for access expiry.")
    end_touched = data.access_expires_at is not None or data.expires_with_phase is not None or data.clear_access_end
    if end_touched:
        # Aware (the browser sends "...Z") -> naive UTC. Without this, the `new_at > old` comparison in the
        # freeze branch below raises TypeError (aware vs naive) and the request fails with HTTP 500.
        new_at = naive_utc(data.access_expires_at)
        new_phase = data.expires_with_phase
        if data.clear_access_end:
            new_at, new_phase = None, None
        elif new_at is not None and new_phase is None:
            new_phase = None          # a fixed date replaces a phase-based end
        elif new_phase is not None and new_at is None:
            new_at = None             # and the other way round
        if not p.get("is_member") and not (new_at or new_phase):
            raise HTTPException(400, "An external panelist needs an access end: a date or a timeline phase.")
        # Same rule as creation (SEC-08): a phase-only end for an external must resolve to a real end date,
        # otherwise nothing would ever close the account and new logins would be refused.
        if new_phase and not new_at and not p.get("is_member"):
            phase_end = (await get_phase_schedule(request))["phases"].get(new_phase, {}).get("end")
            if not phase_end:
                raise HTTPException(400, "That timeline phase has no end date yet, so it cannot close an external's "
                                         "access. Set a fixed access end, or schedule the phase first.")
        update["access_expires_at"] = new_at
        update["expires_with_phase"] = new_phase
        # The panel is frozen while vetting is open. The one change allowed then is giving a
        # panelist MORE time (a later fixed date); shortening or switching could change who counts.
        try:
            await _panel_open_guard(request)
        except HTTPException:
            old = await _panel_access_end(request, p)
            if new_phase and not new_at:
                new_end = naive_utc((await get_phase_schedule(request))["phases"].get(new_phase, {}).get("end"))
            else:
                new_end = new_at
            if not (new_end and old and new_end > old):
                raise
    if not update:
        raise HTTPException(400, "Nothing to change.")
    await tdb(request).panel_members.update_one({"_id": p["_id"]}, {"$set": update})
    await log_action("vetting_panel_member_updated", current_actor(request), {
        "panel_member_id": panel_member_id, "fields": sorted(update.keys())}, org_id=request.state.org_id)
    return {"status": "updated", "panel_member_id": panel_member_id}


@app.post("/superadmin/vetting-panel/{panel_member_id}/set-credentials")
async def superadmin_panel_set_credentials(panel_member_id: str, data: PanelMemberCredentials, request: Request):
    p = await tdb(request).panel_members.find_one({"panel_member_id": panel_member_id})
    if not p:
        raise HTTPException(404, "Panel member not found.")
    temp_password = generate_temp_password()
    email = data.email.strip().lower()
    if not email:
        raise HTTPException(400, "An email is required.")
    conflict = await _panel_email_conflict(request, email, exclude_pm_id=p["panel_member_id"])
    if conflict:
        raise HTTPException(409, conflict)
    await tdb(request).panel_members.update_one({"_id": p["_id"]}, {"$set": {
        "email": email,
        "password_hash": hash_password(temp_password),
        "must_change_password": True,
        "temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
        **(await _invalidate_sessions(p["_id"])),
    }})
    sms_sent = await send_temp_password_sms(p, "Vetting Panel", temp_password)
    await log_action("vetting_panel_credentials_set", current_actor(request), {
        "panel_member_id": panel_member_id, "sms_notified": sms_sent}, org_id=request.state.org_id)
    return {"status": "credentials_set", "sms_notified": sms_sent}


@app.post("/superadmin/vetting-panel/{panel_member_id}/active")
async def superadmin_panel_set_active(panel_member_id: str, request: Request, background_tasks: BackgroundTasks, active: bool = True):
    await _panel_open_guard(request)
    p = await tdb(request).panel_members.find_one({"panel_member_id": panel_member_id})
    if not p:
        raise HTTPException(404, "Panel member not found.")
    if active and p.get("student_id") and await _has_live_application(request, p["student_id"]):
        raise HTTPException(409, "This member has an application in progress and cannot be activated on the Vetting Panel.")
    if not active and p.get("active"):
        # Guide 7 item 6: never let the active panel drop below 3.
        remaining = await tdb(request).panel_members.count_documents({
            "active": True, "panel_member_id": {"$ne": panel_member_id}})
        if remaining < 3:
            raise HTTPException(409, "The Vetting Panel must keep at least 3 active panelists.")
    update = {"active": active, **(await _invalidate_sessions(p["_id"]))}
    # Stamp the removal on deactivation; clear it on re-activation so a live panelist never carries a stale date.
    update["removed_at"] = None if active else datetime.utcnow()
    await tdb(request).panel_members.update_one({"_id": p["_id"]}, {"$set": update})
    background_tasks.add_task(_safe_resweep, request.state.org_id, include_removals=False)
    await log_action("vetting_panel_member_" + ("activated" if active else "deactivated"),
                     current_actor(request), {"panel_member_id": panel_member_id},
                     org_id=request.state.org_id)
    return {"status": "active" if active else "inactive", "panel_member_id": panel_member_id}


# =============================================================================
# ADMIN — HAT SWITCH (guide 5.2)
# =============================================================================
# Any admin linked to an ACTIVE panel member can switch to the panel view and back. One token has one
# role, so switching issues a new token and revokes the old one. The panel token remembers which role
# it came from (hat_role) so "switch back" returns each person to their own screen.
# Overseer: while serving on the panel the overseer role is PAUSED (see auth_guard_middleware), so an
# overseer never oversees their own votes. Financial controller: deliberately no extra rule.

HAT_ROLE_FLAGS = {"commission": "is_commissioner", "it_admin": "is_it_admin",
                  "financial_controller": "is_financial_controller", "overseer": "is_overseer"}
HAT_ROLE_LABELS = {"commission": "Commissioner", "it_admin": "IT Admin",
                   "financial_controller": "Financial Controller", "overseer": "Overseer"}
HAT_ROLES = tuple(HAT_ROLE_FLAGS)


def _held_hat_roles(voter: dict | None) -> list[str]:
    return [r for r, f in HAT_ROLE_FLAGS.items() if voter and voter.get(f)]


async def _active_panel_record(request: Request, student_id) -> dict | None:
    """The person's ACTIVE panel record whose access has not ended, or None."""
    if not student_id:
        return None
    panelist = await tdb(request).panel_members.find_one({
        "student_id": normalize_student_id(student_id), "active": True})
    if not panelist or await _panel_access_ended(request, panelist):
        return None
    return panelist


@app.post("/admin/switch-hat")
async def switch_hat(request: Request, admin: dict = Depends(require_role(*HAT_ROLES, "vetting"))):
    org_id = require_org(request.state.org_id)
    if admin["role"] in HAT_ROLE_FLAGS:
        origin = admin["role"]
        student_id = admin.get("sub")
        voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
        if not voter or not voter.get(HAT_ROLE_FLAGS[origin]):
            raise HTTPException(403, f"Not a {HAT_ROLE_LABELS[origin].lower()}.")
        panelist = await tdb(request).panel_members.find_one({
            "student_id": normalize_student_id(student_id), "active": True})
        if not panelist:
            raise HTTPException(403, "You are not on the Vetting Panel.")
        if await _panel_access_ended(request, panelist):
            raise HTTPException(403, "Your panel access has ended.")
        new_token = create_access_token(
            subject=panelist["panel_member_id"], role="vetting", org_id=org_id,
            full_name=panelist.get("full_name", ""), scope="full",
            extra_claims={"via_hat": True, "hat_role": origin})
        # The origin token's jti is what gets revoked; the old token then stops working.
        await db.revoked_tokens.insert_one({"jti": admin.get("jti"), "revoked_at": datetime.utcnow()})
        await log_action("hat_switched", student_id, {
            "from": origin, "to": "vetting", "panel_member_id": panelist["panel_member_id"]}, org_id=org_id)
        return {"status": "switched", "role": "vetting", "access_token": new_token,
                "back_to": origin, "back_label": HAT_ROLE_LABELS[origin]}

    # role == vetting: switch back to the role the session came from.
    # Only a session that began as an admin login may return to it. A panelist who signed in directly
    # with panel credentials has not proven an admin password, so no admin token is issued.
    if not admin.get("via_hat"):
        raise HTTPException(403, "Sign in with your admin account to open that view.")
    origin = admin.get("hat_role") or "commission"   # tokens issued before hat_role existed were commissioners
    if origin not in HAT_ROLE_FLAGS:
        raise HTTPException(403, "Only a linked admin can switch back.")
    if origin == "overseer":
        # Overseer access stays paused for as long as they serve; ending the service (or their
        # panel access) ends this session, and a fresh overseer login works again.
        raise HTTPException(403, "Overseer access is paused while you serve on the Vetting Panel.")
    panel = await tdb(request).panel_members.find_one({
        "panel_member_id": admin.get("sub"), "active": True})
    if not panel or not panel.get("student_id"):
        raise HTTPException(403, "Only a linked admin can switch back.")
    voter = await tdb(request).voters.find_one(get_forgiving_filter(panel["student_id"]))
    if not voter or not voter.get(HAT_ROLE_FLAGS[origin]):
        raise HTTPException(403, "You no longer hold that role.")
    new_token = create_access_token(
        subject=voter["student_id"], role=origin, org_id=org_id,
        full_name=voter.get("full_name", ""), scope="full")
    await db.revoked_tokens.insert_one({"jti": admin.get("jti"), "revoked_at": datetime.utcnow()})
    await log_action("hat_switched", voter["student_id"], {
        "from": "vetting", "to": origin}, org_id=org_id)
    return {"status": "switched", "role": origin, "access_token": new_token}


@app.get("/admin/panel-link")
async def panel_link(request: Request, admin: dict = Depends(require_role(*HAT_ROLES))):
    """Whether the signed-in admin can switch to the Vetting Panel. Answers only for the
    caller (never lists who is on the panel), so the dashboard can hide the switch button."""
    panelist = await _active_panel_record(request, admin.get("sub"))
    linked = bool(panelist)
    # Guide 7.2: tell the Chairperson (and only them) when a tie is waiting for their decision,
    # so they know to switch to the panel view. Only a count; no votes or names.
    tie_waiting = 0
    if linked and admin["role"] == "commission":
        chair = await tdb(request).voters.find_one({
            **get_forgiving_filter(admin.get("sub")), "is_chief_commissioner": True}, {"_id": 1})
        if chair:
            tie_waiting = await tdb(request).applications.count_documents({
                "tied_pending_chief": True, "status": {"$nin": list(RESOLVED_STATUSES)}})
    return {"panel_linked": linked, "tie_waiting": tie_waiting,
            "overseer_paused": linked and admin["role"] == "overseer"}


# =============================================================================
# SUPERADMIN — FINANCIAL CONTROLLER MANAGEMENT (student register approvals)
# =============================================================================

@app.get("/superadmin/financial-controllers")
async def list_financial_controllers(request: Request):
    result = []
    async for v in tdb(request).voters.find(
        {"is_financial_controller": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "financial_controller_email": 1}
    ):
        result.append(v)
    return result


@app.post("/superadmin/financial-controllers/{student_id:path}/toggle")
async def toggle_financial_controller(student_id: str, request: Request):
    """Grant or revoke Financial Controller status. The Financial Controller clears voter-register
    payments AND candidate payments. It may be held together with the commissioner role: the two
    portals and logins stay separate."""
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_financial_controller", False)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_financial_controller": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("financial_controller_toggled", current_actor(request), {
        "student_id": student_id, "is_financial_controller": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_financial_controller": new_val}


@app.post("/superadmin/financial-controllers/{student_id:path}/set-credentials")
async def set_financial_controller_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_financial_controller"):
        raise HTTPException(400, "This person is not a Financial Controller.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "financial_controller_email":                data.email,
            "financial_controller_password_hash":        hashed,
            "financial_controller_must_change_password": True,
            "financial_controller_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Financial Controller", temp_password)
    await log_action("financial_controller_credentials_set", current_actor(request), {
        "student_id": student_id, "email": data.email, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "credentials_set", "sms_notified": sms_sent}


@app.post("/superadmin/financial-controllers/{student_id:path}/reset-password")
async def reset_financial_controller_password(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter or not voter.get("is_financial_controller"):
        raise HTTPException(404, "Financial Controller not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "financial_controller_password_hash":        hashed,
            "financial_controller_must_change_password": True,
            "financial_controller_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Financial Controller", temp_password)
    await log_action("financial_controller_password_reset", current_actor(request), {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}


# =============================================================================
# SUPERADMIN — OVERSEER MANAGEMENT (read-only, anonymized platform view)
# =============================================================================

@app.get("/superadmin/overseers")
async def list_overseers(request: Request):
    result = []
    async for v in tdb(request).voters.find(
        {"is_overseer": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "overseer_email": 1,
         "overseer_password_hash": 1, "overseer_must_change_password": 1, "overseer_temp_password_expires": 1}
    ):
        v["login_state"] = _login_state(v, "overseer")
        for k in ("overseer_password_hash", "overseer_must_change_password", "overseer_temp_password_expires"):
            v.pop(k, None)
        result.append(v)
    return result


@app.post("/superadmin/overseers/{student_id:path}/toggle")
async def toggle_overseer(student_id: str, request: Request):
    """Grant or revoke Overseer status for any voter. Read-only role — never
    touches votes, applications, or student changes, only observes them."""
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_overseer", False)
    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_overseer": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("overseer_toggled", current_actor(request), {
        "student_id": student_id, "is_overseer": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_overseer": new_val}


@app.post("/superadmin/overseers/{student_id:path}/set-credentials")
async def set_overseer_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_overseer"):
        raise HTTPException(400, "This person is not an Overseer.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "overseer_email":                data.email,
            "overseer_password_hash":        hashed,
            "overseer_must_change_password": True,
            "overseer_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Overseer", temp_password)
    await log_action("overseer_credentials_set", current_actor(request), {
        "student_id": student_id, "email": data.email, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "credentials_set", "sms_notified": sms_sent}


@app.post("/superadmin/overseers/{student_id:path}/reset-password")
async def reset_overseer_password(student_id: str, request: Request):
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter or not voter.get("is_overseer"):
        raise HTTPException(404, "Overseer not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await tdb(request).voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {
            "overseer_password_hash":        hashed,
            "overseer_must_change_password": True,
            "overseer_temp_password_expires": datetime.utcnow() + timedelta(hours=TEMP_PASSWORD_EXPIRE_HOURS),
            **(await _invalidate_sessions(voter["_id"])),
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Overseer", temp_password)
    await log_action("overseer_password_reset", current_actor(request), {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}


@app.get("/superadmin/student-changes")
async def superadmin_list_student_changes(request: Request, status: str = None):
    if (await roster_status(request))["frozen"]:
        await _expire_pending_at_freeze(request)
    # Superadmin sees ALL including cancelled
    query = org_query(request)
    if status:
        query["status"] = status
    changes = []
    async for c in tdb(request).student_changes.find(query).sort("requested_at", -1):
        c["_id"] = str(c["_id"])
        changes.append(c)
    return changes


@app.post("/superadmin/student-changes/{change_id}/force-approve")
async def superadmin_force_student_change_approve(change_id: str, request: Request):
    await assert_roster_unfrozen(request)
    oid = parse_oid(change_id, "change id")
    change = await tdb(request).student_changes.find_one({"_id": oid})
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("approved", "force_approved"):
        raise HTTPException(400, "Already approved.")
    if change.get("status") == "cancelled":
        raise HTTPException(400, "Cannot approve a cancelled request.")

    # Atomic guard: only proceed if this call is the one that actually
    # claims the request out of every non-final status — prevents a
    # superadmin force-approve from racing a Financial Controller decision
    # (or a duplicate click) into executing the change twice.
    result = await tdb(request).student_changes.update_one(
        {
            "_id": oid,
            "status": {"$nin": ["approved", "force_approved", "denied", "force_denied", "cancelled"]},
        },
        {"$set": {
            "status":               "force_approved",
            "superadmin_override":  True,
            "resolved_at":          datetime.utcnow()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This request was just resolved by someone else. Please refresh.")
    await _execute_student_change(change, request.state.org_id)
    await log_action("student_change_force_approved", current_actor(request), {
        "change_type":  change["change_type"],
        "student_id":   change["student_id"],
        "requested_by": change.get("requested_by", "")
    }, org_id=request.state.org_id)
    return {"status": "force_approved"}


@app.post("/superadmin/student-changes/{change_id}/force-deny")
async def superadmin_force_student_change_deny(change_id: str, request: Request):
    await assert_roster_unfrozen(request)
    oid = parse_oid(change_id, "change id")
    change = await tdb(request).student_changes.find_one({"_id": oid})
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("denied", "force_denied", "cancelled"):
        raise HTTPException(400, f"Request is already {change.get('status')}.")

    result = await tdb(request).student_changes.update_one(
        {
            "_id": oid,
            "status": {"$nin": ["approved", "force_approved", "denied", "force_denied", "cancelled"]},
        },
        {"$set": {
            "status":               "force_denied",
            "superadmin_override":  True,
            "resolved_at":          datetime.utcnow()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This request was just resolved by someone else. Please refresh.")
    await log_action("student_change_force_denied", current_actor(request), {
        "change_type":  change["change_type"],
        "student_id":   change["student_id"],
        "requested_by": change.get("requested_by", "")
    }, org_id=request.state.org_id)
    return {"status": "force_denied"}


# =============================================================================
# VIEW AS  (superadmin: read-only window into another admin's interface)
# =============================================================================
# Mints a short-lived token carrying the target admin's role + id and view_only=True. The frontend
# opens it in a separate tab, so the real dashboard renders with the real data. The auth guard
# rejects every non-GET request for such a token, and it cannot reach /superadmin routes because
# its role is the target's, not superadmin. Each session is audit-logged with who viewed whom.

VIEW_AS_MINUTES = int(os.getenv("VIEW_AS_MINUTES", "30"))
VIEW_AS_ROLE_FLAGS = {"it_admin": "is_it_admin", "commission": "is_commissioner",
                      "financial_controller": "is_financial_controller", "overseer": "is_overseer"}


class ViewAsRequest(BaseModel):
    student_id: str
    role: str


@app.post("/superadmin/view-as")
async def superadmin_view_as(data: ViewAsRequest, request: Request,
                             admin: dict = Depends(require_role("superadmin"))):
    if data.role == "vetting":
        # Panelists live in panel_members and are keyed by panel_member_id (guide 6.3), so the
        # `student_id` field carries that id for this role. Read-only like every view-as token.
        p = await tdb(request).panel_members.find_one({
            "panel_member_id": data.student_id, "active": True})
        if not p:
            raise HTTPException(404, "That person is not an active member of the Vetting Panel.")
        if await _panel_access_ended(request, p):
            raise HTTPException(409, "This panelist's access has ended.")
        token = create_access_token(
            subject=p["panel_member_id"], role="vetting", org_id=request.state.org_id,
            full_name=p.get("full_name", ""), scope="full", expire_minutes=VIEW_AS_MINUTES,
            extra_claims={"view_only": True, "viewer": current_actor(request)})
        await log_action("admin_view_as_started", current_actor(request), {
            "target": p["panel_member_id"], "target_name": p.get("full_name", ""),
            "role": "vetting", "minutes": VIEW_AS_MINUTES}, org_id=request.state.org_id)
        return {"access_token": token, "role": "vetting", "student_id": p["panel_member_id"],
                "full_name": p.get("full_name", ""), "org_slug": request.state.org_slug or "",
                "expires_in_minutes": VIEW_AS_MINUTES}
    flag = VIEW_AS_ROLE_FLAGS.get(data.role)
    if not flag:
        raise HTTPException(400, "Unknown admin role.")
    voter = await tdb(request).voters.find_one({**get_forgiving_filter(data.student_id), flag: True})
    if not voter:
        raise HTTPException(404, "That person does not currently hold this admin role.")
    token = create_access_token(
        subject=voter["student_id"], role=data.role, org_id=request.state.org_id,
        full_name=voter.get("full_name", ""), scope="full", expire_minutes=VIEW_AS_MINUTES,
        extra_claims={"view_only": True, "viewer": current_actor(request)})
    await log_action("admin_view_as_started", current_actor(request), {
        "target": voter["student_id"], "target_name": voter.get("full_name", ""),
        "role": data.role, "minutes": VIEW_AS_MINUTES}, org_id=request.state.org_id)
    return {"access_token": token, "role": data.role, "student_id": voter["student_id"],
            "full_name": voter.get("full_name", ""), "org_slug": request.state.org_slug or "",
            "expires_in_minutes": VIEW_AS_MINUTES}


@app.post("/superadmin/students/add")
async def superadmin_add_student(data: ITAdminStudentAdd, request: Request):
    await assert_roster_unfrozen(request)
    data.full_name = normalize_name(data.full_name)
    # Must match the canonical stored form: every lookup (login, search, votes) does an exact
    # match on normalize_student_id(), so a reg no. saved as typed could never be found.
    data.student_id = normalize_student_id(data.student_id)
    data.attrs = await _validate_voter_attrs(request.state.org_id, data.attrs)
    if await tdb(request).voters.find_one({"student_id": data.student_id}, {"_id": 1}):
        raise HTTPException(409, "Already registered, use Edit Student.")
    if not any(str(p or "").strip() for p in data.phones):
        raise HTTPException(400, "At least one phone number is required.")
    phones = []
    for raw in data.phones:
        if not str(raw or "").strip():
            continue
        clean = normalize_phone_number(raw)
        if clean not in phones:
            phones.append(clean)
    set_doc = org_stamp(request, {
        "full_name": data.full_name, "phone_numbers": phones,
        "added_by": "superadmin", "add_reason": data.reason
    })
    set_doc.update(attr_set_paths(data.attrs))
    await tdb(request).voters.update_one(
        {"student_id": data.student_id},
        {"$set": set_doc,
         # Defaults ONLY on insert (see _execute_student_change): never un-vote an existing voter or wipe roles.
         "$setOnInsert": {
            "is_commissioner": False,
            "is_it_admin":     False,
            "has_voted":       False,
            "last_status":     "idle",
         }},
        upsert=True
    )
    await log_action("student_added_by_superadmin", current_actor(request), {
        "student_id": data.student_id,
        "full_name":  data.full_name,
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "added"}


class NormalizeNamesRequest(BaseModel):
    dry_run: bool = True


@app.post("/superadmin/maintenance/normalize-names")
async def superadmin_normalize_names(data: NormalizeNamesRequest, request: Request,
                                     admin: dict = Depends(require_role("superadmin"))):
    """Title-case every stored person name in THIS organisation (register, applications,
    candidates, student-change requests). dry_run=True (the default) only reports what
    would change. Case/whitespace only; audit history is left as originally written."""
    org_id = require_org(request.state.org_id)
    report = await run_name_backfill(db, org_id=org_id, dry_run=data.dry_run)
    if not data.dry_run and report["total_changed"]:
        await log_action("names_normalized", current_actor(request),
                         {"total_changed": report["total_changed"], "collections": report["collections"]},
                         org_id=org_id)
        await append_ledger(org_id, "names_normalized", "roster", current_actor(request), "superadmin",
                            {"total_changed": report["total_changed"]})
    return report


class CheckRegNumbersRequest(BaseModel):
    fix: bool = False


@app.post("/superadmin/maintenance/check-reg-numbers")
async def superadmin_check_reg_numbers(data: CheckRegNumbersRequest, request: Request,
                                       admin: dict = Depends(require_role("superadmin"))):
    """Find (and with fix=True repair) registration numbers not stored in canonical form
    (lowercase, no spaces) — such voters are on the register but cannot be found at login.
    Conflicts and voters who already voted are reported only, never modified."""
    org_id = require_org(request.state.org_id)
    report = await audit_reg_numbers(db, org_id=org_id, fix=data.fix)
    if data.fix and report["total_fixed"]:
        await log_action("reg_numbers_normalized", current_actor(request),
                         {"total_fixed": report["total_fixed"], "needs_review": report["needs_review"]}, org_id=org_id)
        await append_ledger(org_id, "reg_numbers_normalized", "roster", current_actor(request), "superadmin",
                            {"total_fixed": report["total_fixed"]})
    return report


@app.post("/superadmin/students/remove")
async def superadmin_remove_student(data: ITAdminStudentRemove, request: Request):
    await assert_roster_unfrozen(request)
    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(404, "Student not found.")
    await tdb(request).voters.delete_one(get_forgiving_filter(data.student_id))
    await log_action("student_removed_by_superadmin", current_actor(request), {
        "student_id": data.student_id,
        "full_name":  student.get("full_name", ""),
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "removed"}

# =============================================================================
# STUDENT DETAIL EDITS  (Task 1 superadmin screen + Task 2 IT admin screen)
# =============================================================================
# ONE endpoint and ONE audit writer serve both UIs, so they cannot drift apart.
# Editable fields: name, phone numbers (add / change / remove), registration
# number. Nothing else on the voter document can be changed through here.
# No approval step and no notifications by design: the audit trail is the control.
# Audit rows live in `student_edit_audit` (append-only: this file has no route that
# updates or deletes them). They hold full phone numbers, so they are readable only
# by IT admin / superadmin; the general activity log gets a masked mirror entry.

STUDENT_EDIT_ROLES = ("it_admin", "superadmin")
STUDENT_ROLE_FLAGS = ("is_commissioner", "is_it_admin", "is_financial_controller", "is_overseer")


class StudentPhoneOp(BaseModel):
    op: str                        # "add" | "change" | "remove"
    index: int | None = None       # position in phone_numbers (change / remove)
    expected_old: str | None = None  # number the editor saw at that position
    number: str | None = None      # new number (add / change)


class StudentAttrOp(BaseModel):
    key: str
    expected_old: str | None = None
    value: str | None = None


class StudentEditRequest(BaseModel):
    student_id: str                # CURRENT registration number of the record
    full_name: str | None = None
    new_student_id: str | None = None
    phone_ops: list[StudentPhoneOp] = []
    attr_ops: list[StudentAttrOp] = []
    reason: str


def normalize_phone_number(raw: str) -> str:
    """Same rules the roster-add flow uses (0-prefix and bare 9-digit -> 256...)."""
    clean = re.sub(r"\D", "", raw or "")
    if clean.startswith("0"):
        clean = "256" + clean[1:]
    elif len(clean) == 9 and (clean.startswith("7") or clean.startswith("4")):
        clean = "256" + clean
    if not 10 <= len(clean) <= 15:
        raise HTTPException(400, f"'{raw}' is not a valid phone number.")
    return clean


def _mask_phone(p: str | None) -> str | None:
    return None if p is None else ("*" * max(len(p) - 3, 0)) + p[-3:]


def _student_edit_view(v: dict, role: str = "superadmin", enabled_keys=None) -> dict:
    enabled_keys = set(enabled_keys or [])
    out = {
        "student_id": v.get("student_id", ""),
        "full_name": v.get("full_name", ""),
        "phone_numbers": v.get("phone_numbers", []),
        "attrs": {k: v.get("attrs", {}).get(k, "") for k in enabled_keys if v.get("attrs", {}).get(k, "") != ""},
        "holds_admin_role": any(v.get(f) for f in STUDENT_ROLE_FLAGS),
    }
    if role == "superadmin":
        out["has_voted"] = bool(v.get("has_voted"))
    return out


@app.get("/admin/students/lookup")
async def lookup_students_for_edit(q: str, request: Request,
                                   admin: dict = Depends(require_role(*STUDENT_EDIT_ROLES))):
    q = q.strip()
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    cur = tdb(request).voters.find({"org_id": request.state.org_id, "$or": [{"student_id": rx}, {"full_name": rx}]}).limit(10)
    role = admin.get("role", "")
    fields = await get_voter_fields(request)
    enabled = {f["key"] for f in fields["fields"] if f.get("enabled")}
    return [_student_edit_view(v, role, enabled) async for v in cur]


async def _apply_student_edit(org_id, voter: dict, full_name: str | None, new_student_id: str | None,
                              phone_ops: list, attr_ops: list = None) -> dict:
    """Validate and apply name / registration-number / phone operations with optimistic concurrency.
    Shared by direct edits and approved contact changes so the two can never drift apart."""
    old_sid = voter["student_id"]
    old_name = voter.get("full_name", "")
    old_phones = list(voter.get("phone_numbers", []))
    new_name, new_sid, phones = old_name, old_sid, list(old_phones)
    old_attrs = dict(voter.get("attrs") or {})
    new_attrs = dict(old_attrs)
    events: list[dict] = []          # {event, field, old, new}

    fields = await get_voter_fields_for_org(org_id)
    enabled = {f["key"] for f in fields if f.get("enabled")}
    attr_ops = attr_ops or []
    if attr_ops:
        unknown = [op.key for op in attr_ops if op.key not in enabled]
        if unknown:
            raise HTTPException(400, f"Unknown or disabled voter field: {unknown[0]}")
        seen = set()
        for op in attr_ops:
            if op.key in seen:
                raise HTTPException(400, f"Duplicate voter field operation: {op.key}")
            seen.add(op.key)
            current = old_attrs.get(op.key, "")
            if op.expected_old is not None and normalize_attr_value(op.expected_old) != current:
                raise HTTPException(409, "A voter field changed since you loaded it; reload and try again.")
            value = normalize_attr_value(op.value) if op.value else ""
            if value == current:
                continue
            if value:
                new_attrs[op.key] = value
            else:
                new_attrs.pop(op.key, None)
            events.append({"event": "student_attr_changed", "field": f"attrs.{op.key}", "old": current or None, "new": value or None})

    if full_name is not None:
        candidate = normalize_name(full_name)
        if not candidate or len(candidate) > 120:
            raise HTTPException(400, "Name must be 1-120 characters.")
        if candidate != old_name:
            new_name = candidate
            events.append({"event": "student_name_changed", "field": "full_name", "old": old_name, "new": candidate})

    if new_student_id is not None:
        candidate_sid = normalize_student_id(new_student_id)
        if not re.fullmatch(r"[^\s\x00-\x1f]{1,64}", candidate_sid):
            raise HTTPException(400, f"{_cap(await id_noun(org_id))} must be 1-64 characters with no spaces.")
        if candidate_sid != old_sid:
            if any(voter.get(f) for f in STUDENT_ROLE_FLAGS):
                raise HTTPException(409, "This student holds an admin/commission role, whose sessions and votes are "
                                         f"keyed to the {await id_noun(org_id)}. Remove the role before changing it.")
            if await tdb_for(org_id).voters.find_one({"org_id": org_id, "student_id": candidate_sid, "_id": {"$ne": voter["_id"]}}):
                raise HTTPException(409, f"Another student in this organization already has that {await id_noun(org_id)}.")
            new_sid = candidate_sid
            events.append({"event": "student_registration_number_changed", "field": "student_id",
                           "old": old_sid, "new": candidate_sid})

    for op in phone_ops:
        if op.op == "add":
            num = normalize_phone_number(op.number or "")
            if num in phones:
                raise HTTPException(400, "That phone number is already on this student.")
            phones.append(num)
            events.append({"event": "phone_added", "field": "phone_numbers", "old": None, "new": num})
        elif op.op in ("change", "remove"):
            if op.index is None or not 0 <= op.index < len(phones):
                raise HTTPException(400, "Phone position is out of range; reload the student and try again.")
            current = phones[op.index]
            if op.expected_old is not None and normalize_phone_number(op.expected_old) != current:
                raise HTTPException(409, "The phone list changed since you loaded it; reload and try again.")
            if op.op == "remove":
                phones.pop(op.index)
                events.append({"event": "phone_removed", "field": "phone_numbers", "old": current, "new": None})
            else:
                num = normalize_phone_number(op.number or "")
                if num != current:
                    if num in phones:
                        raise HTTPException(400, "That phone number is already on this student.")
                    phones[op.index] = num
                    events.append({"event": "phone_changed", "field": "phone_numbers", "old": current, "new": num})
        else:
            raise HTTPException(400, f"Unknown phone operation '{op.op}'.")

    if not events:
        raise HTTPException(400, "No changes to save.")

    # Optimistic concurrency: the update only applies if the student still looks the way the
    # editor saw it, so two simultaneous edits cannot silently overwrite each other.
    filter_doc = {"_id": voter["_id"], "org_id": org_id, "student_id": old_sid,
                  "full_name": old_name, "phone_numbers": old_phones}
    for op in attr_ops:
        filter_doc[f"attrs.{op.key}"] = old_attrs.get(op.key, None)
    set_doc = {"full_name": new_name, "student_id": new_sid, "phone_numbers": phones}
    for key, value in new_attrs.items():
        if key in enabled and value != old_attrs.get(key, ""):
            set_doc[f"attrs.{key}"] = value
    unset_doc = {f"attrs.{op.key}": "" for op in attr_ops if not new_attrs.get(op.key)}
    update_doc = {"$set": set_doc}
    if unset_doc:
        update_doc["$unset"] = unset_doc
    updated = await tdb_for(org_id).voters.update_one(filter_doc, update_doc)
    if updated.matched_count != 1:
        raise HTTPException(409, "This student was changed by someone else; reload and try again.")

    if new_sid != old_sid:
        # No unique index exists on (org_id, student_id), so re-check after writing and roll back
        # if a concurrent edit/import produced a duplicate.
        if await tdb_for(org_id).voters.count_documents({"org_id": org_id, "student_id": new_sid}) > 1:
            await tdb_for(org_id).voters.update_one(
                {"_id": voter["_id"]},
                {"$set": {"full_name": old_name, "student_id": old_sid, "phone_numbers": old_phones}})
            raise HTTPException(409, f"Another student in this organization already has that {await id_noun(org_id)}.")
        # Keep the student's own records attached to the new number.
        _t = tdb_for(org_id)
        for coll in (_t.applications, _t.exception_grants, _t.contact_changes, _t.candidate_tokens):
            await coll.update_many({"student_id": old_sid}, {"$set": {"student_id": new_sid}})

    return {"events": events, "old_sid": old_sid, "new_sid": new_sid, "old_name": old_name,
            "new_name": new_name, "old_phones": old_phones, "phones": phones, "attrs": new_attrs}


async def _write_student_audit(org_id, voter: dict, res: dict, reason: str, actor: str, role: str,
                               extra: dict | None = None):
    now, batch = datetime.utcnow(), secrets.token_hex(8)
    old_sid, new_sid = res["old_sid"], res["new_sid"]
    terms = sorted({old_sid, new_sid, res["old_name"].lower(), res["new_name"].lower()} - {""})
    for ev in res["events"]:
        await tdb_for(org_id).student_edit_audit.insert_one({
            "org_id": org_id, "student_key": str(voter["_id"]), "batch": batch,
            "event": ev["event"], "field": ev["field"], "old_value": ev["old"], "new_value": ev["new"],
            "reason": reason, "actor": actor, "actor_role": role, "at": now,
            "student_id_before": old_sid, "student_id_after": new_sid, "search_terms": terms,
            **(extra or {}),
        })
        # Masked mirror in the general activity log (that log is visible to every admin role).
        await log_action(ev["event"], actor, {
            "student_id": new_sid, "role": role, "reason": reason, "field": ev["field"],
            "old": _mask_phone(ev["old"]) if ev["field"] == "phone_numbers" else ev["old"],
            "new": _mask_phone(ev["new"]) if ev["field"] == "phone_numbers" else ev["new"],
        }, org_id=org_id)


@app.post("/admin/students/edit")
async def edit_student(data: StudentEditRequest, request: Request,
                       admin: dict = Depends(require_role(*STUDENT_EDIT_ROLES))):
    org_id = request.state.org_id          # the tenant being acted on; exact match, never unscoped
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every change.")

    old_sid = normalize_student_id(data.student_id)
    voter = await tdb(request).voters.find_one({"org_id": org_id, "student_id": old_sid})
    if not voter:
        raise HTTPException(404, "Student not found in this organization.")

    # Roster freeze (design D3/D4): from the freeze until voting closes, phone and registration-number
    # edits are requests a commissioner approves; only name typos stay direct (unvoted voters, max 2).
    st = await roster_status(request)
    if st["contact_change_required"]:
        touches_contact = bool(data.phone_ops) or (
            data.new_student_id is not None and normalize_student_id(data.new_student_id) != old_sid)
        if touches_contact:
            raise ApiError(409, f"The roster is frozen: phone and {await id_noun(request.state.org_id)} changes must be submitted "
                                "as a contact-change request for a commissioner to approve.", "contact_change_required")
        if voter.get("has_voted"):
            role = admin.get("role", "")
            detail = "This voter's details can no longer be edited." if role == "it_admin" else "This voter has already voted; their details can no longer be edited."
            raise ApiError(409, detail, "already_voted")
        name_changes = await tdb(request).student_edit_audit.count_documents({
            "org_id": org_id, "student_key": str(voter["_id"]), "event": "student_name_changed",
            "at": {"$gte": st["freeze_at"] or datetime(1970, 1, 1)}})
        if name_changes >= 2:
            raise ApiError(409, "This voter has already had 2 name corrections since the freeze.", "name_edit_cap")
        if data.attr_ops:
            attr_changes = await tdb(request).student_edit_audit.count_documents({
                "org_id": org_id, "student_key": str(voter["_id"]), "event": "student_attr_changed",
                "at": {"$gte": st["freeze_at"] or datetime(1970, 1, 1)}})
            if attr_changes + len(data.attr_ops) > 2:
                raise ApiError(409, "This voter has already had 2 optional-field corrections since the freeze.", "attr_edit_cap")

    res = await _apply_student_edit(org_id, voter, data.full_name, data.new_student_id, data.phone_ops, data.attr_ops)
    actor, role = current_actor(request), admin.get("role", "")
    await _write_student_audit(org_id, voter, res, reason, actor, role)
    # D5: any applied correction forgets this voter's send/guess state and live code.
    await reset_voter_otp_state(org_id, [res["old_sid"], res["new_sid"]])
    if st["phase"] != "pre_freeze":
        for ev in res["events"]:
            is_name = ev["event"] == "student_name_changed"
            await append_ledger(org_id, "name_changed" if is_name else "contact_edit_audit_only", res["new_sid"], actor, role, {
                "reason": reason, "event": ev["event"],
                "old": _mask_name(ev["old"]) if is_name else _mask_phone(ev["old"]) if ev["field"] == "phone_numbers" else _mask_student_id(ev["old"] or ""),
                "new": _mask_name(ev["new"]) if is_name else _mask_phone(ev["new"]) if ev["field"] == "phone_numbers" else _mask_student_id(ev["new"] or "")})

    fields = await get_voter_fields(request)
    enabled = {f["key"] for f in fields["fields"] if f.get("enabled")}
    student_view = {**voter, "full_name": res["new_name"], "student_id": res["new_sid"],
                    "phone_numbers": res["phones"], "attrs": res.get("attrs", voter.get("attrs", {}))}
    return {"status": "updated", "changes": [e["event"] for e in res["events"]],
            "student": _student_edit_view(student_view, admin.get("role", ""), enabled)}


@app.get("/admin/students/edit-history")
async def student_edit_history(request: Request, q: str = "", limit: int = 100,
                               admin: dict = Depends(require_role(*STUDENT_EDIT_ROLES))):
    """Read-only. Searching an OLD or NEW registration number (or a name) finds the student
    and every change ever made to that student, because each row carries the student's
    internal key and both numbers."""
    org_id = require_org(request.state.org_id)
    limit = min(max(limit, 1), 500)
    q = q.strip()
    query: dict = {"org_id": org_id}
    if q:
        keys = set()
        exact = {normalize_student_id(q), q.lower()}
        rx = {"$regex": re.escape(q.lower())}
        async for r in tdb(request).student_edit_audit.find(
                {"org_id": org_id, "$or": [{"search_terms": {"$in": list(exact)}}, {"search_terms": rx}]},
                {"student_key": 1}):
            keys.add(r["student_key"])
        async for v in tdb(request).voters.find({"org_id": org_id, "$or": [
                {"student_id": normalize_student_id(q)},
                {"full_name": {"$regex": re.escape(q), "$options": "i"}}]}, {"_id": 1}).limit(50):
            keys.add(str(v["_id"]))
        if not keys:
            return {"entries": []}
        query["student_key"] = {"$in": list(keys)}
    entries = []
    async for r in tdb(request).student_edit_audit.find(query).sort("at", -1).limit(limit):
        r["_id"] = str(r["_id"])
        entries.append(r)
    return {"entries": entries}


@app.post("/superadmin/audit/checkpoint")
async def post_audit_checkpoint(request: Request, admin: dict = Depends(require_role("superadmin"))):
    checkpoint = await create_audit_checkpoint(request)
    if checkpoint is None:
        return {"status": "no_new_events"}
    checkpoint["_id"] = str(checkpoint["_id"])
    checkpoint["to_id"] = str(checkpoint["to_id"])
    checkpoint["from_id"] = str(checkpoint["from_id"]) if checkpoint["from_id"] else None
    return {"status": "checkpoint_created", "checkpoint": checkpoint}


@app.get("/superadmin/audit/verify")
async def get_audit_verify(request: Request, admin: dict = Depends(require_role("superadmin"))):
    result = await verify_audit_chain(request)
    result["roster_ledger"] = await verify_roster_ledger(request.state.org_id)
    return result

# =============================================================================
# AUDIT LOG
# =============================================================================

@app.get("/superadmin/audit-log")
async def get_audit_log(request: Request, limit: int = 200, action: str = None):
    query = org_query(request)
    if action:
        query["action"] = {"$regex": action, "$options": "i"}
    logs = []
    async for entry in tdb(request).audit_log.find(query).sort("timestamp", -1).limit(limit):
        entry["_id"] = str(entry["_id"])
        logs.append(entry)
    return logs


# =============================================================================
# DEMO MODE — per-organisation, safe, fake-number-only SMS capture
# =============================================================================
DEMO_SETTING = "demo_mode"
DEMO_DEFAULT_DAYS = 3
DEMO_MAX_DAYS = 14
DEMO_INBOX_MAX = 200
DEMO_INBOX_READ_MAX = 50
DEMO_PHONE_PREFIX = re.sub(r"\D", "", os.getenv("DEMO_PHONE_PREFIX", "256700000")) or "256700000"


class DemoEnableRequest(BaseModel):
    reason: str = Field(..., max_length=300)
    days: int = Field(DEMO_DEFAULT_DAYS, ge=1, le=DEMO_MAX_DAYS)


class DemoReasonRequest(BaseModel):
    reason: str = Field(..., max_length=300)


class DemoExtendRequest(BaseModel):
    reason: str = Field(..., max_length=300)
    days: int = Field(1, ge=1, le=DEMO_MAX_DAYS)


class DemoPhaseRequest(BaseModel):
    phase: str = Field(..., max_length=32)


async def _demo_active(org_id) -> bool:
    if not org_id:
        return False
    doc = await cached_setting(org_id, DEMO_SETTING) or {}
    exp = doc.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            exp = None
    exp = naive_utc(exp) if exp else None
    return bool(doc.get("enabled") and exp and exp > datetime.utcnow())


async def _demo_capture(org_id: str, to_number: str, message_text: str, kind: str) -> str:
    number = re.sub(r"\D", "", str(to_number or ""))
    if not number.startswith(DEMO_PHONE_PREFIX):
        await log_action("demo_sms_refused", "system", {"to": number[-4:] if number else "", "kind": kind}, org_id=org_id)
        return "failed"
    now = datetime.utcnow()
    inbox = tdb_for(org_id).demo_inbox
    await inbox.insert_one({"to": number, "kind": kind, "message": str(message_text or "")[:2000], "created_at": now})
    # Keep only the newest N messages. This is intentionally tenant-scoped.
    ids = []
    async for row in inbox.find({}, {"_id": 1}).sort("created_at", -1).skip(DEMO_INBOX_MAX):
        ids.append(row["_id"])
    if ids:
        await inbox.delete_many({"_id": {"$in": ids}})
    return "ok"


def _demo_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every demo-mode change.")
    return reason[:300]


async def _demo_snapshot(org_id: str) -> dict:
    phases = await tdb_for(org_id).settings.find_one({"name": "election_phases"})
    config = await tdb_for(org_id).settings.find_one({"name": "election_config"})
    return {
        "election_phases": {k: v for k, v in (phases or {}).items() if k != "_id"},
        "election_config": {k: v for k, v in (config or {}).items() if k != "_id"},
    }


async def _demo_restore_snapshot(org_id: str, snapshot: dict) -> None:
    for name, doc in (("election_phases", snapshot.get("election_phases") or {}),
                      ("election_config", snapshot.get("election_config") or {})):
        if doc:
            clean = dict(doc)
            clean["name"] = name
            await tdb_for(org_id).settings.replace_one({"name": name}, clean, upsert=True)
        else:
            await tdb_for(org_id).settings.delete_one({"name": name})
    invalidate_settings(org_id)


DEMO_TAGGED_COLLECTIONS = ("voters", "positions", "panel_members", "applications", "candidates", "vote_events",
                           "candidate_tokens", "certificates", "exception_grants", "nomination_uploads")
async def _demo_fenced_reset(org_id: str, snapshot: dict) -> dict:
    """Delete only synthetic demo principals/data; activity collections were empty at enable time."""
    deleted = {}
    dbs = tdb_for(org_id)
    demo_files = [r async for r in dbs.nomination_uploads.find({"is_demo": True}, {"key": 1, "upload_id": 1})]
    deleted["nomination_files"] = await _delete_nomination_objects(demo_files)
    for name in DEMO_TAGGED_COLLECTIONS:
        result = await getattr(dbs, name).delete_many({"is_demo": True})
        deleted[name] = result.deleted_count
    # OTP documents created by the demo are tagged; preserve any live OTP a real
    # voter may have had before demo mode was enabled.
    otp_res = await dbs.otps.delete_many({"is_demo": True})
    deleted["otps"] = otp_res.deleted_count
    otp_key_rx = {"key": {"$regex": f"^{re.escape(org_id)}:otp:DEMO-"}}
    for name in ("otp_send_state", "otp_guess_state", "otp_attempts"):
        if hasattr(db, name):
            result = await getattr(db, name).delete_many(otp_key_rx)
            deleted[name] = result.deleted_count
    inbox = await dbs.demo_inbox.delete_many({})
    deleted["demo_inbox"] = inbox.deleted_count
    # Demo never sends billable SMS, so it does not mutate the org SMS budget.
    # Leave any pre-demo usage accounting untouched on reset.
    await _demo_restore_snapshot(org_id, snapshot)
    return deleted


async def _demo_counts(org_id: str) -> dict:
    dbs = tdb_for(org_id)
    return {
        "voters": await dbs.voters.count_documents({"is_demo": True}),
        "positions": await dbs.positions.count_documents({"is_demo": True}),
        "panel_members": await dbs.panel_members.count_documents({"is_demo": True}),
        "applications": await dbs.applications.count_documents({"is_demo": True}),
        "candidates": await dbs.candidates.count_documents({"is_demo": True}),
        "vote_events": await dbs.vote_events.count_documents({"is_demo": True}),
        "inbox": await dbs.demo_inbox.count_documents({}),
    }


async def _demo_public_status(org_id: str) -> dict:
    doc = await cached_setting(org_id, DEMO_SETTING) or {}
    return {"enabled": bool(await _demo_active(org_id)),
            "enabled_at": doc.get("enabled_at"), "expires_at": doc.get("expires_at")}


@app.get("/demo/inbox")
async def demo_inbox(request: Request):
    org_id = require_org(request.state.org_id)
    if not await _demo_active(org_id):
        raise HTTPException(404, "Demo mode is not active.")
    await _check_rate_limit(request, bucket="demo_inbox", limit=120, window_s=60,
                            message="Too many inbox requests. Please try again shortly.")
    items = []
    async for row in tdb(request).demo_inbox.find({}).sort("created_at", -1).limit(DEMO_INBOX_READ_MAX):
        items.append({"id": str(row["_id"]), "to": row.get("to", ""), "kind": row.get("kind", "notice"),
                      "message": row.get("message", ""), "created_at": row.get("created_at")})
    return {"enabled": True, "messages": items}


@app.post("/superadmin/demo/enable")
async def demo_enable(data: DemoEnableRequest, request: Request, admin: dict = Depends(require_role("superadmin"))):
    org_id = require_org(request.state.org_id)
    reason = _demo_reason(data.reason)
    current = await cached_setting(org_id, DEMO_SETTING) or {}
    if await _demo_active(org_id):
        raise HTTPException(409, "Demo mode is already active.")
    # An expired demo is already treated as off by _demo_active. Clean its fenced
    # data before allowing a new enable, otherwise old demo applications would
    # make the safety precondition fail forever.
    prior_exp = naive_utc(current.get("expires_at")) if current.get("expires_at") else None
    if current.get("enabled") and prior_exp and prior_exp <= datetime.utcnow():
        await _demo_fenced_reset(org_id, current.get("snapshot") or {})
        await tdb(request).settings.update_one({"name": DEMO_SETTING}, {"$set": {"enabled": False, "expires_at": datetime.utcnow()}})
        invalidate_settings(org_id, DEMO_SETTING)
        await log_action("demo_disabled", "system", {"reason": "Automatic expiry cleanup before re-enable"}, org_id=org_id)
    apps = await tdb(request).applications.count_documents({})
    votes = await tdb(request).vote_events.count_documents({})
    config = await tdb(request).settings.find_one({"name": "election_config"}) or {}
    if apps or votes or config.get("is_certified"):
        raise HTTPException(409, "Demo mode can only be enabled before applications/votes exist and before certification.")
    now = datetime.utcnow()
    expiry = now + timedelta(days=data.days)
    snapshot = await _demo_snapshot(org_id)
    doc = {"name": DEMO_SETTING, "enabled": True, "enabled_at": now, "expires_at": expiry,
           "enabled_by": current_actor(request), "snapshot": snapshot}
    await tdb(request).settings.update_one({"name": DEMO_SETTING}, {"$set": org_stamp(request, doc)}, upsert=True)
    invalidate_settings(org_id, DEMO_SETTING)
    await log_action("demo_enabled", current_actor(request),
                     {"reason": reason, "days": data.days, "expires_at": expiry}, org_id=org_id)
    return await _demo_public_status(org_id)


async def _demo_require_active(request: Request) -> dict:
    org_id = require_org(request.state.org_id)
    if not await _demo_active(org_id):
        raise HTTPException(409, "Demo mode is not active.")
    return await tdb(request).settings.find_one({"name": DEMO_SETTING}) or {}


@app.post("/superadmin/demo/extend")
async def demo_extend(data: DemoExtendRequest, request: Request, admin: dict = Depends(require_role("superadmin"))):
    doc = await _demo_require_active(request)
    reason = _demo_reason(data.reason)
    now = datetime.utcnow()
    enabled_at = naive_utc(doc.get("enabled_at")) or now
    current_exp = naive_utc(doc.get("expires_at")) or now
    new_exp = max(current_exp, now) + timedelta(days=data.days)
    cap = enabled_at + timedelta(days=DEMO_MAX_DAYS)
    if new_exp > cap:
        raise HTTPException(400, f"Demo mode cannot run for more than {DEMO_MAX_DAYS} days from enablement.")
    await tdb(request).settings.update_one({"name": DEMO_SETTING}, {"$set": {"expires_at": new_exp}})
    invalidate_settings(request.state.org_id, DEMO_SETTING)
    await log_action("demo_extended", current_actor(request),
                     {"reason": reason, "days": data.days, "expires_at": new_exp}, org_id=request.state.org_id)
    return await _demo_public_status(request.state.org_id)


@app.post("/superadmin/demo/seed")
async def demo_seed(request: Request, admin: dict = Depends(require_role("superadmin"))):
    doc = await _demo_require_active(request)
    org_id = require_org(request.state.org_id)
    now = datetime.utcnow()
    expires = naive_utc(doc.get("expires_at")) or (now + timedelta(days=DEMO_DEFAULT_DAYS))
    dbs = tdb(request)
    created = {"voters": 0, "roles": 0, "panelists": 0, "applications": 0, "positions": 0}
    credentials = dict((doc.get("credentials") or {}))

    # Reserved fake voters. Refuse collisions with any untagged roster entry:
    # otherwise seeding a role onto a real voter would make reset destructive.
    reserved_ids = [f"DEMO-{i:03d}" for i in range(1, 41)]
    collisions = await dbs.voters.find(
        {"student_id": {"$in": reserved_ids}, "is_demo": {"$ne": True}},
        {"student_id": 1},
    ).to_list(length=41)
    if collisions:
        ids = ", ".join(sorted(v.get("student_id", "?") for v in collisions[:5]))
        extra = "…" if len(collisions) > 5 else ""
        raise HTTPException(409, f"Reserved demo voter IDs are already in use: {ids}{extra}")
    voter_docs = []
    for i in range(1, 41):
        sid = f"DEMO-{i:03d}"
        if await dbs.voters.find_one({"student_id": sid}):
            continue
        voter_docs.append({"student_id": sid, "full_name": f"Demo Voter {i:03d}",
                           "phone_numbers": [f"{DEMO_PHONE_PREFIX}{100+i:03d}"],
                           "has_voted": False, "last_status": "idle", "is_demo": True,
                           "is_commissioner": False, "is_it_admin": False,
                           "is_financial_controller": False, "is_overseer": False})
    if voter_docs:
        await dbs.voters.insert_many(voter_docs)
        created["voters"] = len(voter_docs)

    # Create sample positions only when the organisation has none, matching the guide's "if none exist" rule.
    positions = [p async for p in dbs.positions.find({}).sort("order", 1).limit(3)]
    if not positions:
        for i, title in enumerate(("President", "Vice President", "Treasurer")):
            r = await dbs.positions.insert_one({"title": title, "description": "Demo election position", "order": i,
                                                "application_fee": 0, "is_demo": True})
            positions.append(await dbs.positions.find_one({"_id": r.inserted_id}))
            created["positions"] += 1
    if not positions:
        raise HTTPException(409, "No election positions are available for the demo.")

    role_specs = [
        ("IT admin", "DEMO-001", "it_admin_email", "it_admin_password_hash", "it_admin_must_change_password", "it_admin_temp_password_expires", "is_it_admin", "demo.itadmin@example.invalid"),
        ("Commissioner", "DEMO-002", "commissioner_email", "commissioner_password_hash", "commissioner_must_change_password", "commissioner_temp_password_expires", "is_commissioner", "demo.commissioner@example.invalid"),
        ("Financial Controller", "DEMO-003", "financial_controller_email", "financial_controller_password_hash", "financial_controller_must_change_password", "financial_controller_temp_password_expires", "is_financial_controller", "demo.finance@example.invalid"),
        ("Overseer", "DEMO-004", "overseer_email", "overseer_password_hash", "overseer_must_change_password", "overseer_temp_password_expires", "is_overseer", "demo.overseer@example.invalid"),
    ]
    for role_label, sid, email_field, hash_field, must_field, exp_field, flag_field, email in role_specs:
        voter = await dbs.voters.find_one({"student_id": sid})
        if not voter:
            continue
        cred = credentials.get(role_label.lower()) or {}
        password = cred.get("password") or generate_temp_password()
        await dbs.voters.update_one({"_id": voter["_id"]}, {"$set": {
            email_field: email, hash_field: hash_password(password), must_field: False, exp_field: expires, flag_field: True, "is_demo": True}})
        credentials[role_label.lower()] = {"email": email, "password": password, "student_id": sid}
        created["roles"] += 1

    existing_panels = [p async for p in dbs.panel_members.find({"is_demo": True})]
    for i in range(1, 4):
        pid = f"DEMO-PANEL-{i}"
        if any(p.get("panel_member_id") == pid for p in existing_panels):
            continue
        password = generate_temp_password()
        email = f"demo.panel{i}@example.invalid"
        await dbs.panel_members.insert_one({"panel_member_id": pid, "email": email, "full_name": f"Demo Panelist {i}",
                                            "password_hash": hash_password(password), "active": True,
                                            "is_member": False, "access_expires_at": expires,
                                            "must_change_password": False, "temp_password_expires": expires,
                                            "confidentiality_required": False, "confidentiality_accepted": True,
                                            "confidentiality_version": CONFIDENTIALITY_VERSION, "is_demo": True,
                                            "created_at": now})
        credentials[f"panelist_{i}"] = {"email": email, "password": password, "panel_member_id": pid}
        created["panelists"] += 1

    await tdb(request).settings.update_one({"name": DEMO_SETTING}, {"$set": {"credentials": credentials}})
    invalidate_settings(org_id, DEMO_SETTING)

    # A few synthetic applications are created idempotently. These are tagged so reset never touches real applications.
    existing_demo_apps = [a async for a in dbs.applications.find({"is_demo": True}).limit(6)]
    if not existing_demo_apps:
        nom_cfg = await get_nomination_form(org_id)
        pos = positions[0]
        for i in range(1, 5):
            sid = f"DEMO-{i+10:03d}"
            voter = await dbs.voters.find_one({"student_id": sid}) or await dbs.voters.find_one({"is_demo": True})
            if not voter:
                continue
            doc = {"student_id": voter["student_id"], "full_name": voter.get("full_name", ""), "position_id": str(pos["_id"]),
                   "manifesto": f"Demo manifesto for candidate {i}.", "image_url": "", "payment_method": "Demo", "payment_proof_url": "https://example.invalid/demo-receipt",
                   "nomination_form": None, "nomination_form_required": bool(nom_cfg["enabled"] and nom_cfg["required"]),
                   "round_id": (await get_phase_schedule(request))["round_id"], "status": "pending", "votes": {}, "removal_votes": {},
                   "fee_required": int(pos.get("application_fee") or 0), "finance_cleared": False,
                   "finance_cleared_by": None, "finance_cleared_at": None, "submitted_at": now,
                   "application_snapshot": {"student_id": voter["student_id"], "full_name": voter.get("full_name", ""), "position_title": pos.get("title", ""),
                                             "manifesto": f"Demo manifesto for candidate {i}.", "image_url": "", "submitted_at": now},
                   "denial_snapshot": None, "certificate_id": None, "certificate_issued_at": None, "is_demo": True}
            await dbs.applications.insert_one(doc)
            created["applications"] += 1

    return {"status": "seeded", "created": created, "credentials": credentials, "counts": await _demo_counts(org_id)}


@app.post("/superadmin/demo/phase")
async def demo_phase(data: DemoPhaseRequest, request: Request, admin: dict = Depends(require_role("superadmin"))):
    await _demo_require_active(request)
    org_id = require_org(request.state.org_id)
    phase = data.phase.strip().lower()
    if phase not in PHASE_NAMES:
        raise HTTPException(400, f"Phase must be one of: {', '.join(PHASE_NAMES)}.")
    if phase == "voting":
        await _demo_prepare_for_voting(request)
    now = datetime.utcnow()
    short = timedelta(minutes=2)
    later = timedelta(hours=2)
    phases = {}
    idx = PHASE_NAMES.index(phase)
    for i, name in enumerate(PHASE_NAMES):
        if i < idx:
            phases[name] = {"start": now - later - timedelta(minutes=(idx-i)*5), "end": now - short, "enforced": True}
        elif i == idx:
            phases[name] = {"start": now - short, "end": now + timedelta(hours=1), "enforced": True}
        else:
            phases[name] = {"start": now + timedelta(hours=1) + timedelta(minutes=(i-idx)*5),
                            "end": now + timedelta(hours=2) + timedelta(minutes=(i-idx)*5), "enforced": True}
    sched = await get_phase_schedule(request)
    await _write_phase_schedule(org_id, phases, sched.get("timezone") or DEFAULT_ELECTION_TZ, sched.get("round_id") or DEFAULT_ROUND_ID)
    # Voting is a real gate in the application. Open it only for the voting demo window; results closes it.
    await tdb(request).settings.update_one({"name": "election_config"}, {"$set": org_stamp(request, {"name": "election_config", "is_open": phase == "voting"})}, upsert=True)
    invalidate_settings(org_id, "election_config")
    return {"status": "phase_set", "phase": phase, "schedule": await get_phase_schedule(request)}


async def _demo_prepare_for_voting(request: Request) -> None:
    org_id = require_org(request.state.org_id)
    # Ensure the seed created its panel and applications.
    await demo_seed(request, request.state.admin or {})
    panelists = await _live_panelists(org_id)
    if len(panelists) < 3:
        raise HTTPException(409, "Demo voting needs 3 active demo panelists.")
    policy = (await security_settings_for(org_id))["approval_policy"]
    # Resolve up to three demo applications through the same resolution path the real vetting route uses.
    apps = [a async for a in tdb(request).applications.find({"is_demo": True}).sort("submitted_at", 1).limit(3)]
    for idx, app in enumerate(apps):
        if app.get("status") in RESOLVED_STATUSES:
            continue
        fc = await tdb(request).voters.find_one({"student_id": "DEMO-003", "is_financial_controller": True, "is_demo": True})
        if not fc:
            raise HTTPException(409, "Demo financial controller account is missing; reseed demo data.")
        await _finance_clear_application_core(str(app["_id"]),
                                              FinanceClear(financial_controller_id=fc["student_id"], reason="Demo payment cleared"),
                                              request, fc)
        choice = "approve" if idx < 2 else "deny"
        votes = { _panel_vote_key(p): choice for p in panelists[:3] }
        await tdb(request).applications.update_one({"_id": app["_id"]}, {"$set": {"votes": votes}})
        refreshed = await tdb(request).applications.find_one({"_id": app["_id"]})
        await _resolve_application(str(app["_id"]), refreshed, org_id)


@app.post("/superadmin/demo/reset")
async def demo_reset(data: DemoReasonRequest, request: Request, admin: dict = Depends(require_role("superadmin"))):
    doc = await _demo_require_active(request)
    reason = _demo_reason(data.reason)
    deleted = await _demo_fenced_reset(request.state.org_id, doc.get("snapshot") or {})
    # Reset removes demo principals, so previously returned temporary credentials
    # must not remain visible in status until a fresh seed recreates them.
    await tdb(request).settings.update_one({"name": DEMO_SETTING}, {"$unset": {"credentials": ""}})
    invalidate_settings(request.state.org_id, DEMO_SETTING)
    await log_action("demo_reset", current_actor(request), {"reason": reason, "deleted": deleted}, org_id=request.state.org_id)
    return {"status": "reset", "deleted": deleted, "enabled": True, "expires_at": (await _demo_public_status(request.state.org_id))["expires_at"]}


@app.post("/superadmin/demo/disable")
async def demo_disable(data: DemoReasonRequest, request: Request, admin: dict = Depends(require_role("superadmin"))):
    doc = await _demo_require_active(request)
    reason = _demo_reason(data.reason)
    deleted = await _demo_fenced_reset(request.state.org_id, doc.get("snapshot") or {})
    await tdb(request).settings.update_one({"name": DEMO_SETTING}, {"$set": {"enabled": False, "expires_at": datetime.utcnow(), "enabled_by": doc.get("enabled_by")}})
    invalidate_settings(request.state.org_id, DEMO_SETTING)
    await log_action("demo_disabled", current_actor(request), {"reason": reason, "deleted": deleted}, org_id=request.state.org_id)
    return {"status": "disabled", "enabled": False}


@app.get("/superadmin/demo/status")
async def demo_status(request: Request, admin: dict = Depends(require_role("superadmin"))):
    org_id = require_org(request.state.org_id)
    doc = await cached_setting(org_id, DEMO_SETTING) or {}
    active = await _demo_active(org_id)
    return {"enabled": active, "enabled_at": doc.get("enabled_at"), "expires_at": doc.get("expires_at"),
            "counts": await _demo_counts(org_id) if active else {}, "credentials": (doc.get("credentials") or {}) if active else {}}


# =============================================================================
# ELECTION PHASES — schedule read/write
# =============================================================================
# Read is open to every admin role (full transparency was the explicit
# decision); only SuperAdmin can edit the base schedule.

@app.get("/admin/schedule")
async def get_admin_schedule(request: Request):
    """Read-only phase schedule + legacy voting window, for the countdown
    widget mounted in all five dashboards."""
    schedule = await get_phase_schedule(request)
    config = await tdb(request).settings.find_one({"name": "election_config"}) or {}
    now = datetime.utcnow()

    phases = []
    for name in PHASE_NAMES:
        window = schedule["phases"][name]
        start, end = window.get("start"), window.get("end")
        if start and now < start:
            state = "upcoming"
        elif end and now > end:
            state = "closed"
        elif start or end:
            state = "active"
        else:
            state = "unscheduled"
        phases.append({
            "name": name,
            "start": start,
            "end": end,
            "enforced": window.get("enforced", False),
            "state": state,
            "seconds_until_start": int((start - now).total_seconds()) if start and now < start else None,
            "seconds_until_end": int((end - now).total_seconds()) if end and now < end else None,
        })

    return {
        "round_id": schedule["round_id"],
        "timezone": schedule["timezone"],
        "phases": phases,
        "server_time": now,
        "election": {
            "is_open": config.get("is_open", True),
            "is_certified": config.get("is_certified", False),
            "start": config.get("start_time"),
            "end": config.get("end_time"),
        },
    }


@app.post("/admin/schedule/phases")
async def set_phase_schedule(data: PhaseScheduleUpdate, request: Request,
                             admin: dict = Depends(require_role("superadmin"))):
    unknown = set(data.phases) - set(PHASE_NAMES)
    if unknown:
        raise HTTPException(400, f"Unknown phase(s): {', '.join(sorted(unknown))}.")

    tz_name = validate_timezone(data.timezone) if data.timezone else (await get_phase_schedule(request))["timezone"]
    stored = {}
    for name, window in data.phases.items():
        if window.start and window.end and window.end <= window.start:
            raise HTTPException(400, f"'{name}' end time must be after its start time.")
        stored[name] = {"start": window.start, "end": window.end, "enforced": window.enforced}

    # Editing the schedule is the other way to end voting early: pull the voting end into the past
    # (or push the start into the future) while it is live and the window slams shut with no
    # record of why. Same rule as an early stop from the election switch: a reason is required.
    now = datetime.utcnow()
    old_schedule = await get_phase_schedule(request)
    was_live = voting_window_state(old_schedule, now)["live"]
    new_v = stored.get("voting") or {}
    new_window = {"start": naive_utc(new_v.get("start")), "end": naive_utc(new_v.get("end")),
                  "enforced": bool(new_v.get("enforced"))}
    vet = stored.get("vetting") or {}
    vet_end = naive_utc(vet.get("end"))
    if bool(vet.get("enforced")) and (vet_end is None or vet_end > now):
        if await get_panel_count(request.state.org_id) < 3:
            raise HTTPException(409, "Vetting cannot open with fewer than 3 active panelists.")
    ends_voting_now = was_live and new_window["enforced"] and not _phase_is_open(new_window, now)
    reason = (data.reason or "").strip()
    if ends_voting_now and len(reason) < EARLY_STOP_MIN_REASON:
        old_end = old_schedule["phases"]["voting"]["end"]
        raise HTTPException(409, {
            "code": "early_end_reason_required",
            "message": "This change closes the voting window while it is still open — a reason is required.",
            "voting_ends_at": old_end.isoformat() if old_end else None,
            "timezone": old_schedule["timezone"],
        })

    await _write_phase_schedule(request.state.org_id, stored, tz_name, data.round_id or DEFAULT_ROUND_ID)
    await log_action("phases_scheduled", current_actor(request), {
        "round_id": data.round_id, "timezone": tz_name,
        "phases": {k: {"enforced": v["enforced"], "start_utc": v["start"].isoformat() if v["start"] else None,
                       "end_utc": v["end"].isoformat() if v["end"] else None} for k, v in stored.items()},
        **({"early_end": True, "reason": reason[:500]} if ends_voting_now else {}),
    }, org_id=request.state.org_id)

    # Design 5.3(2): recompute lock strength from the new window and log it whenever W changes.
    if "voting" in stored:
        params = await guess_params(request)
        prior = await tdb(request).settings.find_one({"name": "otp_derived"}) or {}
        if int(prior.get("window_s", -1)) != int(params["window_s"]):
            await tdb(request).settings.update_one(
                {"name": "otp_derived"},
                {"$set": org_stamp(request, {"name": "otp_derived", "window_s": int(params["window_s"])})}, upsert=True)
            await log_action("otp_lock_params_changed", current_actor(request), {
                "window_s": int(params["window_s"]), "guess_budget": round(params["budget"], 1),
                "refill_interval_s": int(params["interval"]), "window_is_default": params["window_is_default"]},
                org_id=request.state.org_id)
        # A new future voting window re-arms the roster freeze; a new round with a past start lifts it.
        new_start = stored["voting"].get("start")
        if new_start is not None and new_start.tzinfo is not None:      # pydantic hands us aware datetimes
            new_start = new_start.astimezone(timezone.utc).replace(tzinfo=None)
        prev_round = (await tdb(request).settings.find_one({"name": "otp_derived"}) or {}).get("round_id")
        if new_start and new_start > datetime.utcnow():
            await _save_security(request, {"freeze_lifted_at": None})
        elif prev_round and prev_round != (data.round_id or DEFAULT_ROUND_ID):
            await _save_security(request, {"freeze_lifted_at": datetime.utcnow(), "epoch_at": datetime.utcnow()})
        await tdb(request).settings.update_one({"name": "otp_derived"},
                                     {"$set": {"round_id": data.round_id or DEFAULT_ROUND_ID}})
    return {"status": "saved", "round_id": data.round_id or DEFAULT_ROUND_ID}


@app.get("/admin/roadmap")
async def get_admin_roadmap(request: Request):
    """Read-only for any admin role (matches /admin/schedule's transparency
    rule); only superadmin can write via POST /admin/roadmap below."""
    doc = await tdb(request).settings.find_one({"name": "election_roadmap"})
    return {
        "milestones": (doc or {}).get("milestones", []),
        "week_start_day": (doc or {}).get("week_start_day", 1),
    }


@app.post("/admin/roadmap")
async def set_roadmap(data: RoadmapUpdate, request: Request,
                      admin: dict = Depends(require_role("superadmin"))):
    """Free-text, informational election roadmap (e.g. the client's own
    week-by-week PDF table). Doesn't gate anything — PHASE_NAMES/PhaseWindow
    above still do that. Each row carries a picked start date and an optional
    end date (range); the "today" auto-highlight on the public timeline is
    derived from those. Week
    numbers are derived from those dates too (Week 1 = the week the first
    event happens; later weeks start on `week_start_day`). Rows are stored
    and returned in the order given, never re-sorted."""
    stored = [m.model_dump() for m in data.milestones]
    await tdb(request).settings.update_one(
        {"name": "election_roadmap"},
        {"$set": org_stamp(request, {
            "name": "election_roadmap",
            "milestones": stored,
            "week_start_day": data.week_start_day,
            "updated_at": datetime.utcnow(),
        })},
        upsert=True,
    )
    await log_action("roadmap_updated", current_actor(request), {
        "milestone_count": len(stored),
        "week_start_day": data.week_start_day,
    }, org_id=request.state.org_id)
    return {"status": "saved", "milestone_count": len(stored),
            "week_start_day": data.week_start_day}


@app.get("/election-schedule")
async def get_public_election_schedule(request: Request):
    """Public, read-only, unauthenticated view of the phase schedule for the
    Help menu's Election Timeline. Independent of /election-roadmap below —
    each is its own document, its own endpoint, and the frontend fetches
    them separately so one being slow/unset never blocks the other."""
    schedule = await get_phase_schedule(request)
    return {
        "timezone": schedule["timezone"],
        "phases": schedule["phases"],
    }


@app.get("/election-roadmap")
async def get_public_election_roadmap(request: Request):
    """Public, read-only, unauthenticated view of the informational
    milestone roadmap (see Milestone/RoadmapUpdate above), shown to voters
    under Help -> Election Timeline. Also returns the election timezone (set
    on the admin Timeline) so the page can show a live clock and decide
    "today" in that zone. The 4 enforced phases are deliberately NOT exposed
    here — they're an admin-facing view of when the system switches state,
    not voter information."""
    doc = await tdb(request).settings.find_one({"name": "election_roadmap"})
    schedule = await get_phase_schedule(request)
    return {
        "milestones": (doc or {}).get("milestones", []),
        "week_start_day": (doc or {}).get("week_start_day", 1),
        "timezone": schedule["timezone"],
    }


# =============================================================================
# EXCEPTION GRANTS  (Chief Commissioner only)
# =============================================================================
# A blanket "reopen nominations" toggle would let everyone back in and leave
# no reviewable record of who used the reopened window. A scoped, named,
# time-bound, logged grant solves the real problem — one late applicant —
# without the blast radius.

@app.get("/admin/exception-grants")
async def list_exception_grants(request: Request):
    grants = []
    async for g in tdb(request).exception_grants.find({}).sort("granted_at", -1).limit(200):
        g["_id"] = str(g["_id"])
        grants.append(g)
    return grants


@app.post("/admin/exception-grants")
async def create_exception_grant(data: ExceptionGrantCreate, request: Request,
                                 admin: dict = Depends(require_chief_commissioner)):
    if data.phase not in PHASE_NAMES:
        raise HTTPException(400, f"Phase must be one of: {', '.join(PHASE_NAMES)}.")
    if not data.reason.strip():
        raise HTTPException(400, "A written reason is required — this grant is the decision record.")
    if data.expires_at and data.expires_at <= datetime.utcnow():
        raise HTTPException(400, "Expiry must be in the future.")

    student = await tdb(request).voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(404, "That student is not on the voter register.")

    doc = org_stamp(request, {
        "student_id": normalize_student_id(data.student_id),
        "full_name": student.get("full_name", ""),
        "phase": data.phase,
        "reason": data.reason.strip(),
        "granted_by": current_actor(request),
        "granted_at": datetime.utcnow(),
        "expires_at": data.expires_at,
        "round_id": await current_round_id(request),
        "revoked": False,
    })
    result = await tdb(request).exception_grants.insert_one(doc)
    await log_action("phase_exception_granted", current_actor(request), {
        "student_id": doc["student_id"],
        "full_name": doc["full_name"],
        "phase": data.phase,
        "reason": doc["reason"],
        "expires_at": data.expires_at.isoformat() if data.expires_at else None,
    }, org_id=request.state.org_id)
    return {"status": "granted", "id": str(result.inserted_id)}


@app.post("/admin/exception-grants/{grant_id}/revoke")
async def revoke_exception_grant(grant_id: str, request: Request,
                                 admin: dict = Depends(require_chief_commissioner)):
    try:
        oid = ObjectId(grant_id)
    except Exception:
        raise HTTPException(400, "Invalid grant id.")
    grant = await tdb(request).exception_grants.find_one({"_id": oid})
    if not grant:
        raise HTTPException(404, "Grant not found.")
    await tdb(request).exception_grants.update_one(
        {"_id": oid},
        {"$set": {"revoked": True, "revoked_at": datetime.utcnow(), "revoked_by": current_actor(request)}},
    )
    await log_action("phase_exception_revoked", current_actor(request), {
        "grant_id": grant_id, "student_id": grant.get("student_id"), "phase": grant.get("phase")
    }, org_id=request.state.org_id)
    return {"status": "revoked"}


# =============================================================================
# AUDIT TRANSPARENCY  (readable by every admin role)
# =============================================================================
# The activity log and integrity chain were superadmin-only. Moving the READS
# to /admin/* makes them visible to every role under the existing "any valid
# admin token" gate. Writes (creating a checkpoint) stay superadmin-only.

@app.get("/admin/audit-log")
async def get_admin_audit_log(request: Request, limit: int = 200, action: str = None,
                              actor: str = None, skip: int = 0):
    """Shared across all five admin roles (the RecentActivity design's explicit
    full-transparency decision). /superadmin/audit-log below is the
    superadmin-only twin of this and returns entries unredacted — for
    security review (e.g. tracing a login-lockout IP) that needs the real
    value. This endpoint redacts the two detail fields that carry PII with
    no transparency benefit to a role that isn't superadmin: an admin's own
    email address (already visible to them on their own account) and a
    failed-login IP address (only ever useful for someone doing security
    review, not for "what happened" transparency)."""
    query = org_query(request)
    if action:
        query["action"] = {"$regex": re.escape(action.strip()[:60]), "$options": "i"}
    if actor:
        query["actor"] = {"$regex": re.escape(actor.strip()[:60]), "$options": "i"}
    limit = min(max(limit, 1), 500)
    skip = max(skip, 0)
    privileged = current_role(request) == "superadmin"
    if not privileged:
        hidden_actions = list(PANEL_HIDDEN_AUDIT_ACTIONS)
        if actor:
            # The actor filter runs against the STORED actor. Left in place it would let a non-superadmin
            # ask "which of these vote events did panelist X cast?" and so learn who has voted on an
            # application even though the returned actor is redacted. Vote events are therefore not
            # searchable by actor for anyone but the superadmin.
            hidden_actions.append("application_vote_cast")
        query.setdefault("$and", []).append({"action": {"$nin": hidden_actions}})
    total = await tdb(request).audit_log.count_documents(query)
    logs = []
    async for entry in tdb(request).audit_log.find(query).sort("timestamp", -1).skip(skip).limit(limit):
        entry["_id"] = str(entry["_id"])
        if not privileged:
            details = entry.get("details") or {}
            if "email" in details:
                details["email"] = _mask_email(details["email"])
            if "ip" in details:
                details["ip"] = _mask_ip(details["ip"])
            if entry.get("action") == "admin_login_locked":
                entry["actor"] = _mask_email(entry.get("actor", ""))
            _mask_audit_identifiers(entry)
            _redact_panel_audit(entry, current_role(request))
        logs.append(entry)
    return {"total": total, "limit": limit, "skip": skip, "entries": logs}


@app.get("/admin/audit/verify")
async def get_admin_audit_verify(request: Request):
    """Independently re-derives the whole hash chain from raw vote_events."""
    result = await verify_audit_chain(request)
    result["roster_ledger"] = await verify_roster_ledger(request.state.org_id)
    await log_action("audit_chain_verified", current_actor(request), {
        "valid": result.get("valid"),
        "checkpoints": result.get("checkpoints_verified"),
        "ledger_valid": result["roster_ledger"].get("valid"),
    }, org_id=request.state.org_id)
    return result


@app.get("/admin/audit/checkpoints")
async def list_audit_checkpoints(request: Request, limit: int = 100):
    limit = min(max(limit, 1), 500)
    rows = []
    async for cp in db.audit_checkpoints.find(org_query(request)).sort("to_id", -1).limit(limit):
        rows.append({
            "id": str(cp["_id"]),
            "from_id": str(cp["from_id"]) if cp.get("from_id") else None,
            "to_id": str(cp["to_id"]),
            "event_count": cp.get("event_count", 0),
            "prev_chain_hash": cp.get("prev_chain_hash"),
            "chain_hash": cp.get("chain_hash"),
            "created_at": cp.get("created_at"),
        })
    anchor_failures = await tdb(request).audit_log.count_documents(
        {"action": "audit_checkpoint_anchor_failed"}
    )
    return {"checkpoints": rows, "anchor_failures": anchor_failures}


# =============================================================================
# ANALYTICS  (read-only aggregations, shared across all admin roles)
# =============================================================================

@app.get("/admin/analytics/turnout-velocity")
async def analytics_turnout_velocity(request: Request, bucket: str = "hour"):
    """Votes cast per hour or day, built from vote_events.cast_at — collected
    since day one and never surfaced anywhere until now."""
    if bucket not in ("hour", "day"):
        raise HTTPException(400, "Bucket must be 'hour' or 'day'.")
    fmt = "%Y-%m-%dT%H:00" if bucket == "hour" else "%Y-%m-%d"
    series = []
    async for row in tdb(request).vote_events.aggregate([
        {"$match": org_query(request)},
        {"$group": {"_id": {"$dateToString": {"format": fmt, "date": "$cast_at"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]):
        series.append({"bucket": row["_id"], "votes": row["count"]})

    running = 0
    for point in series:
        running += point["votes"]
        point["cumulative"] = running

    peak = max(series, key=lambda p: p["votes"]) if series else None
    return {
        "bucket": bucket,
        "series": series,
        "total_votes": running,
        "peak": peak,
    }


@app.get("/admin/analytics/funnel")
async def analytics_funnel(request: Request):
    """Conversion between voters.last_status stages, not just a snapshot count
    of each. idle -> otp_sent -> authenticated -> completed."""
    stages = ["idle", "otp_sent", "authenticated", "completed"]
    counts = {stage: 0 for stage in stages}
    async for row in tdb(request).voters.aggregate([
        {"$match": org_query(request)},
        {"$group": {"_id": {"$ifNull": ["$last_status", "idle"]}, "count": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = counts.get(row["_id"], 0) + row["count"]

    total = sum(counts.values())
    # Each stage is cumulative: anyone who completed necessarily passed
    # through every earlier stage, so "reached" counts everyone at or beyond.
    reached, running = {}, 0
    for stage in reversed(stages):
        running += counts.get(stage, 0)
        reached[stage] = running

    steps = []
    for i, stage in enumerate(stages):
        prev = reached[stages[i - 1]] if i else total
        steps.append({
            "stage": stage,
            "at_stage": counts.get(stage, 0),
            "reached": reached[stage],
            "conversion_from_previous_pct": round((reached[stage] / prev) * 100, 1) if prev else 0.0,
            "dropped_off": max(prev - reached[stage], 0) if i else 0,
        })
    return {"total_registered": total, "steps": steps}


@app.get("/admin/analytics/undervote")
async def analytics_undervote(request: Request):
    """Positions where fewer votes were cast than there were completed voters
    — i.e. voters skipped that race. Nothing in the system checked this."""
    completed = await tdb(request).voters.count_documents({"has_voted": True})
    vote_counts = await get_vote_counts(request)

    by_position: dict[str, int] = {}
    async for cand in tdb(request).candidates.find({}).sort("order", 1):
        title = cand.get("position", "Unknown Position")
        by_position[title] = by_position.get(title, 0) + vote_counts.get(str(cand["_id"]), 0)

    rows = []
    for title, votes in by_position.items():
        skipped = max(completed - votes, 0)
        rows.append({
            "position": title,
            "votes_cast": votes,
            "eligible_completed_voters": completed,
            "undervotes": skipped,
            "undervote_rate_pct": round((skipped / completed) * 100, 1) if completed else 0.0,
            # votes_cast should never exceed completed voters — each
            # completed voter casts at most one vote_events row per
            # position. If it does, has_voted (reset by re-import — see the
            # comment in /admin/import-voters) and vote_events (only ever
            # cleared by /admin/reset-election) have fallen out of sync,
            # most likely stale tallies from a prior round that was never
            # reset. max(...) above would otherwise silently clamp this to
            # 0% skipped, which reads as "everyone voted" when the real
            # story is "these two counters disagree."
            "overcounted": max(votes - completed, 0),
        })
    rows.sort(key=lambda r: r["undervote_rate_pct"], reverse=True)
    return {"completed_voters": completed, "positions": rows}


@app.get("/admin/analytics/anomalies")
async def analytics_anomalies(request: Request, limit: int = 100):
    """Pulls the security-relevant entries out of the general activity log
    into one feed, instead of requiring someone to spot them buried in it."""
    limit = min(max(limit, 1), 300)
    watched = [
        "admin_guard_403", "admin_guard_401", "admin_login_locked",
        "otp_verify_locked", "audit_checkpoint_anchor_failed",
        "phase_exception_granted", "phase_exception_used", "phase_exception_revoked",
        "election_reset", "results_certified", "election_toggled",
        "chief_commissioner_set", "chief_commissioner_cleared",
    ]
    query = org_query(request, {"action": {"$in": watched}})
    # Mounted in Analytics for every admin role (same as /admin/audit-log),
    # so it needs the same email/IP redaction for non-superadmin readers —
    # this queries audit_log directly rather than going through that
    # endpoint, so the redaction has to be repeated here rather than shared.
    privileged = current_role(request) == "superadmin"
    events = []
    async for entry in tdb(request).audit_log.find(query).sort("timestamp", -1).limit(limit):
        entry["_id"] = str(entry["_id"])
        if not privileged:
            details = entry.get("details") or {}
            if "email" in details:
                details["email"] = _mask_email(details["email"])
            if "ip" in details:
                details["ip"] = _mask_ip(details["ip"])
            if entry.get("action") == "admin_login_locked":
                entry["actor"] = _mask_email(entry.get("actor", ""))
            _mask_audit_identifiers(entry)   # student-ID actors (OTP lockouts, phase exceptions) and free-text reasons
        events.append(entry)

    since = datetime.utcnow() - timedelta(hours=24)
    summary = []
    async for row in tdb(request).audit_log.aggregate([
        {"$match": org_query(request, {"action": {"$in": watched}, "timestamp": {"$gte": since}})},
        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]):
        summary.append({"action": row["_id"], "count_24h": row["count"]})

    return {"summary_24h": summary, "events": events}


@app.get("/admin/analytics/overview")
async def analytics_overview(request: Request):
    """Compact roster/turnout snapshot — the landing view for IT Admin, which
    previously had no visibility into election state at all."""
    total = await tdb(request).voters.count_documents({})
    voted = await tdb(request).voters.count_documents({"has_voted": True})
    config = await tdb(request).settings.find_one({"name": "election_config"}) or {}
    return {
        "total_registered": total,
        "voted": voted,
        "turnout_pct": round((voted / total) * 100, 1) if total else 0.0,
        "candidates": await tdb(request).candidates.count_documents({}),
        "positions": await tdb(request).positions.count_documents({}),
        "applications_pending": await tdb(request).applications.count_documents({"status": "pending"}),
        "student_changes_pending": await tdb(request).student_changes.count_documents({"status": "pending"}),
        "with_phone_on_file": await tdb(request).voters.count_documents({"phone_numbers": {"$ne": []}}),
        "is_open": config.get("is_open", True),
        "is_certified": config.get("is_certified", False),
    }


async def _turnout_groups(request: Request, key: str) -> list[dict]:
    """Registered/voted counts per value of one voter attribute. `key` is always taken from the org's
    own field config, never from the request. Counts only - no voter is identified."""
    pipeline = [
        {"$match": org_query(request)},
        {"$group": {"_id": f"$attrs.{key}", "registered": {"$sum": 1},
                    "voted": {"$sum": {"$cond": [{"$eq": ["$has_voted", True]}, 1, 0]}}}},
    ]
    merged: dict[str, dict] = {}
    async for g in tdb(request).voters.aggregate(pipeline):
        label = g["_id"] if isinstance(g["_id"], str) and g["_id"].strip() else UNRECORDED_LABEL
        m = merged.setdefault(label, {"label": label, "registered": 0, "voted": 0})
        m["registered"] += g["registered"]
        m["voted"] += g["voted"]
    return list(merged.values())


@app.get("/admin/analytics/turnout-breakdown")
async def analytics_turnout_breakdown(request: Request):
    """Turnout per enabled voter field (gender, programme, ...). Admin-only, live, unsuppressed counts.
    Never includes how anyone voted."""
    vf = await get_voter_fields(request)
    total = await tdb(request).voters.count_documents({})
    voted = await tdb(request).voters.count_documents({"has_voted": True})
    return {
        "total": {"registered": total, "voted": voted},
        "fields": [{"key": f["key"], "label": f["label"], "public": f["public"],
                    "groups": finish_groups(await _turnout_groups(request, f["key"]))}
                   for f in vf["fields"] if f["enabled"]],
    }


@app.get("/admin/voters/stats")
async def admin_voter_stats(request: Request, admin: dict = Depends(require_role("superadmin"))):
    """CUSTOM-1 (restored): headline voter numbers for the superadmin Voters tab.
    Counts only - no voter is identified and nothing says how anyone voted. `sections` is registered/voted
    per enabled voter field (faculty, hostel, ...); field keys come from the org's own config, never the request."""
    total = await tdb(request).voters.count_documents({})
    voted = await tdb(request).voters.count_documents({"has_voted": True})
    with_phone = await tdb(request).voters.count_documents({"phone_numbers": {"$exists": True, "$ne": []}})
    vf = await get_voter_fields(request)
    sections = []
    for f in vf["fields"]:
        if not f.get("enabled"):
            continue
        groups = sorted(await _turnout_groups(request, f["key"]), key=lambda g: (-g["registered"], g["label"]))
        for g in groups:
            g["pct"] = round(100 * g["voted"] / g["registered"], 1) if g["registered"] else 0
        sections.append({"key": f["key"], "label": f["label"], "groups": groups})
    sms = await get_sms_usage(request, {})
    return {
        "total": total, "voted": voted, "not_voted": total - voted,
        "turnout_pct": round(100 * voted / total, 1) if total else 0,
        "with_phone": with_phone, "without_phone": total - with_phone,
        "sections": sections,
        "sms": {k: sms[k] for k in ("sent_total", "sent_otp", "sent_notice", "verified_total", "budget_total",
                                    "budget_left", "budget_pct_left", "suggested_budget", "mode")},
    }


# =============================================================================
# OFFICIAL REPORT  (admin-only — declaration, signatures, cc list)
# =============================================================================
# The sworn declaration, signature grid and cc_list used to render on the
# PUBLIC results page, hidden only by a client-side `isCertified &&` check —
# which is not an access boundary, since the code ships in the public bundle
# either way. They now only exist behind this authenticated endpoint; the
# public page never fetches them.

@app.get("/admin/official-report")
async def get_official_report(request: Request):
    config = await tdb(request).settings.find_one({"name": "election_config"}) or {}
    branding = await tdb(request).settings.find_one({"name": "branding"}) or {}

    commissioners = []
    async for c in tdb(request).voters.find(
        {"is_commissioner": True},
        {"_id": 0, "full_name": 1, "commissioner_role": 1, "is_chief_commissioner": 1,
         "is_deputy_chief_commissioner": 1},
    ):
        commissioners.append(c)
    commissioners.sort(key=lambda c: (
        not c.get("is_chief_commissioner"), not c.get("is_deputy_chief_commissioner"), c.get("full_name", "")
    ))

    chief = next((c for c in commissioners if c.get("is_chief_commissioner")), None)
    commissioner_name = (
        (chief or {}).get("full_name")
        or branding.get("commissioner_name")   # legacy value only; no longer editable in Branding
        or "The Electoral Commissioner"
    )
    org_name = branding.get("org_name", "the Organisation")
    is_certified = config.get("is_certified", False)
    is_open = config.get("is_open", True)

    # Same tally source the public /election-results endpoint uses, so the
    # signed document and the public report can never show different numbers
    # for the same election. Duplicated here rather than calling the other
    # route internally because this one runs behind auth and needs to stay a
    # single round trip for the frontend.
    voter_turnout = await tdb(request).voters.count_documents({"has_voted": True})
    vote_counts = await get_vote_counts(request)
    results = []
    async for cand in tdb(request).candidates.find({}).sort("order", 1):
        results.append({
            "id": str(cand["_id"]),
            "name": cand["name"],
            "position": cand["position"],
            "votes": vote_counts.get(str(cand["_id"]), 0),
            "order": cand.get("order", 0),
        })

    # The report fingerprint is now the REAL head hash of the verified audit
    # chain, not a client-side rolling hash of whatever JSON happened to be on
    # screen. "Verified Secure" previously verified nothing.
    chain = await verify_audit_chain(request)
    fingerprint = (chain.get("head_hash") or "")[:32].upper() or "NO-CHECKPOINTS"

    declaration = None
    if is_certified:
        declaration = (
            f"I, {commissioner_name}, the duly appointed Electoral Commissioner, hereby declare that "
            f"the {org_name} elections conducted through the official online voting portal were carried "
            f"out in accordance with the {org_name} electoral guidelines and procedures. After the close "
            f"of voting and the tallying of all valid votes cast, I hereby officially declare the "
            f"successful candidates listed in the summary as the duly elected leaders of {org_name}. "
            f"I congratulate the successful candidates and extend appreciation to all aspirants, members, "
            f"and voters for participating and upholding the principles of a free, fair, and transparent election."
        )

    ledger = await verify_roster_ledger(request.state.org_id)
    sec_r = await get_security_settings(request)
    contact_changes = [
        {"student_id": _mask_student_id(c["student_id"]), "type": c["change"]["type"],
         "requested_by": c.get("requested_by"), "requested_at": c.get("requested_at"),
         "decided_by": c.get("decided_by"), "decided_at": c.get("decided_at"), "status": c.get("status"),
         "evidence_type": c.get("evidence_type"), "notice_status": c.get("notice_status"),
         "breakglass": bool(c.get("breakglass"))}
        async for c in tdb(request).contact_changes.find({
            "status": {"$in": ["approved", "denied", "expired", "failed"]},
            "requested_at": {"$gte": _epoch(sec_r)}}).sort("requested_at", 1).limit(1000)
    ]

    await log_action("official_report_generated", current_actor(request), {
        "is_certified": is_certified, "chain_valid": chain.get("valid"), "ledger_valid": ledger.get("valid")
    }, org_id=request.state.org_id)

    return {
        "is_certified": is_certified,
        "org_name": org_name,
        "university_name": branding.get("university_name", ""),
        "logo_url": branding.get("logo_url", ""),
        "university_logo_url": branding.get("university_logo_url", ""),
        "is_open": is_open,
        "voter_turnout": voter_turnout,
        "results": results,
        "commissioner_name": commissioner_name,
        "declaration": declaration,
        "signatories": branding.get("signatories") or [
            {"full_name": c.get("full_name", ""), "role": c.get("commissioner_role") or (
                "Chairperson EC" if c.get("is_chief_commissioner")
                else "Deputy Chairperson EC" if c.get("is_deputy_chief_commissioner")
                else "Commissioner"
            )}
            for c in commissioners
        ] or [
            {"full_name": "", "role": r}
            for r in ("Chairperson EC", "Secretary EC", "Commissioner", "Commissioner")
        ],
        "cc_list": branding.get("cc_list", []),
        "chain": {
            "valid": chain.get("valid"),
            "checkpoints_verified": chain.get("checkpoints_verified", 0),
            "head_hash": chain.get("head_hash"),
        },
        "fingerprint": fingerprint,
        "contact_changes": contact_changes,
        "roster_ledger": ledger,
        "generated_at": datetime.utcnow(),
        "generated_by": current_actor(request),
    }


# =============================================================================
# PUBLIC VOTER PARTICIPATION ROLL
# =============================================================================
# Results.jsx has always called /election-results/voter-roll; the route never
# existed, so the call 403'd, was swallowed by .catch(), and the roll silently
# rendered empty forever. Implemented here with the privacy threshold enforced
# SERVER-SIDE (it was previously only a client-side conditional) and names
# masked the same way the public register already masks them.

PUBLIC_ROLL_THRESHOLD = 50
PUBLIC_ROLL_MAX = 500

# The roll used to share the "register" bucket (10 requests / 60s / IP) with the searchable voter
# register, while the public results page polled it every 5s (12/min). The page tripped its own
# limit, got a 429, and the UI (which swallowed the error) fell back to "Privacy Lock Active" even
# with 1820 voters. Own bucket, sized for a 30s poll with several viewers behind one campus NAT.
ROLL_RATE_LIMIT = 30
ROLL_RATE_WINDOW_S = 60


@app.get("/election-results/voter-roll")
async def get_public_voter_roll(request: Request):
    await _check_rate_limit(
        request, bucket="voter_roll", limit=ROLL_RATE_LIMIT, window_s=ROLL_RATE_WINDOW_S,
        message="Too many requests. Please try again shortly.",
    )
    voted = await tdb(request).voters.count_documents({"has_voted": True})
    if voted < PUBLIC_ROLL_THRESHOLD:
        # Below the threshold the server returns nothing at all, so a small
        # turnout can't be de-anonymised by reading the network response.
        return {"threshold": PUBLIC_ROLL_THRESHOLD, "voted": voted, "unlocked": False, "roll": []}

    roll = []
    cursor = tdb(request).voters.find(
        {"has_voted": True}, {"_id": 0, "full_name": 1}
    ).limit(PUBLIC_ROLL_MAX)
    async for v in cursor:
        roll.append({"full_name": _mask_name(v.get("full_name", ""))})
    return {"threshold": PUBLIC_ROLL_THRESHOLD, "voted": voted, "unlocked": True, "roll": roll}


async def _election_closed(request: Request) -> bool:
    """Voting is over: master switch off, results certified, or the enforced voting window has ended."""
    cfg = await tdb(request).settings.find_one({"name": "election_config"}) or {}
    if cfg.get("is_certified") or not cfg.get("is_open", True):
        return True
    return voting_window_state(await get_phase_schedule(request), datetime.utcnow())["ended"]


@app.get("/election-results/turnout-breakdown")
async def get_public_turnout_breakdown(request: Request):
    """Public turnout split for fields the org marked `public`. Turnout only, never candidate votes.
    Withheld until the election has closed; groups under the org's minimum size are folded into
    "Other" (or the field is withheld if too little remains)."""
    await _check_rate_limit(
        request, bucket="turnout_breakdown", limit=ROLL_RATE_LIMIT, window_s=ROLL_RATE_WINDOW_S,
        message="Too many requests. Please try again shortly.",
    )
    vf = await get_voter_fields(request)
    public = [f for f in vf["fields"] if f["public"]]
    if not public or not await _election_closed(request):
        return {"available": False, "fields": []}
    out = []
    for f in public:
        res = suppress_small_groups(await _turnout_groups(request, f["key"]), vf["min_group_size"])
        out.append({"key": f["key"], "label": f["label"], **res})
    return {"available": True, "min_group_size": vf["min_group_size"], "fields": out}


# =============================================================================
# OTP_SMS_Design_v2 — ROUTES: contact-change approval, OTP-limit reset, SMS budget,
# security settings, roster status / ledger
# =============================================================================

class ContactChangeRequest(BaseModel):
    student_id: str
    change_type: str                  # phone_change | phone_add | phone_remove | registration_number_change
    index: int | None = None          # phone position (change / remove)
    expected_old: str | None = None   # what the requester saw there (409 if it moved)
    new_value: str | None = None
    evidence_type: str
    evidence_note: str = ""


class ContactChangeDecision(BaseModel):
    decision: str = "approve"         # approve | deny
    note: str = ""
    acknowledge_warnings: bool = False


class ContactChangeCancel(BaseModel):
    reason: str = ""


class OtpResetRequest(BaseModel):
    reason: str
    note: str


class CapOverride(BaseModel):
    kind: str                         # approver_daily | reset_hourly
    admin_id: str
    cap: int
    reason: str


class SecuritySettingsUpdate(BaseModel):
    reason: str
    roster_freeze_at: datetime | None = None
    clear_roster_freeze_at: bool = False
    roster_freeze_enabled: bool | None = None
    contact_change_required: bool | None = None
    otp_target_risk: float | None = None
    turnstile_mode: str | None = None
    public_results_mode: str | None = None
    contact_change_ttl_hours: int | None = None
    contact_change_max_per_voter: int | None = None
    approver_daily_cap: int | None = None
    quota_alert_pct: float | None = None
    quota_hard_cap_pct: float | None = None
    superadmin_breakglass: bool | None = None
    sms_fallback_on_timeout: bool | None = None
    sms_route_otp: str | None = None
    sms_route_other: str | None = None
    reset_admin_hourly_alert: int | None = None
    reset_admin_hourly_hard_cap: int | None = None
    reset_per_voter_daily: int | None = None
    reset_per_voter_election: int | None = None
    approval_policy: str | None = None


class SmsBudgetUpdate(BaseModel):
    reason: str
    sms_budget_total: int | None = None
    sms_mode: str | None = None
    sms_budget_enforce: bool | None = None
    sms_balance_floor_ugx: int | None = None


_SEC_RANGES = {
    "otp_target_risk": (1e-6, 0.01), "contact_change_ttl_hours": (1, 72), "contact_change_max_per_voter": (1, 10),
    "approver_daily_cap": (1, 1000), "quota_alert_pct": (0, 100), "quota_hard_cap_pct": (0, 100),
    "reset_admin_hourly_alert": (1, 10000), "reset_admin_hourly_hard_cap": (1, 10000),
    "reset_per_voter_daily": (1, 50), "reset_per_voter_election": (1, 200),
}


def _capkey(sid: str) -> str:
    return normalize_student_id(sid).replace(".", "%2E").replace("$", "%24")


async def _save_security(request: Request, updates: dict):
    await tdb(request).settings.update_one(
        {"name": "security_settings"},
        {"$set": org_stamp(request, {"name": "security_settings", **updates, "updated_at": datetime.utcnow()})},
        upsert=True)
    invalidate_settings(request.state.org_id)


async def _is_chief(request: Request) -> bool:
    try:
        await require_chief_commissioner(request)
        return True
    except HTTPException:
        return False


async def _branding(request: Request) -> dict:
    return await tdb(request).settings.find_one({"name": "branding"}) or {}


# ── Contact-change requests ─────────────────────────────────────────────────

async def _expire_contact_changes(request: Request):
    now = datetime.utcnow()
    async for c in tdb(request).contact_changes.find({"status": "pending", "expires_at": {"$lt": now}}):
        r = await tdb(request).contact_changes.update_one({"_id": c["_id"], "status": "pending"},
                                                {"$set": {"status": "expired", "decided_at": now}})
        if r.modified_count:
            await append_ledger(request.state.org_id, "contact_change_expired", c["student_id"], "system", "system",
                                {"change_id": str(c["_id"]), "type": c["change"]["type"]})


async def _validate_contact_change(data: ContactChangeRequest, voter: dict, org_id) -> dict:
    t = data.change_type
    if t not in CONTACT_CHANGE_TYPES:
        raise HTTPException(400, f"Change type must be one of: {', '.join(CONTACT_CHANGE_TYPES)}.")
    phones = list(voter.get("phone_numbers", []))
    ch: dict = {"type": t, "index": None, "expected_old": None, "new_value": None}
    if t in ("phone_change", "phone_remove"):
        if data.index is None or not 0 <= data.index < len(phones):
            raise HTTPException(400, "Phone position is out of range; reload the student and try again.")
        if data.expected_old is not None and normalize_phone_number(data.expected_old) != phones[data.index]:
            raise HTTPException(409, "The phone list changed since you loaded it; reload and try again.")
        ch["index"], ch["expected_old"] = data.index, phones[data.index]
    if t in ("phone_change", "phone_add"):
        num = normalize_phone_number(data.new_value or "")
        if num in phones:
            raise HTTPException(400, "That phone number is already on this student.")
        ch["new_value"] = num
    if t == "phone_remove" and len(phones) <= 1:
        raise HTTPException(400, "That would leave the voter with no phone number. Change the number instead.")
    if t == "registration_number_change":
        new_sid = normalize_student_id(data.new_value or "")
        if not re.fullmatch(r"[^\s\x00-\x1f]{1,64}", new_sid):
            raise HTTPException(400, f"{_cap(await id_noun(org_id))} must be 1-64 characters with no spaces.")
        if new_sid == voter["student_id"]:
            raise HTTPException(400, f"That is already this student's {await id_noun(org_id)}.")
        if any(voter.get(f) for f in STUDENT_ROLE_FLAGS):
            raise HTTPException(409, f"This student holds an admin/commission role; the {await id_noun(org_id)} cannot be changed.")
        if await tdb_for(org_id).voters.find_one({"student_id": new_sid}):
            raise HTTPException(409, f"Another student in this organization already has that {await id_noun(org_id)}.")
        ch["new_value"], ch["expected_old"] = new_sid, voter["student_id"]
    return ch


@app.post("/it-admin/contact-changes/request")
async def request_contact_change(data: ContactChangeRequest, request: Request,
                                 admin: dict = Depends(require_role("it_admin", "superadmin"))):
    org_id = require_org(request.state.org_id)
    sec = await get_security_settings(request)
    st = await roster_status(request, sec)
    if st["phase"] == "pre_freeze":
        raise HTTPException(409, "The roster is not frozen yet — edit the student directly (audit-logged).")
    if st["phase"] == "closed":
        raise HTTPException(409, "Voting has closed, so no code can be issued. Edit the student directly (audit-only).")
    if not st["contact_change_required"]:
        raise HTTPException(409, "Contact-change approval is switched off for this election — edit the student directly.")

    if data.evidence_type not in CONTACT_EVIDENCE_TYPES:
        raise HTTPException(400, f"Evidence type must be one of: {', '.join(CONTACT_EVIDENCE_TYPES)}.")
    note = data.evidence_note.strip()
    if len(note) < (20 if data.evidence_type == "other_documented" else 3):
        raise HTTPException(400, "Describe the evidence you checked (at least 20 characters for 'other_documented').")

    voter = await tdb_for(org_id).voters.find_one(get_forgiving_filter(data.student_id))
    if not voter:
        raise HTTPException(404, "Student not found in this organization.")
    if voter.get("has_voted"):
        raise HTTPException(409, "This student has already voted; their contact details can no longer be changed.")
    actor, role = current_actor(request), current_role(request)
    if normalize_student_id(actor) == voter["student_id"]:
        raise HTTPException(403, "You cannot request a change to your own record.")

    await _expire_contact_changes(request)
    approved = await tdb_for(org_id).contact_changes.count_documents({
        "student_id": voter["student_id"], "status": "approved", "requested_at": {"$gte": _epoch(sec)}})
    if approved >= sec["contact_change_max_per_voter"]:
        raise HTTPException(409, f"This voter already has {approved} approved contact changes (the maximum).")
    ch = await _validate_contact_change(data, voter, org_id)

    now = datetime.utcnow()
    doc = {"org_id": org_id, "student_id": voter["student_id"], "student_key": str(voter["_id"]),
           "full_name": voter.get("full_name", ""), "change": ch, "evidence_type": data.evidence_type,
           "evidence_note": note, "requested_by": actor, "requested_role": role, "requested_at": now,
           "status": "pending", "expires_at": now + timedelta(hours=sec["contact_change_ttl_hours"]),
           "decided_by": None, "decided_at": None, "decision_note": "", "notice_status": None}
    try:
        res = await tdb(request).contact_changes.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "This voter already has a pending contact-change request.")
    await append_ledger(org_id, "contact_change_requested", voter["student_id"], actor, role,
                        {"change_id": str(res.inserted_id), "type": ch["type"], "evidence": data.evidence_type})
    await log_action("contact_change_requested", actor, {
        "student_id": _mask_student_id(voter["student_id"]), "type": ch["type"], "evidence": data.evidence_type,
    }, org_id=org_id)
    return {"status": "requested", "id": str(res.inserted_id), "expires_at": doc["expires_at"]}


@app.post("/it-admin/contact-changes/{change_id}/cancel")
async def cancel_contact_change(change_id: str, data: ContactChangeCancel, request: Request,
                                admin: dict = Depends(require_role("it_admin", "superadmin"))):
    oid = parse_oid(change_id, "change id")
    c = await tdb(request).contact_changes.find_one({"_id": oid})
    if not c:
        raise HTTPException(404, "Request not found.")
    actor = current_actor(request)
    if current_role(request) != "superadmin" and normalize_student_id(c["requested_by"]) != normalize_student_id(actor):
        raise HTTPException(403, "You can only cancel your own requests.")
    r = await tdb(request).contact_changes.update_one(
        {"_id": oid, "status": "pending"},
        {"$set": {"status": "cancelled", "decided_by": actor, "decided_at": datetime.utcnow(),
                  "decision_note": data.reason.strip()}})
    if r.modified_count == 0:
        raise HTTPException(409, f"Cannot cancel a request that is already {c.get('status')}.")
    await append_ledger(request.state.org_id, "contact_change_cancelled", c["student_id"], actor,
                        current_role(request), {"change_id": change_id})
    return {"status": "cancelled"}


async def _cc_warnings(request: Request, c: dict) -> list[dict]:
    ch, out = c["change"], []
    nv = ch.get("new_value")
    if nv and ch["type"] != "registration_number_change":
        on_voters = await tdb(request).voters.count_documents({
            "phone_numbers": nv, "student_id": {"$ne": c["student_id"]}})
        in_pending = await tdb(request).contact_changes.count_documents({
            "status": "pending", "change.new_value": nv, "_id": {"$ne": c["_id"]}})
        if on_voters:
            out.append({"code": "new_number_on_other_voter",
                        "message": f"This new number is already registered to {on_voters} other voter(s)."})
        if in_pending:
            out.append({"code": "new_number_in_other_request",
                        "message": f"This new number is also in {in_pending} other pending request(s)."})
    return out


async def _cc_view(request: Request, c: dict, role: str) -> dict:
    ch = c["change"]
    full = role in ("it_admin", "superadmin")
    old = ch.get("expected_old")
    old_masked = (_mask_student_id(old) if ch["type"] == "registration_number_change" else _mask_phone(old)) if old else None
    live_otp = bool(await tdb(request).otps.find_one({"student_id": c["student_id"]}))
    return {
        "id": str(c["_id"]),
        "student_id": c["student_id"] if full else _mask_student_id(c["student_id"]),
        "full_name": c.get("full_name", "") if full else _mask_name(c.get("full_name", "")),
        "change_type": ch["type"], "old_masked": old_masked, "new_value": ch.get("new_value"),
        "evidence_type": c.get("evidence_type"), "evidence_note": c.get("evidence_note", ""),
        "requested_by": c.get("requested_by"), "requested_at": c.get("requested_at"),
        "status": c.get("status"), "decided_by": c.get("decided_by"), "decided_at": c.get("decided_at"),
        "decision_note": c.get("decision_note", ""), "expires_at": c.get("expires_at"),
        "notice_status": c.get("notice_status"), "breakglass": bool(c.get("breakglass")),
        "otp_in_progress": live_otp,
        "warnings": await _cc_warnings(request, c) if c.get("status") == "pending" else [],
    }


async def _cc_stats(request: Request, sec: dict) -> dict:
    since = _epoch(sec)
    rows = [c async for c in tdb(request).contact_changes.find(
        {"requested_at": {"$gte": since}, "status": {"$in": ["approved", "pending"]}},
        {"status": 1, "decided_by": 1, "change": 1, "notice_status": 1})]
    approved = [c for c in rows if c["status"] == "approved"]
    electorate = await tdb(request).voters.count_documents({})
    by_approver: dict = {}
    for c in approved:
        by_approver[c.get("decided_by")] = by_approver.get(c.get("decided_by"), 0) + 1
    top_share = (max(by_approver.values()) / len(approved)) if approved else 0.0
    seen: dict = {}
    for c in rows:
        nv = c["change"].get("new_value")
        if nv and c["change"]["type"] != "registration_number_change":
            seen[nv] = seen.get(nv, 0) + 1
    pct = (100.0 * len(approved) / electorate) if electorate else 0.0
    resets = [{"actor": a["actor"], "at": a["timestamp"]} async for a in tdb(request).audit_log.find({
        "action": "otp_reset_admin_alert", "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=24)}})
        .sort("timestamp", -1).limit(10)]
    return {
        "approved_total": len(approved), "pending_total": len(rows) - len(approved), "electorate": electorate,
        "pct_of_electorate": round(pct, 2), "approvals_by_approver": by_approver, "top_approver_share": round(top_share, 2),
        "duplicate_new_numbers": [n for n, k in seen.items() if k > 1],
        "notice_failed": sum(1 for c in approved if c.get("notice_status") == "failed"),
        "alerts": {
            "quota": pct >= sec["quota_alert_pct"], "hard_stop": pct >= sec["quota_hard_cap_pct"],
            "approver_concentration": len(approved) >= 10 and top_share > 0.70,
            "duplicate_number": any(k > 1 for k in seen.values()),
        },
        "otp_reset_alerts": resets,
        "limits": {"alert_pct": sec["quota_alert_pct"], "hard_cap_pct": sec["quota_hard_cap_pct"],
                   "approver_daily_cap": sec["approver_daily_cap"]},
    }


@app.get("/admin/contact-changes")
async def list_contact_changes(request: Request, status: str | None = None,
                               admin: dict = Depends(require_role("commission", "overseer", "it_admin", "superadmin"))):
    sec = await get_security_settings(request)
    await _expire_contact_changes(request)
    role = current_role(request)
    q = org_query(request)
    if status:
        q["status"] = status
    if role == "it_admin":
        q["requested_by"] = current_actor(request)          # IT admins only ever see their own requests
    items = [await _cc_view(request, c, role) async for c in tdb(request).contact_changes.find(q).sort("requested_at", -1).limit(300)]
    out = {"items": items, "role": role, "roster": await roster_status(request, sec)}
    if role != "it_admin":
        out["stats"] = await _cc_stats(request, sec)
    return out


@app.get("/admin/contact-changes/digest")
async def contact_changes_digest(request: Request,
                                 admin: dict = Depends(require_role("commission", "overseer", "superadmin"))):
    """Read-only list of every direct contact edit an IT admin has ever made (masked, unless the
    viewer can also undo one — see below). Not windowed to the days-before-freeze any more: an IT
    admin can edit at any time before the freeze, so limiting this to the last N days could hide
    edits made earlier in the election and let quiet misuse go unnoticed."""
    sec = await get_security_settings(request)
    st = await roster_status(request, sec)
    until = min(datetime.utcnow(), st["freeze_at"]) if st["freeze_at"] else datetime.utcnow()
    privileged = await _can_undo_digest(request, admin)
    entries = []
    async for r in tdb(request).student_edit_audit.find({
            "at": {"$lte": until},
            "event": {"$in": ["phone_added", "phone_removed", "phone_changed",
                              "student_registration_number_changed", "student_name_changed"]},
    }).sort("at", -1).limit(1000):
        mk = ({"student_registration_number_changed": _mask_student_id,
               "student_name_changed": _mask_name}.get(r["event"], _mask_phone))
        entries.append({
            "id": str(r["_id"]), "at": r["at"], "event": r["event"],
            "student_id": r.get("student_id_after", "") if privileged else _mask_student_id(r.get("student_id_after", "")),
            "old": (r.get("old_value") if privileged else (mk(r["old_value"]) if r.get("old_value") else None)),
            "new": (r.get("new_value") if privileged else (mk(r["new_value"]) if r.get("new_value") else None)),
            "actor": r.get("actor"), "reason": r.get("reason"),
            "undone_at": r.get("undone_at"), "undone_by": r.get("undone_by"), "undo_reason": r.get("undo_reason"),
            "can_undo": privileged and not r.get("undone_at") and not r.get("undoes"),
        })
    return {"freeze_at": st["freeze_at"], "entries": entries, "can_undo": privileged}


async def _can_undo_digest(request: Request, admin: dict) -> bool:
    return await _is_chief_or_deputy(request, admin)


class UndoDigestEntry(BaseModel):
    reason: str


@app.post("/admin/contact-changes/digest/{entry_id}/undo")
async def undo_digest_entry(entry_id: str, data: UndoDigestEntry, request: Request,
                            admin: dict = Depends(require_chief_commissioner)):
    """Reverse a single direct IT-admin edit (phone, registration-number, or name change) found in
    the pre-freeze digest. SuperAdmin, Chief Commissioner or Deputy Chief Commissioner only. Always
    requires a written reason, and the reversal itself is written back into the same audit trail
    so the undo is just as visible as the original edit was."""
    reason = data.reason.strip()
    if len(reason) < 10:
        raise HTTPException(400, "Undoing a change needs a written reason (10+ characters).")

    org_id = require_org(request.state.org_id)
    oid = parse_oid(entry_id, "entry id")
    rec = await tdb(request).student_edit_audit.find_one({"org_id": org_id, "_id": oid})
    if not rec:
        raise HTTPException(404, "Audit entry not found.")
    if rec.get("event") not in ("phone_added", "phone_removed", "phone_changed",
                                "student_registration_number_changed", "student_name_changed"):
        raise HTTPException(400, "This kind of entry can't be undone here.")
    if rec.get("undone_at"):
        raise HTTPException(409, "This change was already undone.")
    if rec.get("undoes"):
        raise HTTPException(400, "This entry is itself an undo and can't be undone again here.")

    voter = await tdb(request).voters.find_one({"org_id": org_id, "_id": ObjectId(rec["student_key"])})
    if not voter:
        raise HTTPException(404, "The student this change applied to no longer exists.")

    field = rec["field"]
    old_value, new_value = rec.get("old_value"), rec.get("new_value")
    actor, role = current_actor(request), current_role(request)
    new_voter_sid = voter["student_id"]

    if field == "student_id":
        if voter["student_id"] != new_value:
            raise HTTPException(409, f"The {await id_noun(org_id)} has changed again since this edit; review manually.")
        if await tdb(request).voters.find_one({"org_id": org_id, "student_id": old_value, "_id": {"$ne": voter["_id"]}}):
            raise HTTPException(409, f"Another student now holds that {await id_noun(org_id)}; can't restore it automatically.")
        await tdb(request).voters.update_one({"_id": voter["_id"]}, {"$set": {"student_id": old_value}})
        _t = tdb_for(org_id)
        for coll in (_t.applications, _t.exception_grants, _t.contact_changes, _t.candidate_tokens):
            await coll.update_many({"student_id": new_value}, {"$set": {"student_id": old_value}})
        new_voter_sid = old_value
    elif field == "phone_numbers":
        phones = list(voter.get("phone_numbers", []))
        if rec["event"] == "phone_added":
            if new_value not in phones:
                raise HTTPException(409, "That phone number is no longer on this student; nothing to undo.")
            phones.remove(new_value)
        elif rec["event"] == "phone_removed":
            if old_value in phones:
                raise HTTPException(409, "That phone number is already back on this student.")
            phones.append(old_value)
        else:  # phone_changed
            if new_value not in phones:
                raise HTTPException(409, "The phone number has changed again since this edit; review manually.")
            phones[phones.index(new_value)] = old_value
        await tdb(request).voters.update_one({"_id": voter["_id"]}, {"$set": {"phone_numbers": phones}})
    elif field == "full_name":
        if voter.get("full_name", "") != new_value:
            raise HTTPException(409, "The name has changed again since this edit; review manually.")
        await tdb(request).voters.update_one({"_id": voter["_id"]}, {"$set": {"full_name": old_value}})
    else:
        raise HTTPException(400, "This kind of entry can't be undone here.")

    now = datetime.utcnow()
    await tdb(request).student_edit_audit.update_one({"_id": rec["_id"]}, {"$set": {
        "undone_at": now, "undone_by": actor, "undo_reason": reason}})
    await tdb(request).student_edit_audit.insert_one({
        "org_id": org_id, "student_key": rec["student_key"], "batch": secrets.token_hex(8),
        "event": f"{rec['event']}_undone", "field": field, "old_value": new_value, "new_value": old_value,
        "reason": reason, "actor": actor, "actor_role": role, "at": now,
        "student_id_before": voter["student_id"], "student_id_after": new_voter_sid,
        "search_terms": [], "undoes": str(rec["_id"]),
    })
    await log_action(f"{rec['event']}_undone", actor, {
        "student_id": new_voter_sid, "role": role, "reason": reason, "field": field,
    }, org_id=org_id)
    return {"status": "undone"}


async def _notify_old_number(request: Request, c: dict, old_phones: list[str], new_sid: str) -> str:
    """Best-effort notice (no code inside) to the number that just lost control. Counted toward the SMS budget."""
    ch = c["change"]
    old = ch.get("expected_old") if ch["type"] in ("phone_change", "phone_remove") else (old_phones[0] if old_phones else None)
    if not old:
        return "failed"
    b = await _branding(request)
    org = b.get("org_name", "the election")
    when = datetime.utcnow().strftime("%H:%M UTC")
    what = {"phone_change": "The phone number on", "phone_remove": "A phone number on",
            "phone_add": "A phone number was added to", "registration_number_change": f"The {_id_noun_from(b)} on"}[ch["type"]]
    tail = " was changed" if ch["type"] in ("phone_change", "registration_number_change") else (
        " was removed" if ch["type"] == "phone_remove" else "")
    reach = b.get("support_phone") or next(
        (c.get("link") for g in (b.get("support_contacts") or []) for c in (g.get("contacts") or []) if c.get("link")), "")
    contact = f" If this was not you, contact {reach}." if reach else " If this was not you, contact the Electoral Commission."
    text = f"{what} the {org} voting register{tail} at {when}.{contact}" if ch["type"] != "phone_add" else \
           f"{what} the {org} voting register at {when}.{contact}"
    return "sent" if await send_sms(old, text, request, kind="notice") else "failed"


async def _decide_contact_change(change_id: str, data: ContactChangeDecision, request: Request, breakglass: bool):
    if data.decision not in ("approve", "deny"):
        raise HTTPException(400, "Decision must be 'approve' or 'deny'.")
    note = data.note.strip()
    if data.decision == "deny" and len(note) < 3:
        raise HTTPException(400, "A denial needs a note.")
    if breakglass and len(note) < 10:
        raise HTTPException(400, "Break-glass approval needs a written justification (10+ characters).")
    org_id, oid = request.state.org_id, parse_oid(change_id, "change id")
    sec = await get_security_settings(request)
    await _expire_contact_changes(request)
    c = await tdb(request).contact_changes.find_one({"_id": oid})
    if not c:
        raise HTTPException(404, "Contact-change request not found.")
    if c["status"] != "pending":
        raise HTTPException(409, f"This request is already {c['status']}. Please refresh.")

    actor, role = current_actor(request), current_role(request)
    actor_n = normalize_student_id(actor)
    if actor_n == normalize_student_id(c["requested_by"]):
        raise HTTPException(403, "The person who requested a change cannot decide it.")
    if actor_n == c["student_id"]:
        raise HTTPException(403, "You cannot decide a change to your own record.")
    if role == "commission" and not await tdb(request).voters.find_one({
            **get_forgiving_filter(actor), "is_commissioner": True}):
        raise HTTPException(403, "Not a registered commissioner.")

    now = datetime.utcnow()
    if data.decision == "approve":
        warnings = await _cc_warnings(request, c)
        if warnings and not data.acknowledge_warnings:
            raise ApiError(409, "Please review the warnings and tick 'I have checked' to approve.",
                           "warnings_unacknowledged", warnings=warnings)
        cap = (sec["cap_overrides"].get("approver_daily") or {}).get(_capkey(actor), sec["approver_daily_cap"])
        done_today = await tdb(request).contact_changes.count_documents({
            "decided_by": actor, "status": "approved", "decided_at": {"$gte": now - timedelta(days=1)}})
        if done_today >= cap:
            raise ApiError(429, f"Daily approval limit reached ({cap}). The chief commissioner can raise it.", "approver_cap")
        electorate = await tdb(request).voters.count_documents({})
        total_approved = await tdb(request).contact_changes.count_documents({
            "status": "approved", "requested_at": {"$gte": _epoch(sec)}})
        if electorate and 100.0 * total_approved / electorate >= sec["quota_hard_cap_pct"] and not await _is_chief(request):
            raise ApiError(409, "The election-wide contact-change limit has been reached. "
                                "Only the chief commissioner can approve further changes.", "quota_hard_stop")

    claim = await tdb(request).contact_changes.update_one(
        {"_id": oid, "status": "pending", "expires_at": {"$gt": now}},
        {"$set": {"status": "approved" if data.decision == "approve" else "denied", "decided_by": actor,
                  "decided_role": role, "decided_at": now, "decision_note": note, "breakglass": breakglass,
                  "warnings_acknowledged": bool(data.acknowledge_warnings)}})
    if claim.matched_count == 0:
        raise HTTPException(409, "This request was just decided by someone else or has expired. Please refresh.")

    sid_masked = _mask_student_id(c["student_id"])
    if data.decision == "deny":
        await append_ledger(org_id, "contact_change_denied", c["student_id"], actor, role,
                            {"change_id": change_id, "requested_by": c["requested_by"]})
        await log_action("contact_change_denied", actor, {"student_id": sid_masked, "requested_by": c["requested_by"]}, org_id=org_id)
        return {"status": "denied"}

    async def _fail(msg: str):
        await tdb(request).contact_changes.update_one({"_id": oid}, {"$set": {"status": "failed", "decision_note": f"{note} | FAILED: {msg}"}})
        await append_ledger(org_id, "contact_change_failed", c["student_id"], actor, role, {"change_id": change_id, "why": msg})

    voter = await tdb_for(org_id).voters.find_one({"_id": ObjectId(c["student_key"])})
    if not voter or voter.get("has_voted"):
        await _fail("voter missing or already voted")
        raise HTTPException(409, "This voter has already voted (or was removed), so the change was not applied.")
    ch = c["change"]
    try:
        res = await _apply_student_edit(
            org_id, voter,
            None, ch["new_value"] if ch["type"] == "registration_number_change" else None,
            {"phone_change": [StudentPhoneOp(op="change", index=ch["index"], expected_old=ch["expected_old"], number=ch["new_value"])],
             "phone_remove": [StudentPhoneOp(op="remove", index=ch["index"], expected_old=ch["expected_old"])],
             "phone_add": [StudentPhoneOp(op="add", number=ch["new_value"])]}.get(ch["type"], []))
    except HTTPException as e:
        await _fail(str(e.detail))
        raise

    await _write_student_audit(org_id, voter, res, f"[contact change] {c['evidence_type']}: {c['evidence_note']}", actor, role,
                               {"requested_by": c["requested_by"], "approved_by": actor, "change_id": change_id})
    await reset_voter_otp_state(org_id, [res["old_sid"], res["new_sid"]])       # D5: nothing issued before survives
    notice = await _notify_old_number(request, c, res["old_phones"], res["new_sid"])
    await tdb(request).contact_changes.update_one({"_id": oid}, {"$set": {"notice_status": notice}})
    await append_ledger(org_id, "contact_change_approved", res["new_sid"], actor, role, {
        "change_id": change_id, "type": ch["type"], "requested_by": c["requested_by"], "evidence": c["evidence_type"],
        "notice": notice, "breakglass": breakglass})
    if notice == "failed":
        await append_ledger(org_id, "contact_change_notice_failed", res["new_sid"], "system", "system", {"change_id": change_id})
    await log_action("contact_change_approved" if not breakglass else "contact_change_breakglass", actor, {
        "student_id": _mask_student_id(res["new_sid"]), "type": ch["type"], "requested_by": c["requested_by"],
        "notice": notice, "breakglass": breakglass}, org_id=org_id)

    electorate = await tdb(request).voters.count_documents({})
    total_approved = await tdb(request).contact_changes.count_documents({
        "status": "approved", "requested_at": {"$gte": _epoch(sec)}})
    if electorate and 100.0 * total_approved / electorate >= sec["quota_alert_pct"] and not await tdb(request).roster_ledger.find_one(
            {"org_id": org_id, "event": "contact_quota_alert", "ts": {"$gte": _epoch(sec)}}):
        await append_ledger(org_id, "contact_quota_alert", "election", "system", "system", {"approved": total_approved})
        await log_action("contact_change_quota_alert", "system", {"approved": total_approved, "electorate": electorate}, org_id=org_id)
    return {"status": "approved", "notice_status": notice}


@app.post("/admin/contact-changes/{change_id}/decide")
async def decide_contact_change(change_id: str, data: ContactChangeDecision, request: Request,
                                admin: dict = Depends(require_role("commission"))):
    """Any ONE commissioner may decide (D7). it_admin / overseer / financial_controller are refused by role."""
    return await _decide_contact_change(change_id, data, request, breakglass=False)


@app.post("/superadmin/contact-changes/{change_id}/force-approve")
async def superadmin_force_contact_change(change_id: str, data: ContactChangeDecision, request: Request):
    """Break-glass only (CONTACT_CHANGE_SUPERADMIN_BREAKGLASS): flagged red in the ledger and overseer feed."""
    sec = await get_security_settings(request)
    if not sec["superadmin_breakglass"]:
        raise HTTPException(403, "Superadmin break-glass approval is disabled for contact changes.")
    data.decision = "approve"
    return await _decide_contact_change(change_id, data, request, breakglass=True)


@app.post("/admin/caps/override")
async def override_cap(data: CapOverride, request: Request, admin: dict = Depends(require_chief_commissioner)):
    """Chief commissioner raises one person's approval cap (approver_daily) or reset cap (reset_hourly)."""
    if data.kind not in ("approver_daily", "reset_hourly"):
        raise HTTPException(400, "Kind must be 'approver_daily' or 'reset_hourly'.")
    if not 1 <= data.cap <= 10000 or len(data.reason.strip()) < 3:
        raise HTTPException(400, "The cap must be between 1 and 10000, and a reason is required.")
    await _save_security(request, {f"cap_overrides.{data.kind}.{_capkey(data.admin_id)}": data.cap})
    await append_ledger(request.state.org_id, "cap_override", normalize_student_id(data.admin_id), current_actor(request),
                        current_role(request), {"kind": data.kind, "cap": data.cap, "reason": data.reason.strip()})
    await log_action("cap_override", current_actor(request), {"kind": data.kind, "admin": data.admin_id, "cap": data.cap},
                     org_id=request.state.org_id)
    return {"status": "saved"}


@app.get("/admin/otp/voter-search")
async def search_voters_for_otp_reset(q: str, request: Request,
                                       admin: dict = Depends(require_role("it_admin", "commission", "superadmin"))):
    """Name/registration-number search for the Reset OTP panel only. Deliberately
    separate from /admin/students/lookup (which is IT-admin/superadmin only and
    exposes phone numbers for editing) — this returns just enough to pick the
    right voter and never phone numbers."""
    q = q.strip()
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    cur = tdb(request).voters.find({"$or": [{"student_id": rx}, {"full_name": rx}]},
                          {"_id": 0, "student_id": 1, "full_name": 1}).limit(10)
    return [{"student_id": v["student_id"], "full_name": v.get("full_name", "")} async for v in cur]


@app.get("/admin/otp/admin-search")
async def search_admins_for_cap_override(q: str, request: Request,
                                          admin: dict = Depends(require_chief_commissioner)):
    """Name/login-id search for 'Raise one person's cap'. Matches anyone holding
    an admin role (commissioner, IT admin, financial controller, overseer) so
    Chief/Deputy/superadmin don't have to know someone's exact login ID."""
    q = q.strip()
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    role_labels = {
        "is_chief_commissioner": "Chief Commissioner",
        "is_deputy_chief_commissioner": "Deputy Chairperson",
        "is_commissioner": "Commissioner",
        "is_it_admin": "IT Admin",
        "is_financial_controller": "Financial Controller",
        "is_overseer": "Overseer",
    }
    cur = tdb(request).voters.find({
        "$and": [
            {"$or": [{"student_id": rx}, {"full_name": rx}]},
            {"$or": [{f: True} for f in STUDENT_ROLE_FLAGS]},
        ]
    }, {"_id": 0, "student_id": 1, "full_name": 1, **{f: 1 for f in role_labels}}).limit(10)
    out = []
    async for v in cur:
        label = next((label for flag, label in role_labels.items() if v.get(flag)), "Admin")
        out.append({"id": v["student_id"], "name": v.get("full_name", ""), "role": label})
    return out


# ── Part E: admin "Reset OTP limits" ────────────────────────────────────────

@app.post("/admin/voters/{student_id:path}/reset-otp-limits")
async def reset_otp_limits(student_id: str, data: OtpResetRequest, request: Request,
                           admin: dict = Depends(require_role("it_admin", "commission", "superadmin"))):
    """Clears the send ladder and guess bucket. NEVER reveals or creates a code."""
    if data.reason not in RESET_REASONS:
        raise HTTPException(400, f"Reason must be one of: {', '.join(RESET_REASONS)}.")
    if len(data.note.strip()) < 3:
        raise HTTPException(400, "A short note is required.")
    org_id, sec = request.state.org_id, await get_security_settings(request)
    voter = await tdb(request).voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    sid, actor, role, now = voter["student_id"], current_actor(request), current_role(request), datetime.utcnow()
    base = {"org_id": org_id, "event": "otp_limits_reset", "ts": {"$gte": _epoch(sec)}}

    if await tdb(request).roster_ledger.count_documents({**base, "ref_id": sid, "ts": {"$gte": max(_epoch(sec), now - timedelta(days=1))}}) \
            >= sec["reset_per_voter_daily"]:
        raise ApiError(429, "This voter has reached today's reset limit. Ask the commission to review.", "reset_voter_daily_cap")
    if await tdb(request).roster_ledger.count_documents({**base, "ref_id": sid}) >= sec["reset_per_voter_election"]:
        raise ApiError(429, "This voter has reached the reset limit for this election.", "reset_voter_election_cap")

    hourly = await tdb(request).roster_ledger.count_documents({**base, "actor": actor, "ts": {"$gte": now - timedelta(hours=1)}})
    hard = (sec["cap_overrides"].get("reset_hourly") or {}).get(_capkey(actor), sec["reset_admin_hourly_hard_cap"])
    if hourly >= hard:
        raise ApiError(429, f"Hourly reset limit reached ({hard}). The chief commissioner can lift it.", "reset_admin_hard_cap")

    await clear_otp_limit_state(org_id, [sid])
    await append_ledger(org_id, "otp_limits_reset", sid, actor, role, {"reason": data.reason, "note": data.note.strip()})
    await log_action("otp_limits_reset", actor, {"student_id": _mask_student_id(sid), "reason": data.reason, "role": role}, org_id=org_id)
    if hourly + 1 > sec["reset_admin_hourly_alert"] and not await tdb(request).audit_log.find_one({
            "action": "otp_reset_admin_alert", "actor": actor, "timestamp": {"$gte": now - timedelta(hours=1)}}):
        await log_action("otp_reset_admin_alert", actor, {"resets_last_hour": hourly + 1}, org_id=org_id)   # alert only, never blocks
    return {"status": "reset"}


# ── Roster status, ledger, SMS usage, settings ──────────────────────────────

@app.get("/admin/roster-status")
async def get_roster_status(request: Request):
    st = await roster_status(request)
    return {**st, "server_time": datetime.utcnow()}


@app.get("/admin/roster-ledger/verify")
async def get_roster_ledger_verify(request: Request, admin: dict = Depends(require_role("superadmin", "commission", "overseer"))):
    return await verify_roster_ledger(request.state.org_id)


@app.get("/admin/sms-usage")
async def get_sms_usage(request: Request, admin: dict = Depends(require_role("superadmin", "overseer", "commission"))):
    sec, usage = await get_security_settings(request), await sms_usage_doc(request.state.org_id)
    now = datetime.utcnow()
    cut = now - timedelta(seconds=ol.GUARD_WINDOW_S)
    s30 = sum(1 for t in usage.get("recent_sends", []) if t > cut)
    v30 = sum(1 for t in usage.get("recent_verifies", []) if t > cut)
    sent_otp, verified = usage.get("sent_otp", 0), usage.get("verified_total", 0)
    total = sec["sms_budget_total"]
    voters = await tdb(request).voters.count_documents({})
    return {
        "sent_total": usage.get("sent_total", 0), "sent_otp": sent_otp, "sent_notice": usage.get("sent_notice", 0),
        "verified_total": verified, "send_to_verify_ratio": round(verified / sent_otp, 3) if sent_otp else None,
        "recent": {"sends_30m": s30, "verifies_30m": v30, "ratio_30m": round(v30 / s30, 3) if s30 else None},
        "budget_total": total, "budget_left": (total - usage.get("sent_total", 0)) if total else None,
        "budget_pct_left": round(100 * (total - usage.get("sent_total", 0)) / total, 1) if total else None,
        "mode": current_sms_mode(sec, usage), "budget_enforced": sec["sms_budget_enforce"],
        "alerts_fired": sorted(usage.get("alerts_fired", []), reverse=True),
        "balance_floor_ugx": sec.get("sms_balance_floor_ugx"),
        "voters": voters, "suggested_budget": math.ceil(voters * SMS_BUDGET_DEFAULT_MULTIPLIER),
        "turnstile_mode": sec["turnstile_mode"],
        "sms_route_otp": sec["sms_route_otp"], "sms_route_other": sec["sms_route_other"],
    }


@app.get("/superadmin/sms-budget")
async def superadmin_get_sms_budget(request: Request):
    return await get_sms_usage(request, {})


@app.put("/superadmin/sms-budget")
async def superadmin_put_sms_budget(data: SmsBudgetUpdate, request: Request):
    if len(data.reason.strip()) < 3:
        raise HTTPException(400, "A reason is required.")
    sec, updates = await get_security_settings(request), {}
    if data.sms_budget_total is not None:
        if data.sms_budget_total < 0:
            raise HTTPException(400, "Budget cannot be negative.")
        updates["sms_budget_total"] = data.sms_budget_total
    if data.sms_mode is not None:
        if data.sms_mode not in ("normal", "conservation"):
            raise HTTPException(400, "SMS mode must be 'normal' or 'conservation'.")
        updates["sms_mode"] = data.sms_mode
    if data.sms_budget_enforce is not None:
        updates["sms_budget_enforce"] = data.sms_budget_enforce
    if data.sms_balance_floor_ugx is not None:
        if data.sms_balance_floor_ugx < 0:
            raise HTTPException(400, "Balance floor cannot be negative.")
        updates["sms_balance_floor_ugx"] = data.sms_balance_floor_ugx or None
    if not updates:
        raise HTTPException(400, "Nothing to change.")
    await _save_security(request, updates)
    if "sms_budget_total" in updates:      # a top-up re-arms the 50/25/10 % alerts
        await db.sms_usage.update_one({"org_key": request.state.org_id or "default"}, {"$set": {"alerts_fired": []}})
    diff = {k: {"old": sec.get(k), "new": v} for k, v in updates.items()}
    await log_action("sms_budget_changed", current_actor(request), {"reason": data.reason.strip(), "changes": diff}, org_id=request.state.org_id)
    await append_ledger(request.state.org_id, "sms_budget_changed", "election", current_actor(request), "superadmin",
                        {"reason": data.reason.strip(), **{k: str(v["new"]) for k, v in diff.items()}})
    return await get_sms_usage(request, {})


@app.get("/superadmin/security-settings")
async def superadmin_get_security_settings(request: Request):
    sec = await get_security_settings(request)
    params = await guess_params(request, sec)
    voters = await tdb(request).voters.count_documents({})
    return {
        "settings": {k: v for k, v in sec.items() if k not in ("cap_overrides", "epoch_at", "freeze_lifted_at")},
        "roster": await roster_status(request, sec),
        "derived": {
            "voting_window_seconds": params["window_s"], "window_scheduled": not params["window_is_default"],
            "guess_budget": round(params["budget"], 1), "refill_interval_seconds": round(params["interval"]),
            "free_guesses": ol.FREE_GUESSES, "suggested_sms_budget": math.ceil(voters * SMS_BUDGET_DEFAULT_MULTIPLIER),
            "turnstile_secret_configured": bool(TURNSTILE_SECRET),
            "sms_providers_configured": {"egosms": bool(EGOSMS_USER and EGOSMS_PASS), "mambosms": bool(MAMBOSMS_API_KEY)},
            "sms_routes": list(SMS_ROUTES),
        },
        "banner": None if not params["window_is_default"] else
                  f"Voting window not scheduled — using {ol.DEFAULT_WINDOW_HOURS} h defaults for lock strength.",
    }


@app.put("/superadmin/security-settings")
async def superadmin_put_security_settings(data: SecuritySettingsUpdate, request: Request):
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every settings change.")
    sec, updates = await get_security_settings(request), {}
    for f in ("roster_freeze_enabled", "contact_change_required", "superadmin_breakglass",
              "sms_fallback_on_timeout"):
        if getattr(data, f) is not None:
            updates[f] = getattr(data, f)
    for f, (lo, hi) in _SEC_RANGES.items():
        v = getattr(data, f)
        if v is not None:
            if not lo <= v <= hi:
                raise HTTPException(400, f"{f.replace('_', ' ').capitalize()} must be between {lo} and {hi}.")
            updates[f] = v
    if data.turnstile_mode is not None:
        if data.turnstile_mode not in ("off", "adaptive", "on"):
            raise HTTPException(400, "Bot check mode must be 'off', 'adaptive' or 'on'.")
        updates["turnstile_mode"] = data.turnstile_mode
    if data.public_results_mode is not None:
        if data.public_results_mode not in ("live", "closed", "certified"):
            raise HTTPException(400, "Public results mode must be 'live', 'closed' or 'certified'.")
        updates["public_results_mode"] = data.public_results_mode
    for f in ("sms_route_otp", "sms_route_other"):
        v = getattr(data, f)
        if v is not None:
            if v not in SMS_ROUTES:
                raise HTTPException(400, f"The {'OTP' if f == 'sms_route_otp' else 'other-messages'} SMS route must be one of: {', '.join(SMS_ROUTES)}.")
            updates[f] = v
    if data.approval_policy is not None:
        if data.approval_policy not in VALID_APPROVAL_POLICIES:
            raise HTTPException(400, f"Approval policy must be one of: {', '.join(sorted(VALID_APPROVAL_POLICIES))}.")
        updates["approval_policy"] = data.approval_policy
    if data.clear_roster_freeze_at:
        updates["roster_freeze_at"] = None
    elif data.roster_freeze_at is not None:
        updates["roster_freeze_at"] = data.roster_freeze_at
    if "reset_admin_hourly_alert" in updates or "reset_admin_hourly_hard_cap" in updates:
        a = updates.get("reset_admin_hourly_alert", sec["reset_admin_hourly_alert"])
        h = updates.get("reset_admin_hourly_hard_cap", sec["reset_admin_hourly_hard_cap"])
        if a >= h:
            raise HTTPException(400, "The hourly alert threshold must be below the hard cap.")
    if not updates:
        raise HTTPException(400, "Nothing to change.")
    await _save_security(request, updates)
    # Only log fields that actually changed value — `updates` includes every
    # field the client sent, even ones resubmitted unchanged (e.g. a form that
    # posts its whole state), which was flooding the activity log with
    # "old: X, new: X" noise for every save.
    diff = {k: {"old": str(sec.get(k)), "new": str(v)} for k, v in updates.items() if str(sec.get(k)) != str(v)}
    actor = current_actor(request)
    if diff:
        await log_action("security_settings_changed", actor, {"reason": reason, "changes": diff}, org_id=request.state.org_id)
        await append_ledger(request.state.org_id, "security_settings_changed", "election", actor, "superadmin",
                            {"reason": reason, **{k: v["new"] for k, v in diff.items()}})
    warning = None
    # Only when the policy actually CHANGED. The Security form posts every field on each save, so
    # `"approval_policy" in updates` is true even for an unrelated edit; re-evaluating every open
    # application each time was slow and could fail AFTER the new settings were already stored,
    # which showed "Save failed" for a save that had in fact been applied.
    if "approval_policy" in diff:
        try:
            await _resweep_pending_after_policy_change(request.state.org_id)
            await log_action("approval_policy_resweep", actor, {
                "reason": reason, "new_policy": updates["approval_policy"],
            }, org_id=request.state.org_id)
        except Exception:
            # The settings are saved and logged; report the follow-up problem instead of a false failure.
            logger.exception("approval_policy resweep failed after the policy was saved")
            warning = ("Settings saved, but re-checking the open applications under the new approval policy "
                       "failed. They will be re-evaluated as new votes arrive; check the server log.")
    out = await superadmin_get_security_settings(request)
    if warning:
        out["warning"] = warning
    return out


# ── Optional voter fields (gender / programme / custom) ─────────────────────
# Per-org switchable attributes stored under voter["attrs"][key]. `enabled` = read from imports and
# shown in the admin turnout breakdown; `public` = also publish the turnout split (never how anyone
# voted) after the election closes. Turning a field off keeps its data (re-enable is lossless); use
# `purge` to erase stored values. Removing a custom field purges it.

class VoterFieldEdit(BaseModel):
    key: str
    label: str | None = None
    enabled: bool | None = None
    public: bool | None = None


class VoterFieldsUpdate(BaseModel):
    reason: str
    fields: list[VoterFieldEdit] = []     # upsert; an unknown key creates a custom field
    remove: list[str] = []                # custom fields to delete (values purged)
    purge: list[str] = []                 # erase stored values, keep the field definition
    min_group_size: int | None = None     # public turnout groups smaller than this are folded into "Other"


@app.get("/superadmin/voter-fields")
async def superadmin_get_voter_fields(request: Request):
    return await get_voter_fields(request)


@app.put("/superadmin/voter-fields")
async def superadmin_put_voter_fields(data: VoterFieldsUpdate, request: Request):
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every change.")
    cur = await get_voter_fields(request)
    try:
        new_fields, removed = apply_field_changes(
            cur["fields"], [f.dict(exclude_unset=True) for f in data.fields], data.remove)
    except ValueError as e:
        raise HTTPException(400, str(e))
    known = {f["key"] for f in cur["fields"]}
    if any(k not in known for k in data.purge):
        raise HTTPException(400, "Unknown field in purge list.")
    min_group = cur["min_group_size"]
    if data.min_group_size is not None:
        lo, hi = MIN_GROUP_RANGE
        if not lo <= data.min_group_size <= hi:
            raise HTTPException(400, f"min_group_size must be between {lo} and {hi}.")
        min_group = data.min_group_size
    purge = sorted(set(data.purge) | set(removed))
    if new_fields == cur["fields"] and min_group == cur["min_group_size"] and not purge:
        raise HTTPException(400, "Nothing to change.")

    await tdb(request).settings.update_one(
        {"name": "voter_fields"},
        {"$set": org_stamp(request, {
            "name": "voter_fields", "min_group_size": min_group, "updated_at": datetime.utcnow(),
            "fields": [{k: f[k] for k in ("key", "label", "enabled", "public")} for f in new_fields]})},
        upsert=True)
    if purge:
        await tdb(request).voters.update_many({}, {"$unset": {f"attrs.{k}": "" for k in purge}})

    def brief(fl): return {f["key"]: (f["enabled"], f["public"]) for f in fl}
    details = {"reason": reason, "fields": {k: {"enabled": v[0], "public": v[1]} for k, v in brief(new_fields).items()
                                            if brief(cur["fields"]).get(k) != v},
               "removed": removed, "purged": purge, "min_group_size": min_group}
    actor = current_actor(request)
    await log_action("voter_fields_changed", actor, details, org_id=request.state.org_id)
    await append_ledger(request.state.org_id, "voter_fields_changed", "roster", actor, "superadmin", details)
    return await get_voter_fields(request)


# ── Mobile Money payment details (shown with the nomination fees) ───────────
# One number + the name it is registered under, per org. Applicants are told to pay this number, so a
# change is superadmin-only, needs a reason, and is written to the audit log with the old and new value.

# =============================================================================
# UPLOAD BYPASS  (superadmin switch)
# =============================================================================
# When ON, IT admins can add already-paid voters without a reason / proof of payment and without
# waiting for Financial Controller approval. OFF by default. Every flip is audit-logged + ledgered.

async def upload_bypass_enabled(request: Request) -> bool:
    doc = await tdb(request).settings.find_one({"name": "upload_bypass"}) or {}
    return bool(doc.get("enabled"))


@app.get("/admin/upload-bypass")
async def get_upload_bypass(request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    return {"enabled": await upload_bypass_enabled(request)}


class UploadBypassUpdate(BaseModel):
    enabled: bool
    reason: str = Field(..., max_length=300)


@app.put("/superadmin/upload-bypass")
async def superadmin_put_upload_bypass(data: UploadBypassUpdate, request: Request,
                                       admin: dict = Depends(require_role("superadmin"))):
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every change.")
    await tdb(request).settings.update_one(
        {"name": "upload_bypass"},
        {"$set": org_stamp(request, {"name": "upload_bypass", "enabled": data.enabled,
                                     "updated_by": current_actor(request), "updated_at": datetime.utcnow()})},
        upsert=True)
    details = {"enabled": data.enabled, "reason": reason}
    await log_action("upload_bypass_changed", current_actor(request), details, org_id=request.state.org_id)
    await append_ledger(request.state.org_id, "upload_bypass_changed", "roster", current_actor(request),
                        "superadmin", details)
    return {"enabled": data.enabled}


PAYMENT_NAME_MAX_LEN = 60


def _clean_momo_number(raw: str) -> str:
    """'0772 123-456' / '+256 772 123 456' -> '256772123456'. Other countries' numbers keep their digits."""
    n = re.sub(r"[\s\-().]", "", raw or "")
    if n.startswith("+"):
        n = n[1:]
    if not n.isdigit() or not 7 <= len(n) <= 15:
        raise HTTPException(400, "Enter a valid phone number, for example 0772123456.")
    if n.startswith("0") and len(n) == 10:
        n = "256" + n[1:]
    return n


async def get_payment_info(request: Request) -> dict:
    doc = await tdb(request).settings.find_one({"name": "payment_info"}) or {}
    return {"mobile_money_number": doc.get("mobile_money_number") or "",
            "mobile_money_name": doc.get("mobile_money_name") or ""}


@app.get("/payment-info")
async def public_payment_info(request: Request):
    """Public (see _is_public): applicants need it before they have any session."""
    return await get_payment_info(request)


class PaymentInfoUpdate(BaseModel):
    mobile_money_number: str = Field("", max_length=40)
    mobile_money_name: str = Field("", max_length=200)
    reason: str = Field(..., max_length=300)


@app.put("/superadmin/payment-info")
async def superadmin_put_payment_info(data: PaymentInfoUpdate, request: Request):
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every change.")
    raw_number = data.mobile_money_number.strip()
    name = " ".join(data.mobile_money_name.split())
    if not raw_number and not name:
        number = ""                                   # both blank = stop showing payment details
    else:
        if not raw_number or not name:
            raise HTTPException(400, "Give both the number and the name it is registered under, or leave both blank to hide them.")
        if len(name) > PAYMENT_NAME_MAX_LEN or any(ord(c) < 32 for c in name):
            raise HTTPException(400, f"The name must be at most {PAYMENT_NAME_MAX_LEN} characters.")
        number = _clean_momo_number(raw_number)
    old = await get_payment_info(request)
    new = {"mobile_money_number": number, "mobile_money_name": name}
    if new == old:
        raise HTTPException(400, "Nothing to change.")
    await tdb(request).settings.update_one(
        {"name": "payment_info"},
        {"$set": org_stamp(request, {"name": "payment_info", **new, "updated_at": datetime.utcnow()})},
        upsert=True)
    await log_action("payment_info_changed", current_actor(request),
                     {"reason": reason, "old": old, "new": new}, org_id=request.state.org_id)
    return new


# ===============================================================================================
# NOMINATION FORM (settings) - phase N1
#
# A per-organisation, superadmin-configured section of the application: instructions, a downloadable
# blank form, and whether applicants must upload the signed copy. Same pattern as payment_info: a
# settings doc, a public read, a superadmin write that needs a reason and writes an audit row.
# The applicant upload route (/apply/upload-document) is N2 (below); the read-back route arrives in N3; the
# document sniffing helper below is written now so they reuse it rather than re-implement it.
# ===============================================================================================
NOMINATION_SETTING = "nomination_form"
NOMINATION_TITLE_MAX = 80
NOMINATION_INSTRUCTIONS_MAX = 2000
NOMINATION_ALLOWED_TYPES = ("pdf", "docx")          # canonical order for storage and display
NOMINATION_MAX_MB_RANGE = (1, 10)
NOMINATION_TEMPLATE_MAX_BYTES = 10 * 1024 * 1024    # the blank form uses the largest size an org may allow
NOMINATION_FILENAME_MAX = 120
NOMINATION_DOCX_MAX_UNCOMPRESSED = 100 * 1024 * 1024  # refuse zip bombs; we only list the archive, never extract it
_DOC_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _nomination_defaults() -> dict:
    return {"enabled": False, "required": True, "title": "Nomination Form", "instructions": "",
            "template_file": None, "accepted_types": ["pdf"], "max_mb": 5,
            "collect_phone": False}   # ask applicants for a phone number (orgs whose register has none); saved on the voter record


def _nomination_from_doc(doc: dict | None) -> dict:
    """Stored settings doc -> clean config (defaults filled in, bookkeeping fields dropped)."""
    out = _nomination_defaults()
    doc = doc or {}
    for k in out:
        if k in doc and doc[k] is not None:
            out[k] = doc[k]
    tf = out.get("template_file")
    out["template_file"] = ({"url": tf.get("url", ""), "filename": tf.get("filename", "")}
                            if isinstance(tf, dict) and tf.get("url") else None)
    out["accepted_types"] = [t for t in NOMINATION_ALLOWED_TYPES if t in (out["accepted_types"] or [])] or ["pdf"]
    return out


async def get_nomination_form(org_id) -> dict:
    return _nomination_from_doc(await cached_setting(org_id, NOMINATION_SETTING))


def _safe_filename(raw: str, default: str = "document") -> str:
    """Client filenames are attacker-controlled: drop any path, control characters and odd punctuation, cap the length."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*\x7f').strip(" .")
    name = re.sub(r"\s+", " ", name)
    if len(name) > NOMINATION_FILENAME_MAX:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:NOMINATION_FILENAME_MAX - len(ext) - 1] + "." + ext) if dot and len(ext) <= 8 else name[:NOMINATION_FILENAME_MAX]
    return name or default


def _sniff_document(content: bytes, accepted: list[str] | tuple[str, ...]) -> str:
    """Return "pdf" or "docx" from the file's real bytes, or raise 400. Content-Type and filename are never consulted.

    PDF: must start with %PDF-.  DOCX: a ZIP prefix alone matches any zip, so also require the two parts every
    Word file has and refuse macro containers."""
    if content.startswith(b"%PDF-"):
        kind = "pdf"
    elif content.startswith(b"PK\x03\x04"):
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                infos = z.infolist()
                names = {i.filename for i in infos}
                if sum(i.file_size for i in infos) > NOMINATION_DOCX_MAX_UNCOMPRESSED:
                    raise HTTPException(400, "That file is not a valid Word document.")
        except zipfile.BadZipFile:
            raise HTTPException(400, "That file is not a valid PDF or Word document.")
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise HTTPException(400, "That file is not a valid Word document.")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise HTTPException(400, "Word documents containing macros are not accepted.")
        kind = "docx"
    else:
        raise HTTPException(400, "That file is not a valid PDF or Word document.")
    if kind not in accepted:
        allowed = " or ".join(t.upper() for t in NOMINATION_ALLOWED_TYPES if t in accepted)
        raise HTTPException(400, f"Only {allowed} files are accepted.")
    return kind


def _nomination_public_view(cfg: dict) -> dict:
    """What an applicant needs and nothing more. Disabled -> a bare flag, no instructions or links leak."""
    # collect_phone is independent of the nomination-form section, and only sent when on (so the default payload is unchanged).
    phone = {"collect_phone": True} if cfg.get("collect_phone") else {}
    if not cfg["enabled"]:
        return {"enabled": False, **phone}
    return {**{k: cfg[k] for k in ("enabled", "required", "title", "instructions", "template_file", "accepted_types", "max_mb")}, **phone}


def _nomination_download_url(url: str, org_name: str) -> str:
    """Cloudinary `fl_attachment:<name>` makes the browser save the blank form as "<Org>_Nomination_Form.<ext>"
    instead of the random public id. The `download` attribute is ignored on cross-origin links, so the name has
    to come from the URL. Falls back to the plain URL if it is not a Cloudinary raw upload URL."""
    marker = "/raw/upload/"
    if marker not in url:
        return url
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{org_name} Nomination Form").strip("_")[:80] or "Nomination_Form"
    head, tail = url.split(marker, 1)
    return f"{head}{marker}fl_attachment:{stem}/{tail}"


@app.get("/nomination-form")
async def public_nomination_form(request: Request):
    """Public (see _is_public): applicants load it before they have any session."""
    view = _nomination_public_view(await get_nomination_form(request.state.org_id))
    tf = view.get("template_file")
    if tf and tf.get("url"):
        org_name = (await _branding(request)).get("org_name") or ""
        view["template_file"] = {**tf, "download_url": _nomination_download_url(tf["url"], org_name)}
    return view


class NominationTemplateIn(BaseModel):
    url: str = Field(..., max_length=500)
    filename: str = Field("", max_length=200)


class NominationFormUpdate(BaseModel):
    """Partial update: any field left out is unchanged. `reason` is always required."""
    enabled: bool | None = None
    required: bool | None = None
    title: str | None = Field(None, max_length=200)
    instructions: str | None = Field(None, max_length=10000)
    accepted_types: list[str] | None = Field(None, max_length=10)
    max_mb: int | None = None
    collect_phone: bool | None = None
    template_file: NominationTemplateIn | None = None
    clear_template_file: bool = False
    reason: str = Field(..., max_length=300)


def _clean_plain_text(raw: str, *, multiline: bool) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if any((ord(c) < 32 and not (multiline and c in "\n\t")) or ord(c) == 127 for c in text):
        raise HTTPException(400, "Text contains characters that are not allowed.")
    if multiline:
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return " ".join(text.split())


def _require_https_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or any(ord(c) <= 32 for c in url):
        raise HTTPException(400, "The form link must be a secure https:// address.")
    return url


@app.put("/superadmin/nomination-form")
async def superadmin_put_nomination_form(data: NominationFormUpdate, request: Request):
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "A reason is required for every change.")
    org_id = request.state.org_id
    old = await get_nomination_form(org_id)
    new = copy.deepcopy(old)

    if data.enabled is not None:
        new["enabled"] = data.enabled
    if data.required is not None:
        new["required"] = data.required
    if data.collect_phone is not None:
        new["collect_phone"] = data.collect_phone
    if data.title is not None:
        title = _clean_plain_text(data.title, multiline=False)
        if not title or len(title) > NOMINATION_TITLE_MAX:
            raise HTTPException(400, f"The title must be 1 to {NOMINATION_TITLE_MAX} characters.")
        new["title"] = title
    if data.instructions is not None:
        instructions = _clean_plain_text(data.instructions, multiline=True)
        if len(instructions) > NOMINATION_INSTRUCTIONS_MAX:
            raise HTTPException(400, f"The instructions must be at most {NOMINATION_INSTRUCTIONS_MAX} characters.")
        new["instructions"] = instructions
    if data.accepted_types is not None:
        wanted = {str(t).strip().lower() for t in data.accepted_types}
        if not wanted or not wanted <= set(NOMINATION_ALLOWED_TYPES):
            raise HTTPException(400, "Accepted file types must be PDF, DOCX, or both.")
        new["accepted_types"] = [t for t in NOMINATION_ALLOWED_TYPES if t in wanted]
    if data.max_mb is not None:
        lo, hi = NOMINATION_MAX_MB_RANGE
        if not lo <= data.max_mb <= hi:
            raise HTTPException(400, f"The maximum size must be between {lo} and {hi} MB.")
        new["max_mb"] = data.max_mb
    if data.clear_template_file and data.template_file is not None:
        raise HTTPException(400, "Either set the form link or clear it, not both.")
    if data.clear_template_file:
        new["template_file"] = None
    elif data.template_file is not None:
        filename = _safe_filename(data.template_file.filename, "nomination-form")
        new["template_file"] = {"url": _require_https_url(data.template_file.url), "filename": filename}

    if new == old:
        raise HTTPException(400, "Nothing to change.")
    await _save_nomination_form(request, new)
    await log_action("nomination_form_changed", current_actor(request),
                     {"reason": reason, "old": old, "new": new}, org_id=org_id)
    return new


async def _save_nomination_form(request: Request, cfg: dict) -> None:
    org_id = request.state.org_id
    await tdb(request).settings.update_one(
        {"name": NOMINATION_SETTING},
        {"$set": org_stamp(request, {"name": NOMINATION_SETTING, **cfg, "updated_at": datetime.utcnow()})},
        upsert=True)
    invalidate_settings(org_id, NOMINATION_SETTING)   # without this the public read serves the old value for up to the cache TTL


@app.post("/superadmin/nomination-form/template")
async def superadmin_upload_nomination_template(request: Request, file: UploadFile = File(...),
                                                reason: str = Form("")):
    """Upload the blank form applicants download. Public by nature (anyone filling in the application gets it),
    so a normal public Cloudinary raw upload is right here; the *completed* forms uploaded by applicants are
    the sensitive ones and are handled separately (N2)."""
    reason = reason.strip()
    if len(reason) < 3 or len(reason) > 300:
        raise HTTPException(400, "A reason is required for every change.")
    content = await file.read(NOMINATION_TEMPLATE_MAX_BYTES + 1)   # never buffer an unbounded body
    if len(content) > NOMINATION_TEMPLATE_MAX_BYTES:
        raise HTTPException(400, f"The form must be under {NOMINATION_TEMPLATE_MAX_BYTES // (1024 * 1024)}MB.")
    kind = _sniff_document(content, NOMINATION_ALLOWED_TYPES)
    org_id = request.state.org_id
    stem = _safe_filename(file.filename or "", "nomination-form").rsplit(".", 1)[0] or "nomination-form"
    filename = f"{stem[:NOMINATION_FILENAME_MAX - 6]}.{kind}"
    try:
        # Raw resources keep their extension inside the public id, which is what makes the download open correctly.
        result = cloudinary.uploader.upload(
            content, folder=f"ballotbox/nomination-templates/{org_id}", resource_type="raw",
            public_id=f"{secrets.token_hex(8)}.{kind}", use_filename=False, unique_filename=False)
        url = _require_https_url(result["secure_url"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cloudinary nomination template upload failed: {e}")
        await alert_warning("Cloudinary upload failing (nomination template)",
                            f"{type(e).__name__}: {e}\nOrg: {org_id}")
        raise HTTPException(502, "Form upload failed. Please try again.")

    old = await get_nomination_form(org_id)
    new = {**old, "template_file": {"url": url, "filename": filename}}
    await _save_nomination_form(request, new)
    await log_action("nomination_form_template_uploaded", current_actor(request),
                     {"reason": reason, "filename": filename, "bytes": len(content), "type": kind,
                      "replaced": bool(old["template_file"])}, org_id=org_id)
    return new


# ── Phase N2: completed (signed) forms go to a PRIVATE bucket, never to Cloudinary ─────────────────────────
NOMINATION_UPLOAD_TTL_HOURS = 24      # an upload must be attached to an application within this long
_NOMINATION_MIME = {"pdf": "application/pdf",
                    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@app.post("/superadmin/nomination-form/test-storage")
async def superadmin_test_nomination_storage(request: Request):
    """One click: prove the private bucket settings work (write, read back, staff download link, delete) without
    submitting a fake application. Touches only a throwaway file under nomination-forms/<org>/_selftest/."""
    org_id = require_org(request.state.org_id)
    key = f"nomination-forms/{org_id}/_selftest/{secrets.token_hex(8)}.pdf"
    result = await run_in_threadpool(nomination_storage.self_test, key)
    await log_action("nomination_storage_tested", current_actor(request),
                     {"ok": result["ok"], "failed": [s["name"] for s in result["steps"] if not s["ok"]]}, org_id=org_id)
    return result


@app.post("/apply/upload-document")
async def apply_upload_document(request: Request, file: UploadFile = File(...)):
    """Public (applicants have no login). Stores the signed form in the private bucket and returns only an opaque
    `upload_id`, which the applicant sends with /apply. No storage key or link is ever returned."""
    await _check_document_upload_rate_limit(request)
    await assert_phase_open(request, "applications")
    org_id = require_org(request.state.org_id)
    cfg = await get_nomination_form(org_id)
    if not cfg["enabled"]:
        raise HTTPException(404, "A nomination form is not required for this election.")
    max_bytes = cfg["max_mb"] * 1024 * 1024
    content = await file.read(max_bytes + 1)          # never buffer an unbounded body
    if len(content) > max_bytes:
        analytics.set_reason(request, "too_large")
        raise HTTPException(400, f"The form must be under {cfg['max_mb']}MB.")
    try:
        kind = _sniff_document(content, cfg["accepted_types"])
    except HTTPException:
        analytics.set_reason(request, "bad_file_type")
        raise
    if not nomination_storage.is_configured():
        logger.error("Nomination form storage is not configured: " + ", ".join(nomination_storage.missing_settings()))
        await alert_critical("Nomination form storage not configured",
                             f"Missing: {', '.join(nomination_storage.missing_settings())}\nOrg: {org_id}")
        analytics.set_reason(request, "upload_failed")
        raise HTTPException(503, "Form upload is temporarily unavailable. Please try again later.")

    upload_id = secrets.token_hex(16)
    key = f"nomination-forms/{org_id}/{upload_id}.{kind}"
    filename = _safe_filename(file.filename or "", "nomination-form")
    stem = filename.rsplit(".", 1)[0] or "nomination-form"
    filename = f"{stem[:NOMINATION_FILENAME_MAX - 6]}.{kind}"
    try:
        await run_in_threadpool(nomination_storage.put_object, key, content, _NOMINATION_MIME[kind])
    except Exception as e:
        logger.error(f"Nomination form upload failed: {type(e).__name__}: {e}")
        await alert_critical("Nomination form storage failing",
                             f"{type(e).__name__}: {e}\nOrg: {org_id}")
        analytics.set_reason(request, "upload_failed")
        raise HTTPException(502, "Form upload failed. Please try again.")
    now = datetime.utcnow()
    await tdb(request).nomination_uploads.insert_one({
        "upload_id": upload_id, "key": key, "filename": filename, "kind": kind, "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(), "status": "pending",
        "created_at": now, "uploaded_at": now,
        "is_demo": bool(await _demo_active(org_id)),
    })
    try:
        await _sweep_stale_nomination_uploads(tdb(request))
    except Exception as e:
        logger.warning(f"Nomination sweep skipped: {type(e).__name__}")
    return {"upload_id": upload_id, "filename": filename, "kind": kind, "bytes": len(content)}


async def _delete_nomination_objects(rows) -> int:
    """Best-effort removal of private files. A storage error never blocks the caller; the record is kept so a
    later sweep can retry."""
    removed = 0
    if not nomination_storage.is_configured():
        return 0
    for row in rows:
        try:
            await run_in_threadpool(nomination_storage.delete_object, row["key"])
            removed += 1
        except Exception as e:
            logger.warning(f"Nomination file cleanup failed for {row.get('upload_id')}: {type(e).__name__}")
    return removed


async def _sweep_stale_nomination_uploads(dbs, limit: int = 25) -> int:
    """Pending uploads never attached to an application within the TTL: delete file, then record.
    Attached uploads are NEVER touched (the application depends on them)."""
    cutoff = datetime.utcnow() - timedelta(hours=NOMINATION_UPLOAD_TTL_HOURS)
    rows = [r async for r in dbs.nomination_uploads.find(
        {"status": "pending", "$or": [{"created_at": {"$lt": cutoff}},
                                      {"created_at": {"$exists": False}, "uploaded_at": {"$lt": cutoff}}]}).limit(limit)]
    n = 0
    for r in rows:
        if nomination_storage.is_configured():
            try:
                await run_in_threadpool(nomination_storage.delete_object, r["key"])
            except Exception as e:
                logger.warning(f"Stale nomination file cleanup failed: {type(e).__name__}")
                continue
        await dbs.nomination_uploads.delete_one({"_id": r["_id"]})
        n += 1
    return n


async def _claim_nomination_upload(request: Request, upload_id: str, student_id: str, position_id: str) -> dict:
    """Atomically attach a pending upload to this application attempt. One upload serves one application, so a
    leaked or reused id cannot be attached twice. Unknown, stale or used ids all give the same answer."""
    cutoff = datetime.utcnow() - timedelta(hours=NOMINATION_UPLOAD_TTL_HOURS)
    doc = await tdb(request).nomination_uploads.find_one_and_update(
        {"upload_id": upload_id, "status": "pending",
         "$or": [{"created_at": {"$gte": cutoff}}, {"created_at": {"$exists": False}, "uploaded_at": {"$gte": cutoff}}]},
        {"$set": {"status": "attached", "student_id": student_id, "position_id": position_id,
                  "attached_at": datetime.utcnow()}},
    )
    if not doc:
        raise HTTPException(400, "The uploaded nomination form could not be used. Please upload it again.")
    return doc
