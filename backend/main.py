from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import secrets
import asyncio
import motor.motor_asyncio
from pymongo.errors import DuplicateKeyError
from pymongo import UpdateOne
import os
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
from name_backfill import run_backfill as run_name_backfill
from regno_audit import audit_reg_numbers
import otp_limits as ol

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
    await db.roster_ledger.create_index([("org_id", 1), ("event", 1), ("ref_id", 1), ("ts", -1)])
    await db.voters.create_index([("has_voted", 1), ("sms_sends_total", 1)])
    # Phase exception grants — looked up on every gated action.
    await db.exception_grants.create_index([("org_id", 1), ("student_id", 1), ("phase", 1)])
    # The activity log is read by every admin role now, filtered and sorted.
    await db.student_edit_audit.create_index([("org_id", 1), ("student_key", 1), ("at", -1)])
    await db.student_edit_audit.create_index([("org_id", 1), ("search_terms", 1)])
    await db.audit_log.create_index([("org_id", 1), ("timestamp", -1)])
    await db.audit_log.create_index([("org_id", 1), ("action", 1), ("timestamp", -1)])
    # Turnout-velocity aggregation scans cast_at.
    await db.vote_events.create_index([("org_id", 1), ("cast_at", 1)])
    set_revocation_check(_is_token_revoked)
    await _check_config_on_boot()
    yield
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
# IMPORTANT: absence of the header is NOT rejected here — requests without it
# get request.state.org_id = None, so the existing single-tenant deployment
# keeps working unmodified during rollout. Individual routes decide whether
# org scoping is required once they're retrofitted in the next pass.

# Fail-closed tenancy. Set REQUIRE_ORG_CONTEXT=false ONLY for a legacy single-tenant deployment
# whose data still has org_id=None.
REQUIRE_ORG_CONTEXT = os.getenv("REQUIRE_ORG_CONTEXT", "true").strip().lower() == "true"
ORG_EXEMPT_PREFIXES = ("/health", "/internal/backup", "/docs", "/redoc", "/openapi.json",
                       "/superadmin/orgs", "/superadmin/mfa", "/verify-admin")


@app.middleware("http")
async def org_context_middleware(request: Request, call_next):
    org_slug = request.headers.get("X-Org-Slug")
    request.state.org_id = None
    request.state.org_slug = None
    if org_slug:
        org_doc = await db.organizations.find_one({"slug": org_slug})
        if not org_doc:
            # Unknown slug used to fall through as "no tenant" and org_query() then returned
            # UNSCOPED filters, i.e. every tenant's data.
            return JSONResponse(status_code=404, content={"detail": "Unknown organization."})
        request.state.org_id = str(org_doc["_id"])
        request.state.org_slug = org_slug
    elif (REQUIRE_ORG_CONTEXT and request.method != "OPTIONS" and request.url.path != "/"
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
    "/", "/health", "/election-status",
    "/verify-identity", "/verify-otp", "/vote", "/vote-bulk",
    "/apply/check-eligibility", "/apply", "/apply/upload-image",
    "/verify-admin", "/election-results", "/election-results/voter-roll",
    "/voter-register", "/voter-register/check-number",
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
    if method == "GET" and path in {"/candidates", "/positions", "/superadmin/branding", "/election-schedule", "/election-roadmap"}:
        return True
    return False


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
            await log_action("admin_guard_401", "unknown", {"path": request.url.path}, org_id=None)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if payload.get("role") not in ADMIN_ROLES:
        return JSONResponse(status_code=403, content={"detail": "Not authorized."})

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
        _od = await db.organizations.find_one({"slug": request.headers["X-Org-Slug"]})
        req_org = str(_od["_id"]) if _od else None
    if payload["role"] != "superadmin" and payload.get("org_id") != req_org:
        await log_action(
            "admin_guard_tenant_mismatch", payload.get("sub", "unknown"),
            {"path": request.url.path, "role": payload.get("role")}, org_id=payload.get("org_id"))
        return JSONResponse(status_code=403, content={"detail": "This session does not belong to this organization."})

    # A temp-password login's token is scoped to password_change_only until the admin
    # actually changes their password — everything else 403s even with a valid token.
    if payload.get("scope") == SCOPE_PASSWORD_CHANGE_ONLY and request.url.path not in PASSWORD_CHANGE_ONLY_ALLOWED_PATHS:
        return JSONResponse(status_code=403, content={
            "detail": "You must change your temporary password before continuing."})

    # Per-account session cutoff: a password reset or role revocation stamps
    # sessions_valid_after on the voter doc (see _invalidate_sessions), so any token
    # issued before that moment stops working here even though the JWT itself hasn't
    # expired yet. Superadmin has no voter doc to stamp — it relies on its own shorter
    # SUPERADMIN_JWT_EXPIRE_MINUTES lifetime instead.
    if payload["role"] != "superadmin":
        # NB: no flag_field filter here — a revoked role's whole point is that the flag is
        # now False, so filtering on it True would make the lookup miss exactly the account
        # whose session we most need to cut off. Role authorization is a separate check
        # (require_role); this is only about "does this token still correspond to a live
        # session for this account at all."
        acct = await db.voters.find_one(
            {**({"org_id": req_org} if req_org else {}), "student_id": payload.get("sub")},
            {"sessions_valid_after": 1}
        )
        cutoff = acct.get("sessions_valid_after") if acct else None
        if cutoff:
            iat = payload.get("iat")
            iat_dt = datetime.utcfromtimestamp(iat) if isinstance(iat, (int, float)) else iat
            if iat_dt and iat_dt < cutoff:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Org-Slug", "X-Voter-Token"],
    max_age=600,
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

app.include_router(build_backup_router(lambda: db))

# =============================================================================
# MODELS
# =============================================================================     
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

class ApplicationSubmit(BaseModel):
    student_id:        str
    full_name:         str
    position_id:       str
    manifesto:         str = Field("", max_length=MANIFESTO_MAX_CHARS)
    image_url:         str = ""
    payment_method:    str = ""     
    payment_proof_url: str = ""      
    
class CommissionerVote(BaseModel):
    commissioner_id: str   # the commissioner's student_id
    vote: str              # "approve" or "deny"
    reason: str = ""

class FinanceClear(BaseModel):
    commissioner_id: str   # must belong to the voter flagged is_finance_commissioner

class FinanceReject(BaseModel):
    commissioner_id: str   # must belong to the voter flagged is_finance_commissioner
    reason: str
    

class ITAdminStudentAdd(BaseModel):
    student_id:        str
    full_name:         str
    phones:            list[str]
    reason:            str
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

class ApplicationEligibilityCheck(BaseModel):
    student_id: str
    full_name: str

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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api-mongolia.mambosms.com/v1/send-sms",
                json=payload,
                headers=headers,
                timeout=15.0,
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
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://comms.egosms.co/api/v1/plain/",
                params=params,
                timeout=15.0
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


async def _send_sms_priority(to_number: str, message_text: str, org, kind: str) -> str:
    """EgoSMS (primary) first; on a DEFINITE failure falls back to MamboSMS. On an AMBIGUOUS EgoSMS result
    (timeout) it does NOT fall back unless the org's sms_fallback_on_timeout setting is on (per-org,
    defaults from SMS_FALLBACK_ON_TIMEOUT), because the first send may have been delivered and billed.
    """
    first = await send_sms_via_egosms(to_number, message_text)
    if first == "ok":
        await _safe_count_sms(org, kind)
        return "ok"
    if first == "ambiguous":
        await _safe_count_sms(org, kind)        # may have been billed
        sec = await security_settings_for(org)
        if not sec["sms_fallback_on_timeout"]:
            await log_action("sms_ambiguous_no_fallback", "system", {"primary": "egosms"}, org_id=org)
            return "ambiguous"

    logger.warning(f"EgoSMS failed for {to_number}, falling back to MamboSMS.")
    await log_action("sms_provider_fallback", "system", {"primary": "egosms", "fallback": "mambosms"}, org_id=org)
    if await send_sms_via_mambosms(to_number, message_text):
        await _safe_count_sms(org, kind)
        return "ok"
    # Both providers down. This is the exact silent-failure case: a voter is
    # sitting on the OTP screen and nothing ever arrives, with no error shown
    # anywhere but the server log. Tier 1 for "otp" (a voter is blocked right
    # now); warning for other priority kinds.
    level = "critical" if kind == "otp" else "warning"
    await send_alert(
        f"Both SMS providers failed ({kind})",
        f"EgoSMS and MamboSMS both failed sending to {to_number}. Org: {org}. Kind: {kind}.",
        level=level,
    )
    return "failed"


async def _send_sms_non_priority(to_number: str, message_text: str, org, kind: str) -> str:
    """MamboSMS (primary) first — cheap, slow, fine for non-time-critical notices. On a Mambo
    failure falls back to EgoSMS so the message still gets there, just at EgoSMS's cost.
    """
    if await send_sms_via_mambosms(to_number, message_text):
        await _safe_count_sms(org, kind)
        return "ok"

    logger.warning(f"MamboSMS failed for {to_number}, falling back to EgoSMS.")
    await log_action("sms_provider_fallback", "system", {"primary": "mambosms", "fallback": "egosms"}, org_id=org)
    second = await send_sms_via_egosms(to_number, message_text)
    if second in ("ok", "ambiguous"):
        await _safe_count_sms(org, kind)        # ambiguous here too may have been billed
        return "ok" if second == "ok" else "ambiguous"
    level = "critical" if kind == "otp" else "warning"
    await send_alert(
        f"Both SMS providers failed ({kind})",
        f"MamboSMS and EgoSMS both failed sending to {to_number}. Org: {org}. Kind: {kind}.",
        level=level,
    )
    return "failed"


async def send_sms_status(to_number: str, message_text: str, request: Request | None = None,
                          kind: str = "otp", org_id: str | None = None) -> str:
    """Single entrypoint every route should call to send an SMS. Returns "ok", "failed" or "ambiguous".

    Provider order depends on `kind`: see PRIORITY_SMS_KINDS, _send_sms_priority and
    _send_sms_non_priority. Every provider send (Ego and Mambo) is counted toward the election budget.
    """
    org = request.state.org_id if request is not None else org_id
    if DEBUG_MODE:
        # Local/load-testing only: never hit either real API. Log the message (which contains the OTP)
        # so Locust or a manual tester can read it back, and report success.
        logger.info(f"[DEBUG_MODE] SMS to {to_number}: {message_text}")
        await _safe_count_sms(org, kind)
        return "ok"

    if kind in PRIORITY_SMS_KINDS:
        return await _send_sms_priority(to_number, message_text, org, kind)
    return await _send_sms_non_priority(to_number, message_text, org, kind)


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
SCOPE_PASSWORD_CHANGE_ONLY = "password_change_only"
PASSWORD_CHANGE_ONLY_ALLOWED_PATHS = {"/admin/set-password", "/admin/logout"}


def _login_token_for(voter: dict, role: str, must_change_field: str, org_id: str | None) -> str:
    """A temp-password login (must_change_field still true) gets a token that the guard
    will accept ONLY for /admin/set-password and /admin/logout — so an intercepted temp
    password's token can't be used to touch anything else even if the client is buggy or
    the person never opens the change-password screen."""
    must_change = voter.get(must_change_field, True)
    return create_access_token(
        subject=voter["student_id"], role=role, org_id=org_id,
        full_name=voter.get("full_name", ""),
        scope=SCOPE_PASSWORD_CHANGE_ONLY if must_change else "full",
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

def org_query(request: Request, extra: dict = None) -> dict:
    """
    Merge tenant scoping into a query filter. If the request carries no
    X-Org-Slug (request.state.org_id is None), the filter is returned
    unchanged — this is what keeps the existing single-tenant KYUCCU
    deployment working exactly as before, with no header set.
    """
    q = dict(extra) if extra else {}
    if request.state.org_id:
        q["org_id"] = request.state.org_id
    return q

def org_stamp(request: Request, doc: dict) -> dict:
    """Stamp a new document with the current org_id (None for legacy/default)."""
    doc = dict(doc)
    doc["org_id"] = request.state.org_id
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
    async for row in db.vote_events.aggregate([
        {"$match": org_query(request)},
        {"$group": {"_id": "$candidate_id", "count": {"$sum": 1}}}
    ]):
        counts[str(row["_id"])] = row["count"]
    return counts

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
    org_id = request.state.org_id
    await anchor_roster_ledger(request)   # ledger head goes to B2 Object Lock even when there are no new ballots
    ledger_head = await db.roster_ledger.find_one({"org_id": org_id}, sort=[("seq", -1)])
    last = await db.audit_checkpoints.find_one(
        org_query(request), sort=[("to_id", -1)]
    )
    prev_hash = last["chain_hash"] if last else "GENESIS"

    match: dict = org_query(request)
    if last:
        match["_id"] = {"$gt": last["to_id"]}
    events = await db.vote_events.find(match).sort("_id", 1).to_list(length=None)
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
        events = await db.vote_events.find(match).sort("_id", 1).to_list(length=None)

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
    branding_query = {"name": "branding"}
    if voter.get("org_id"):
        branding_query["org_id"] = voter["org_id"]
    branding_doc = await db.settings.find_one(branding_query)
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
                               admin: dict = Depends(require_role("commission"))):
    """Read-only view of the active policy, for commissioners only — IT Admin
    and Overseer have no need to know it, and superadmin already sees it via
    GET /superadmin/security-settings."""
    sec = await security_settings_for(request.state.org_id)
    total = await get_commissioner_count(request.state.org_id)
    return {
        "policy": sec["approval_policy"],
        "total_commissioners": total,
        "required_for_majority_total": (total // 2) + 1,
    }


async def get_commissioner_count(org_id: str = None) -> int:
    q = {"is_commissioner": True}
    if org_id:
        q["org_id"] = org_id
    return await db.voters.count_documents(q)

async def _resolve_position_title(position_id: str, org_id: str = None) -> tuple[str, int]:
    """Returns (title, order) for a position id, with safe fallbacks."""
    try:
        q = {"_id": ObjectId(position_id)}
        if org_id:
            q["org_id"] = org_id
        pos = await db.positions.find_one(q)
        if pos:
            return pos.get("title", position_id), pos.get("order", 0)
    except Exception:
        pass
    return position_id, 0

async def _create_candidate_from_application(app_doc: dict, org_id: str = None):
    title, order = await _resolve_position_title(app_doc.get("position_id", ""), org_id)
    await db.candidates.insert_one({
        "name": app_doc["full_name"],
        "position": title,
        "image_url": app_doc.get("image_url", ""),
        "order": order,
        "votes": 0,
        "application_id": str(app_doc["_id"]),
        "org_id": org_id
    })

async def _position_fee(position_id: str, org_id: str = None) -> int:
    """Nomination fee (UGX) configured on a position; 0 when none/unknown."""
    try:
        q = {"_id": ObjectId(position_id)}
        if org_id:
            q["org_id"] = org_id
        pos = await db.positions.find_one(q)
        return int((pos or {}).get("application_fee") or 0)
    except Exception:
        return 0


def fmt_ugx(n) -> str:
    return f"UGX {int(n or 0):,}"


async def _notify_applicant(app_doc: dict, org_id: str, text_for) -> str:
    """Best-effort SMS to the applicant's first registered number. `text_for(org_name, position_title)` -> str.
    Never raises and never blocks the decision that triggered it. Returns 'sent' | 'failed' | 'no_phone'."""
    try:
        voter = await db.voters.find_one({**get_forgiving_filter(app_doc.get("student_id", "")), "org_id": org_id})
        phones = (voter or {}).get("phone_numbers") or []
        if not phones:
            return "no_phone"
        b = await db.settings.find_one({"name": "branding", "org_id": org_id}) or {}
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
    await db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"tied_pending_chief": True}}
    )
    await log_action("application_vote_tied", "commission", {"app_id": app_id}, org_id=org_id)


async def _resolve_application(app_id: str, app_doc: dict, org_id: str = None):
    """
    Called after every commissioner vote. Resolution rule (unanimous /
    majority-of-total / majority-of-votes-cast) is read per-org from
    security_settings.approval_policy — see _tally_outcome.
    """
    total = await get_commissioner_count(org_id)
    if total == 0:
        return
    policy = (await security_settings_for(org_id))["approval_policy"]

    votes = _dedupe_votes(app_doc.get("votes", {}))
    approve_count = sum(1 for v in votes.values() if v == "approve")
    deny_count    = sum(1 for v in votes.values() if v == "deny")

    outcome = _tally_outcome(policy, total, approve_count, deny_count)

    if outcome == "approve":
        # SECURITY/CONCURRENCY: two commissioners casting the deciding vote
        # within milliseconds of each other could both reach this branch for
        # the same application before either had written "approved" yet,
        # which used to create two candidate documents for one application.
        # The status flip is now the atomic guard: only the caller whose
        # update_one actually matches an unresolved document is allowed to
        # create the candidate. The loser's matched_count is 0 and it does
        # nothing further — the winner's own vote is already recorded either
        # way, so no vote is lost, only the duplicate side effect.
        result = await db.applications.update_one(
            {"_id": ObjectId(app_id), "status": {"$nin": ["approved", "denied", "removed"]}},
            {"$set": {"status": "approved"}, "$unset": {"tied_pending_chief": ""}}
        )
        if result.matched_count == 0:
            return
        await _create_candidate_from_application(app_doc, org_id)
        await log_action("application_approved", "commission", {
            "app_id": app_id, "approve_count": approve_count, "total_commissioners": total, "policy": policy,
        }, org_id=org_id)
        await _notify_applicant(app_doc, org_id, lambda org, pos: (
            f"{org}: Congratulations! Your nomination for {pos} has been approved. "
            f"Your name will appear on the ballot."))
        logger.info(f"Application {app_id} approved by commission ({approve_count}/{total}, policy={policy}).")
    elif outcome == "deny":
        # Same atomic guard: only the winning caller logs/proceeds.
        result = await db.applications.update_one(
            {"_id": ObjectId(app_id), "status": {"$nin": ["approved", "denied", "removed"]}},
            {"$set": {"status": "denied"}, "$unset": {"tied_pending_chief": ""}}
        )
        if result.matched_count == 0:
            return
        await log_action("application_denied", "commission", {
            "app_id": app_id, "deny_count": deny_count, "total_commissioners": total, "policy": policy,
        }, org_id=org_id)
        await _notify_applicant(app_doc, org_id, lambda org, pos: (
            f"{org}: Your nomination for {pos} was not approved by the Electoral Commission."))
        logger.info(f"Application {app_id} denied by commission ({deny_count}/{total}, policy={policy}).")
    elif policy == "majority_cast" and (approve_count + deny_count) == total and approve_count == deny_count:
        await _flag_tie_for_chief(app_id, org_id)

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
        result = await db.applications.update_one(
            {"_id": ObjectId(app_id), "status": "approved"},
            {"$set": {"status": "removed", "removal_votes": {}}, "$unset": {"tied_pending_chief": ""}}
        )
        if result.matched_count == 0:
            return
        cand = await db.candidates.find_one({"application_id": app_id})
        await db.candidates.delete_one({"application_id": app_id})
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
        await db.applications.update_one({"_id": ObjectId(app_id)}, {"$unset": {"tied_pending_chief": ""}})
    elif policy == "majority_cast" and (approve_removals + deny_removals) == total and approve_removals == deny_removals:
        await _flag_tie_for_chief(app_id, org_id)


async def _resweep_pending_after_policy_change(org_id: str):
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
    async for app_doc in db.applications.find(_oq(org_id, {"status": "pending"})):
        await _resolve_application(str(app_doc["_id"]), app_doc, org_id)

    async for app_doc in db.applications.find(_oq(org_id, {
        "status": "approved", "removal_votes": {"$exists": True, "$ne": {}},
    })):
        await _resolve_removal(str(app_doc["_id"]), app_doc, org_id)

#--IT Administration Helpers---

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
        q = {"student_id": normalize_student_id(change_doc["student_id"])}
        if org_id:
            q["org_id"] = org_id
        await db.voters.update_one(
            q,
            {"$set": {
                "full_name":       change_doc["full_name"],
                "phone_numbers":   phones,
                "added_by_it":     True,
                "added_by":        change_doc.get("requested_by", ""),
                "org_id":          org_id,
                "student_id":      normalize_student_id(change_doc["student_id"])
            },
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
        if org_id:
            q["org_id"] = org_id
        await db.voters.delete_one(q)

async def log_action(action: str, actor: str, details: dict | None = None, org_id: str = None):
    # details defaults to None, not {} — a mutable default argument is shared
    # across every call site in the process, so one accidental mutation would
    # leak into unrelated log entries.
    await db.audit_log.insert_one({
        "action":    action,
        "actor":     actor,
        "details":   details or {},
        "org_id":    org_id,
        "timestamp": datetime.utcnow()
    })


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


async def _is_chief_or_deputy(request: Request, admin: dict) -> bool:
    """Superadmin, or the commissioner flagged is_chief_commissioner or is_deputy_chief_commissioner."""
    if admin.get("role") == "superadmin":
        return True
    if admin.get("role") != "commission":
        return False
    voter = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(admin.get("sub", "")),
        "is_commissioner": True,
        "$or": [{"is_chief_commissioner": True}, {"is_deputy_chief_commissioner": True}],
    }))
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
            raise ValueError("dates must be YYYY-MM-DD")

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        start = info.data.get("start_date")
        if v and not start:
            raise ValueError("end_date requires start_date")
        if v and start and v < start:
            raise ValueError("end_date must not be before start_date")
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


async def get_phase_schedule(request: Request) -> dict:
    doc = await db.settings.find_one(org_query(request, {"name": "election_phases"}))
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
    return await db.exception_grants.find_one(org_query(request, {
        "student_id": normalize_student_id(student_id),
        "phase": phase,
        "revoked": {"$ne": True},
        "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
    }))


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
    elif end and now > end:
        detail = (f"The {label} period has ended. It closed on {_when(end)}. "
                  "Contact the Electoral Commission if you believe this is an error.")
    else:
        detail = f"The {label} period is currently closed. Contact the Electoral Commission if you believe this is an error."
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
    config = await db.settings.find_one(org_query(request, {"name": "election_config"}))
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


def _login_attempt_key(email: str, org_id: str | None, ip: str) -> str:
    return f"{org_id or 'default'}:{email}:{ip}"


def _is_superadmin_email(email: str) -> bool:
    return email.strip().lower() == SUPER_ADMIN_ID.strip().lower()


async def enforce_login_rate_limit(email: str, org_id: str | None, ip: str):
    key = _login_attempt_key(email, org_id, ip)
    record = await db.login_attempts.find_one({"key": key})
    if not record:
        return

    locked_until = record.get("locked_until")
    if locked_until and locked_until > datetime.utcnow():
        remaining_s = int((locked_until - datetime.utcnow()).total_seconds())
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
        if _is_superadmin_email(email):
            lock_for = timedelta(seconds=min(
                SUPERADMIN_LOCKOUT_SECONDS_CAP,
                5 * (2 ** (attempts - LOGIN_MAX_ATTEMPTS))))   # short, capped backoff — never a hard 15-min block
        else:
            lock_for = timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        await db.login_attempts.update_one(
            {"key": key}, {"$set": {"locked_until": datetime.utcnow() + lock_for}}
        )
        await log_action("admin_login_locked", email, {"attempts": attempts, "ip": ip}, org_id=org_id)


async def clear_login_attempts(email: str, org_id: str | None, ip: str):
    key = _login_attempt_key(email, org_id, ip)
    await db.login_attempts.delete_one({"key": key})

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

# Per-org overrides live in db.settings {name: "security_settings"}; these are the fallbacks.
_SEC_DEFAULTS = {
    "roster_freeze_at": None,
    "roster_freeze_enabled": ol.env_bool("ROSTER_FREEZE_ENABLED", True),
    "contact_change_required": ol.env_bool("CONTACT_CHANGE_REQUIRED", True),
    "otp_target_risk": ol.TARGET_RISK,
    "turnstile_mode": os.getenv("TURNSTILE_MODE", "off").strip().lower(),
    "public_results_mode": os.getenv("PUBLIC_RESULTS_MODE", "live").strip().lower(),
    "sms_fallback_on_timeout": ol.env_bool("SMS_FALLBACK_ON_TIMEOUT", False),
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


def _oq(org_id, extra: dict | None = None) -> dict:
    """org_query for code that has an org_id but no request (same semantics)."""
    q = dict(extra) if extra else {}
    if org_id:
        q["org_id"] = org_id
    return q


class ApiError(Exception):
    """HTTP error that carries machine-readable fields (reason, retry_after, ...) next to `detail`."""

    def __init__(self, status_code: int, detail: str, reason: str | None = None,
                 retry_after: int | None = None, **extra):
        self.status_code, self.detail, self.reason = status_code, detail, reason
        self.retry_after, self.extra = retry_after, extra


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
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
    doc = await db.settings.find_one(_oq(org_id, {"name": "security_settings"})) or {}
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
        await db.otps.delete_many(q)
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
        reserve = await db.voters.count_documents(org_query(request, {
            "has_voted": {"$ne": True}, "sms_sends_total": {"$not": {"$gt": 0}}}))
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
    live_grant = await db.exception_grants.count_documents(org_query(request, {
        "phase": "voting", "revoked": {"$ne": True},
        "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}))
    if end and now > end and not live_grant:
        return {**base, "phase": "closed", "frozen": True, "contact_change_required": False}
    return {**base, "phase": "voting_frozen", "frozen": True,
            "contact_change_required": bool(sec["contact_change_required"])}


async def _expire_pending_at_freeze(request: Request):
    await db.student_changes.update_many(
        org_query(request, {"status": "pending"}),
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
        last = await db.roster_ledger.find_one({"org_id": org_id}, sort=[("seq", -1)])
        seq = (last["seq"] if last else 0) + 1
        prev = last["hash"] if last else "GENESIS"
        now = datetime.utcnow()
        ts = now.replace(microsecond=(now.microsecond // 1000) * 1000)   # Mongo keeps milliseconds
        doc = {"org_id": org_id, "seq": seq, "event": event, "ref_id": ref_id, "actor": actor, "role": role,
               "ts": ts, "details": details, "prev_hash": prev,
               "hash": _ledger_hash(prev, seq, event, ref_id, actor, role, ts, details)}
        try:
            await db.roster_ledger.insert_one(doc)
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
    async for e in db.roster_ledger.find({"org_id": org_id}).sort("seq", 1):
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
    org_id = request.state.org_id
    head = await db.roster_ledger.find_one({"org_id": org_id}, sort=[("seq", -1)])
    if not head:
        return
    marker = await db.settings.find_one(org_query(request, {"name": "roster_ledger_anchor"})) or {}
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
    await db.settings.update_one(org_query(request, {"name": "roster_ledger_anchor"}),
                                 {"$set": org_stamp(request, {"name": "roster_ledger_anchor", "seq": head["seq"],
                                                              "head_hash": head["hash"], "at": datetime.utcnow()})},
                                 upsert=True)


# =============================================================================
# SYSTEM & HEALTH
# =============================================================================

@app.get("/")
def read_root():
    return {"status": "Online", "sms_provider": "EgoSMS"}

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
    status_doc = await db.settings.find_one(org_query(request, {"name": "election_config"}))
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
    status_doc = await db.settings.find_one(org_query(request, {"name": "election_config"}))

    if status_doc and not status_doc.get("is_open", True):
        raise HTTPException(status_code=403, detail="Election is closed.")

    # Timing is governed entirely by the "voting" phase schedule (see PHASE_NAMES / assert_phase_open).
    await assert_phase_open(request, "voting", data.student_id)

    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        await ip_record(request, "fails")
        raise HTTPException(status_code=404, detail="Student ID not found")

    # LEGACY (OTP_LIMITER_MODE=legacy only): permanent 3-send cap. The new limiter never reads otp_count.
    if legacy and student.get("otp_count", 0) >= 3:
        raise HTTPException(
            status_code=403,
            detail="Too many attempts. Please check the official register for your details."
        )

    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Already voted")

    if not names_match(student.get("full_name", ""), data.full_name):
        await ip_record(request, "fails")
        logger.warning(f"Name Match Fail: Reg({student.get('full_name','')}) vs Input({data.full_name})")
        raise HTTPException(status_code=400, detail="Name mismatch. Please provide your full registered names.")

    phone_list = student.get("phone_numbers", [])
    if not phone_list:
        raise HTTPException(status_code=400, detail="No phone found.")

    if len(phone_list) > 1 and data.phone_index is None:
        return {"status": "needs_selection", "masked_numbers": [f"{p[:6]}****{p[-2:]}" for p in phone_list]}

    idx = data.phone_index if data.phone_index is not None else 0
    if not 0 <= idx < len(phone_list):
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
    existing = None if legacy else await db.otps.find_one(org_query(request, {"student_id": sid}))
    live = bool(existing and existing.get("created_at")
                and now - existing["created_at"] < timedelta(minutes=ol.CODE_TTL_MINUTES))
    otp = existing["code"] if live else str(secrets.randbelow(900000) + 100000)

    first_name = student.get("full_name", "Voter").split()[0].capitalize()
    branding_doc = await db.settings.find_one(org_query(request, {"name": "branding"}))
    sms_org_name = (branding_doc or {}).get("org_name", "Election")

    message = (
        f"Hello {first_name}, your {sms_org_name} voting code is {otp}. "
        f"Your vote is secret. Do not share this code with anyone. Your voice, your power!"
    )

    outcome = await send_sms_status(raw_phone, message, request)
    if outcome == "failed":
        if reservation:
            await rollback_send(request, sid, reservation["snapshot"])      # gateway failure is free
        raise HTTPException(status_code=500, detail="SMS Delivery Failed")

    # "ok" or "ambiguous": the SMS may well be on its way, so the code must be valid and the cooldown must hold.
    if not live:
        await db.otps.update_one(
            org_query(request, {"student_id": sid}),
            {"$set": org_stamp(request, {"code": otp, "created_at": now})},
            upsert=True
        )
    await db.voters.update_one(
        org_query(request, {"student_id": sid}),
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
    voter  = await db.voters.find_one(search)
    if not voter:
        raise HTTPException(status_code=404, detail="Voter not found")

    record = await db.otps.find_one(search) or await db.admin_otps.find_one(search)

    if record:
        created_at = record.get("created_at")
        is_expired = (
            created_at is None
            or datetime.utcnow() - created_at > timedelta(minutes=OTP_EXPIRY_MINUTES)
        )
        if is_expired:
            await db.otps.delete_one(search)
            raise HTTPException(status_code=400, detail="This code has expired. Please request a new one.")

        # Constant-time compare so response timing can't leak how many
        # leading digits of a guess were correct.
        if secrets.compare_digest(str(record.get("code", "")), str(data.code)):
            voter_token, vote_jti = create_voter_token(
                student_id=normalize_student_id(voter["student_id"]), org_id=request.state.org_id)
            await db.voters.update_one(search, {"$set": {
                "last_status": "authenticated", "otp_count": 0, "vote_jti": vote_jti,
                "authenticated_at": datetime.utcnow()}})
            await db.otps.delete_one(search)
            await _clear_otp_attempts(request, data.student_id)
            # Failure (otp_verify_locked) was already logged; success never
            # was, so the log couldn't show a complete authentication
            # lifecycle for a voter — only that they'd been locked out, never
            # that they got in.
            await log_action("otp_verified", normalize_student_id(data.student_id), {}, org_id=request.state.org_id)
            return {"status": "success", "voter_token": voter_token}

    await _record_otp_failure(request, data.student_id)
    raise HTTPException(status_code=400, detail="Invalid OTP. Please check your messages and try again.")


@app.post("/verify-otp")
async def verify_otp(data: OTPCheck, request: Request):
    if OTP_LIMITER_MODE == "legacy":
        return await _verify_otp_legacy(data, request)

    search = org_query(request, get_forgiving_filter(data.student_id))
    voter = await db.voters.find_one(search)
    if not voter:
        raise HTTPException(status_code=404, detail="Voter not found")
    sid = voter["student_id"]

    record = await db.otps.find_one(search) or await db.admin_otps.find_one(search)
    created_at = (record or {}).get("created_at")
    live = bool(record and created_at
                and datetime.utcnow() - created_at <= timedelta(minutes=ol.CODE_TTL_MINUTES))
    if not live:
        # No live code: a guess cannot succeed, so it must NOT cost the voter a token (otherwise anyone
        # could lock any voter out for free). Limited only by the per-IP guard.
        if record:
            await db.otps.delete_one(search)
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
        await db.voters.update_one(search, {"$set": {
            "last_status": "authenticated", "otp_count": 0, "vote_jti": vote_jti,
            "authenticated_at": datetime.utcnow()}})
        await db.otps.delete_one(search)
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
    payload = verify_voter_token(request, normalize_student_id(student.get("student_id", "")), request.state.org_id)
    if not student.get("vote_jti") or not secrets.compare_digest(str(payload["jti"]), str(student["vote_jti"])):
        raise HTTPException(status_code=401, detail="Your voting session has expired. Please verify your identity again.")


@app.post("/vote")
async def cast_vote(data: VoteRequest, request: Request):
    try:
        candidate_oid = ObjectId(data.candidate_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid candidate.")

    # Wrapped in a transaction: "mark voter as having voted" and "increment
    # the candidate's tally" are all-or-nothing. Uses with_transaction()
    # rather than a bare start_transaction() context manager because it
    # auto-retries on transient write conflicts — expected when many voters
    # hit the same popular candidate's document concurrently on election
    # day — instead of surfacing those as hard errors to the voter.
    # HTTPException raised inside the callback isn't a PyMongoError, so
    # with_transaction lets it propagate immediately rather than retrying it.
    candidate_exists = await db.candidates.count_documents(
        org_query(request, {"_id": candidate_oid})
    )
    if not candidate_exists:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    await assert_voting_allowed(request, data.student_id)

    async def _do_vote(session):
        student = await db.voters.find_one(
            org_query(request, get_forgiving_filter(data.student_id)), session=session
        )
        if not student or student.get("has_voted"):
            raise HTTPException(status_code=400, detail="Ineligible voter")
        if student.get("last_status") != "authenticated":
            raise HTTPException(status_code=403, detail="OTP verification required before voting.")
        _assert_voter_session(request, student)

        candidate_still_exists = await db.candidates.count_documents(
            org_query(request, {"_id": candidate_oid}), session=session
        )
        if not candidate_still_exists:
            raise HTTPException(status_code=404, detail="Candidate not found.")

        claimed = await db.voters.update_one(
            {"_id": student["_id"], "has_voted": {"$ne": True}},
            {"$set": {"has_voted": True, "last_status": "completed"}, "$unset": {"vote_jti": ""}},
            session=session
        )
        if claimed.matched_count != 1:
            raise HTTPException(status_code=400, detail="Ineligible voter")
        # Append-only insert — no shared document for concurrent voters to
        # lock against, unlike the $inc this replaces. No voter_id is stored:
        # has_voted (on the voter doc) and this event are deliberately
        # decoupled so nothing in the DB links a voter to their choice.
        await db.vote_events.insert_one(
            org_stamp(request, {
                "candidate_id": candidate_oid,
                "cast_at": datetime.utcnow(),
            }),
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
    await log_action("vote_cast", normalize_student_id(data.student_id), {}, org_id=request.state.org_id)

    return {"status": "success"}


@app.post("/vote-bulk")
async def cast_bulk_vote(data: BulkVoteRequest, request: Request):
    try:
        candidate_oids = [ObjectId(c_id) for c_id in data.candidate_ids]
    except Exception:
        raise HTTPException(status_code=400, detail="One or more candidate IDs are invalid.")

    # Same id submitted twice used to slip through: the existence check only
    # compared distinct ids, but insert_many below looped over the raw list
    # — so a repeated id got inserted as two separate vote_events, double
    # counting that one candidate. Reject outright instead of silently
    # de-duping, since a client sending duplicates is either buggy or
    # tampering with the ballot.
    if len(candidate_oids) != len(set(candidate_oids)):
        raise HTTPException(status_code=400, detail="Duplicate candidate selected.")

    await assert_voting_allowed(request, data.student_id)

    # with_transaction auto-retries transient write conflicts — expected
    # under concurrent load when many voters hit the same popular
    # candidate's document at once — instead of surfacing them as hard
    # errors to the voter. See /vote for the same pattern.
    async def _do_bulk_vote(session):
        student = await db.voters.find_one(
            org_query(request, get_forgiving_filter(data.student_id)), session=session
        )
        if not student:
            raise HTTPException(status_code=404, detail="Voter not found")
        if student.get("has_voted"):
            raise HTTPException(status_code=400, detail="You have already cast your vote.")
        if student.get("last_status") != "authenticated":
            raise HTTPException(status_code=403, detail="OTP verification required before voting.")
        _assert_voter_session(request, student)

        # Validate every candidate exists BEFORE writing anything. The old
        # version incremented whichever candidates happened to resolve and
        # silently swallowed failures for the rest — a voter could end up
        # marked as voted with some of their choices never counted. Now
        # it's genuinely all-or-nothing: either every choice is recorded,
        # or none are and the voter can retry.
        candidates = await db.candidates.find(
            org_query(request, {"_id": {"$in": candidate_oids}}), session=session
        ).to_list(length=None)
        if len(candidates) != len(set(candidate_oids)):
            raise HTTPException(status_code=404, detail="One or more selected candidates could not be found.")

        # Nothing previously stopped two candidates for the SAME position
        # both being submitted — a voter (or a crafted request bypassing the
        # UI) could cast two ballots for President in one go. One candidate
        # per position, same as a real ballot.
        positions = [c.get("position") for c in candidates]
        if len(positions) != len(set(positions)):
            raise HTTPException(status_code=400, detail="Only one candidate can be selected per position.")

        claimed = await db.voters.update_one(
            {"_id": student["_id"], "has_voted": {"$ne": True}},
            {"$set": {"has_voted": True, "last_status": "completed"}, "$unset": {"vote_jti": ""}},
            session=session
        )
        if claimed.matched_count != 1:
            raise HTTPException(status_code=400, detail="You have already cast your vote.")
        # Same append-only pattern as /vote, batched as one insert_many so a
        # multi-position ballot is still a single round trip inside the
        # transaction (still all-or-nothing with the has_voted update above).
        cast_at = datetime.utcnow()
        await db.vote_events.insert_many(
            [org_stamp(request, {"candidate_id": c_oid, "cast_at": cast_at})
             for c_oid in candidate_oids],
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

    await log_action("vote_cast", normalize_student_id(data.student_id), {"positions": len(candidate_oids)}, org_id=request.state.org_id)

    return {"status": "success", "message": "Ballot cast successfully"}


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
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
        cand["_id"] = str(cand["_id"])
        candidates.append(cand)
    return candidates

# =============================================================================
# PUBLIC ROUTES
# =============================================================================

@app.get("/positions")
async def get_positions(request: Request):
    positions = []
    async for p in db.positions.find(org_query(request)).sort("order", 1):
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


REGISTER_RATE_LIMIT = 10
REGISTER_RATE_WINDOW_S = 60


async def _check_register_rate_limit(request: Request):
    await _check_rate_limit(
        request, bucket="register", limit=REGISTER_RATE_LIMIT, window_s=REGISTER_RATE_WINDOW_S,
        message="Too many requests. Please try again shortly.",
    )


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
    total = await db.voters.count_documents(query)
    cursor = db.voters.find(
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
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
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
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP, or GIF images are allowed.")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
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
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    return {"secure_url": result["secure_url"]}


@app.post("/apply/check-eligibility")
async def check_application_eligibility(data: ApplicationEligibilityCheck, request: Request):
    await assert_phase_open(request, "applications", data.student_id)
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        raise HTTPException(
            status_code=404,
            detail="Your Student ID was not found on the voter register. Please contact IT support if you believe this is an error."
        )
    if not names_match(student.get("full_name", ""), data.full_name):
        raise HTTPException(
            status_code=400,
            detail="The name entered doesn't match our records for this Student ID. Please enter your full registered name."
        )
    return {"status": "eligible"}

@app.post("/apply")
async def submit_application(data: ApplicationSubmit, request: Request):
    # Applications had NO time gating anywhere — a candidacy could be filed
    # after voting had already closed.
    await assert_phase_open(request, "applications", data.student_id)
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        raise HTTPException(
            status_code=404,
            detail="Your Student ID was not found on the voter register. Please contact IT support if you believe this is an error."
        )
    if not names_match(student.get("full_name", ""), data.full_name):
        raise HTTPException(
            status_code=400,
            detail="The name entered doesn't match our records for this Student ID."
        )
    data.full_name = normalize_name(data.full_name)
    data.student_id = student["student_id"]     # canonical stored form, whatever the applicant typed

    existing = await db.applications.find_one(org_query(request, {
        "student_id": data.student_id,
        "position_id": data.position_id
    }))
    if existing:
        raise HTTPException(400, "You have already applied for this position.")

    await db.applications.insert_one(org_stamp(request, {
        **data.dict(),
        # round_id is written now so multi-round support later is a feature
        # addition, not a breaking data migration.
        "round_id": await current_round_id(request),
        "status": "pending",
        "votes": {},          # { commissioner_student_id: "approve" | "deny" }
        "removal_votes": {},  # same structure, used after approval
        "fee_required": await _position_fee(data.position_id, request.state.org_id),  # what the applicant was told to pay
        "finance_cleared": False,      # gate: Finance Commissioner must clear before voting opens
        "finance_cleared_by": None,
        "finance_cleared_at": None,
        "submitted_at": datetime.utcnow()
    }))
    await log_action("application_submitted", data.student_id, {
    "position_id": data.position_id,
    "full_name":   data.full_name
    }, org_id=request.state.org_id)
    return {"status": "submitted"}

# =============================================================================
# ADMIN ROUTES  (election control — accessible to both superadmin & commission)
# =============================================================================

@app.post("/verify-admin")
async def verify_admin(data: AdminLoginCheck, request: Request):
    email_key = data.email.strip().lower()
    org_id = request.state.org_id
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

    # ── IT Admin ──
    it_admin = await db.voters.find_one(org_query(request, {
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    }))
    if it_admin:
        stored_hash = it_admin.get("it_admin_password_hash", "")
        if not verify_password(data.password, stored_hash):
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
    financial_controller = await db.voters.find_one(org_query(request, {
        "financial_controller_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_financial_controller": True
    }))
    if financial_controller:
        stored_hash = financial_controller.get("financial_controller_password_hash", "")
        if not verify_password(data.password, stored_hash):
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
    overseer = await db.voters.find_one(org_query(request, {
        "overseer_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_overseer": True
    }))
    if overseer:
        stored_hash = overseer.get("overseer_password_hash", "")
        if not verify_password(data.password, stored_hash):
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

    # ── Commissioner ──
    commissioner = await db.voters.find_one(org_query(request, {
        "commissioner_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_commissioner": True
    }))
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
        bcrypt.checkpw(data.password.encode()[:72], _DUMMY_BCRYPT_HASH)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    stored_hash = commissioner.get("commissioner_password_hash", "")
    if not verify_password(data.password, stored_hash):
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
    current    = await db.settings.find_one(org_query(request, {"name": "election_config"}))
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

    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$set": org_stamp(request, {"is_open": new_status, "name": "election_config"})},
        upsert=True
    )
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
    config = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    if (config or {}).get("is_certified"):
        raise HTTPException(400, "Certified results cannot be reset. Revoke certification first.")
    # Safety snapshot BEFORE anything is deleted. If it cannot be uploaded to B2 the
    # reset aborts — it never continues without a backup. With no X-Org-Slug,
    # org_query() is unscoped and this reset touches every tenant, so snapshot all.
    try:
        await backup.snapshot_before_destructive(
            db, request.state.org_id, "reset-election", all_tenants=request.state.org_id is None)
    except Exception as e:
        logger.error(f"reset-election aborted: pre-reset snapshot failed: {e}")
        await backup.send_alert(
            "[BallotBox] Reset ABORTED: pre-reset backup failed",
            f"An election reset was requested by {current_actor(request)} but the safety snapshot "
            f"could not be uploaded, so nothing was deleted.\n\nError: {e}")
        raise HTTPException(503, "Reset aborted: the safety backup could not be uploaded, so nothing was deleted.")
    await db.otps.delete_many(org_query(request))
    # New limiter state belongs to this election run only (the roster_ledger is append-only and is kept).
    _kf = {} if request.state.org_id is None else {"key": {"$regex": f"^{re.escape(request.state.org_id)}:otp:"}}
    await db.otp_send_state.delete_many(_kf)
    await db.otp_guess_state.delete_many(_kf)
    await db.sms_usage.delete_many({} if request.state.org_id is None else {"org_key": request.state.org_id})
    await db.ip_send_stats.delete_many({})
    await db.contact_changes.delete_many(org_query(request))
    await _save_security(request, {"freeze_lifted_at": datetime.utcnow(), "epoch_at": datetime.utcnow()})
    await append_ledger(request.state.org_id, "election_reset", "election", current_actor(request),
                        current_role(request), {"note": "roster freeze lifted; caps and quotas restart"})
    await db.voters.update_many(org_query(request), {"$set": {"has_voted": False, "last_status": "idle"}})
    await db.candidates.update_many(org_query(request), {"$set": {"votes": 0}})
    # votes now live in vote_events, not candidates.votes — without this, a
    # reset (used for testing/re-runs) would leave stale events behind and
    # the next election's tally would include last time's votes.
    await db.vote_events.delete_many(org_query(request))
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
    current    = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    new_status = not (current.get("is_certified", False) if current else False)
    # "Stop the election before certifying" used to live only in the dashboards. Certified results
    # also block voting (assert_voting_allowed), so certifying an open election was a way to end
    # voting early with no reason on record. Enforce it here; revoking is always allowed.
    if new_status and (current.get("is_open", True) if current else True):
        raise HTTPException(400, "Stop the election before certifying results.")
    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$set": {"is_certified": new_status}},
        upsert=True
    )
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
    # free SMS relay for every provisioned role. Goes through the same
    # send_sms() dispatch as real OTPs (EgoSMS primary, MamboSMS fallback),
    # so this test reflects what a voter would actually experience.
    await log_action("sms_test_sent", current_actor(request), {"phone": _mask_phone(data.phone)}, org_id=request.state.org_id)
    success = await send_sms(data.phone, "SMS Connection Verified for BallotBox!", request, kind="test")
    if success:
        return {"status": "success", "message": f"Test message delivered to {data.phone}"}
    raise HTTPException(status_code=400, detail="Both MamboSMS and EgoSMS rejected the request. Check server logs for the reason.")


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


@app.post("/admin/import-voters")
async def import_voters(request: Request, file: UploadFile = File(...), admin: dict = Depends(require_role("it_admin", "superadmin"))):
    await assert_roster_unfrozen(request)   # import also overwrites phones/names of existing voters
    content = await file.read()
    reader  = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    now     = datetime.utcnow()

    ops: list[UpdateOne] = []
    warnings: list[str] = []
    skipped = 0
    row_num = 1  # header is row 1; first data row is 2, matching what a spreadsheet shows

    for row in reader:
        row_num += 1
        # Handle both hyphen (student-id) and underscore (student_id) column names
        sid             = normalize_student_id(row.get('student_id') or row.get('student-id') or '')
        name            = normalize_name((row.get('full_name')  or row.get('full-name')  or '').strip())
        raw_phone_field = (row.get('phone') or '').strip()

        if not (sid and name):
            skipped += 1
            continue

        if len(sid) > IMPORT_FIELD_MAX_LEN or len(name) > IMPORT_FIELD_MAX_LEN:
            skipped += 1
            warnings.append(f"Row {row_num}: student_id or full_name exceeds {IMPORT_FIELD_MAX_LEN} characters — skipped.")
            continue

        raw_numbers       = raw_phone_field.split('/')
        formatted_numbers = []

        for num in raw_numbers:
            clean = re.sub(r'\D', '', num.strip())
            if not clean:
                continue
            if clean.startswith('0'):
                clean = '256' + clean[1:]
            elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
                clean = '256' + clean
            if not _UGANDA_MSISDN_RE.match(clean):
                # Not rejected outright — some legitimate numbers (a foreign
                # number for a diaspora student, say) won't match this
                # pattern, and the importing admin is in a better position
                # than this endpoint to judge one flagged row. It's kept,
                # just surfaced.
                warnings.append(
                    f"Row {row_num} ({sid}): phone \"{num.strip()}\" normalized to \"{clean}\", "
                    f"which doesn't look like a standard Ugandan number — please double-check it."
                )
            if clean not in formatted_numbers:
                formatted_numbers.append(clean)

        # This used to $set has_voted/last_status/is_commissioner to
        # their defaults on EVERY row, including voters who already
        # existed. Re-importing the roster mid-election (to fix a typo,
        # add a few late names, etc.) silently un-voted every existing
        # voter, wiped every commissioner's role, and reset otp_count —
        # while vote_events (the actual tally) is untouched by import
        # and only ever cleared by /admin/reset-election. That's how
        # "votes cast" (from vote_events, cumulative across re-imports)
        # and "completed voters" (from voters.has_voted, reset by the
        # next import) drift apart — the Undervote/Funnel panels were
        # comparing two counters that could silently fall out of sync.
        # It was also a real double-vote path: a re-imported voter's
        # has_voted flips back to False, so they can authenticate and
        # vote again, adding a second vote_events row for the same
        # person. $setOnInsert confines the reset-to-defaults to voters
        # that don't exist yet; an existing voter's status is untouched
        # by a re-import, only their name/phone are refreshed.
        ops.append(UpdateOne(
            org_query(request, {"student_id": sid}),
            {
                "$set": org_stamp(request, {
                    "full_name":     name,
                    "phone_numbers": formatted_numbers,
                    "updated_at":    now,
                }),
                "$setOnInsert": {
                    "is_commissioner": False,
                    "has_voted":       False,
                    "last_active":     None,
                    "last_status":     "idle",
                    "otp_count":       0,
                },
            },
            upsert=True
        ))

    if ops:
        # PERFORMANCE: previously one update_one round trip per CSV row in a
        # plain Python loop — fine for a few hundred students, but a roster
        # in the low thousands could take long enough to risk hitting the
        # platform's request timeout, leaving the import silently partial
        # with no clear signal of where it stopped. bulk_write sends every
        # row's update in one (or a few, batched by the driver) round trip.
        # unordered=True so one bad row doesn't abort the rows after it.
        await db.voters.bulk_write(ops, ordered=False)
    count = len(ops)  # rows that passed validation and were sent to Mongo

    # Cap how many individual warnings ride along in the response — a badly
    # formatted file could otherwise generate thousands of lines. The admin
    # still gets the total count and a representative sample.
    MAX_WARNINGS_RETURNED = 50
    await log_action("voters_imported", current_actor(request), {
        "count": count, "skipped": skipped, "warning_count": len(warnings)
    }, org_id=request.state.org_id)
    return {
        "status": "success",
        "imported_count": count,
        "skipped_rows": skipped,
        "warnings": warnings[:MAX_WARNINGS_RETURNED],
        "warning_count": len(warnings),
    }

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB


@app.post("/admin/upload-image")
async def admin_upload_image(request: Request, file: UploadFile = File(...), admin: dict = Depends(require_role("it_admin", "superadmin"))):
    """Signed, server-side Cloudinary upload for candidate photos etc.
    Replaces the old unsigned-preset upload that ran directly from the
    browser. Protected automatically by auth_guard_middleware (any admin
    role) since this path starts with /admin.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP, or GIF images are allowed.")

    content = await file.read()
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


@app.get("/admin/voters")
async def get_all_voters(request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    voters = []
    async for v in db.voters.find(org_query(request), {"_id": 0}):
        # Full numbers are only served by the audited /admin/students/lookup edit screens.
        v["phone_numbers"] = [_mask_phone(p) for p in v.get("phone_numbers", [])]
        voters.append(v)
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
    it_admin = await db.voters.find_one(org_query(request, {
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    }))
    if it_admin:
        _assert_self(it_admin)
        if not verify_password(data.old_password, it_admin.get("it_admin_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await db.voters.update_one(
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
    financial_controller = await db.voters.find_one(org_query(request, {
        "financial_controller_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_financial_controller": True
    }))
    if financial_controller:
        _assert_self(financial_controller)
        if not verify_password(data.old_password, financial_controller.get("financial_controller_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await db.voters.update_one(
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
    overseer = await db.voters.find_one(org_query(request, {
        "overseer_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_overseer": True
    }))
    if overseer:
        _assert_self(overseer)
        if not verify_password(data.old_password, overseer.get("overseer_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await db.voters.update_one(
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

    # Try commissioner
    commissioner = await db.voters.find_one(org_query(request, {
        "commissioner_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_commissioner": True
    }))
    if commissioner:
        _assert_self(commissioner)
        if not verify_password(data.old_password, commissioner.get("commissioner_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        _assert_password_strength(data.new_password)
        await db.voters.update_one(
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
    result = await db.candidates.insert_one(org_stamp(request, candidate.dict()))
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
    await db.candidates.update_one(org_query(request, {"_id": oid}), {"$set": upd})
    await log_action("candidate_updated", current_actor(request), {
        "candidate_id": candidate_id, "name": upd.get("name"), "position": upd.get("position")
    }, org_id=request.state.org_id)
    return {"status": "success"}


@app.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, request: Request, admin: dict = Depends(require_role("superadmin"))):
    oid = parse_oid(candidate_id, "candidate id")
    doomed = await db.candidates.find_one(org_query(request, {"_id": oid}))
    await db.candidates.delete_one(org_query(request, {"_id": oid}))
    await log_action("candidate_deleted", current_actor(request), {
        "candidate_id": candidate_id,
        "name": (doomed or {}).get("name", ""),
        "position": (doomed or {}).get("position", ""),
    }, org_id=request.state.org_id)
    return {"status": "deleted"}


# --- Applications list (shared: both superadmin and commission can read) ---

@app.get("/admin/applications")
async def list_applications(request: Request, status: str = None):
    query = org_query(request)
    if status:
        query["status"] = status
    apps = []
    async for a in db.applications.find(query).sort("submitted_at", -1):
        a["_id"] = str(a["_id"])
        if a.get("position_id"):
            title, order = await _resolve_position_title(a["position_id"], request.state.org_id)
            a["position_title"] = title
            a["position_order"] = order
        else:
            a["position_order"] = 0
        apps.append(a)
    apps.sort(key=lambda x: (x.get("position_order", 0), -x["submitted_at"].timestamp() if x.get("submitted_at") else 0))
    return apps

# =============================================================================
# COMMISSION ROUTES  (voting — requires commission login)
# =============================================================================

@app.post("/admin/applications/{app_id}/vote")
async def commissioner_vote(app_id: str, data: CommissionerVote, request: Request):
    """A commissioner casts their approve/deny vote on a pending application."""
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' or 'deny'.")

    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if not app_doc.get("finance_cleared"):
        raise HTTPException(400, "Awaiting Finance Commissioner clearance before voting can open.")
    # Commissioners may only cast approve/deny votes inside the scheduled vetting window
    # (set on the Timeline tab); Finance clearance above is deliberately exempt from this.
    await assert_phase_open(request, "vetting")

    # SECURITY: the body-supplied commissioner_id used to be trusted on its
    # own, so any valid admin token (an Overseer's, an IT Admin's) could cast
    # a Commission vote under another commissioner's name. Bind it to the
    # authenticated token subject first.
    bind_identity(request, data.commissioner_id, "commissioner account")

    # Verify the voter exists and is actually a commissioner
    commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    }))
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    await log_action("application_vote_cast", current_actor(request), {
        "app_id": app_id, "vote": data.vote, "reason": data.reason
    }, org_id=request.state.org_id)

    # Record vote (keyed by commissioner_id so they can only vote once per application)
    await db.applications.update_one(
        org_query(request, {"_id": oid}),
        {"$set": {f"votes.{_vote_key(data.commissioner_id)}": data.vote}}
    )

    updated = await db.applications.find_one(org_query(request, {"_id": oid}))
    await _resolve_application(app_id, updated, request.state.org_id)

    return {"status": "vote_recorded"}


@app.post("/admin/applications/{app_id}/vote-remove")
async def commissioner_vote_remove(app_id: str, data: CommissionerVote, request: Request):
    """A commissioner votes to remove an already-approved candidate.

    ON HOLD: deliberately not wired into any frontend (no button in CommissionDashboard
    calls this route). It was pulled from the UI earlier because it confused commissioners,
    and we're still deciding whether it's worth bringing back before re-exposing it. Leave
    this endpoint as-is until that's settled — don't add UI for it without checking first.
    """
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' (remove) or 'deny' (keep).")

    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") != "approved":
        raise HTTPException(400, "Can only vote to remove an approved candidate.")

    bind_identity(request, data.commissioner_id, "commissioner account")

    commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    }))
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    await log_action("candidate_removal_vote", current_actor(request), {
        "app_id": app_id, "vote": data.vote
    }, org_id=request.state.org_id)

    safe_key = _vote_key(data.commissioner_id)
    await db.applications.update_one(
        org_query(request, {"_id": oid}),
        {"$set": {f"removal_votes.{safe_key}": data.vote}}
    )

    updated = await db.applications.find_one(org_query(request, {"_id": oid}))
    await _resolve_removal(app_id, updated, request.state.org_id)

    return {"status": "removal_vote_recorded"}


@app.post("/admin/applications/{app_id}/finance-clear")
async def finance_clear_application(app_id: str, data: FinanceClear, request: Request):
    """
    The Finance Commissioner verifies the candidate's payment status and clears
    the application for voting. No commissioner (including her) can cast a vote
    on this application until this is done.
    """
    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared.")

    bind_identity(request, data.commissioner_id, "commissioner account")

    finance_commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True,
        "is_finance_commissioner": True
    }))
    if not finance_commissioner:
        raise HTTPException(403, "Only the designated Finance Commissioner can clear applications.")

    # Atomic guard: fold the "not already cleared / not already resolved"
    # check into the update filter itself instead of trusting the read
    # above. Two near-simultaneous clear requests (a double-click, or a
    # retry) would otherwise both pass the earlier read-based check and
    # both write — this keeps finance_cleared_by/at accurate to whoever's
    # write actually won, and matches the guard pattern used everywhere
    # else in this file (see _resolve_application, _resolve_removal, and
    # financial_controller_decide_student_change).
    result = await db.applications.update_one(
        org_query(request, {
            "_id": oid,
            "finance_cleared": {"$ne": True},
            "status": {"$nin": ["approved", "denied", "removed"]},
        }),
        {"$set": {
            "finance_cleared": True,
            "finance_cleared_by": data.commissioner_id,
            "finance_cleared_at": datetime.utcnow()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(400, "This application was already resolved or finance-cleared by someone else.")
    await log_action("application_finance_cleared", data.commissioner_id, {"app_id": app_id}, org_id=request.state.org_id)

    # Nomination/vetting date comes from the "vetting" phase on the admin Timeline, not a
    # hardcoded string, so it always matches whatever dates are actually configured this round.
    # Shown in the org's election timezone (same convention as assert_phase_open's _when()) —
    # the raw UTC value alone can read as the wrong calendar day/time to the applicant.
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
        + (f" on {when}." if when else " — the date will be communicated once the Timeline is set.")))
    logger.info(f"Application {app_id} finance-cleared by {data.commissioner_id}.")
    return {"status": "finance_cleared"}


@app.post("/admin/applications/{app_id}/finance-reject")
async def finance_reject_application(app_id: str, data: FinanceReject, request: Request):
    """
    The Finance Commissioner rejects the candidate's payment/receipt with a
    required reason. This resolves the application as denied, mirroring the
    commission's deny flow but for the finance gate specifically.
    """
    if not data.reason.strip():
        raise HTTPException(400, "A reason is required to reject an application.")

    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared and can no longer be finance-rejected.")

    bind_identity(request, data.commissioner_id, "commissioner account")

    finance_commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True,
        "is_finance_commissioner": True
    }))
    if not finance_commissioner:
        raise HTTPException(403, "Only the designated Finance Commissioner can reject applications.")

    # Same atomic-guard pattern as finance_clear_application: fold the
    # "not already cleared / not already resolved" check into the update
    # filter itself so a double-click or race can't double-write.
    result = await db.applications.update_one(
        org_query(request, {
            "_id": oid,
            "finance_cleared": {"$ne": True},
            "status": {"$nin": ["approved", "denied", "removed"]},
        }),
        {"$set": {
            "status": "denied",
            "finance_rejected": True,
            "finance_rejected_by": data.commissioner_id,
            "finance_rejected_at": datetime.utcnow(),
            "finance_rejection_reason": data.reason.strip(),
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(400, "This application was already resolved or cleared by someone else.")

    await log_action("application_finance_rejected", data.commissioner_id,
                      {"app_id": app_id, "reason": data.reason.strip()}, org_id=request.state.org_id)
    fee = app_doc.get("fee_required") or 0
    reason = data.reason.strip()[:80]
    await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
        f"{org}: Your nomination for {pos} was rejected because of your payment: {reason}."
        + (f" The required amount is {fmt_ugx(fee)}; incomplete payments are not accepted." if fee else "")
        + " Contact the Electoral Commission."))
    logger.info(f"Application {app_id} finance-rejected by {data.commissioner_id}.")
    return {"status": "denied"}


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
    async for v in db.voters.find(
        org_query(request, {"is_commissioner": True}),
        {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1,
         "is_deputy_chief_commissioner": 1, "is_finance_commissioner": 1, "commissioner_role": 1},
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
    total_voters = await db.voters.count_documents(org_query(request))
    voted_count = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    vote_counts = await get_vote_counts(request)
    positions_by_id = {}
    async for pos in db.positions.find(org_query(request)).sort("order", 1):
        positions_by_id[str(pos["_id"])] = pos
    grouped: dict = {}
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
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
        "created_at":        datetime.utcnow(),
        "branding_defaults": {
            "org_name": data.name
        }
    }
    result = await db.organizations.insert_one(org_doc)
    await log_action("organization_created", current_actor(request), {
        "org_id": str(result.inserted_id), "name": data.name, "slug": slug
    })
    logger.info(f"Organization '{data.name}' provisioned with slug '{slug}'.")
    return {
        "org_id": str(result.inserted_id),
        "name":   data.name,
        "slug":   slug
    }


@app.get("/superadmin/orgs")
async def list_organizations():
    orgs = []
    async for o in db.organizations.find({}).sort("created_at", -1):
        o["_id"] = str(o["_id"])
        orgs.append(o)
    return orgs


# =============================================================================
# SUPERADMIN ROUTES  (instant overrides — no voting required)
# =============================================================================

# --- Branding ---

@app.get("/superadmin/branding")
async def get_branding(request: Request):
    doc = await db.settings.find_one(org_query(request, {"name": "branding"}))
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
            "cc_list":             []
        }
        
    # This endpoint is unauthenticated by design (App.jsx and Results.jsx fetch it for
    # every visitor before anyone logs in), so only return fields meant for a public
    # visitor. cc_list (officials' email addresses) and org_id have no business here.
    PUBLIC_BRANDING_FIELDS = (
        "logo_url", "primary_color", "accent_color", "org_name", "university_name",
        "university_logo_url", "support_phone",
    )
    out = {k: doc.get(k, "") for k in PUBLIC_BRANDING_FIELDS}
    out["support_contacts"] = doc.get("support_contacts") or []
    return out


# The public endpoint above deliberately strips cc_list/signatories for
# unauthenticated visitors. The SuperAdmin settings form needs those back to
# edit them without wiping them on every save, hence this authenticated twin.
@app.get("/superadmin/branding-full")
async def get_branding_full(request: Request, admin: dict = Depends(require_role("superadmin"))):
    doc = await db.settings.find_one(org_query(request, {"name": "branding"})) or {}
    defaults = {
        "logo_url": "", "primary_color": "#003366", "accent_color": "#f1c40f",
        "org_name": "", "university_name": "", "university_logo_url": "",
        "support_phone": "", "support_contacts": [],
        "cc_list": [], "signatories": [],
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
    await db.settings.update_one(
        org_query(request, {"name": "branding"}),
        {"$set": org_stamp(request, {**doc, "name": "branding"})},
        upsert=True
    )
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
    result = await db.positions.insert_one(org_stamp(request, data.dict()))
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
    res = await db.positions.update_one(org_query(request, {"_id": oid}), {"$set": changes})
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
    await db.positions.delete_one(org_query(request, {"_id": oid}))
    await log_action("position_deleted", current_actor(request), {"position_id": position_id}, org_id=request.state.org_id)
    return {"status": "deleted"}


# --- Commissioner management ---

@app.get("/superadmin/commissioners")
async def list_commissioners(request: Request):
    result = []
    async for v in db.voters.find(
        org_query(request, {"is_commissioner": True}),
        {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1, "is_deputy_chief_commissioner": 1, "is_finance_commissioner": 1, "commissioner_role": 1, "commissioner_email": 1}
    ):
        result.append(v)
    return result
    
@app.post("/superadmin/commissioners/{student_id:path}/set-chief")
async def set_chief_commissioner(student_id: str, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await db.voters.update_many(org_query(request), {"$set": {"is_chief_commissioner": False}})
    await db.voters.update_one(
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
    await db.voters.update_one(
        org_query(request, get_forgiving_filter(student_id)),
        {"$set": {"is_chief_commissioner": False}}
    )
    await log_action("chief_commissioner_cleared", current_actor(request), {
        "student_id": normalize_student_id(student_id)
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_chief_commissioner": False}


@app.post("/superadmin/commissioners/{student_id:path}/set-deputy-chief")
async def set_deputy_chief_commissioner(student_id: str, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await db.voters.update_many(org_query(request), {"$set": {"is_deputy_chief_commissioner": False}})
    await db.voters.update_one(
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
    await db.voters.update_one(
        org_query(request, get_forgiving_filter(student_id)),
        {"$set": {"is_deputy_chief_commissioner": False}}
    )
    await log_action("deputy_chief_commissioner_cleared", current_actor(request), {
        "student_id": normalize_student_id(student_id)
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_deputy_chief_commissioner": False}


@app.get("/superadmin/chief-commissioner")
async def get_chief_commissioner(request: Request):
    chief = await db.voters.find_one(
        org_query(request, {"is_chief_commissioner": True}),
        {"_id": 0, "student_id": 1, "full_name": 1}
    )
    if not chief:
        return {"full_name": None}
    return chief


@app.post("/superadmin/commissioners/{student_id:path}/set-finance-commissioner")
async def set_finance_commissioner(student_id: str, request: Request):
    """Designate one commissioner as the Finance Commissioner (Treasurer).
    Only one at a time — mirrors the chief-commissioner exclusivity pattern."""
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_finance_commissioner": True}}
    )
    await log_action("finance_commissioner_set", current_actor(request), {"student_id": student_id}, org_id=request.state.org_id)
    return {"student_id": student_id, "is_finance_commissioner": True}


@app.post("/superadmin/commissioners/{student_id:path}/clear-finance-commissioner")
async def clear_finance_commissioner(student_id: str, request: Request):
    await db.voters.update_one(
        org_query(request, get_forgiving_filter(student_id)),
        {"$set": {"is_finance_commissioner": False}}
    )
    await log_action("finance_commissioner_cleared", current_actor(request), {"student_id": student_id}, org_id=request.state.org_id)
    return {"student_id": student_id, "is_finance_commissioner": False}


@app.get("/superadmin/finance-commissioner")
async def get_finance_commissioner(request: Request):
    """Returns all current finance commissioners (there can be more than one)."""
    result = []
    async for fc in db.voters.find(
        org_query(request, {"is_finance_commissioner": True}),
        {"_id": 0, "student_id": 1, "full_name": 1}
    ):
        result.append(fc)
    return result


@app.post("/superadmin/commissioners/{student_id:path}/set-role")
async def set_commissioner_role(student_id: str, data: CommissionerRoleUpdate, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await db.voters.update_one(
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
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_commissioner", False)
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_commissioner": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("commissioner_toggled", current_actor(request), {
    "student_id": student_id, "is_commissioner": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_commissioner": new_val}

@app.post("/superadmin/it-admins/{student_id:path}/set-credentials")
async def set_it_admin_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_it_admin"):
        raise HTTPException(400, "This person is not an IT admin.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    """Approve an application instantly, bypassing commission voting."""
    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") == "approved":
        raise HTTPException(400, "Already approved.")

    # Atomic guard, same pattern as _resolve_application: claim the
    # not-yet-approved document via the update filter so this can't race a
    # commission majority vote (or a concurrent duplicate click) into
    # creating two candidates for the same application.
    result = await db.applications.update_one(
        org_query(request, {"_id": oid, "status": {"$ne": "approved"}}),
        {"$set": {
            "status": "approved",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just approved by someone else. Please refresh.")
    await _create_candidate_from_application(app_doc, request.state.org_id)
    await _notify_applicant(app_doc, request.state.org_id, lambda org, pos: (
        f"{org}: Congratulations! Your nomination for {pos} has been approved. "
        f"Your name will appear on the ballot."))
    await log_action("application_force_approved", current_actor(request), {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f" Superadmin force-approved application {app_id}.")
    return {"status": "force_approved"}


@app.post("/superadmin/applications/{app_id}/force-deny")
async def superadmin_force_deny(app_id: str, request: Request):
    """Deny an application instantly, bypassing commission voting."""
    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("denied", "removed"):
        raise HTTPException(400, "Application is already denied or removed.")

    result = await db.applications.update_one(
        org_query(request, {"_id": oid, "status": {"$nin": ["denied", "removed"]}}),
        {"$set": {
            "status": "denied",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(409, "This application was just resolved by someone else. Please refresh.")
    await log_action("application_force_denied", current_actor(request), {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f" Superadmin force-denied application {app_id}.")
    return {"status": "force_denied"}


@app.post("/superadmin/applications/{app_id}/force-finance-clear")
async def superadmin_force_finance_clear(app_id: str, request: Request):
    """Bypass the Finance Commissioner gate — for cases where no Finance
    Commissioner is currently assigned. Voting can proceed after this."""
    oid = parse_oid(app_id, "application id")
    app_doc = await db.applications.find_one(org_query(request, {"_id": oid}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared.")

    result = await db.applications.update_one(
        org_query(request, {"_id": oid, "finance_cleared": {"$ne": True}}),
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
    cand = await db.candidates.find_one(org_query(request, {"_id": oid}))
    if not cand:
        raise HTTPException(404, "Candidate not found.")

    await db.candidates.delete_one(org_query(request, {"_id": oid}))
    await log_action("candidate_removed", current_actor(request), {
    "name": cand.get("name"), "position": cand.get("position")
    }, org_id=request.state.org_id)
    
    # If the candidate came from an application, mark it removed
    if cand.get("application_id"):
        await db.applications.update_one(
            org_query(request, {"_id": parse_oid(cand["application_id"], "application id")}),
            {"$set": {
                "status": "removed",
                "superadmin_override": True,
                "removed_at": datetime.utcnow()
            }}
        )

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
            cfg = await db.settings.find_one(org_query(request, {"name": "election_config"})) or {}
            results_released = cfg.get("is_certified", False) or (
                results_mode == "closed" and not cfg.get("is_open", True))
    voter_turnout = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    results = []
    if results_released:
        vote_counts = await get_vote_counts(request)
        async for cand in db.candidates.find(org_query(request)).sort("order", 1):
            results.append({
                "id": str(cand["_id"]),
                "name": cand["name"],
                "position": cand["position"],
                "votes": vote_counts.get(str(cand["_id"]), 0),
                "order": cand.get("order", 0)
            })
    return {"voter_turnout": voter_turnout, "results": results, "results_released": results_released}

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
    status_doc = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    election_status = {
        "is_open":      (status_doc or {}).get("is_open", True),
        "is_certified": (status_doc or {}).get("is_certified", False),
        "start":        (status_doc or {}).get("start_time"),
        "end":          (status_doc or {}).get("end_time")
    }

    total_voters   = await db.voters.count_documents(org_query(request))
    voted_count    = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    total_commissioners = await get_commissioner_count(request.state.org_id)

    applications_summary = []
    async for a in db.applications.find(org_query(request)).sort("submitted_at", -1):
        votes = a.get("votes", {})
        removal_votes = a.get("removal_votes", {})
        applications_summary.append({
            "id":               str(a["_id"]),
            "full_name":        a.get("full_name", ""),
            "position_id":      a.get("position_id", ""),
            "status":           a.get("status", "pending"),
            "finance_cleared":  a.get("finance_cleared", False),
            "approve_count":    sum(1 for v in votes.values() if v == "approve"),
            "deny_count":       sum(1 for v in votes.values() if v == "deny"),
            "votes_cast":       len(votes),
            "removal_approve_count": sum(1 for v in removal_votes.values() if v == "approve"),
            "submitted_at":     a.get("submitted_at")
            # NOTE: raw `votes` / `removal_votes` maps intentionally omitted —
            # those identify which commissioner cast which vote.
        })

    student_changes_summary = []
    async for c in db.student_changes.find(org_query(request)).sort("requested_at", -1):
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
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
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
    # Prevent duplicate pending requests for same student
    existing = await db.student_changes.find_one(org_query(request, {
        "student_id":  data.student_id,
        "change_type": "add",
        "status":      "pending"
    }))
    if existing:
        raise HTTPException(400, "A pending add request already exists for this student.")

    result = await db.student_changes.insert_one(org_stamp(request, {
        **data.dict(),
        "change_type":  "add",
        "status":       "pending",
        "requested_at": datetime.utcnow()
    }))
    await log_action("student_add_requested", data.requested_by, {
        "student_id": data.student_id,
        "full_name":  data.full_name,
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "requested", "id": str(result.inserted_id)}

@app.post("/superadmin/it-admins/{student_id:path}/reset-password")
async def reset_it_admin_password(student_id: str, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter or not voter.get("is_it_admin"):
        raise HTTPException(404, "IT admin not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter or not voter.get("is_commissioner"):
        raise HTTPException(404, "Commissioner not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        raise HTTPException(404, "Student not found in voter register.")

    existing = await db.student_changes.find_one(org_query(request, {
        "student_id":  data.student_id,
        "change_type": "remove",
        "status":      "pending"
    }))
    if existing:
        raise HTTPException(400, "A pending removal request already exists for this student.")

    result = await db.student_changes.insert_one(org_stamp(request, {
        **data.dict(),
        "full_name":    student.get("full_name", ""),
        "change_type":  "remove",
        "status":       "pending",
        "requested_at": datetime.utcnow()
    }))
    await log_action("student_remove_requested", data.requested_by, {
        "student_id": data.student_id,
        "full_name":  student.get("full_name", ""),
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "requested", "id": str(result.inserted_id)}


@app.post("/it-admin/students/requests/{change_id}/cancel")
async def cancel_student_change(change_id: str, data: StudentChangeCancelRequest, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    oid = parse_oid(change_id, "change id")
    change = await db.student_changes.find_one(org_query(request, {"_id": oid}))
    if not change:
        raise HTTPException(404, "Request not found.")
    bind_identity(request, data.requested_by, "IT Admin account")
    if change.get("requested_by") != data.requested_by:
        raise HTTPException(403, "You can only cancel your own requests.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"Cannot cancel a request that is already {change.get('status')}.")

    await db.student_changes.update_one(
        org_query(request, {"_id": oid}),
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


@app.get("/it-admin/students/my-requests/{it_admin_id}")
async def get_my_requests(it_admin_id: str, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    bind_identity(request, it_admin_id, "IT Admin account")
    changes = []
    async for c in db.student_changes.find(
        org_query(request, {"requested_by": it_admin_id})
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
    async for c in db.student_changes.find(query).sort("requested_at", -1):
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
        raise HTTPException(400, "decision must be 'approve' or 'deny'.")

    oid = parse_oid(change_id, "change id")
    change = await db.student_changes.find_one(org_query(request, {"_id": oid}))
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"This request is already {change.get('status')}.")

    bind_identity(request, data.financial_controller_id, "Financial Controller account")

    financial_controller = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.financial_controller_id),
        "is_financial_controller": True
    }))
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
    claim = await db.student_changes.update_one(
        org_query(request, {"_id": oid, "status": "pending"}),
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

@app.get("/superadmin/it-admins")
async def list_it_admins(request: Request):
    result = []
    async for v in db.voters.find(
        org_query(request, {"is_it_admin": True}),
        {"_id": 0, "student_id": 1, "full_name": 1, "it_admin_email": 1}
    ):
        result.append(v)
    return result


@app.post("/superadmin/it-admins/{student_id:path}/toggle")
async def toggle_it_admin(student_id: str, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_it_admin", False)
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_it_admin": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("it_admin_toggled", current_actor(request), {
        "student_id": student_id, "is_it_admin": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_it_admin": new_val}


@app.post("/superadmin/commissioners/{student_id:path}/set-credentials")
async def set_commissioner_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
# SUPERADMIN — FINANCIAL CONTROLLER MANAGEMENT (student register approvals)
# =============================================================================

@app.get("/superadmin/financial-controllers")
async def list_financial_controllers(request: Request):
    result = []
    async for v in db.voters.find(
        org_query(request, {"is_financial_controller": True}),
        {"_id": 0, "student_id": 1, "full_name": 1, "financial_controller_email": 1}
    ):
        result.append(v)
    return result


@app.post("/superadmin/financial-controllers/{student_id:path}/toggle")
async def toggle_financial_controller(student_id: str, request: Request):
    """Grant or revoke Financial Controller status for any voter. Independent
    of is_commissioner — this role never touches candidate business."""
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_financial_controller", False)
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_financial_controller": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("financial_controller_toggled", current_actor(request), {
        "student_id": student_id, "is_financial_controller": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_financial_controller": new_val}


@app.post("/superadmin/financial-controllers/{student_id:path}/set-credentials")
async def set_financial_controller_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_financial_controller"):
        raise HTTPException(400, "This person is not a Financial Controller.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter or not voter.get("is_financial_controller"):
        raise HTTPException(404, "Financial Controller not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    async for v in db.voters.find(
        org_query(request, {"is_overseer": True}),
        {"_id": 0, "student_id": 1, "full_name": 1, "overseer_email": 1}
    ):
        result.append(v)
    return result


@app.post("/superadmin/overseers/{student_id:path}/toggle")
async def toggle_overseer(student_id: str, request: Request):
    """Grant or revoke Overseer status for any voter. Read-only role — never
    touches votes, applications, or student changes, only observes them."""
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_overseer", False)
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_overseer": new_val, **(await _invalidate_sessions(voter["_id"]))}}
    )
    await log_action("overseer_toggled", current_actor(request), {
        "student_id": student_id, "is_overseer": new_val
    }, org_id=request.state.org_id)
    return {"student_id": student_id, "is_overseer": new_val}


@app.post("/superadmin/overseers/{student_id:path}/set-credentials")
async def set_overseer_credentials(student_id: str, data: SetEmailOnly, request: Request):
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_overseer"):
        raise HTTPException(400, "This person is not an Overseer.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter or not voter.get("is_overseer"):
        raise HTTPException(404, "Overseer not found.")

    temp_password = generate_temp_password()
    hashed = hash_password(temp_password)

    await db.voters.update_one(
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
    async for c in db.student_changes.find(query).sort("requested_at", -1):
        c["_id"] = str(c["_id"])
        changes.append(c)
    return changes


@app.post("/superadmin/student-changes/{change_id}/force-approve")
async def superadmin_force_student_change_approve(change_id: str, request: Request):
    await assert_roster_unfrozen(request)
    oid = parse_oid(change_id, "change id")
    change = await db.student_changes.find_one(org_query(request, {"_id": oid}))
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
    result = await db.student_changes.update_one(
        org_query(request, {
            "_id": oid,
            "status": {"$nin": ["approved", "force_approved", "denied", "force_denied", "cancelled"]},
        }),
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
    change = await db.student_changes.find_one(org_query(request, {"_id": oid}))
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("denied", "force_denied", "cancelled"):
        raise HTTPException(400, f"Request is already {change.get('status')}.")

    result = await db.student_changes.update_one(
        org_query(request, {
            "_id": oid,
            "status": {"$nin": ["approved", "force_approved", "denied", "force_denied", "cancelled"]},
        }),
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


@app.post("/superadmin/students/add")
async def superadmin_add_student(data: ITAdminStudentAdd, request: Request):
    await assert_roster_unfrozen(request)
    data.full_name = normalize_name(data.full_name)
    # Must match the canonical stored form: every lookup (login, search, votes) does an exact
    # match on normalize_student_id(), so a reg no. saved as typed could never be found.
    data.student_id = normalize_student_id(data.student_id)
    phones = []
    for raw in data.phones:
        if not str(raw or "").strip():
            continue
        clean = normalize_phone_number(raw)
        if clean not in phones:
            phones.append(clean)
    await db.voters.update_one(
        org_query(request, {"student_id": data.student_id}),
        {"$set": org_stamp(request, {
            "full_name":       data.full_name,
            "phone_numbers":   phones,
            "added_by":        "superadmin",
            "add_reason":      data.reason
        }),
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
    org_id = request.state.org_id
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
    org_id = request.state.org_id
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
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        raise HTTPException(404, "Student not found.")
    await db.voters.delete_one(org_query(request, get_forgiving_filter(data.student_id)))
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


class StudentEditRequest(BaseModel):
    student_id: str                # CURRENT registration number of the record
    full_name: str | None = None
    new_student_id: str | None = None
    phone_ops: list[StudentPhoneOp] = []
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


def _student_edit_view(v: dict) -> dict:
    return {
        "student_id": v.get("student_id", ""),
        "full_name": v.get("full_name", ""),
        "phone_numbers": v.get("phone_numbers", []),
        "has_voted": bool(v.get("has_voted")),
        "holds_admin_role": any(v.get(f) for f in STUDENT_ROLE_FLAGS),
    }


@app.get("/admin/students/lookup")
async def lookup_students_for_edit(q: str, request: Request,
                                   admin: dict = Depends(require_role(*STUDENT_EDIT_ROLES))):
    q = q.strip()
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    cur = db.voters.find({"org_id": request.state.org_id, "$or": [{"student_id": rx}, {"full_name": rx}]}).limit(10)
    return [_student_edit_view(v) async for v in cur]


async def _apply_student_edit(org_id, voter: dict, full_name: str | None, new_student_id: str | None,
                              phone_ops: list) -> dict:
    """Validate and apply name / registration-number / phone operations with optimistic concurrency.
    Shared by direct edits and approved contact changes so the two can never drift apart."""
    old_sid = voter["student_id"]
    old_name = voter.get("full_name", "")
    old_phones = list(voter.get("phone_numbers", []))
    new_name, new_sid, phones = old_name, old_sid, list(old_phones)
    events: list[dict] = []          # {event, field, old, new}

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
            raise HTTPException(400, "Registration number must be 1-64 characters with no spaces.")
        if candidate_sid != old_sid:
            if any(voter.get(f) for f in STUDENT_ROLE_FLAGS):
                raise HTTPException(409, "This student holds an admin/commission role, whose sessions and votes are "
                                         "keyed to the registration number. Remove the role before changing it.")
            if await db.voters.find_one({"org_id": org_id, "student_id": candidate_sid, "_id": {"$ne": voter["_id"]}}):
                raise HTTPException(409, "Another student in this organization already has that registration number.")
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
    updated = await db.voters.update_one(
        {"_id": voter["_id"], "org_id": org_id, "student_id": old_sid,
         "full_name": old_name, "phone_numbers": old_phones},
        {"$set": {"full_name": new_name, "student_id": new_sid, "phone_numbers": phones}},
    )
    if updated.matched_count != 1:
        raise HTTPException(409, "This student was changed by someone else; reload and try again.")

    if new_sid != old_sid:
        # No unique index exists on (org_id, student_id), so re-check after writing and roll back
        # if a concurrent edit/import produced a duplicate.
        if await db.voters.count_documents({"org_id": org_id, "student_id": new_sid}) > 1:
            await db.voters.update_one(
                {"_id": voter["_id"]},
                {"$set": {"full_name": old_name, "student_id": old_sid, "phone_numbers": old_phones}})
            raise HTTPException(409, "Another student in this organization already has that registration number.")
        # Keep the student's own records attached to the new number.
        for coll in (db.applications, db.exception_grants, db.contact_changes):
            await coll.update_many({"org_id": org_id, "student_id": old_sid}, {"$set": {"student_id": new_sid}})

    return {"events": events, "old_sid": old_sid, "new_sid": new_sid, "old_name": old_name,
            "new_name": new_name, "old_phones": old_phones, "phones": phones}


async def _write_student_audit(org_id, voter: dict, res: dict, reason: str, actor: str, role: str,
                               extra: dict | None = None):
    now, batch = datetime.utcnow(), secrets.token_hex(8)
    old_sid, new_sid = res["old_sid"], res["new_sid"]
    terms = sorted({old_sid, new_sid, res["old_name"].lower(), res["new_name"].lower()} - {""})
    for ev in res["events"]:
        await db.student_edit_audit.insert_one({
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
    voter = await db.voters.find_one({"org_id": org_id, "student_id": old_sid})
    if not voter:
        raise HTTPException(404, "Student not found in this organization.")

    # Roster freeze (design D3/D4): from the freeze until voting closes, phone and registration-number
    # edits are requests a commissioner approves; only name typos stay direct (unvoted voters, max 2).
    st = await roster_status(request)
    if st["contact_change_required"]:
        touches_contact = bool(data.phone_ops) or (
            data.new_student_id is not None and normalize_student_id(data.new_student_id) != old_sid)
        if touches_contact:
            raise ApiError(409, "The roster is frozen: phone and registration-number changes must be submitted "
                                "as a contact-change request for a commissioner to approve.", "contact_change_required")
        if voter.get("has_voted"):
            raise ApiError(409, "This voter has already voted; their details can no longer be edited.", "already_voted")
        name_changes = await db.student_edit_audit.count_documents({
            "org_id": org_id, "student_key": str(voter["_id"]), "event": "student_name_changed",
            "at": {"$gte": st["freeze_at"] or datetime(1970, 1, 1)}})
        if name_changes >= 2:
            raise ApiError(409, "This voter has already had 2 name corrections since the freeze.", "name_edit_cap")

    res = await _apply_student_edit(org_id, voter, data.full_name, data.new_student_id, data.phone_ops)
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

    return {"status": "updated", "changes": [e["event"] for e in res["events"]],
            "student": _student_edit_view({**voter, "full_name": res["new_name"], "student_id": res["new_sid"],
                                           "phone_numbers": res["phones"]})}


@app.get("/admin/students/edit-history")
async def student_edit_history(request: Request, q: str = "", limit: int = 100,
                               admin: dict = Depends(require_role(*STUDENT_EDIT_ROLES))):
    """Read-only. Searching an OLD or NEW registration number (or a name) finds the student
    and every change ever made to that student, because each row carries the student's
    internal key and both numbers."""
    org_id = request.state.org_id
    limit = min(max(limit, 1), 500)
    q = q.strip()
    query: dict = {"org_id": org_id}
    if q:
        keys = set()
        exact = {normalize_student_id(q), q.lower()}
        rx = {"$regex": re.escape(q.lower())}
        async for r in db.student_edit_audit.find(
                {"org_id": org_id, "$or": [{"search_terms": {"$in": list(exact)}}, {"search_terms": rx}]},
                {"student_key": 1}):
            keys.add(r["student_key"])
        async for v in db.voters.find({"org_id": org_id, "$or": [
                {"student_id": normalize_student_id(q)},
                {"full_name": {"$regex": re.escape(q), "$options": "i"}}]}, {"_id": 1}).limit(50):
            keys.add(str(v["_id"]))
        if not keys:
            return {"entries": []}
        query["student_key"] = {"$in": list(keys)}
    entries = []
    async for r in db.student_edit_audit.find(query).sort("at", -1).limit(limit):
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
    async for entry in db.audit_log.find(query).sort("timestamp", -1).limit(limit):
        entry["_id"] = str(entry["_id"])
        logs.append(entry)
    return logs


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
    config = await db.settings.find_one(org_query(request, {"name": "election_config"})) or {}
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

    await db.settings.update_one(
        org_query(request, {"name": "election_phases"}),
        {"$set": org_stamp(request, {
            "name": "election_phases",
            "phases": stored,
            "round_id": data.round_id or DEFAULT_ROUND_ID,
            "timezone": tz_name,
            "updated_at": datetime.utcnow(),
        })},
        upsert=True,
    )
    await log_action("phases_scheduled", current_actor(request), {
        "round_id": data.round_id, "timezone": tz_name,
        "phases": {k: {"enforced": v["enforced"], "start_utc": v["start"].isoformat() if v["start"] else None,
                       "end_utc": v["end"].isoformat() if v["end"] else None} for k, v in stored.items()},
        **({"early_end": True, "reason": reason[:500]} if ends_voting_now else {}),
    }, org_id=request.state.org_id)

    # Design 5.3(2): recompute lock strength from the new window and log it whenever W changes.
    if "voting" in stored:
        params = await guess_params(request)
        prior = await db.settings.find_one(org_query(request, {"name": "otp_derived"})) or {}
        if int(prior.get("window_s", -1)) != int(params["window_s"]):
            await db.settings.update_one(
                org_query(request, {"name": "otp_derived"}),
                {"$set": org_stamp(request, {"name": "otp_derived", "window_s": int(params["window_s"])})}, upsert=True)
            await log_action("otp_lock_params_changed", current_actor(request), {
                "window_s": int(params["window_s"]), "guess_budget": round(params["budget"], 1),
                "refill_interval_s": int(params["interval"]), "window_is_default": params["window_is_default"]},
                org_id=request.state.org_id)
        # A new future voting window re-arms the roster freeze; a new round with a past start lifts it.
        new_start = stored["voting"].get("start")
        if new_start is not None and new_start.tzinfo is not None:      # pydantic hands us aware datetimes
            new_start = new_start.astimezone(timezone.utc).replace(tzinfo=None)
        prev_round = (await db.settings.find_one(org_query(request, {"name": "otp_derived"})) or {}).get("round_id")
        if new_start and new_start > datetime.utcnow():
            await _save_security(request, {"freeze_lifted_at": None})
        elif prev_round and prev_round != (data.round_id or DEFAULT_ROUND_ID):
            await _save_security(request, {"freeze_lifted_at": datetime.utcnow(), "epoch_at": datetime.utcnow()})
        await db.settings.update_one(org_query(request, {"name": "otp_derived"}),
                                     {"$set": {"round_id": data.round_id or DEFAULT_ROUND_ID}})
    return {"status": "saved", "round_id": data.round_id or DEFAULT_ROUND_ID}


@app.get("/admin/roadmap")
async def get_admin_roadmap(request: Request):
    """Read-only for any admin role (matches /admin/schedule's transparency
    rule); only superadmin can write via POST /admin/roadmap below."""
    doc = await db.settings.find_one(org_query(request, {"name": "election_roadmap"}))
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
    await db.settings.update_one(
        org_query(request, {"name": "election_roadmap"}),
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
    doc = await db.settings.find_one(org_query(request, {"name": "election_roadmap"}))
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
    async for g in db.exception_grants.find(org_query(request)).sort("granted_at", -1).limit(200):
        g["_id"] = str(g["_id"])
        grants.append(g)
    return grants


@app.post("/admin/exception-grants")
async def create_exception_grant(data: ExceptionGrantCreate, request: Request,
                                 admin: dict = Depends(require_chief_commissioner)):
    if data.phase not in PHASE_NAMES:
        raise HTTPException(400, f"phase must be one of: {', '.join(PHASE_NAMES)}.")
    if not data.reason.strip():
        raise HTTPException(400, "A written reason is required — this grant is the decision record.")
    if data.expires_at and data.expires_at <= datetime.utcnow():
        raise HTTPException(400, "Expiry must be in the future.")

    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
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
    result = await db.exception_grants.insert_one(doc)
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
    grant = await db.exception_grants.find_one(org_query(request, {"_id": oid}))
    if not grant:
        raise HTTPException(404, "Grant not found.")
    await db.exception_grants.update_one(
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
    total = await db.audit_log.count_documents(query)
    privileged = current_role(request) == "superadmin"
    logs = []
    async for entry in db.audit_log.find(query).sort("timestamp", -1).skip(skip).limit(limit):
        entry["_id"] = str(entry["_id"])
        if not privileged:
            details = entry.get("details") or {}
            if "email" in details:
                details["email"] = _mask_email(details["email"])
            if "ip" in details:
                details["ip"] = _mask_ip(details["ip"])
            if entry.get("action") == "admin_login_locked":
                entry["actor"] = _mask_email(entry.get("actor", ""))
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
    anchor_failures = await db.audit_log.count_documents(
        org_query(request, {"action": "audit_checkpoint_anchor_failed"})
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
        raise HTTPException(400, "bucket must be 'hour' or 'day'.")
    fmt = "%Y-%m-%dT%H:00" if bucket == "hour" else "%Y-%m-%d"
    series = []
    async for row in db.vote_events.aggregate([
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
    async for row in db.voters.aggregate([
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
    completed = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    vote_counts = await get_vote_counts(request)

    by_position: dict[str, int] = {}
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
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
    async for entry in db.audit_log.find(query).sort("timestamp", -1).limit(limit):
        entry["_id"] = str(entry["_id"])
        if not privileged:
            details = entry.get("details") or {}
            if "email" in details:
                details["email"] = _mask_email(details["email"])
            if "ip" in details:
                details["ip"] = _mask_ip(details["ip"])
            if entry.get("action") == "admin_login_locked":
                entry["actor"] = _mask_email(entry.get("actor", ""))
        events.append(entry)

    since = datetime.utcnow() - timedelta(hours=24)
    summary = []
    async for row in db.audit_log.aggregate([
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
    total = await db.voters.count_documents(org_query(request))
    voted = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    config = await db.settings.find_one(org_query(request, {"name": "election_config"})) or {}
    return {
        "total_registered": total,
        "voted": voted,
        "turnout_pct": round((voted / total) * 100, 1) if total else 0.0,
        "candidates": await db.candidates.count_documents(org_query(request)),
        "positions": await db.positions.count_documents(org_query(request)),
        "applications_pending": await db.applications.count_documents(org_query(request, {"status": "pending"})),
        "student_changes_pending": await db.student_changes.count_documents(org_query(request, {"status": "pending"})),
        "with_phone_on_file": await db.voters.count_documents(org_query(request, {"phone_numbers": {"$ne": []}})),
        "is_open": config.get("is_open", True),
        "is_certified": config.get("is_certified", False),
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
    config = await db.settings.find_one(org_query(request, {"name": "election_config"})) or {}
    branding = await db.settings.find_one(org_query(request, {"name": "branding"})) or {}

    commissioners = []
    async for c in db.voters.find(
        org_query(request, {"is_commissioner": True}),
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
    voter_turnout = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    vote_counts = await get_vote_counts(request)
    results = []
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
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
        async for c in db.contact_changes.find(org_query(request, {
            "status": {"$in": ["approved", "denied", "expired", "failed"]},
            "requested_at": {"$gte": _epoch(sec_r)}})).sort("requested_at", 1).limit(1000)
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
    voted = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    if voted < PUBLIC_ROLL_THRESHOLD:
        # Below the threshold the server returns nothing at all, so a small
        # turnout can't be de-anonymised by reading the network response.
        return {"threshold": PUBLIC_ROLL_THRESHOLD, "voted": voted, "unlocked": False, "roll": []}

    roll = []
    cursor = db.voters.find(
        org_query(request, {"has_voted": True}), {"_id": 0, "full_name": 1}
    ).limit(PUBLIC_ROLL_MAX)
    async for v in cursor:
        roll.append({"full_name": _mask_name(v.get("full_name", ""))})
    return {"threshold": PUBLIC_ROLL_THRESHOLD, "voted": voted, "unlocked": True, "roll": roll}


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
    await db.settings.update_one(
        org_query(request, {"name": "security_settings"}),
        {"$set": org_stamp(request, {"name": "security_settings", **updates, "updated_at": datetime.utcnow()})},
        upsert=True)


async def _is_chief(request: Request) -> bool:
    try:
        await require_chief_commissioner(request)
        return True
    except HTTPException:
        return False


async def _branding(request: Request) -> dict:
    return await db.settings.find_one(org_query(request, {"name": "branding"})) or {}


# ── Contact-change requests ─────────────────────────────────────────────────

async def _expire_contact_changes(request: Request):
    now = datetime.utcnow()
    async for c in db.contact_changes.find(org_query(request, {"status": "pending", "expires_at": {"$lt": now}})):
        r = await db.contact_changes.update_one({"_id": c["_id"], "status": "pending"},
                                                {"$set": {"status": "expired", "decided_at": now}})
        if r.modified_count:
            await append_ledger(request.state.org_id, "contact_change_expired", c["student_id"], "system", "system",
                                {"change_id": str(c["_id"]), "type": c["change"]["type"]})


async def _validate_contact_change(data: ContactChangeRequest, voter: dict, org_id) -> dict:
    t = data.change_type
    if t not in CONTACT_CHANGE_TYPES:
        raise HTTPException(400, f"change_type must be one of: {', '.join(CONTACT_CHANGE_TYPES)}.")
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
            raise HTTPException(400, "Registration number must be 1-64 characters with no spaces.")
        if new_sid == voter["student_id"]:
            raise HTTPException(400, "That is already this student's registration number.")
        if any(voter.get(f) for f in STUDENT_ROLE_FLAGS):
            raise HTTPException(409, "This student holds an admin/commission role; the registration number cannot be changed.")
        if await db.voters.find_one(_oq(org_id, {"student_id": new_sid})):
            raise HTTPException(409, "Another student in this organization already has that registration number.")
        ch["new_value"], ch["expected_old"] = new_sid, voter["student_id"]
    return ch


@app.post("/it-admin/contact-changes/request")
async def request_contact_change(data: ContactChangeRequest, request: Request,
                                 admin: dict = Depends(require_role("it_admin", "superadmin"))):
    org_id = request.state.org_id
    sec = await get_security_settings(request)
    st = await roster_status(request, sec)
    if st["phase"] == "pre_freeze":
        raise HTTPException(409, "The roster is not frozen yet — edit the student directly (audit-logged).")
    if st["phase"] == "closed":
        raise HTTPException(409, "Voting has closed, so no code can be issued. Edit the student directly (audit-only).")
    if not st["contact_change_required"]:
        raise HTTPException(409, "Contact-change approval is switched off for this election — edit the student directly.")

    if data.evidence_type not in CONTACT_EVIDENCE_TYPES:
        raise HTTPException(400, f"evidence_type must be one of: {', '.join(CONTACT_EVIDENCE_TYPES)}.")
    note = data.evidence_note.strip()
    if len(note) < (20 if data.evidence_type == "other_documented" else 3):
        raise HTTPException(400, "Describe the evidence you checked (at least 20 characters for 'other_documented').")

    voter = await db.voters.find_one(_oq(org_id, get_forgiving_filter(data.student_id)))
    if not voter:
        raise HTTPException(404, "Student not found in this organization.")
    if voter.get("has_voted"):
        raise HTTPException(409, "This student has already voted; their contact details can no longer be changed.")
    actor, role = current_actor(request), current_role(request)
    if normalize_student_id(actor) == voter["student_id"]:
        raise HTTPException(403, "You cannot request a change to your own record.")

    await _expire_contact_changes(request)
    approved = await db.contact_changes.count_documents(_oq(org_id, {
        "student_id": voter["student_id"], "status": "approved", "requested_at": {"$gte": _epoch(sec)}}))
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
        res = await db.contact_changes.insert_one(doc)
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
    c = await db.contact_changes.find_one(org_query(request, {"_id": oid}))
    if not c:
        raise HTTPException(404, "Request not found.")
    actor = current_actor(request)
    if current_role(request) != "superadmin" and normalize_student_id(c["requested_by"]) != normalize_student_id(actor):
        raise HTTPException(403, "You can only cancel your own requests.")
    r = await db.contact_changes.update_one(
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
        on_voters = await db.voters.count_documents(org_query(request, {
            "phone_numbers": nv, "student_id": {"$ne": c["student_id"]}}))
        in_pending = await db.contact_changes.count_documents(org_query(request, {
            "status": "pending", "change.new_value": nv, "_id": {"$ne": c["_id"]}}))
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
    live_otp = bool(await db.otps.find_one(org_query(request, {"student_id": c["student_id"]})))
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
    rows = [c async for c in db.contact_changes.find(
        org_query(request, {"requested_at": {"$gte": since}, "status": {"$in": ["approved", "pending"]}}),
        {"status": 1, "decided_by": 1, "change": 1, "notice_status": 1})]
    approved = [c for c in rows if c["status"] == "approved"]
    electorate = await db.voters.count_documents(org_query(request))
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
    resets = [{"actor": a["actor"], "at": a["timestamp"]} async for a in db.audit_log.find(org_query(request, {
        "action": "otp_reset_admin_alert", "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=24)}}))
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
    items = [await _cc_view(request, c, role) async for c in db.contact_changes.find(q).sort("requested_at", -1).limit(300)]
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
    async for r in db.student_edit_audit.find(org_query(request, {
            "at": {"$lte": until},
            "event": {"$in": ["phone_added", "phone_removed", "phone_changed",
                              "student_registration_number_changed", "student_name_changed"]},
    })).sort("at", -1).limit(1000):
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

    org_id = request.state.org_id
    oid = parse_oid(entry_id, "entry id")
    rec = await db.student_edit_audit.find_one({"org_id": org_id, "_id": oid})
    if not rec:
        raise HTTPException(404, "Audit entry not found.")
    if rec.get("event") not in ("phone_added", "phone_removed", "phone_changed",
                                "student_registration_number_changed", "student_name_changed"):
        raise HTTPException(400, "This kind of entry can't be undone here.")
    if rec.get("undone_at"):
        raise HTTPException(409, "This change was already undone.")
    if rec.get("undoes"):
        raise HTTPException(400, "This entry is itself an undo and can't be undone again here.")

    voter = await db.voters.find_one({"org_id": org_id, "_id": ObjectId(rec["student_key"])})
    if not voter:
        raise HTTPException(404, "The student this change applied to no longer exists.")

    field = rec["field"]
    old_value, new_value = rec.get("old_value"), rec.get("new_value")
    actor, role = current_actor(request), current_role(request)
    new_voter_sid = voter["student_id"]

    if field == "student_id":
        if voter["student_id"] != new_value:
            raise HTTPException(409, "The registration number has changed again since this edit; review manually.")
        if await db.voters.find_one({"org_id": org_id, "student_id": old_value, "_id": {"$ne": voter["_id"]}}):
            raise HTTPException(409, "Another student now holds that registration number; can't restore it automatically.")
        await db.voters.update_one({"_id": voter["_id"]}, {"$set": {"student_id": old_value}})
        for coll in (db.applications, db.exception_grants, db.contact_changes):
            await coll.update_many({"org_id": org_id, "student_id": new_value}, {"$set": {"student_id": old_value}})
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
        await db.voters.update_one({"_id": voter["_id"]}, {"$set": {"phone_numbers": phones}})
    elif field == "full_name":
        if voter.get("full_name", "") != new_value:
            raise HTTPException(409, "The name has changed again since this edit; review manually.")
        await db.voters.update_one({"_id": voter["_id"]}, {"$set": {"full_name": old_value}})
    else:
        raise HTTPException(400, "This kind of entry can't be undone here.")

    now = datetime.utcnow()
    await db.student_edit_audit.update_one({"_id": rec["_id"]}, {"$set": {
        "undone_at": now, "undone_by": actor, "undo_reason": reason}})
    await db.student_edit_audit.insert_one({
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
            "phone_add": "A phone number was added to", "registration_number_change": "The registration number on"}[ch["type"]]
    tail = " was changed" if ch["type"] in ("phone_change", "registration_number_change") else (
        " was removed" if ch["type"] == "phone_remove" else "")
    reach = b.get("support_phone") or next(
        (c.get("link") for g in (b.get("support_contacts") or []) for c in (g.get("contacts") or []) if c.get("link")), "")
    contact = f" If this was not you, contact {reach}." if reach else " If this was not you, contact the electoral commission."
    text = f"{what} the {org} voting register{tail} at {when}.{contact}" if ch["type"] != "phone_add" else \
           f"{what} the {org} voting register at {when}.{contact}"
    return "sent" if await send_sms(old, text, request, kind="notice") else "failed"


async def _decide_contact_change(change_id: str, data: ContactChangeDecision, request: Request, breakglass: bool):
    if data.decision not in ("approve", "deny"):
        raise HTTPException(400, "decision must be 'approve' or 'deny'.")
    note = data.note.strip()
    if data.decision == "deny" and len(note) < 3:
        raise HTTPException(400, "A denial needs a note.")
    if breakglass and len(note) < 10:
        raise HTTPException(400, "Break-glass approval needs a written justification (10+ characters).")
    org_id, oid = request.state.org_id, parse_oid(change_id, "change id")
    sec = await get_security_settings(request)
    await _expire_contact_changes(request)
    c = await db.contact_changes.find_one(org_query(request, {"_id": oid}))
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
    if role == "commission" and not await db.voters.find_one(org_query(request, {
            **get_forgiving_filter(actor), "is_commissioner": True})):
        raise HTTPException(403, "Not a registered commissioner.")

    now = datetime.utcnow()
    if data.decision == "approve":
        warnings = await _cc_warnings(request, c)
        if warnings and not data.acknowledge_warnings:
            raise ApiError(409, "Please review the warnings and tick 'I have checked' to approve.",
                           "warnings_unacknowledged", warnings=warnings)
        cap = (sec["cap_overrides"].get("approver_daily") or {}).get(_capkey(actor), sec["approver_daily_cap"])
        done_today = await db.contact_changes.count_documents(org_query(request, {
            "decided_by": actor, "status": "approved", "decided_at": {"$gte": now - timedelta(days=1)}}))
        if done_today >= cap:
            raise ApiError(429, f"Daily approval limit reached ({cap}). The chief commissioner can raise it.", "approver_cap")
        electorate = await db.voters.count_documents(org_query(request))
        total_approved = await db.contact_changes.count_documents(org_query(request, {
            "status": "approved", "requested_at": {"$gte": _epoch(sec)}}))
        if electorate and 100.0 * total_approved / electorate >= sec["quota_hard_cap_pct"] and not await _is_chief(request):
            raise ApiError(409, "The election-wide contact-change limit has been reached. "
                                "Only the chief commissioner can approve further changes.", "quota_hard_stop")

    claim = await db.contact_changes.update_one(
        org_query(request, {"_id": oid, "status": "pending", "expires_at": {"$gt": now}}),
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
        await db.contact_changes.update_one({"_id": oid}, {"$set": {"status": "failed", "decision_note": f"{note} | FAILED: {msg}"}})
        await append_ledger(org_id, "contact_change_failed", c["student_id"], actor, role, {"change_id": change_id, "why": msg})

    voter = await db.voters.find_one(_oq(org_id, {"_id": ObjectId(c["student_key"])}))
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
    await db.contact_changes.update_one({"_id": oid}, {"$set": {"notice_status": notice}})
    await append_ledger(org_id, "contact_change_approved", res["new_sid"], actor, role, {
        "change_id": change_id, "type": ch["type"], "requested_by": c["requested_by"], "evidence": c["evidence_type"],
        "notice": notice, "breakglass": breakglass})
    if notice == "failed":
        await append_ledger(org_id, "contact_change_notice_failed", res["new_sid"], "system", "system", {"change_id": change_id})
    await log_action("contact_change_approved" if not breakglass else "contact_change_breakglass", actor, {
        "student_id": _mask_student_id(res["new_sid"]), "type": ch["type"], "requested_by": c["requested_by"],
        "notice": notice, "breakglass": breakglass}, org_id=org_id)

    electorate = await db.voters.count_documents(org_query(request))
    total_approved = await db.contact_changes.count_documents(org_query(request, {
        "status": "approved", "requested_at": {"$gte": _epoch(sec)}}))
    if electorate and 100.0 * total_approved / electorate >= sec["quota_alert_pct"] and not await db.roster_ledger.find_one(
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
        raise HTTPException(400, "kind must be approver_daily or reset_hourly.")
    if not 1 <= data.cap <= 10000 or len(data.reason.strip()) < 3:
        raise HTTPException(400, "cap must be 1-10000 and a reason is required.")
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
    cur = db.voters.find(org_query(request, {"$or": [{"student_id": rx}, {"full_name": rx}]}),
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
    cur = db.voters.find(org_query(request, {
        "$and": [
            {"$or": [{"student_id": rx}, {"full_name": rx}]},
            {"$or": [{f: True} for f in STUDENT_ROLE_FLAGS]},
        ]
    }), {"_id": 0, "student_id": 1, "full_name": 1, **{f: 1 for f in role_labels}}).limit(10)
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
        raise HTTPException(400, f"reason must be one of: {', '.join(RESET_REASONS)}.")
    if len(data.note.strip()) < 3:
        raise HTTPException(400, "A short note is required.")
    org_id, sec = request.state.org_id, await get_security_settings(request)
    voter = await db.voters.find_one(org_query(request, get_forgiving_filter(student_id)))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    sid, actor, role, now = voter["student_id"], current_actor(request), current_role(request), datetime.utcnow()
    base = {"org_id": org_id, "event": "otp_limits_reset", "ts": {"$gte": _epoch(sec)}}

    if await db.roster_ledger.count_documents({**base, "ref_id": sid, "ts": {"$gte": max(_epoch(sec), now - timedelta(days=1))}}) \
            >= sec["reset_per_voter_daily"]:
        raise ApiError(429, "This voter has reached today's reset limit. Ask the commission to review.", "reset_voter_daily_cap")
    if await db.roster_ledger.count_documents({**base, "ref_id": sid}) >= sec["reset_per_voter_election"]:
        raise ApiError(429, "This voter has reached the reset limit for this election.", "reset_voter_election_cap")

    hourly = await db.roster_ledger.count_documents({**base, "actor": actor, "ts": {"$gte": now - timedelta(hours=1)}})
    hard = (sec["cap_overrides"].get("reset_hourly") or {}).get(_capkey(actor), sec["reset_admin_hourly_hard_cap"])
    if hourly >= hard:
        raise ApiError(429, f"Hourly reset limit reached ({hard}). The chief commissioner can lift it.", "reset_admin_hard_cap")

    await clear_otp_limit_state(org_id, [sid])
    await append_ledger(org_id, "otp_limits_reset", sid, actor, role, {"reason": data.reason, "note": data.note.strip()})
    await log_action("otp_limits_reset", actor, {"student_id": _mask_student_id(sid), "reason": data.reason, "role": role}, org_id=org_id)
    if hourly + 1 > sec["reset_admin_hourly_alert"] and not await db.audit_log.find_one(org_query(request, {
            "action": "otp_reset_admin_alert", "actor": actor, "timestamp": {"$gte": now - timedelta(hours=1)}})):
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
    voters = await db.voters.count_documents(org_query(request))
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
            raise HTTPException(400, "sms_mode must be normal or conservation.")
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
    voters = await db.voters.count_documents(org_query(request))
    return {
        "settings": {k: v for k, v in sec.items() if k not in ("cap_overrides", "epoch_at", "freeze_lifted_at")},
        "roster": await roster_status(request, sec),
        "derived": {
            "voting_window_seconds": params["window_s"], "window_scheduled": not params["window_is_default"],
            "guess_budget": round(params["budget"], 1), "refill_interval_seconds": round(params["interval"]),
            "free_guesses": ol.FREE_GUESSES, "suggested_sms_budget": math.ceil(voters * SMS_BUDGET_DEFAULT_MULTIPLIER),
            "turnstile_secret_configured": bool(TURNSTILE_SECRET),
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
                raise HTTPException(400, f"{f} must be between {lo} and {hi}.")
            updates[f] = v
    if data.turnstile_mode is not None:
        if data.turnstile_mode not in ("off", "adaptive", "on"):
            raise HTTPException(400, "turnstile_mode must be off, adaptive or on.")
        updates["turnstile_mode"] = data.turnstile_mode
    if data.public_results_mode is not None:
        if data.public_results_mode not in ("live", "closed", "certified"):
            raise HTTPException(400, "public_results_mode must be live, closed or certified.")
        updates["public_results_mode"] = data.public_results_mode
    if data.approval_policy is not None:
        if data.approval_policy not in VALID_APPROVAL_POLICIES:
            raise HTTPException(400, f"approval_policy must be one of: {', '.join(sorted(VALID_APPROVAL_POLICIES))}.")
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
    if "approval_policy" in updates:
        await _resweep_pending_after_policy_change(request.state.org_id)
        await log_action("approval_policy_resweep", actor, {
            "reason": reason, "new_policy": updates["approval_policy"],
        }, org_id=request.state.org_id)
    return await superadmin_get_security_settings(request)
