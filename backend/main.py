from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import random
import motor.motor_asyncio
import os
import csv
import io
import re
import httpx
import logging
from datetime import datetime
from bson import ObjectId
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import bcrypt
import string
import cloudinary
import cloudinary.uploader

from auth import (
    create_access_token,
    decode_access_token,
    get_bearer_token,
    require_role,
    ADMIN_ROLES,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BallotBoxAPI")

# --- CONFIGURATION & SECRETS ---
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
EGOSMS_USER = os.getenv("EGOSMS_USERNAME")
EGOSMS_PASS = os.getenv("EGOSMS_PASSWORD")
EGOSMS_SENDER_ID = os.getenv("ESMS_SENDER_ID", "SMS").strip()

SUPER_ADMIN_ID   = os.getenv("SUPER_ADMIN_ID")
SUPER_ADMIN_NAME = os.getenv("SUPER_ADMIN_NAME")
if not SUPER_ADMIN_ID or not SUPER_ADMIN_NAME:
    raise RuntimeError(
        "SUPER_ADMIN_ID / SUPER_ADMIN_NAME must be set via environment variables. "
        "No hardcoded fallback is used on purpose."
    )

# --- CLOUDINARY (signed, server-side uploads only — no unsigned preset) ---
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

# --- MONGODB ---
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    client.close()

app = FastAPI(title="BallotBox Master API", lifespan=lifespan)

client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URL,
    maxPoolSize=20,
    minPoolSize=1,
    waitQueueTimeoutMS=2500
)
db = client["electiondbaccounting"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
# public on purpose — voters authenticate per-request via student_id + OTP,
# not via this admin session layer.

PUBLIC_PATHS = {
    "/", "/health", "/election-status",
    "/verify-identity", "/verify-otp", "/vote", "/vote-bulk",
    "/apply/check-eligibility", "/apply", "/apply/upload-image",
    "/verify-admin",
}
PUBLIC_DOC_PREFIXES = ("/docs", "/openapi.json", "/redoc")


def _is_public(path: str, method: str) -> bool:
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_DOC_PREFIXES):
        return True
    # Public read-only endpoints voters/applicants need before they're
    # "logged in" anywhere.
    if method == "GET" and path in {"/candidates", "/positions"}:
        return True
    return False


@app.middleware("http")
async def auth_guard_middleware(request: Request, call_next):
    if _is_public(request.url.path, request.method):
        return await call_next(request)

    try:
        token = get_bearer_token(request)
        payload = decode_access_token(token)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    if payload.get("role") not in ADMIN_ROLES:
        return JSONResponse(status_code=403, content={"detail": "Not authorized."})

    # Superadmin-only namespace, even though every caller here already holds
    # a valid admin token.
    if request.url.path.startswith("/superadmin") and payload["role"] != "superadmin":
        return JSONResponse(status_code=403, content={"detail": "Superadmin access required."})

    request.state.admin = payload
    return await call_next(request)

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

class ElectionSchedule(BaseModel):
    start: datetime
    end: datetime

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

def get_forgiving_filter(student_id: str):
    clean_id = student_id.replace(" ", "").strip()
    return {
        "student_id": {
            "$regex": f'^"?{re.escape(clean_id)}"?$',
            "$options": "i"
        }
    }

def names_match(registered_name: str, input_name: str) -> bool:
    reg_parts   = set(registered_name.strip().lower().split())
    input_parts = set(input_name.strip().lower().split())
    common_parts = reg_parts.intersection(input_parts)
    match_threshold = 2 if len(reg_parts) >= 2 else 1
    return len(common_parts) >= match_threshold

async def send_sms_via_egosms(to_number: str, message_text: str):
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
            logger.info(f"📡 EgoSMS Result: {resp_text}")
            return "OK" in resp_text.upper()
    except Exception as e:
        logger.error(f"❌ Connection Error: {e}")
        return False

# =============================================================================
# PASSWORD HELPERS
# =============================================================================

def generate_temp_password() -> str:
    """Simple 6-digit numeric code — easy to read and type from an SMS."""
    return ''.join(random.choices(string.digits, k=6))

def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()

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

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except Exception:
        return False

async def send_temp_password_sms(voter: dict, role_label: str, temp_password: str) -> bool:
    phone_list = voter.get("phone_numbers", [])
    if not phone_list:
        return False

    branding_doc = await db.settings.find_one({"name": "branding"})
    sms_org_name = (branding_doc or {}).get("org_name", "Election")

    message = (
        f"Hello {voter.get('full_name', 'User')}, your temporary {role_label} login code "
        f"for the {sms_org_name} Election Portal is {temp_password}. "
        f"You will be asked to set a new password on first login. "
        f"Do not share this code with anyone."
    )
    return await send_sms_via_egosms(phone_list[0], message)

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
        # Majority reached — create candidate and mark approved
        await _create_candidate_from_application(app_doc, org_id)
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "approved"}}
        )
        await log_action("application_approved", "commission", {
            "app_id": app_id, "approve_count": approve_count, "total_commissioners": total
        }, org_id=org_id)
        logger.info(f"✅ Application {app_id} approved by commission majority ({approve_count}/{total}).")
    elif deny_count >= required:
        # Majority reached against — application denied
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "denied"}}
        )
        await log_action("application_denied", "commission", {
            "app_id": app_id, "deny_count": deny_count, "total_commissioners": total
        }, org_id=org_id)
        logger.info(f"❌ Application {app_id} denied by commission majority ({deny_count}/{total}).")

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
        await db.candidates.delete_one({"application_id": app_id})
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "removed", "removal_votes": {}}}
        )
        logger.info(f"🗑️ Candidate from application {app_id} removed by commission majority ({approve_removals}/{total}).")

#--IT Administration Helpers---

async def _execute_student_change(change_doc: dict, org_id: str = None):
    if change_doc["change_type"] == "add":
        phone = change_doc.get("phone", "")
        clean = re.sub(r'\D', '', phone)
        if clean.startswith('0'):
            clean = '256' + clean[1:]
        elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
            clean = '256' + clean
        q = {"student_id": change_doc["student_id"]}
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
                "org_id":          org_id
            }},
            upsert=True
        )
    elif change_doc["change_type"] == "remove":
        q = get_forgiving_filter(change_doc["student_id"])
        if org_id:
            q["org_id"] = org_id
        await db.voters.delete_one(q)

async def log_action(action: str, actor: str, details: dict = {}, org_id: str = None):
    await db.audit_log.insert_one({
        "action":    action,
        "actor":     actor,
        "details":   details,
        "org_id":    org_id,
        "timestamp": datetime.utcnow()
    })

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
    if not status_doc:
        return {"is_open": True, "is_certified": False, "start": None, "end": None}
    return {
        "is_open": status_doc.get("is_open", True),
        "is_certified": status_doc.get("is_certified", False),
        "start": status_doc.get("start_time"),
        "end": status_doc.get("end_time")
    }

# =============================================================================
# VOTER ROUTES  (unchanged)
# =============================================================================

@app.post("/verify-identity")
async def verify_identity(data: IdentityCheck, request: Request):
    now = datetime.utcnow()
    status_doc = await db.settings.find_one(org_query(request, {"name": "election_config"}))

    if status_doc:
        if not status_doc.get("is_open", True):
            raise HTTPException(status_code=403, detail="Election is closed.")
        start, end = status_doc.get("start_time"), status_doc.get("end_time")
        if start and end and not (start <= now <= end):
            raise HTTPException(status_code=403, detail="Not within scheduled time.")

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
    otp       = str(random.randint(100000, 999999))

    first_name = student.get("full_name", "Voter").split()[0].capitalize()
    branding_doc = await db.settings.find_one(org_query(request, {"name": "branding"}))
    sms_org_name = (branding_doc or {}).get("org_name", "Election")
    
    message = (
        f"Hello {first_name}, your {sms_org_name} voting code is {otp}. "
        f"Your vote is secret. Do not share this code with anyone. Your voice, your power!"
    )

    if await send_sms_via_egosms(raw_phone, message):
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


@app.post("/verify-otp")
async def verify_otp(data: OTPCheck, request: Request):
    search = org_query(request, get_forgiving_filter(data.student_id))
    voter  = await db.voters.find_one(search)
    if not voter:
        raise HTTPException(status_code=404, detail="Voter not found")

    record = await db.otps.find_one(search) or await db.admin_otps.find_one(search)

    if record and record["code"] == data.code:
        await db.voters.update_one(search, {"$set": {"last_status": "authenticated", "otp_count": 0}})
        await db.otps.delete_one(search)
        return {"status": "success"}

    raise HTTPException(status_code=400, detail="Invalid OTP. Please check your messages and try again.")


@app.post("/vote")
async def cast_vote(data: VoteRequest, request: Request):
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student or student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Ineligible voter")
    if student.get("last_status") != "authenticated":
        raise HTTPException(status_code=403, detail="OTP verification required before voting.")
    await db.voters.update_one({"_id": student["_id"]}, {"$set": {"has_voted": True, "last_status": "completed"}})
    await db.candidates.update_one(org_query(request, {"_id": ObjectId(data.candidate_id)}), {"$inc": {"votes": 1}})
    return {"status": "success"}


@app.post("/vote-bulk")
async def cast_bulk_vote(data: BulkVoteRequest, request: Request):
    student = await db.voters.find_one(org_query(request, get_forgiving_filter(data.student_id)))
    if not student:
        raise HTTPException(status_code=404, detail="Voter not found")
    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="You have already cast your vote.")
    if student.get("last_status") != "authenticated":
        raise HTTPException(status_code=403, detail="OTP verification required before voting.")

    await db.voters.update_one(
        {"_id": student["_id"]},
        {"$set": {"has_voted": True, "last_status": "completed"}}
    )

    for c_id in data.candidate_ids:
        try:
            await db.candidates.update_one(org_query(request, {"_id": ObjectId(c_id)}), {"$inc": {"votes": 1}})
        except Exception:
            continue

    return {"status": "success", "message": "Ballot cast successfully"}


@app.get("/candidates")
async def get_candidates(request: Request):
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
# endpoint. Good enough for a single-instance deployment; if this ever runs
# on multiple Render/Railway instances behind a load balancer, swap for a
# Redis-backed limiter (e.g. slowapi) since in-memory state won't be shared
# across instances.
_upload_attempts: dict[str, list[float]] = {}
UPLOAD_RATE_LIMIT = 8       # max uploads
UPLOAD_RATE_WINDOW_S = 600  # per 10 minutes, per IP


def _check_upload_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = datetime.utcnow().timestamp()
    attempts = [t for t in _upload_attempts.get(ip, []) if now - t < UPLOAD_RATE_WINDOW_S]
    if len(attempts) >= UPLOAD_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many uploads. Please try again in a few minutes.")
    attempts.append(now)
    _upload_attempts[ip] = attempts


@app.post("/apply/upload-image")
async def apply_upload_image(request: Request, file: UploadFile = File(...)):
    """Public upload used for candidate photos and payment proof during
    application submission. Applicants have no login, so this can't require
    an admin token — but it still keeps the Cloudinary secret server-side,
    validates file type/size, and rate-limits per IP, none of which the old
    unsigned-preset upload did.
    """
    _check_upload_rate_limit(request)

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP, or GIF images are allowed.")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Image must be under 5MB.")

    try:
        result = cloudinary.uploader.upload(content, folder="ballotbox/applicants")
    except Exception as e:
        logger.error(f"Cloudinary applicant upload failed: {e}")
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    return {"secure_url": result["secure_url"]}


@app.post("/apply/check-eligibility")
async def check_application_eligibility(data: ApplicationEligibilityCheck, request: Request):
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
    # ── Superadmin ── (env var based, no hashing needed — this is you)
    if data.email == SUPER_ADMIN_ID and data.password == SUPER_ADMIN_NAME:
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
        raise HTTPException(status_code=404, detail="Invalid email or password.")

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


@app.post("/admin/toggle-election")
async def toggle_election(request: Request):
    current    = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    new_status = not (current.get("is_open", True) if current else True)
    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$set": org_stamp(request, {"is_open": new_status, "name": "election_config"})},
        upsert=True
    )
    await log_action("election_toggled", "superadmin", {"is_open": new_status}, org_id=request.state.org_id)
    logger.info(f" Election toggled to: {'OPEN' if new_status else 'CLOSED'}")
    return {"is_open": new_status}


@app.post("/admin/schedule-election")
async def schedule_election(data: ElectionSchedule, request: Request):
    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$set": org_stamp(request, {"start_time": data.start, "end_time": data.end, "is_open": True, "name": "election_config"})},
        upsert=True
    )
    return {"status": "scheduled"}


@app.post("/admin/clear-schedule")
async def clear_schedule(request: Request):
    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$unset": {"start_time": "", "end_time": ""}}
    )
    return {"status": "cleared"}


@app.post("/admin/reset-election")
async def reset_election(request: Request):
    await db.otps.delete_many(org_query(request))
    await db.voters.update_many(org_query(request), {"$set": {"has_voted": False, "last_status": "idle"}})
    await db.candidates.update_many(org_query(request), {"$set": {"votes": 0}})
    return {"status": "success"}


@app.post("/admin/toggle-certification")
async def toggle_certification(request: Request):
    current    = await db.settings.find_one(org_query(request, {"name": "election_config"}))
    new_status = not (current.get("is_certified", False) if current else False)
    await db.settings.update_one(
        org_query(request, {"name": "election_config"}),
        {"$set": {"is_certified": new_status}},
        upsert=True
    )
    await log_action("results_certified", "superadmin", {"is_certified": new_status}, org_id=request.state.org_id)
    return {"is_certified": new_status}


@app.get("/admin/sms-balance")
async def get_sms_balance():
    return {"balance": "Check EgoSMS Portal", "currency": "UGX"}


@app.post("/admin/test-connection")
async def test_egosms_connection(data: AdminTestSMS):
    success = await send_sms_via_egosms(data.phone, "EgoSMS Connection Verified for BallotBox!")
    if success:
        return {"status": "success", "message": f"Test message delivered to {data.phone}"}
    raise HTTPException(status_code=400, detail="EgoSMS rejected the request. Check Railway logs for the reason.")


@app.post("/admin/import-voters")
async def import_voters(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    reader  = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    count   = 0
    now     = datetime.utcnow()

    for row in reader:
        # Handle both hyphen (student-id) and underscore (student_id) column names
        sid             = (row.get('student_id') or row.get('student-id') or '').strip()
        name            = (row.get('full_name')  or row.get('full-name')  or '').strip()
        raw_phone_field = (row.get('phone') or '').strip()

        if sid and name:
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
                if clean not in formatted_numbers:
                    formatted_numbers.append(clean)

            await db.voters.update_one(
                org_query(request, {"student_id": sid}),
                {"$set": org_stamp(request, {
                    "full_name":       name,
                    "phone_numbers":   formatted_numbers,
                    "is_commissioner": False,
                    "has_voted":       False,
                    "last_active":     None,
                    "last_status":     "idle",
                    "updated_at":      now
                })},
                upsert=True
            )
            count += 1
    await log_action("voters_imported", "admin", {"count": count}, org_id=request.state.org_id)
    return {"status": "success", "imported_count": count}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB


@app.post("/admin/upload-image")
async def admin_upload_image(request: Request, file: UploadFile = File(...)):
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

    try:
        result = cloudinary.uploader.upload(content, folder="ballotbox/admin")
    except Exception as e:
        logger.error(f"Cloudinary admin upload failed: {e}")
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    return {"secure_url": result["secure_url"]}


@app.get("/admin/voters")
async def get_all_voters(request: Request):
    voters = []
    async for v in db.voters.find(org_query(request), {"_id": 0}):
        voters.append(v)
    return voters

@app.post("/admin/set-password")
async def set_new_password(data: SetNewPassword, request: Request):
    # Try IT admin first
    it_admin = await db.voters.find_one(org_query(request, {
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    }))
    if it_admin:
        if not verify_password(data.old_password, it_admin.get("it_admin_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        if len(data.new_password) < 6:
            raise HTTPException(400, "New password must be at least 6 characters.")
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
        if not verify_password(data.old_password, financial_controller.get("financial_controller_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        if len(data.new_password) < 6:
            raise HTTPException(400, "New password must be at least 6 characters.")
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
        if not verify_password(data.old_password, overseer.get("overseer_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        if len(data.new_password) < 6:
            raise HTTPException(400, "New password must be at least 6 characters.")
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
        if not verify_password(data.old_password, commissioner.get("commissioner_password_hash", "")):
            raise HTTPException(401, "Current password is incorrect.")
        if len(data.new_password) < 6:
            raise HTTPException(400, "New password must be at least 6 characters.")
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
async def add_candidate(candidate: CandidateCreate, request: Request):
    result = await db.candidates.insert_one(org_stamp(request, candidate.dict()))
    await log_action("candidate_added", "superadmin", {
        "name": candidate.name, "position": candidate.position
    }, org_id=request.state.org_id)
    return {"id": str(result.inserted_id)}


@app.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, data: dict, request: Request):
    upd = {
        "name":     data.get("name"),
        "position": data.get("position"),
        "order":    int(data.get("order", 0))
    }
    if data.get("image_url"):
        upd["image_url"] = data["image_url"]
    await db.candidates.update_one(org_query(request, {"_id": ObjectId(candidate_id)}), {"$set": upd})
    return {"status": "success"}


@app.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, request: Request):
    await db.candidates.delete_one(org_query(request, {"_id": ObjectId(candidate_id)}))
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
            try:
                pos = await db.positions.find_one(org_query(request, {"_id": ObjectId(a["position_id"])}))
                a["position_title"] = pos["title"] if pos else a.get("position_id", "")
            except Exception:
                a["position_title"] = a.get("position_id", "")
        apps.append(a)
    return apps


# =============================================================================
# COMMISSION ROUTES  (voting — requires commission login)
# =============================================================================

@app.post("/admin/applications/{app_id}/vote")
async def commissioner_vote(app_id: str, data: CommissionerVote, request: Request):
    """A commissioner casts their approve/deny vote on a pending application."""
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' or 'deny'.")

    app_doc = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if not app_doc.get("finance_cleared"):
        raise HTTPException(400, "Awaiting Finance Commissioner clearance before voting can open.")

    # Verify the voter exists and is actually a commissioner
    commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    }))
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    # Record vote (keyed by commissioner_id so they can only vote once per application)
    await db.applications.update_one(
        org_query(request, {"_id": ObjectId(app_id)}),
        {"$set": {f"votes.{data.commissioner_id.replace('.', '_').replace('/', '_')}": data.vote}}
    )

    updated = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    await _resolve_application(app_id, updated, request.state.org_id)

    return {"status": "vote_recorded"}


@app.post("/admin/applications/{app_id}/vote-remove")
async def commissioner_vote_remove(app_id: str, data: CommissionerVote, request: Request):
    """A commissioner votes to remove an already-approved candidate."""
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' (remove) or 'deny' (keep).")

    app_doc = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") != "approved":
        raise HTTPException(400, "Can only vote to remove an approved candidate.")

    commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    }))
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    safe_key = data.commissioner_id.replace('.', '_').replace('/', '_')
    await db.applications.update_one(
        org_query(request, {"_id": ObjectId(app_id)}),
        {"$set": {f"removal_votes.{safe_key}": data.vote}}
    )

    updated = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    await _resolve_removal(app_id, updated, request.state.org_id)

    return {"status": "removal_vote_recorded"}


@app.post("/admin/applications/{app_id}/finance-clear")
async def finance_clear_application(app_id: str, data: FinanceClear, request: Request):
    """
    The Finance Commissioner verifies the candidate's payment status and clears
    the application for voting. No commissioner (including her) can cast a vote
    on this application until this is done.
    """
    app_doc = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared.")

    finance_commissioner = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True,
        "is_finance_commissioner": True
    }))
    if not finance_commissioner:
        raise HTTPException(403, "Only the designated Finance Commissioner can clear applications.")

    await db.applications.update_one(
        org_query(request, {"_id": ObjectId(app_id)}),
        {"$set": {
            "finance_cleared": True,
            "finance_cleared_by": data.commissioner_id,
            "finance_cleared_at": datetime.utcnow()
        }}
    )
    await log_action("application_finance_cleared", data.commissioner_id, {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f"💰 Application {app_id} finance-cleared by {data.commissioner_id}.")
    return {"status": "finance_cleared"}


@app.get("/commission/results/detailed")
async def get_commission_detailed_results(request: Request):
    """
    Detailed, per-position results view for the Commission portal so
    commissioners can monitor and announce standings themselves. Built entirely
    from the aggregate `candidates.votes` counters — no voter identity is ever
    linked to a candidate choice in this schema, so this view carries no
    anonymity risk; it's the same anonymous data /election-results already
    exposes publicly, just grouped and enriched for commission use.
    """
    total_voters = await db.voters.count_documents(org_query(request))
    voted_count  = await db.voters.count_documents(org_query(request, {"has_voted": True}))

    positions_by_id = {}
    async for pos in db.positions.find(org_query(request)).sort("order", 1):
        positions_by_id[str(pos["_id"])] = pos

    grouped: dict = {}
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
        position_title = cand.get("position", "Unknown Position")
        grouped.setdefault(position_title, []).append(cand)

    detailed = []
    for position_title, candidates in grouped.items():
        position_total_votes = sum(c.get("votes", 0) for c in candidates)
        candidate_rows = []
        for c in sorted(candidates, key=lambda x: x.get("votes", 0), reverse=True):
            votes = c.get("votes", 0)
            candidate_rows.append({
                "id":           str(c["_id"]),
                "name":         c["name"],
                "votes":        votes,
                "pct_of_position": round((votes / position_total_votes) * 100, 1) if position_total_votes else 0,
                "unopposed":    len(candidates) == 1
            })
        detailed.append({
            "position":       position_title,
            "total_votes":    position_total_votes,
            "candidates":     candidate_rows
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
    await log_action("organization_created", "superadmin", {
        "org_id": str(result.inserted_id), "name": data.name, "slug": slug
    })
    logger.info(f"🏢 Organization '{data.name}' provisioned with slug '{slug}'.")
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
    return {"status": "saved"}


# --- Positions ---

@app.post("/positions")
async def add_position(data: PositionCreate, request: Request):
    result = await db.positions.insert_one(org_stamp(request, data.dict()))
    return {"id": str(result.inserted_id)}


@app.delete("/positions/{position_id}")
async def delete_position(position_id: str, request: Request):
    await db.positions.delete_one(org_query(request, {"_id": ObjectId(position_id)}))
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
    return {"student_id": student_id, "is_chief_commissioner": True}


@app.post("/superadmin/commissioners/{student_id:path}/clear-chief")
async def clear_chief_commissioner(student_id: str, request: Request):
    await db.voters.update_one(
        org_query(request, get_forgiving_filter(student_id)),
        {"$set": {"is_chief_commissioner": False}}
    )
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
    await db.voters.update_many(org_query(request), {"$set": {"is_finance_commissioner": False}})
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_finance_commissioner": True}}
    )
    await log_action("finance_commissioner_set", "superadmin", {"student_id": student_id}, org_id=request.state.org_id)
    return {"student_id": student_id, "is_finance_commissioner": True}


@app.post("/superadmin/commissioners/{student_id:path}/clear-finance-commissioner")
async def clear_finance_commissioner(student_id: str, request: Request):
    await db.voters.update_one(
        org_query(request, get_forgiving_filter(student_id)),
        {"$set": {"is_finance_commissioner": False}}
    )
    await log_action("finance_commissioner_cleared", "superadmin", {"student_id": student_id}, org_id=request.state.org_id)
    return {"student_id": student_id, "is_finance_commissioner": False}


@app.get("/superadmin/finance-commissioner")
async def get_finance_commissioner(request: Request):
    fc = await db.voters.find_one(
        org_query(request, {"is_finance_commissioner": True}),
        {"_id": 0, "student_id": 1, "full_name": 1}
    )
    if not fc:
        return {"full_name": None}
    return fc


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
    await log_action("commissioner_role_set", "superadmin", {
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
    await log_action("commissioner_toggled", "superadmin", {
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
    await log_action("it_admin_credentials_set", "superadmin", {
        "student_id": student_id, "email": data.email, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "credentials_set", "sms_notified": sms_sent}
    
# --- Application overrides ---

@app.post("/superadmin/applications/{app_id}/force-approve")
async def superadmin_force_approve(app_id: str, request: Request):
    """Approve an application instantly, bypassing commission voting."""
    app_doc = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") == "approved":
        raise HTTPException(400, "Already approved.")

    await _create_candidate_from_application(app_doc, request.state.org_id)
    await db.applications.update_one(
        org_query(request, {"_id": ObjectId(app_id)}),
        {"$set": {
            "status": "approved",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        }}
    )
    await log_action("application_force_approved", "superadmin", {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f" Superadmin force-approved application {app_id}.")
    return {"status": "force_approved"}


@app.post("/superadmin/applications/{app_id}/force-deny")
async def superadmin_force_deny(app_id: str, request: Request):
    """Deny an application instantly, bypassing commission voting."""
    app_doc = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("denied", "removed"):
        raise HTTPException(400, "Application is already denied or removed.")

    await db.applications.update_one(
        org_query(request, {"_id": ObjectId(app_id)}),
        {"$set": {
            "status": "denied",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        }}
    )
    await log_action("application_force_denied", "superadmin", {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f" Superadmin force-denied application {app_id}.")
    return {"status": "force_denied"}


@app.post("/superadmin/applications/{app_id}/force-finance-clear")
async def superadmin_force_finance_clear(app_id: str, request: Request):
    """Bypass the Finance Commissioner gate — for cases where no Finance
    Commissioner is currently assigned. Voting can proceed after this."""
    app_doc = await db.applications.find_one(org_query(request, {"_id": ObjectId(app_id)}))
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("finance_cleared"):
        raise HTTPException(400, "This application has already been finance-cleared.")

    await db.applications.update_one(
        org_query(request, {"_id": ObjectId(app_id)}),
        {"$set": {
            "finance_cleared": True,
            "finance_cleared_by": "superadmin_override",
            "finance_cleared_at": datetime.utcnow()
        }}
    )
    await log_action("application_force_finance_cleared", "superadmin", {"app_id": app_id}, org_id=request.state.org_id)
    logger.info(f"💰 Superadmin force-cleared finance gate for application {app_id}.")
    return {"status": "force_finance_cleared"}


@app.post("/superadmin/candidates/{candidate_id}/remove")
async def superadmin_remove_candidate(candidate_id: str, request: Request):
    """Remove an approved candidate from the ballot instantly."""
    cand = await db.candidates.find_one(org_query(request, {"_id": ObjectId(candidate_id)}))
    if not cand:
        raise HTTPException(404, "Candidate not found.")

    await db.candidates.delete_one(org_query(request, {"_id": ObjectId(candidate_id)}))
    await log_action("candidate_removed", "superadmin", {
    "name": cand.get("name"), "position": cand.get("position")
    }, org_id=request.state.org_id)
    
    # If the candidate came from an application, mark it removed
    if cand.get("application_id"):
        await db.applications.update_one(
            org_query(request, {"_id": ObjectId(cand["application_id"])}),
            {"$set": {
                "status": "removed",
                "superadmin_override": True,
                "removed_at": datetime.utcnow()
            }}
        )

    logger.info(f"⚡ Superadmin removed candidate {candidate_id}.")
    return {"status": "removed"}


# =============================================================================
# RESULTS
# =============================================================================

@app.get("/election-results")
async def get_election_results(request: Request):
    voter_turnout = await db.voters.count_documents(org_query(request, {"has_voted": True}))
    results = []
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
        results.append({
            "id":       str(cand["_id"]),
            "name":     cand["name"],
            "position": cand["position"],
            "votes":    cand.get("votes", 0),
            "order":    cand.get("order", 0)
        })
    return {"voter_turnout": voter_turnout, "results": results}


# =============================================================================
# OVERSEER ROUTES  (read-only, platform-wide, anonymized)
# =============================================================================

@app.get("/overseer/dashboard")
async def get_overseer_dashboard(request: Request):
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

    candidates_results = []
    async for cand in db.candidates.find(org_query(request)).sort("order", 1):
        candidates_results.append({
            "name":     cand["name"],
            "position": cand["position"],
            "votes":    cand.get("votes", 0)
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
async def request_add_student(data: ITAdminStudentAdd, request: Request):
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
    await log_action("it_admin_password_reset", "superadmin", {
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
    await log_action("commissioner_password_reset", "superadmin", {
        "student_id": student_id, "sms_notified": sms_sent
    }, org_id=request.state.org_id)
    return {"status": "password_reset", "sms_notified": sms_sent}

@app.post("/it-admin/students/request-remove")
async def request_remove_student(data: ITAdminStudentRemove, request: Request):
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
async def cancel_student_change(change_id: str, data: StudentChangeCancelRequest, request: Request):
    change = await db.student_changes.find_one(org_query(request, {"_id": ObjectId(change_id)}))
    if not change:
        raise HTTPException(404, "Request not found.")
    if change.get("requested_by") != data.requested_by:
        raise HTTPException(403, "You can only cancel your own requests.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"Cannot cancel a request that is already {change.get('status')}.")

    await db.student_changes.update_one(
        org_query(request, {"_id": ObjectId(change_id)}),
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
async def get_my_requests(it_admin_id: str, request: Request):
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

    change = await db.student_changes.find_one(org_query(request, {"_id": ObjectId(change_id)}))
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"This request is already {change.get('status')}.")

    financial_controller = await db.voters.find_one(org_query(request, {
        **get_forgiving_filter(data.financial_controller_id),
        "is_financial_controller": True
    }))
    if not financial_controller:
        raise HTTPException(403, "Not a registered Financial Controller.")

    if data.decision == "approve":
        await _execute_student_change(change, request.state.org_id)
        await db.student_changes.update_one(
            org_query(request, {"_id": ObjectId(change_id)}),
            {"$set": {
                "status":                "approved",
                "decided_by":            data.financial_controller_id,
                "decision_reason":       data.reason,
                "resolved_at":           datetime.utcnow()
            }}
        )
        await log_action("student_change_approved", data.financial_controller_id, {
            "change_type": change["change_type"],
            "student_id":  change["student_id"],
            "requested_by": change.get("requested_by", "")
        }, org_id=request.state.org_id)
    else:
        await db.student_changes.update_one(
            org_query(request, {"_id": ObjectId(change_id)}),
            {"$set": {
                "status":                "denied",
                "decided_by":            data.financial_controller_id,
                "decision_reason":       data.reason,
                "resolved_at":           datetime.utcnow()
            }}
        )
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
    await log_action("it_admin_toggled", "superadmin", {
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
    await log_action("commissioner_credentials_set", "superadmin", {
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
    await log_action("financial_controller_toggled", "superadmin", {
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
    await log_action("financial_controller_credentials_set", "superadmin", {
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
    await log_action("financial_controller_password_reset", "superadmin", {
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
    await log_action("overseer_toggled", "superadmin", {
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
    await log_action("overseer_credentials_set", "superadmin", {
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
    await log_action("overseer_password_reset", "superadmin", {
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
    change = await db.student_changes.find_one(org_query(request, {"_id": ObjectId(change_id)}))
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("approved", "force_approved"):
        raise HTTPException(400, "Already approved.")
    if change.get("status") == "cancelled":
        raise HTTPException(400, "Cannot approve a cancelled request.")

    await _execute_student_change(change, request.state.org_id)
    await db.student_changes.update_one(
        org_query(request, {"_id": ObjectId(change_id)}),
        {"$set": {
            "status":               "force_approved",
            "superadmin_override":  True,
            "resolved_at":          datetime.utcnow()
        }}
    )
    await log_action("student_change_force_approved", "superadmin", {
        "change_type":  change["change_type"],
        "student_id":   change["student_id"],
        "requested_by": change.get("requested_by", "")
    }, org_id=request.state.org_id)
    return {"status": "force_approved"}


@app.post("/superadmin/student-changes/{change_id}/force-deny")
async def superadmin_force_student_change_deny(change_id: str, request: Request):
    change = await db.student_changes.find_one(org_query(request, {"_id": ObjectId(change_id)}))
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("denied", "force_denied", "cancelled"):
        raise HTTPException(400, f"Request is already {change.get('status')}.")

    await db.student_changes.update_one(
        org_query(request, {"_id": ObjectId(change_id)}),
        {"$set": {
            "status":               "force_denied",
            "superadmin_override":  True,
            "resolved_at":          datetime.utcnow()
        }}
    )
    await log_action("student_change_force_denied", "superadmin", {
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
    await log_action("student_added_by_superadmin", "superadmin", {
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
    await log_action("student_removed_by_superadmin", "superadmin", {
        "student_id": data.student_id,
        "full_name":  student.get("full_name", ""),
        "reason":     data.reason
    }, org_id=request.state.org_id)
    return {"status": "removed"}


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
