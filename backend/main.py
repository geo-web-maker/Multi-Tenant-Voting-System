from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import secrets
import motor.motor_asyncio
from pymongo.errors import DuplicateKeyError
from pymongo import UpdateOne
import os
import csv
import io
import re
import httpx
import logging
from datetime import datetime, timedelta
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
import boto3
from fastapi.concurrency import run_in_threadpool
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import backup
from backup_routes import build_router as build_backup_router

from auth import (
    create_access_token,
    decode_access_token,
    get_bearer_token,
    require_admin,
    require_role,
    set_revocation_check,
    create_voter_token,
    verify_voter_token,
    VOTER_TOKEN_HEADER,
    ADMIN_ROLES,
    JWT_EXPIRE_MINUTES,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BallotBoxAPI")

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
    yield
    client.close()

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

@app.middleware("http")
async def org_context_middleware(request: Request, call_next):
    org_slug = request.headers.get("X-Org-Slug")
    request.state.org_id = None
    request.state.org_slug = None
    if org_slug:
        org_doc = await db.organizations.find_one({"slug": org_slug})
        if org_doc:
            request.state.org_id = str(org_doc["_id"])
            request.state.org_slug = org_slug
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
# public on purpose — they are outside this admin session layer. Casting a
# ballot (/vote, /vote-bulk) is instead protected by the voter's own token,
# issued by /verify-otp and checked in the handlers (see auth.py).

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
    if method == "GET" and path in {"/candidates", "/positions", "/superadmin/branding"}:
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
    allow_headers=["Authorization", "Content-Type", "X-Org-Slug", VOTER_TOKEN_HEADER],
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
TRUSTED_PROXY_HOSTS = os.getenv("TRUSTED_PROXY_HOSTS", "*")
app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts=[h.strip() for h in TRUSTED_PROXY_HOSTS.split(",")] if TRUSTED_PROXY_HOSTS != "*" else "*",
)


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
    commissioner_name:   str = ""
    support_phone:       str = ""
    support_pdf_url:     str = ""
    cc_list:             list[str] = []

class PositionCreate(BaseModel):
    title: str
    description: str = ""
    order: int = 0

# --- Applications ---
class ApplicationSubmit(BaseModel):
    student_id:        str
    full_name:         str
    position_id:       str
    manifesto:         str = ""
    image_url:         str = ""
    payment_method:    str = ""     
    payment_proof_url: str = ""      
    
class CommissionerVote(BaseModel):
    commissioner_id: str   # the commissioner's student_id
    vote: str              # "approve" or "deny"
    reason: str = ""

class FinanceClear(BaseModel):
    commissioner_id: str   # must belong to the voter flagged is_finance_commissioner
    

class ITAdminStudentAdd(BaseModel):
    student_id:        str
    full_name:         str
    phone:             str
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


async def send_sms_via_egosms(to_number: str, message_text: str) -> bool:
    """Primary OTP provider. See send_sms()."""
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
            return "OK" in resp_text.upper()
    except Exception as e:
        logger.error(f"EgoSMS Connection Error: {e}")
        return False


async def send_sms(to_number: str, message_text: str, request: Request | None = None) -> bool:
    """Single entrypoint every route should call to send an SMS. Tries
    EgoSMS (primary) first; if that fails for any reason, automatically
    falls back to MamboSMS (secondary) before giving up. Logs which provider
    actually delivered, so a pattern of fallback (or total failure) is
    visible in the Activity Log rather than silently invisible.
    """
    if DEBUG_MODE:
        # Local/load-testing only: never hit either real API. Log the
        # message (which contains the OTP) so Locust or a manual tester can
        # read it back, and report success so the normal OTP flow proceeds.
        logger.info(f"[DEBUG_MODE] SMS to {to_number}: {message_text}")
        return True

    if await send_sms_via_egosms(to_number, message_text):
        return True

    logger.warning(f"EgoSMS failed for {to_number}, falling back to MamboSMS.")
    if request is not None:
        await log_action("sms_provider_fallback", "system", {
            "primary": "egosms", "fallback": "mambosms",
        }, org_id=request.state.org_id)

    return await send_sms_via_mambosms(to_number, message_text)

# =============================================================================
# PASSWORD HELPERS
# =============================================================================

def generate_temp_password() -> str:
    """Simple 6-digit numeric code — easy to read and type from an SMS."""
    return ''.join(secrets.choice(string.digits) for _ in range(6))

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
    return await send_sms(phone_list[0], message)

# --- Application consensus helpers ---

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

async def _resolve_application(app_id: str, app_doc: dict, org_id: str = None):
    """
    Called after every commissioner vote.
    Resolves as soon as either side reaches a majority of the TOTAL commissioner
    count (floor(total/2) + 1) — not full consensus, and not just majority of
    votes cast. Works the same way whether the EC has 5 commissioners or 50.
    """
    total = await get_commissioner_count(org_id)
    if total == 0:
        return

    required = (total // 2) + 1  # majority of total commissioner count

    votes = app_doc.get("votes", {})
    approve_count = sum(1 for v in votes.values() if v == "approve")
    deny_count    = sum(1 for v in votes.values() if v == "deny")

    if approve_count >= required:
        # Majority reached — create candidate and mark approved.
        #
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
            {"$set": {"status": "approved"}}
        )
        if result.matched_count == 0:
            return
        await _create_candidate_from_application(app_doc, org_id)
        await log_action("application_approved", "commission", {
            "app_id": app_id, "approve_count": approve_count, "total_commissioners": total
        }, org_id=org_id)
        logger.info(f"Application {app_id} approved by commission majority ({approve_count}/{total}).")
    elif deny_count >= required:
        # Majority reached against — application denied. Same atomic guard:
        # only the winning caller logs/proceeds.
        result = await db.applications.update_one(
            {"_id": ObjectId(app_id), "status": {"$nin": ["approved", "denied", "removed"]}},
            {"$set": {"status": "denied"}}
        )
        if result.matched_count == 0:
            return
        await log_action("application_denied", "commission", {
            "app_id": app_id, "deny_count": deny_count, "total_commissioners": total
        }, org_id=org_id)
        logger.info(f"Application {app_id} denied by commission majority ({deny_count}/{total}).")

async def _resolve_removal(app_id: str, app_doc: dict, org_id: str = None):
    """
    Called after every removal vote.
    Removes the candidate once a majority of the TOTAL commissioner count votes
    to remove — same threshold rule as application approval.
    """
    total = await get_commissioner_count(org_id)
    if total == 0:
        return

    required = (total // 2) + 1  # majority of total commissioner count

    removal_votes = app_doc.get("removal_votes", {})
    approve_removals = sum(1 for v in removal_votes.values() if v == "approve")

    if approve_removals >= required:
        # Same atomic-guard pattern as _resolve_application: only the caller
        # whose update actually flips status to "removed" proceeds to delete
        # the candidate and log it, so two commissioners racing to cast the
        # deciding removal vote can't both fire the delete/log side effects.
        result = await db.applications.update_one(
            {"_id": ObjectId(app_id), "status": "approved"},
            {"$set": {"status": "removed", "removal_votes": {}}}
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
            "approve_removals": approve_removals, "total_commissioners": total,
        }, org_id=org_id)
        logger.info(f"Candidate from application {app_id} removed by commission majority ({approve_removals}/{total}).")

#--IT Administration Helpers---

async def _execute_student_change(change_doc: dict, org_id: str = None):
    if change_doc["change_type"] == "add":
        phone = change_doc.get("phone", "")
        clean = re.sub(r'\D', '', phone)
        if clean.startswith('0'):
            clean = '256' + clean[1:]
        elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
            clean = '256' + clean
        q = {"student_id": normalize_student_id(change_doc["student_id"])}
        if org_id:
            q["org_id"] = org_id
        await db.voters.update_one(
            q,
            {"$set": {
                "full_name":       change_doc["full_name"],
                "phone_numbers":   [clean],
                "is_commissioner": False,
                "is_it_admin":     False,
                "has_voted":       False,
                "last_status":     "idle",
                "added_by_it":     True,
                "added_by":        change_doc.get("requested_by", ""),
                "org_id":          org_id,
                "student_id":      normalize_student_id(change_doc["student_id"])
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


async def require_chief_commissioner(request: Request) -> dict:
    """Superadmin, or the single commissioner flagged is_chief_commissioner."""
    admin = getattr(request.state, "admin", None) or {}
    if admin.get("role") == "superadmin":
        return admin
    if admin.get("role") != "commission":
        raise HTTPException(403, "Chief Commissioner access required.")
    voter = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(admin.get("sub", "")),
        "is_commissioner": True,
        "is_chief_commissioner": True,
    }))
    if not voter:
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

PHASE_NAMES = ("applications", "campaign", "voting", "results")
DEFAULT_ROUND_ID = "round-1"


class PhaseWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    enforced: bool = True


class PhaseScheduleUpdate(BaseModel):
    phases: dict[str, PhaseWindow]
    round_id: str = DEFAULT_ROUND_ID


class ExceptionGrantCreate(BaseModel):
    student_id: str
    phase: str
    reason: str
    expires_at: datetime | None = None


async def get_phase_schedule(request: Request) -> dict:
    doc = await db.settings.find_one(org_query(request, {"name": "election_phases"}))
    phases = (doc or {}).get("phases", {})
    return {
        "round_id": (doc or {}).get("round_id", DEFAULT_ROUND_ID),
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
    raise HTTPException(
        status_code=403,
        detail=f"The {label} period is closed. Contact the Electoral Commission if you believe this is an error.",
    )


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


def _login_attempt_key(email: str, org_id: str | None) -> str:
    return f"{org_id or 'default'}:{email}"


async def enforce_login_rate_limit(email: str, org_id: str | None):
    key = _login_attempt_key(email, org_id)
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


async def record_failed_login(email: str, org_id: str | None):
    key = _login_attempt_key(email, org_id)
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
        await db.login_attempts.update_one(
            {"key": key}, {"$set": {"locked_until": datetime.utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)}}
        )
        await log_action("admin_login_locked", email, {"attempts": attempts}, org_id=org_id)


async def clear_login_attempts(email: str, org_id: str | None):
    key = _login_attempt_key(email, org_id)
    await db.login_attempts.delete_one({"key": key})

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
    except Exception:
        raise HTTPException(status_code=500, detail="Database connection failed")

@app.get("/election-status")
async def get_status(request: Request):
    status_doc = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    schedule = await get_phase_schedule(request)
    voting_phase_open = _phase_is_open(schedule["phases"]["voting"], datetime.utcnow())

    if not status_doc:
        return {"is_open": True, "is_certified": False, "start": None, "end": None, "voting_phase_open": voting_phase_open}
    return {
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
    now = datetime.utcnow()
    status_doc = await db.settings.find_one(org_query(request, {"name": "election_config"}))

    if status_doc and not status_doc.get("is_open", True):
        raise HTTPException(status_code=403, detail="Election is closed.")

    # Timing is governed entirely by the "applications" phase schedule (see
    # PHASE_NAMES / assert_phase_open) — the standalone start_time/end_time
    # window on election_config was a second, disconnected timer that only
    # this one route ever checked. It's retired: this is now the single
    # place voting-window timing is configured (Timeline tab), matching what
    # /vote and /vote-bulk already enforce for the "voting" phase itself.
    await assert_phase_open(request, "voting", data.student_id)

    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        raise HTTPException(status_code=404, detail="Student ID not found")

    # otp_count tracks how many OTPs have already been SENT to this voter.
    # We allow 3 total requests, so we only block once a 4th would be sent
    # (i.e. once 3 have already gone out).
    otp_count = student.get("otp_count", 0)
    if otp_count >= 3:
        raise HTTPException(
            status_code=403,
            detail="Too many attempts. Please check the official register for your details."
        )

    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Already voted")

    if not names_match(student.get("full_name", ""), data.full_name):
        logger.warning(f"Name Match Fail: Reg({student.get('full_name','')}) vs Input({data.full_name})")
        raise HTTPException(status_code=400, detail="Name mismatch. Please provide your full registered names.")

    phone_list = student.get("phone_numbers", [])
    if not phone_list:
        raise HTTPException(status_code=400, detail="No phone found.")

    if len(phone_list) > 1 and data.phone_index is None:
        return {"status": "needs_selection", "masked_numbers": [f"{p[:6]}****{p[-2:]}" for p in phone_list]}

    idx       = data.phone_index if data.phone_index is not None else 0
    raw_phone = phone_list[idx]
    otp       = str(secrets.randbelow(900000) + 100000)

    first_name = student.get("full_name", "Voter").split()[0].capitalize()
    branding_doc = await db.settings.find_one(org_query(request, {"name": "branding"}))
    sms_org_name = (branding_doc or {}).get("org_name", "Election")
    
    message = (
        f"Hello {first_name}, your {sms_org_name} voting code is {otp}. "
        f"Your vote is secret. Do not share this code with anyone. Your voice, your power!"
    )

    if await send_sms(raw_phone, message, request):
        await db.voters.update_one(
            org_query(request, {"student_id": student["student_id"]}),
            {"$set": {"last_status": "otp_sent"}, "$inc": {"otp_count": 1}}
        )
        await db.otps.update_one(
            org_query(request, {"student_id": student["student_id"]}),
            {"$set": org_stamp(request, {"code": otp, "created_at": now})},
            upsert=True
        )
        return {"status": "success", "phone": f"{raw_phone[:6]}****{raw_phone[-2:]}"}

    raise HTTPException(status_code=500, detail="SMS Delivery Failed")


OTP_EXPIRY_MINUTES = 10


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


@app.post("/verify-otp")
async def verify_otp(data: OTPCheck, request: Request):
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
            # Issue the voter's session token. Its jti is stored on the voter
            # record so /vote can require *this* login's token — a newer OTP
            # login replaces it and any earlier token stops working.
            voter_token, voter_jti = create_voter_token(
                student_id=normalize_student_id(data.student_id),
                org_id=request.state.org_id,
            )
            await db.voters.update_one(
                search,
                {"$set": {"last_status": "authenticated", "otp_count": 0, "voter_session_jti": voter_jti}},
            )
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


@app.post("/vote")
async def cast_vote(data: VoteRequest, request: Request):
    try:
        candidate_oid = ObjectId(data.candidate_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid candidate.")

    # Must hold the token /verify-otp issued to THIS voter (see auth.py) —
    # knowing a student_id is no longer enough to cast that voter's ballot.
    voter_claims = verify_voter_token(request, normalize_student_id(data.student_id), request.state.org_id)

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
        if student.get("voter_session_jti") != voter_claims["jti"]:
            # Token is genuine but from an older login — a newer OTP
            # verification has replaced it.
            raise HTTPException(status_code=401, detail="Your voting session has expired. Please verify your identity again.")

        candidate_still_exists = await db.candidates.count_documents(
            org_query(request, {"_id": candidate_oid}), session=session
        )
        if not candidate_still_exists:
            raise HTTPException(status_code=404, detail="Candidate not found.")

        await db.voters.update_one(
            {"_id": student["_id"]},
            {"$set": {"has_voted": True, "last_status": "completed"}},
            session=session
        )
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

    async with await client.start_session() as session:
        await session.with_transaction(_do_vote)

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

    # Must hold the token /verify-otp issued to THIS voter (see auth.py) —
    # knowing a student_id is no longer enough to cast that voter's ballot.
    voter_claims = verify_voter_token(request, normalize_student_id(data.student_id), request.state.org_id)

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
        if student.get("voter_session_jti") != voter_claims["jti"]:
            # Token is genuine but from an older login — a newer OTP
            # verification has replaced it.
            raise HTTPException(status_code=401, detail="Your voting session has expired. Please verify your identity again.")

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

        await db.voters.update_one(
            {"_id": student["_id"]},
            {"$set": {"has_voted": True, "last_status": "completed"}},
            session=session
        )
        # Same append-only pattern as /vote, batched as one insert_many so a
        # multi-position ballot is still a single round trip inside the
        # transaction (still all-or-nothing with the has_voted update above).
        cast_at = datetime.utcnow()
        await db.vote_events.insert_many(
            [org_stamp(request, {"candidate_id": c_oid, "cast_at": cast_at})
             for c_oid in candidate_oids],
            session=session
        )

    async with await client.start_session() as session:
        await session.with_transaction(_do_bulk_vote)

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
    ip = request.client.host if request.client else "unknown"
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

    await enforce_login_rate_limit(email_key, org_id)

    try:
        result = await _verify_admin_credentials(data, request)
    except HTTPException as exc:
        if exc.status_code in (401, 404):
            await record_failed_login(email_key, org_id)
        raise
    else:
        await clear_login_attempts(email_key, org_id)
        return result


async def _verify_admin_credentials(data: AdminLoginCheck, request: Request):
    # ── Superadmin ── (env var based, no hashing needed — this is you)
    # compare_digest instead of == so a wrong password can't be narrowed down
    # character-by-character from response timing.
    if (secrets.compare_digest(data.email, SUPER_ADMIN_ID)
            and secrets.compare_digest(data.password, SUPER_ADMIN_PASSWORD)):
        if SUPERADMIN_TOTP_SECRET:
            if not data.totp_code:
                # Distinct status code from "wrong code" on purpose: this is
                # the signal the frontend uses to reveal the TOTP field only
                # once email+password have actually matched superadmin —
                # never shown for a wrong password, or for any other role.
                raise HTTPException(status_code=428, detail="totp_required")
            if not pyotp.TOTP(SUPERADMIN_TOTP_SECRET).verify(data.totp_code, valid_window=1):
                raise HTTPException(status_code=401, detail="Invalid authenticator code.")
        token = create_access_token(subject="superadmin", role="superadmin", org_id=request.state.org_id)
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
        await log_action("it_admin_login", it_admin["student_id"], {"email": data.email}, org_id=request.state.org_id)
        token = create_access_token(
            subject=it_admin["student_id"], role="it_admin",
            org_id=request.state.org_id, full_name=it_admin.get("full_name", "")
        )
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
        await log_action("financial_controller_login", financial_controller["student_id"], {"email": data.email}, org_id=request.state.org_id)
        token = create_access_token(
            subject=financial_controller["student_id"], role="financial_controller",
            org_id=request.state.org_id, full_name=financial_controller.get("full_name", "")
        )
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
        await log_action("overseer_login", overseer["student_id"], {"email": data.email}, org_id=request.state.org_id)
        token = create_access_token(
            subject=overseer["student_id"], role="overseer",
            org_id=request.state.org_id, full_name=overseer.get("full_name", "")
        )
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

    await log_action("commissioner_login", commissioner["student_id"], {"email": data.email}, org_id=request.state.org_id)
    token = create_access_token(
        subject=commissioner["student_id"], role="commission",
        org_id=request.state.org_id, full_name=commissioner.get("full_name", "")
    )
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
async def toggle_election(request: Request, admin: dict = Depends(require_role("superadmin"))):
    current    = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    new_status = not (current.get("is_open", True) if current else True)
    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$set": org_stamp(request, {"is_open": new_status, "name": "election_config"})},
        upsert=True
    )
    # Was hardcoded actor="superadmin" — this route sits under /admin/*, so
    # ANY admin role could trigger it and the log would still name superadmin.
    await log_action("election_toggled", current_actor(request), {
        "is_open": new_status, "role": current_role(request)
    }, org_id=request.state.org_id)
    logger.info(f" Election toggled to: {'OPEN' if new_status else 'CLOSED'}")
    return {"is_open": new_status}


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


@app.get("/admin/sms-balance")
async def get_sms_balance(admin: dict = Depends(require_role("superadmin"))):
    """Live MamboSMS balance — restricted to superadmin since it calls out
    to a billable third-party account. EgoSMS has no equivalent balance API
    exposed in its docs, so this only ever reflects the fallback provider;
    the primary's (EgoSMS) balance needs checking on EgoSMS's own portal.
    """
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
    success = await send_sms(data.phone, "SMS Connection Verified for BallotBox!", request)
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
        name            = (row.get('full_name')  or row.get('full-name')  or '').strip()
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
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    await log_action("admin_image_uploaded", current_actor(request), {
        "url": result["secure_url"], "bytes": len(content)
    }, org_id=request.state.org_id)
    return {"secure_url": result["secure_url"]}


@app.get("/admin/voters")
async def get_all_voters(request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
    voters = []
    async for v in db.voters.find(org_query(request), {"_id": 0}):
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
                "it_admin_must_change_password": False
            }}
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
                "financial_controller_must_change_password": False
            }}
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
                "overseer_must_change_password": False
            }}
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
                "commissioner_must_change_password": False
            }}
        )
        await log_action("commissioner_password_changed", commissioner["student_id"], {}, org_id=request.state.org_id)
        return {"status": "password_updated"}

    raise HTTPException(404, "Account not found.")

# --- Candidates (superadmin can add/edit/delete freely; commission does not touch these) ---

@app.post("/candidates")
async def add_candidate(candidate: CandidateCreate, request: Request, admin: dict = Depends(require_role("superadmin"))):
    result = await db.candidates.insert_one(org_stamp(request, candidate.dict()))
    await log_action("candidate_added", current_actor(request), {
        "name": candidate.name, "position": candidate.position
    }, org_id=request.state.org_id)
    return {"id": str(result.inserted_id)}


@app.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, data: dict, request: Request, admin: dict = Depends(require_role("superadmin"))):
    oid = parse_oid(candidate_id, "candidate id")
    upd = {
        "name":     data.get("name"),
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
        {"$set": {f"votes.{data.commissioner_id.replace('.', '_').replace('/', '_')}": data.vote}}
    )

    updated = await db.applications.find_one(org_query(request, {"_id": oid}))
    await _resolve_application(app_id, updated, request.state.org_id)

    return {"status": "vote_recorded"}


@app.post("/admin/applications/{app_id}/vote-remove")
async def commissioner_vote_remove(app_id: str, data: CommissionerVote, request: Request):
    """A commissioner votes to remove an already-approved candidate."""
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

    safe_key = data.commissioner_id.replace('.', '_').replace('/', '_')
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
    logger.info(f"Application {app_id} finance-cleared by {data.commissioner_id}.")
    return {"status": "finance_cleared"}


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
         "is_finance_commissioner": 1, "commissioner_role": 1},
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
async def create_organization(data: OrganizationCreate):
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
            "commissioner_name":   "",
            "support_phone":       "",
            "support_pdf_url":     "",
            "cc_list":             []
        }
        
    doc.pop("_id", None)
    return doc


@app.post("/superadmin/branding")
async def save_branding(data: BrandingUpdate, request: Request):
    await db.settings.update_one(
        org_query(request, {"name": "branding"}),
        {"$set": org_stamp(request, {**data.dict(), "name": "branding"})},
        upsert=True
    )
    # Branding drives the org name, the commissioner name printed on the
    # official declaration, and the cc list — all of which appear on the
    # certified report. Changes to it belong in the audit trail.
    await log_action("branding_updated", current_actor(request), {
        "org_name": data.org_name,
        "commissioner_name": data.commissioner_name,
        "cc_count": len(data.cc_list),
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
        {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1, "is_finance_commissioner": 1, "commissioner_role": 1, "commissioner_email": 1}
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
        {"$set": {"is_commissioner": new_val}}
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
            "it_admin_must_change_password": True
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

@app.get("/election-results")
async def get_election_results(request: Request):
    voter_turnout = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    vote_counts = await get_vote_counts(request)
    results = []
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
        results.append({
            "id": str(cand["_id"]),
            "name": cand["name"],
            "position": cand["position"],
            "votes": vote_counts.get(str(cand["_id"]), 0),
            "order": cand.get("order", 0)
        })
    return {"voter_turnout": voter_turnout, "results": results}

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
            "requested_at":  c.get("requested_at")
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
    # A request attributed to someone else would make the audit trail lie
    # about who asked for a voter to be added to the register.
    bind_identity(request, data.requested_by, "IT Admin account")
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
            "it_admin_must_change_password": True
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
            "commissioner_must_change_password": True
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Commissioner", temp_password)
    await log_action("commissioner_password_reset", current_actor(request), {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}

@app.post("/it-admin/students/request-remove")
async def request_remove_student(data: ITAdminStudentRemove, request: Request, admin: dict = Depends(require_role("it_admin", "superadmin"))):
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
        {"$set": {"is_it_admin": new_val}}
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
            "commissioner_must_change_password": True
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
        {"$set": {"is_financial_controller": new_val}}
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
            "financial_controller_must_change_password": True
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
            "financial_controller_must_change_password": True
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
        {"$set": {"is_overseer": new_val}}
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
            "overseer_must_change_password": True
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
            "overseer_must_change_password": True
        }}
    )
    sms_sent = await send_temp_password_sms(voter, "Overseer", temp_password)
    await log_action("overseer_password_reset", current_actor(request), {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}


@app.get("/superadmin/student-changes")
async def superadmin_list_student_changes(request: Request, status: str = None):
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
    phone = data.phone
    clean = re.sub(r'\D', '', phone)
    if clean.startswith('0'):
        clean = '256' + clean[1:]
    elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
        clean = '256' + clean
    await db.voters.update_one(
        org_query(request, {"student_id": data.student_id}),
        {"$set": org_stamp(request, {
            "full_name":       data.full_name,
            "phone_numbers":   [clean],
            "is_commissioner": False,
            "is_it_admin":     False,
            "has_voted":       False,
            "last_status":     "idle",
            "added_by":        "superadmin",
            "add_reason":      data.reason
        })},
        upsert=True
    )
    await log_action("student_added_by_superadmin", current_actor(request), {
        "student_id": data.student_id,
        "full_name":  data.full_name,
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "added"}


@app.post("/superadmin/students/remove")
async def superadmin_remove_student(data: ITAdminStudentRemove, request: Request):
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

    old_name = voter.get("full_name", "")
    old_phones = list(voter.get("phone_numbers", []))
    new_name, new_sid, phones = old_name, old_sid, list(old_phones)
    events: list[dict] = []          # {event, field, old, new}

    if data.full_name is not None:
        candidate = " ".join(data.full_name.split())
        if not candidate or len(candidate) > 120:
            raise HTTPException(400, "Name must be 1-120 characters.")
        if candidate != old_name:
            new_name = candidate
            events.append({"event": "student_name_changed", "field": "full_name", "old": old_name, "new": candidate})

    if data.new_student_id is not None:
        candidate_sid = normalize_student_id(data.new_student_id)
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

    for op in data.phone_ops:
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
        for coll in (db.applications, db.exception_grants):
            await coll.update_many({"org_id": org_id, "student_id": old_sid}, {"$set": {"student_id": new_sid}})

    actor, role, now, batch = current_actor(request), admin.get("role", ""), datetime.utcnow(), secrets.token_hex(8)
    terms = sorted({old_sid, new_sid, old_name.lower(), new_name.lower()} - {""})
    for ev in events:
        await db.student_edit_audit.insert_one({
            "org_id": org_id, "student_key": str(voter["_id"]), "batch": batch,
            "event": ev["event"], "field": ev["field"], "old_value": ev["old"], "new_value": ev["new"],
            "reason": reason, "actor": actor, "actor_role": role, "at": now,
            "student_id_before": old_sid, "student_id_after": new_sid, "search_terms": terms,
        })
        # Masked mirror in the general activity log (that log is visible to every admin role).
        await log_action(ev["event"], actor, {
            "student_id": new_sid, "role": role, "reason": reason, "field": ev["field"],
            "old": _mask_phone(ev["old"]) if ev["field"] == "phone_numbers" else ev["old"],
            "new": _mask_phone(ev["new"]) if ev["field"] == "phone_numbers" else ev["new"],
        }, org_id=org_id)

    return {"status": "updated", "changes": [e["event"] for e in events],
            "student": _student_edit_view({**voter, "full_name": new_name, "student_id": new_sid,
                                           "phone_numbers": phones})}


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
    return await verify_audit_chain(request)

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

    stored = {}
    for name, window in data.phases.items():
        if window.start and window.end and window.end <= window.start:
            raise HTTPException(400, f"'{name}' end time must be after its start time.")
        stored[name] = {"start": window.start, "end": window.end, "enforced": window.enforced}

    await db.settings.update_one(
        org_query(request, {"name": "election_phases"}),
        {"$set": org_stamp(request, {
            "name": "election_phases",
            "phases": stored,
            "round_id": data.round_id or DEFAULT_ROUND_ID,
            "updated_at": datetime.utcnow(),
        })},
        upsert=True,
    )
    await log_action("phases_scheduled", current_actor(request), {
        "round_id": data.round_id,
        "phases": {k: {"enforced": v["enforced"]} for k, v in stored.items()},
    }, org_id=request.state.org_id)
    return {"status": "saved", "round_id": data.round_id or DEFAULT_ROUND_ID}


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
    query = org_query(request)
    if action:
        query["action"] = {"$regex": re.escape(action.strip()[:60]), "$options": "i"}
    if actor:
        query["actor"] = {"$regex": re.escape(actor.strip()[:60]), "$options": "i"}
    limit = min(max(limit, 1), 500)
    skip = max(skip, 0)
    total = await db.audit_log.count_documents(query)
    logs = []
    async for entry in db.audit_log.find(query).sort("timestamp", -1).skip(skip).limit(limit):
        entry["_id"] = str(entry["_id"])
        logs.append(entry)
    return {"total": total, "limit": limit, "skip": skip, "entries": logs}


@app.get("/admin/audit/verify")
async def get_admin_audit_verify(request: Request):
    """Independently re-derives the whole hash chain from raw vote_events."""
    result = await verify_audit_chain(request)
    await log_action("audit_chain_verified", current_actor(request), {
        "valid": result.get("valid"),
        "checkpoints": result.get("checkpoints_verified"),
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
    events = []
    async for entry in db.audit_log.find(query).sort("timestamp", -1).limit(limit):
        entry["_id"] = str(entry["_id"])
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
        {"_id": 0, "full_name": 1, "commissioner_role": 1, "is_chief_commissioner": 1},
    ):
        commissioners.append(c)
    commissioners.sort(key=lambda c: (not c.get("is_chief_commissioner"), c.get("full_name", "")))

    chief = next((c for c in commissioners if c.get("is_chief_commissioner")), None)
    commissioner_name = (
        (chief or {}).get("full_name")
        or branding.get("commissioner_name")
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

    await log_action("official_report_generated", current_actor(request), {
        "is_certified": is_certified, "chain_valid": chain.get("valid")
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
        "signatories": [
            {"full_name": c.get("full_name", ""), "role": c.get("commissioner_role") or "Commissioner"}
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


@app.get("/election-results/voter-roll")
async def get_public_voter_roll(request: Request):
    await _check_register_rate_limit(request)
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
