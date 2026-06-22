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
    logo_url: str
    primary_color: str
    accent_color: str

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
        logger.info(f"✅ Application {app_id} approved by full commission consensus.")
    elif deny_count > 0:
        # Any single deny blocks the application
        await db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"status": "denied"}}
        )
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

# =============================================================================
# SYSTEM & HEALTH
# =============================================================================

@app.get("/")
def read_root():
    return {"status": "Online", "sms_provider": "EgoSMS"}

@app.get("/health")
async def health_check():
    try:
        return {"status": "healthy", "database": "connected"}
    except Exception:
        raise HTTPException(status_code=500, detail="Database down")

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
    message    = (
        f"Hello {first_name}, your KYUCCU 2026 voting code is {otp}. "
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
    return {"status": "submitted"}

# =============================================================================
# ADMIN ROUTES  (election control — accessible to both superadmin & commission)
# =============================================================================

@app.post("/verify-admin")
async def verify_admin(data: AdminIdentityCheck):
    # ── Superadmin: instant bypass, no OTP ──
    if data.student_id == SUPER_ADMIN_ID and data.full_name == SUPER_ADMIN_NAME:
        return {
            "status": "success",
            "bypass": True,
            "role": "superadmin",
            "message": "Superadmin bypass active."
        }

    # ── Commission member: OTP required ──
    commissioner = await db.voters.find_one({
        "student_id": {"$regex": f"^{re.escape(data.student_id)}$", "$options": "i"},
        "is_commissioner": True
    })
    if not commissioner:
        raise HTTPException(status_code=404, detail="Admin access denied.")

    otp = str(random.randint(100000, 999999))
    if await send_sms_via_egosms(commissioner["phone_numbers"][0], f"Commission Auth Code: {otp}"):
        await db.admin_otps.update_one(
            {"student_id": data.student_id},
            {"$set": {"code": otp, "created_at": datetime.utcnow()}},
            upsert=True
        )
        return {"status": "success", "bypass": False, "role": "commission"}

    raise HTTPException(status_code=500, detail="SMS Error")


@app.post("/admin/toggle-election")
async def toggle_election():
    current    = await db.settings.find_one({"name": "election_config"})
    new_status = not (current.get("is_open", True) if current else True)
    await db.settings.update_one(
        {"name": "election_config"},
        {"$set": {"is_open": new_status}},
        upsert=True
    )
    logger.info(f"🗳️ Election toggled to: {'OPEN' if new_status else 'CLOSED'}")
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
        sid             = row.get('student_id', '').strip()
        name            = row.get('full_name', '').strip()
        raw_phone_field = row.get('phone', '').strip()

        if sid and name:
            raw_numbers      = raw_phone_field.split('/')
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
                    "is_commissioner": False,   # was is_admin
                    "has_voted":       False,
                    "last_active":     None,
                    "last_status":     "idle",
                    "updated_at":      now
                }},
                upsert=True
            )
            count += 1

    return {"status": "success", "imported_count": count}


@app.get("/admin/voters")
async def get_all_voters():
    voters = []
    async for v in db.voters.find({}, {"_id": 0}):
        voters.append(v)
    return voters


# --- Candidates (superadmin can add/edit/delete freely; commission does not touch these) ---

@app.post("/candidates")
async def add_candidate(candidate: CandidateCreate):
    result = await db.candidates.insert_one(candidate.dict())
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
        return {"logo_url": "", "primary_color": "#003366", "accent_color": "#f1c40f"}
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
        {"_id": 0, "student_id": 1, "full_name": 1}
    ):
        result.append(v)
    return result


@app.post("/superadmin/commissioners/{student_id}/toggle")
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
    return {"student_id": student_id, "is_commissioner": new_val}


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
    logger.info(f"⚡ Superadmin force-approved application {app_id}.")
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
    logger.info(f"⚡ Superadmin force-denied application {app_id}.")
    return {"status": "force_denied"}


@app.post("/superadmin/candidates/{candidate_id}/remove")
async def superadmin_remove_candidate(candidate_id: str):
    """Remove an approved candidate from the ballot instantly."""
    cand = await db.candidates.find_one({"_id": ObjectId(candidate_id)})
    if not cand:
        raise HTTPException(404, "Candidate not found.")

    await db.candidates.delete_one({"_id": ObjectId(candidate_id)})

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
