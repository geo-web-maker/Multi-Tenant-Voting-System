from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
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

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BallotBoxAPI")

# --- CONFIGURATION & SECRETS ---
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
EGOSMS_USER = os.getenv("EGOSMS_USERNAME")
EGOSMS_PASS = os.getenv("EGOSMS_PASSWORD")
EGOSMS_SENDER_ID = os.getenv("ESMS_SENDER_ID", "SMS").strip()

SUPER_ADMIN_ID   = os.getenv("SUPER_ADMIN_ID",   "geo_web@yahoo.com")
SUPER_ADMIN_NAME = os.getenv("SUPER_ADMIN_NAME",  "dorothygeorge@QWE25")

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
# MODELS
# ============================================================================= 
class ApplicationSubmit(BaseModel):
    student_id:        str
    full_name:         str
    position_id:       str
    manifesto:         str = ""
    image_url:         str = ""
    payment_method:    str = ""     
    payment_proof_url: str = ""      
    
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
    student_id: str
    full_name: str
    position_id: str
    manifesto: str = ""
    image_url: str = ""

class CommissionerVote(BaseModel):
    commissioner_id: str   # the commissioner's student_id
    vote: str              # "approve" or "deny"
    reason: str = ""
    

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

class StudentChangeVote(BaseModel):
    commissioner_id: str
    vote:            str   # "approve" or "deny"
    reason:          str = ""

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

async def get_commissioner_count() -> int:
    return await db.voters.count_documents({"is_commissioner": True})

async def _resolve_position_title(position_id: str) -> tuple[str, int]:
    """Returns (title, order) for a position id, with safe fallbacks."""
    try:
        pos = await db.positions.find_one({"_id": ObjectId(position_id)})
        if pos:
            return pos.get("title", position_id), pos.get("order", 0)
    except Exception:
        pass
    return position_id, 0

async def _create_candidate_from_application(app_doc: dict):
    title, order = await _resolve_position_title(app_doc.get("position_id", ""))
    await db.candidates.insert_one({
        "name": app_doc["full_name"],
        "position": title,
        "image_url": app_doc.get("image_url", ""),
        "order": order,
        "votes": 0,
        "application_id": str(app_doc["_id"])
    })

async def _resolve_application(app_id: str, app_doc: dict):
    """
    Called after every commissioner vote.
    Promotes to approved (creating candidate) when ALL commissioners approve.
    Marks denied as soon as ANY commissioner denies — full consensus required.
    """
    total = await get_commissioner_count()
    if total == 0:
        return

    votes = app_doc.get("votes", {})
    if len(votes) < total:
        return  # not everyone has voted yet

    approve_count = sum(1 for v in votes.values() if v == "approve")
    deny_count    = sum(1 for v in votes.values() if v == "deny")

    if approve_count == total:
        # Full consensus — create candidate and mark approved
        await _create_candidate_from_application(app_doc)
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "approved"}}
        )
        await log_action("application_approved", "commission", {"app_id": app_id})
        logger.info(f"✅ Application {app_id} approved by full commission consensus.")
    elif deny_count > 0:
        # Any single deny blocks the application
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "denied"}}
        )
        await log_action("application_denied", "commission", {"app_id": app_id})
        logger.info(f"❌ Application {app_id} denied — commissioner voted against.")

async def _resolve_removal(app_id: str, app_doc: dict):
    """
    Called after every removal vote.
    Removes the candidate only when ALL commissioners agree to remove.
    """
    total = await get_commissioner_count()
    if total == 0:
        return

    removal_votes = app_doc.get("removal_votes", {})
    if len(removal_votes) < total:
        return

    approve_removals = sum(1 for v in removal_votes.values() if v == "approve")

    if approve_removals == total:
        await db.candidates.delete_one({"application_id": app_id})
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "removed", "removal_votes": {}}}
        )
        logger.info(f"🗑️ Candidate from application {app_id} removed by full commission consensus.")

#--IT Administration Helpers---

async def _execute_student_change(change_doc: dict):
    if change_doc["change_type"] == "add":
        phone = change_doc.get("phone", "")
        clean = re.sub(r'\D', '', phone)
        if clean.startswith('0'):
            clean = '256' + clean[1:]
        elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
            clean = '256' + clean
        await db.voters.update_one(
            {"student_id": change_doc["student_id"]},
            {"$set": {
                "full_name":       change_doc["full_name"],
                "phone_numbers":   [clean],
                "is_commissioner": False,
                "is_it_admin":     False,
                "has_voted":       False,
                "last_status":     "idle",
                "added_by_it":     True,
                "added_by":        change_doc.get("requested_by", "")
            }},
            upsert=True
        )
    elif change_doc["change_type"] == "remove":
        await db.voters.delete_one(
            get_forgiving_filter(change_doc["student_id"])
        )

async def _resolve_student_change(change_id: str, change_doc: dict):
    total = await get_commissioner_count()
    if total == 0:
        return
    votes = change_doc.get("votes", {})
    if len(votes) < total:
        return

    approve_count = sum(1 for v in votes.values() if v == "approve")
    deny_count    = sum(1 for v in votes.values() if v == "deny")

    if approve_count == total:
        await _execute_student_change(change_doc)
        await db.student_changes.update_one(
            {"_id": ObjectId(change_id)},
            {"$set": {"status": "approved", "resolved_at": datetime.utcnow()}}
        )
        await log_action("student_change_approved", "commission", {
            "change_type": change_doc["change_type"],
            "student_id":  change_doc["student_id"],
            "requested_by": change_doc.get("requested_by", "")
        })
    elif deny_count > 0:
        await db.student_changes.update_one(
            {"_id": ObjectId(change_id)},
            {"$set": {"status": "denied", "resolved_at": datetime.utcnow()}}
        )
        await log_action("student_change_denied", "commission", {
            "change_type": change_doc["change_type"],
            "student_id":  change_doc["student_id"],
            "requested_by": change_doc.get("requested_by", "")
        })

async def log_action(action: str, actor: str, details: dict = {}):
    await db.audit_log.insert_one({
        "action":    action,
        "actor":     actor,
        "details":   details,
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
async def get_status():
    status_doc = await db.settings.find_one({"name": "election_config"})
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
async def verify_identity(data: IdentityCheck):
    now = datetime.utcnow()
    status_doc = await db.settings.find_one({"name": "election_config"})

    if status_doc:
        if not status_doc.get("is_open", True):
            raise HTTPException(status_code=403, detail="Election is closed.")
        start, end = status_doc.get("start_time"), status_doc.get("end_time")
        if start and end and not (start <= now <= end):
            raise HTTPException(status_code=403, detail="Not within scheduled time.")

    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(status_code=404, detail="Student ID not found")

    otp_count = student.get("otp_count", 0)
    if otp_count >= 2:
        raise HTTPException(
            status_code=403,
            detail="Too many attempts. Please check the official register for your details."
        )

    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Already voted")

    reg_name    = student.get("full_name", "").strip().lower()
    input_name  = data.full_name.strip().lower()
    reg_parts   = set(reg_name.split())
    input_parts = set(input_name.split())
    common_parts = reg_parts.intersection(input_parts)
    match_threshold = 2 if len(reg_parts) >= 2 else 1

    if len(common_parts) < match_threshold:
        logger.warning(f"Name Match Fail: Reg({reg_name}) vs Input({input_name})")
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
    branding_doc = await db.settings.find_one({"name": "branding"})
    sms_org_name = (branding_doc or {}).get("org_name", "Election")
    
    message = (
        f"Hello {first_name}, your {sms_org_name} voting code is {otp}. "
        f"Your vote is secret. Do not share this code with anyone. Your voice, your power!"
    )

    if await send_sms_via_egosms(raw_phone, message):
        await db.voters.update_one(
            {"student_id": student["student_id"]},
            {"$set": {"last_status": "otp_sent"}, "$inc": {"otp_count": 1}}
        )
        await db.otps.update_one(
            {"student_id": student["student_id"]},
            {"$set": {"code": otp, "created_at": now}},
            upsert=True
        )
        return {"status": "success", "phone": f"{raw_phone[:6]}****{raw_phone[-2:]}"}

    raise HTTPException(status_code=500, detail="SMS Delivery Failed")


@app.post("/verify-otp")
async def verify_otp(data: OTPCheck):
    search = get_forgiving_filter(data.student_id)
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
async def cast_vote(data: VoteRequest):
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student or student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Ineligible voter")
    await db.voters.update_one({"_id": student["_id"]}, {"$set": {"has_voted": True, "last_status": "completed"}})
    await db.candidates.update_one({"_id": ObjectId(data.candidate_id)}, {"$inc": {"votes": 1}})
    return {"status": "success"}


@app.post("/vote-bulk")
async def cast_bulk_vote(data: BulkVoteRequest):
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(status_code=404, detail="Voter not found")
    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="You have already cast your vote.")

    await db.voters.update_one(
        {"_id": student["_id"]},
        {"$set": {"has_voted": True, "last_status": "completed"}}
    )

    for c_id in data.candidate_ids:
        try:
            await db.candidates.update_one({"_id": ObjectId(c_id)}, {"$inc": {"votes": 1}})
        except Exception:
            continue

    return {"status": "success", "message": "Ballot cast successfully"}


@app.get("/candidates")
async def get_candidates():
    candidates = []
    async for cand in db.candidates.find({}).sort("order", 1):
        cand["_id"] = str(cand["_id"])
        candidates.append(cand)
    return candidates

# =============================================================================
# PUBLIC ROUTES
# =============================================================================

@app.get("/positions")
async def get_positions():
    positions = []
    async for p in db.positions.find({}).sort("order", 1):
        p["_id"] = str(p["_id"])
        positions.append(p)
    return positions

@app.post("/apply")
async def submit_application(data: ApplicationSubmit):
    existing = await db.applications.find_one({
        "student_id": data.student_id,
        "position_id": data.position_id
    })
    if existing:
        raise HTTPException(400, "You have already applied for this position.")

    await db.applications.insert_one({
        **data.dict(),
        "status": "pending",
        "votes": {},          # { commissioner_student_id: "approve" | "deny" }
        "removal_votes": {},  # same structure, used after approval
        "submitted_at": datetime.utcnow()
    })
    await log_action("application_submitted", data.student_id, {
    "position_id": data.position_id,
    "full_name":   data.full_name
    })
    return {"status": "submitted"}

# =============================================================================
# ADMIN ROUTES  (election control — accessible to both superadmin & commission)
# =============================================================================

@app.post("/verify-admin")
async def verify_admin(data: AdminLoginCheck):
    # ── Superadmin ── (env var based, no hashing needed — this is you)
    if data.email == SUPER_ADMIN_ID and data.password == SUPER_ADMIN_NAME:
        return {
            "status": "success",
            "bypass": True,
            "role": "superadmin",
            "message": "Superadmin bypass active."
        }

    # ── IT Admin ──
    it_admin = await db.voters.find_one({
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    })
    if it_admin:
        stored_hash = it_admin.get("it_admin_password_hash", "")
        if not verify_password(data.password, stored_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        await log_action("it_admin_login", it_admin["student_id"], {"email": data.email})
        return {
            "status":              "success",
            "bypass":              True,
            "role":                "it_admin",
            "it_admin_id":         it_admin["student_id"],
            "full_name":           it_admin.get("full_name", ""),
            "must_change_password": it_admin.get("it_admin_must_change_password", True)
        }

    # ── Commissioner ──
    commissioner = await db.voters.find_one({
        "commissioner_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_commissioner": True
    })
    if not commissioner:
        raise HTTPException(status_code=404, detail="Invalid email or password.")

    stored_hash = commissioner.get("commissioner_password_hash", "")
    if not verify_password(data.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await log_action("commissioner_login", commissioner["student_id"], {"email": data.email})
    return {
        "status":              "success",
        "bypass":              True,
        "role":                "commission",
        "commissioner_id":     commissioner["student_id"],
        "full_name":           commissioner.get("full_name", ""),
        "must_change_password": commissioner.get("commissioner_must_change_password", True)
    }


@app.post("/admin/toggle-election")
async def toggle_election():
    current    = await db.settings.find_one({"name": "election_config"})
    new_status = not (current.get("is_open", True) if current else True)
    await db.settings.update_one(
        {"name": "election_config"},
        {"$set": {"is_open": new_status}},
        upsert=True
    )
    await log_action("election_toggled", "superadmin", {"is_open": new_status})
    logger.info(f" Election toggled to: {'OPEN' if new_status else 'CLOSED'}")
    return {"is_open": new_status}


@app.post("/admin/schedule-election")
async def schedule_election(data: ElectionSchedule):
    await db.settings.update_one(
        {"name": "election_config"},
        {"$set": {"start_time": data.start, "end_time": data.end, "is_open": True}},
        upsert=True
    )
    return {"status": "scheduled"}


@app.post("/admin/clear-schedule")
async def clear_schedule():
    await db.settings.update_one(
        {"name": "election_config"},
        {"$unset": {"start_time": "", "end_time": ""}}
    )
    return {"status": "cleared"}


@app.post("/admin/reset-election")
async def reset_election():
    await db.otps.delete_many({})
    await db.voters.update_many({}, {"$set": {"has_voted": False, "last_status": "idle"}})
    await db.candidates.update_many({}, {"$set": {"votes": 0}})
    return {"status": "success"}


@app.post("/admin/toggle-certification")
async def toggle_certification():
    current    = await db.settings.find_one({"name": "election_config"})
    new_status = not (current.get("is_certified", False) if current else False)
    await db.settings.update_one(
        {"name": "election_config"},
        {"$set": {"is_certified": new_status}},
        upsert=True
    )
    await log_action("results_certified", "superadmin", {"is_certified": new_status})
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
async def import_voters(file: UploadFile = File(...)):
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
                {"student_id": sid},
                {"$set": {
                    "full_name":       name,
                    "phone_numbers":   formatted_numbers,
                    "is_commissioner": False,
                    "has_voted":       False,
                    "last_active":     None,
                    "last_status":     "idle",
                    "updated_at":      now
                }},
                upsert=True
            )
            count += 1
    await log_action("voters_imported", "admin", {"count": count})
    return {"status": "success", "imported_count": count}

@app.get("/admin/voters")
async def get_all_voters():
    voters = []
    async for v in db.voters.find({}, {"_id": 0}):
        voters.append(v)
    return voters

@app.post("/admin/set-password")
async def set_new_password(data: SetNewPassword):
    # Try IT admin first
    it_admin = await db.voters.find_one({
        "it_admin_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_it_admin": True
    })
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
        await log_action("it_admin_password_changed", it_admin["student_id"], {})
        return {"status": "password_updated"}

    # Try commissioner
    commissioner = await db.voters.find_one({
        "commissioner_email": {"$regex": f"^{re.escape(data.email)}$", "$options": "i"},
        "is_commissioner": True
    })
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
        await log_action("commissioner_password_changed", commissioner["student_id"], {})
        return {"status": "password_updated"}

    raise HTTPException(404, "Account not found.")

# --- Candidates (superadmin can add/edit/delete freely; commission does not touch these) ---

@app.post("/candidates")
async def add_candidate(candidate: CandidateCreate):
    result = await db.candidates.insert_one(candidate.dict())
    await log_action("candidate_added", "superadmin", {
        "name": candidate.name, "position": candidate.position
    })
    return {"id": str(result.inserted_id)}


@app.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, data: dict):
    upd = {
        "name":     data.get("name"),
        "position": data.get("position"),
        "order":    int(data.get("order", 0))
    }
    if data.get("image_url"):
        upd["image_url"] = data["image_url"]
    await db.candidates.update_one({"_id": ObjectId(candidate_id)}, {"$set": upd})
    return {"status": "success"}


@app.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str):
    await db.candidates.delete_one({"_id": ObjectId(candidate_id)})
    return {"status": "deleted"}


# --- Applications list (shared: both superadmin and commission can read) ---

@app.get("/admin/applications")
async def list_applications(status: str = None):
    query = {}
    if status:
        query["status"] = status
    apps = []
    async for a in db.applications.find(query).sort("submitted_at", -1):
        a["_id"] = str(a["_id"])
        if a.get("position_id"):
            try:
                pos = await db.positions.find_one({"_id": ObjectId(a["position_id"])})
                a["position_title"] = pos["title"] if pos else a.get("position_id", "")
            except Exception:
                a["position_title"] = a.get("position_id", "")
        apps.append(a)
    return apps


# =============================================================================
# COMMISSION ROUTES  (voting — requires commission login)
# =============================================================================

@app.post("/admin/applications/{app_id}/vote")
async def commissioner_vote(app_id: str, data: CommissionerVote):
    """A commissioner casts their approve/deny vote on a pending application."""
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' or 'deny'.")

    app_doc = await db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("approved", "denied", "removed"):
        raise HTTPException(400, "This application is already resolved.")

    # Verify the voter exists and is actually a commissioner
    commissioner = await db.voters.find_one({
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    })
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    # Record vote (keyed by commissioner_id so they can only vote once per application)
    await db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {f"votes.{data.commissioner_id.replace('.', '_').replace('/', '_')}": data.vote}}
    )

    updated = await db.applications.find_one({"_id": ObjectId(app_id)})
    await _resolve_application(app_id, updated)

    return {"status": "vote_recorded"}


@app.post("/admin/applications/{app_id}/vote-remove")
async def commissioner_vote_remove(app_id: str, data: CommissionerVote):
    """A commissioner votes to remove an already-approved candidate."""
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' (remove) or 'deny' (keep).")

    app_doc = await db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") != "approved":
        raise HTTPException(400, "Can only vote to remove an approved candidate.")

    commissioner = await db.voters.find_one({
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    })
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    safe_key = data.commissioner_id.replace('.', '_').replace('/', '_')
    await db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {f"removal_votes.{safe_key}": data.vote}}
    )

    updated = await db.applications.find_one({"_id": ObjectId(app_id)})
    await _resolve_removal(app_id, updated)

    return {"status": "removal_vote_recorded"}


# =============================================================================
# SUPERADMIN ROUTES  (instant overrides — no voting required)
# =============================================================================

# --- Branding ---

@app.get("/superadmin/branding")
async def get_branding():
    doc = await db.settings.find_one({"name": "branding"})
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
async def save_branding(data: BrandingUpdate):
    await db.settings.update_one(
        {"name": "branding"},
        {"$set": {**data.dict(), "name": "branding"}},
        upsert=True
    )
    return {"status": "saved"}


# --- Positions ---

@app.post("/positions")
async def add_position(data: PositionCreate):
    result = await db.positions.insert_one(data.dict())
    return {"id": str(result.inserted_id)}


@app.delete("/positions/{position_id}")
async def delete_position(position_id: str):
    await db.positions.delete_one({"_id": ObjectId(position_id)})
    return {"status": "deleted"}


# --- Commissioner management ---

@app.get("/superadmin/commissioners")
async def list_commissioners():
    result = []
    async for v in db.voters.find(
        {"is_commissioner": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "is_chief_commissioner": 1, "commissioner_role": 1, "commissioner_email": 1}
    ):
        result.append(v)
    return result
    
@app.post("/superadmin/commissioners/{student_id:path}/set-chief")
async def set_chief_commissioner(student_id: str):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    if not voter.get("is_commissioner"):
        raise HTTPException(400, "This person is not a commissioner.")
    await db.voters.update_many({}, {"$set": {"is_chief_commissioner": False}})
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_chief_commissioner": True}}
    )
    return {"student_id": student_id, "is_chief_commissioner": True}


@app.post("/superadmin/commissioners/{student_id:path}/clear-chief")
async def clear_chief_commissioner(student_id: str):
    await db.voters.update_one(
        get_forgiving_filter(student_id),
        {"$set": {"is_chief_commissioner": False}}
    )
    return {"student_id": student_id, "is_chief_commissioner": False}


@app.get("/superadmin/chief-commissioner")
async def get_chief_commissioner():
    chief = await db.voters.find_one(
        {"is_chief_commissioner": True},
        {"_id": 0, "student_id": 1, "full_name": 1}
    )
    if not chief:
        return {"full_name": None}
    return chief


@app.post("/superadmin/commissioners/{student_id:path}/set-role")
async def set_commissioner_role(student_id: str, data: CommissionerRoleUpdate):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
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
    })
    return {"student_id": student_id, "commissioner_role": data.role_label}

@app.post("/superadmin/commissioners/{student_id:path}/toggle")
async def toggle_commissioner(student_id: str):
    """Grant or revoke commissioner status for any voter."""
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_commissioner", False)
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_commissioner": new_val}}
    )
    await log_action("commissioner_toggled", "superadmin", {
    "student_id": student_id, "is_commissioner": new_val
    })
    return {"student_id": student_id, "is_commissioner": new_val}

@app.post("/superadmin/it-admins/{student_id:path}/set-credentials")
async def set_it_admin_credentials(student_id: str, data: SetEmailOnly):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
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
    })
    return {"status": "credentials_set", "sms_notified": sms_sent}
    
# --- Application overrides ---

@app.post("/superadmin/applications/{app_id}/force-approve")
async def superadmin_force_approve(app_id: str):
    """Approve an application instantly, bypassing commission voting."""
    app_doc = await db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") == "approved":
        raise HTTPException(400, "Already approved.")

    await _create_candidate_from_application(app_doc)
    await db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {
            "status": "approved",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        }}
    )
    await log_action("application_force_approved", "superadmin", {"app_id": app_id})
    logger.info(f" Superadmin force-approved application {app_id}.")
    return {"status": "force_approved"}


@app.post("/superadmin/applications/{app_id}/force-deny")
async def superadmin_force_deny(app_id: str):
    """Deny an application instantly, bypassing commission voting."""
    app_doc = await db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc:
        raise HTTPException(404, "Application not found.")
    if app_doc.get("status") in ("denied", "removed"):
        raise HTTPException(400, "Application is already denied or removed.")

    await db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {
            "status": "denied",
            "superadmin_override": True,
            "decided_at": datetime.utcnow()
        }}
    )
    await log_action("application_force_denied", "superadmin", {"app_id": app_id})
    logger.info(f" Superadmin force-denied application {app_id}.")
    return {"status": "force_denied"}


@app.post("/superadmin/candidates/{candidate_id}/remove")
async def superadmin_remove_candidate(candidate_id: str):
    """Remove an approved candidate from the ballot instantly."""
    cand = await db.candidates.find_one({"_id": ObjectId(candidate_id)})
    if not cand:
        raise HTTPException(404, "Candidate not found.")

    await db.candidates.delete_one({"_id": ObjectId(candidate_id)})
    await log_action("candidate_removed", "superadmin", {
    "name": cand.get("name"), "position": cand.get("position")
    })
    
    # If the candidate came from an application, mark it removed
    if cand.get("application_id"):
        await db.applications.update_one(
            {"_id": ObjectId(cand["application_id"])},
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
async def get_election_results():
    voter_turnout = await db.voters.count_documents({"has_voted": True})
    results = []
    async for cand in db.candidates.find({}).sort("order", 1):
        results.append({
            "id":       str(cand["_id"]),
            "name":     cand["name"],
            "position": cand["position"],
            "votes":    cand.get("votes", 0),
            "order":    cand.get("order", 0)
        })
    return {"voter_turnout": voter_turnout, "results": results}


# =============================================================================
# IT ADMIN ROUTES
# =============================================================================

@app.post("/it-admin/students/request-add")
async def request_add_student(data: ITAdminStudentAdd):
    # Prevent duplicate pending requests for same student
    existing = await db.student_changes.find_one({
        "student_id":  data.student_id,
        "change_type": "add",
        "status":      "pending"
    })
    if existing:
        raise HTTPException(400, "A pending add request already exists for this student.")

    result = await db.student_changes.insert_one({
        **data.dict(),
        "change_type":  "add",
        "status":       "pending",
        "votes":        {},
        "requested_at": datetime.utcnow()
    })
    await log_action("student_add_requested", data.requested_by, {
        "student_id": data.student_id,
        "full_name":  data.full_name,
        "reason":     data.reason
    })
    return {"status": "requested", "id": str(result.inserted_id)}

@app.post("/superadmin/it-admins/{student_id:path}/reset-password")
async def reset_it_admin_password(student_id: str):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
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
    })
    return {"status": "password_reset", "sms_notified": sms_sent}


@app.post("/superadmin/commissioners/{student_id:path}/reset-password")
async def reset_commissioner_password(student_id: str):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
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
    })
    return {"status": "password_reset", "sms_notified": sms_sent}

@app.post("/it-admin/students/request-remove")
async def request_remove_student(data: ITAdminStudentRemove):
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(404, "Student not found in voter register.")

    existing = await db.student_changes.find_one({
        "student_id":  data.student_id,
        "change_type": "remove",
        "status":      "pending"
    })
    if existing:
        raise HTTPException(400, "A pending removal request already exists for this student.")

    result = await db.student_changes.insert_one({
        **data.dict(),
        "full_name":    student.get("full_name", ""),
        "change_type":  "remove",
        "status":       "pending",
        "votes":        {},
        "requested_at": datetime.utcnow()
    })
    await log_action("student_remove_requested", data.requested_by, {
        "student_id": data.student_id,
        "full_name":  student.get("full_name", ""),
        "reason":     data.reason
    })
    return {"status": "requested", "id": str(result.inserted_id)}


@app.post("/it-admin/students/requests/{change_id}/cancel")
async def cancel_student_change(change_id: str, data: StudentChangeCancelRequest):
    change = await db.student_changes.find_one({"_id": ObjectId(change_id)})
    if not change:
        raise HTTPException(404, "Request not found.")
    if change.get("requested_by") != data.requested_by:
        raise HTTPException(403, "You can only cancel your own requests.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"Cannot cancel a request that is already {change.get('status')}.")

    await db.student_changes.update_one(
        {"_id": ObjectId(change_id)},
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
    })
    return {"status": "cancelled"}


@app.get("/it-admin/students/my-requests/{it_admin_id}")
async def get_my_requests(it_admin_id: str):
    changes = []
    async for c in db.student_changes.find(
        {"requested_by": it_admin_id}
    ).sort("requested_at", -1):
        c["_id"] = str(c["_id"])
        changes.append(c)
    return changes


# =============================================================================
# COMMISSION — STUDENT CHANGES
# =============================================================================

@app.get("/admin/student-changes")
async def list_student_changes(status: str = None):
    query = {}
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


@app.post("/admin/student-changes/{change_id}/vote")
async def vote_student_change(change_id: str, data: StudentChangeVote):
    if data.vote not in ("approve", "deny"):
        raise HTTPException(400, "vote must be 'approve' or 'deny'.")

    change = await db.student_changes.find_one({"_id": ObjectId(change_id)})
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") != "pending":
        raise HTTPException(400, f"This request is already {change.get('status')}.")

    commissioner = await db.voters.find_one({
        **get_forgiving_filter(data.commissioner_id),
        "is_commissioner": True
    })
    if not commissioner:
        raise HTTPException(403, "Not a registered commissioner.")

    safe_key = data.commissioner_id.replace('.', '_').replace('/', '_')
    await db.student_changes.update_one(
        {"_id": ObjectId(change_id)},
        {"$set": {f"votes.{safe_key}": data.vote}}
    )

    updated = await db.student_changes.find_one({"_id": ObjectId(change_id)})
    await _resolve_student_change(change_id, updated)
    return {"status": "vote_recorded"}


# =============================================================================
# SUPERADMIN — IT ADMIN MANAGEMENT + STUDENT CHANGE OVERRIDES
# =============================================================================

@app.get("/superadmin/it-admins")
async def list_it_admins():
    result = []
    async for v in db.voters.find(
        {"is_it_admin": True},
        {"_id": 0, "student_id": 1, "full_name": 1, "it_admin_email": 1}
    ):
        result.append(v)
    return result


@app.post("/superadmin/it-admins/{student_id:path}/toggle")
async def toggle_it_admin(student_id: str):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
    if not voter:
        raise HTTPException(404, "Voter not found.")
    new_val = not voter.get("is_it_admin", False)
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_it_admin": new_val}}
    )
    await log_action("it_admin_toggled", "superadmin", {
        "student_id": student_id, "is_it_admin": new_val
    })
    return {"student_id": student_id, "is_it_admin": new_val}


@app.post("/superadmin/commissioners/{student_id:path}/set-credentials")
async def set_commissioner_credentials(student_id: str, data: SetEmailOnly):
    voter = await db.voters.find_one(get_forgiving_filter(student_id))
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
    })
    return {"status": "credentials_set", "sms_notified": sms_sent}


@app.get("/superadmin/student-changes")
async def superadmin_list_student_changes(status: str = None):
    # Superadmin sees ALL including cancelled
    query = {}
    if status:
        query["status"] = status
    changes = []
    async for c in db.student_changes.find(query).sort("requested_at", -1):
        c["_id"] = str(c["_id"])
        changes.append(c)
    return changes


@app.post("/superadmin/student-changes/{change_id}/force-approve")
async def superadmin_force_student_change_approve(change_id: str):
    change = await db.student_changes.find_one({"_id": ObjectId(change_id)})
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("approved", "force_approved"):
        raise HTTPException(400, "Already approved.")
    if change.get("status") == "cancelled":
        raise HTTPException(400, "Cannot approve a cancelled request.")

    await _execute_student_change(change)
    await db.student_changes.update_one(
        {"_id": ObjectId(change_id)},
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
    })
    return {"status": "force_approved"}


@app.post("/superadmin/student-changes/{change_id}/force-deny")
async def superadmin_force_student_change_deny(change_id: str):
    change = await db.student_changes.find_one({"_id": ObjectId(change_id)})
    if not change:
        raise HTTPException(404, "Change request not found.")
    if change.get("status") in ("denied", "force_denied", "cancelled"):
        raise HTTPException(400, f"Request is already {change.get('status')}.")

    await db.student_changes.update_one(
        {"_id": ObjectId(change_id)},
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
    })
    return {"status": "force_denied"}


@app.post("/superadmin/students/add")
async def superadmin_add_student(data: ITAdminStudentAdd):
    phone = data.phone
    clean = re.sub(r'\D', '', phone)
    if clean.startswith('0'):
        clean = '256' + clean[1:]
    elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
        clean = '256' + clean
    await db.voters.update_one(
        {"student_id": data.student_id},
        {"$set": {
            "full_name":       data.full_name,
            "phone_numbers":   [clean],
            "is_commissioner": False,
            "is_it_admin":     False,
            "has_voted":       False,
            "last_status":     "idle",
            "added_by":        "superadmin",
            "add_reason":      data.reason
        }},
        upsert=True
    )
    await log_action("student_added_by_superadmin", "superadmin", {
        "student_id": data.student_id,
        "full_name":  data.full_name,
        "reason":     data.reason
    })
    return {"status": "added"}


@app.post("/superadmin/students/remove")
async def superadmin_remove_student(data: ITAdminStudentRemove):
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(404, "Student not found.")
    await db.voters.delete_one(get_forgiving_filter(data.student_id))
    await log_action("student_removed_by_superadmin", "superadmin", {
        "student_id": data.student_id,
        "full_name":  student.get("full_name", ""),
        "reason":     data.reason
    })
    return {"status": "removed"}


# =============================================================================
# AUDIT LOG
# =============================================================================

@app.get("/superadmin/audit-log")
async def get_audit_log(limit: int = 200, action: str = None):
    query = {}
    if action:
        query["action"] = {"$regex": action, "$options": "i"}
    logs = []
    async for entry in db.audit_log.find(query).sort("timestamp", -1).limit(limit):
        entry["_id"] = str(entry["_id"])
        logs.append(entry)
    return logs
