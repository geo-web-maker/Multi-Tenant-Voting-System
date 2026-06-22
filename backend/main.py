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

app = FastAPI(title="BallotBox Master API")

# --- CONFIGURATION & SECRETS ---
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
EGOSMS_USER = os.getenv("EGOSMS_USERNAME")
EGOSMS_PASS = os.getenv("EGOSMS_PASSWORD")
EGOSMS_SENDER_ID = os.getenv("ESMS_SENDER_ID", "SMS").strip() 

MASTER_ADMIN_ID = os.getenv("MASTER_ADMIN_ID", "geo_web@yahoo.com")
MASTER_ADMIN_NAME = os.getenv("MASTER_ADMIN_NAME", "dorothygeorge@QWE25")

# --- MONGODB CONNECTION SETTINGS ---
# We limit the pool size so 600 users don't overwhelm your DB tier.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: client is already initialized, but we can verify it here
    yield
    # Shutdown: This is the 'Magic' for Railway Sleeping
    # It explicitly closes the pool so MongoDB knows the connections are free.
    client.close()

app = FastAPI(title="BallotBox Master API", lifespan=lifespan)

# Add pool limits to your MONGO_URL logic
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
# maxPoolSize=10 ensures a single Railway instance doesn't hog connections
client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URL, 
    maxPoolSize=20, 
    minPoolSize=1, 
    waitQueueTimeoutMS=2500
)
db = client["election-db"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELS ---
class ApplicationDecision(BaseModel):
    decision: str   # "approved" or "denied"
    reason: str = ""
    
class ApplicationSubmit(BaseModel):
    student_id: str
    full_name: str
    position_id: str
    manifesto: str = ""
    image_url: str = ""
    
class IdentityCheck(BaseModel):
    student_id: str
    full_name: str
    phone_index: int | None = None 

class CandidateCreate(BaseModel):
    name: str
    position: str
    image_url: str
    order: int = 0

class OTPCheck(BaseModel):
    student_id: str
    code: str

class VoteRequest(BaseModel):
    student_id: str
    candidate_id: str 

class AdminIdentityCheck(BaseModel):
    student_id: str
    full_name: str
    phone_index: int | None = None

class ElectionSchedule(BaseModel):
    start: datetime
    end: datetime

class AdminTestSMS(BaseModel):
    phone: str

class BulkVoteRequest(BaseModel):
    student_id: str
    candidate_ids: list[str]

# --- HELPER FUNCTIONS ---
def get_forgiving_filter(student_id: str):
    # Removes all internal spaces (e.g., "24 / U / 101" -> "24/U/101")
    clean_id = student_id.replace(" ", "").strip()
    return {
        "student_id": {
            "$regex": f'^"?{re.escape(clean_id)}"?$', 
            "$options": "i"
        }
    }

async def send_sms_via_egosms(to_number: str, message_text: str):
    """Integrated with the EgoSMS Plain GET API provided"""
    try:
        # Standardize number: EgoSMS prefers 256... without the '+'
        clean_number = to_number.replace("+", "").strip()
        
        # These are the 5 'Keys' from the URL they gave you
        params = {
            "username": EGOSMS_USER,
            "password": EGOSMS_PASS,
            "number": clean_number,
            "message": message_text,
            "sender": EGOSMS_SENDER_ID
        }
        
        async with httpx.AsyncClient() as client:
            # This is the 'Base URL' before the question mark
            url = "https://comms.egosms.co/api/v1/plain/"
            
            # This sends the request exactly like the link you provided
            response = await client.get(url, params=params, timeout=15.0)
            
            resp_text = response.text.strip()
            logger.info(f"📡 EgoSMS Result: {resp_text}")
            
            if "OK" in resp_text.upper():
                return True
            return False
            
    except Exception as e:
        logger.error(f"❌ Connection Error: {e}")
        return False

# ── Superadmin: branding ──
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

# ── Superadmin: positions ──
class PositionCreate(BaseModel):
    title: str
    description: str = ""
    order: int = 0

@app.get("/positions")
async def get_positions():
    positions = []
    async for p in db.positions.find({}).sort("order", 1):
        p["_id"] = str(p["_id"])
        positions.append(p)
    return positions

@app.post("/positions")
async def add_position(data: PositionCreate):
    result = await db.positions.insert_one(data.dict())
    return {"id": str(result.inserted_id)}

@app.delete("/positions/{position_id}")
async def delete_position(position_id: str):
    await db.positions.delete_one({"_id": ObjectId(position_id)})
    return {"status": "deleted"}
    
# --- SYSTEM & HEALTH ---
@app.get("/")
def read_root():
    return {"status": "Online", "sms_provider": "EgoSMS"}

@app.get("/health")
async def health_check():
    try:
        #-- await client.admin.command('ping')
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
        "is_certified": status_doc.get("is_certified", False), # <--- ADD THIS LINE
        "start": status_doc.get("start_time"),
        "end": status_doc.get("end_time")
    }

# --- VOTER ROUTES ---
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

    # Uses the updated space-agnostic filter
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    
    if not student:
        raise HTTPException(status_code=404, detail="Student ID not found")

    # --- NEW: LOCKOUT CHECK ---
    # If the user has requested too many OTPs, block them.
    # You can set the limit (e.g., 3) and lockout duration (e.g., 2099 for permanent)
    otp_count = student.get("otp_count", 0)
    if otp_count >= 2:
        raise HTTPException(
            status_code=403, 
            detail="Too many attempts. Please check the official register for your details."
        )
    # -------------------------

    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Already voted")

    # --- FUZZY NAME MATCHING LOGIC ---
    reg_name = student.get("full_name", "").strip().lower()
    input_name = data.full_name.strip().lower()
    reg_parts = set(reg_name.split())
    input_parts = set(input_name.split())
    common_parts = reg_parts.intersection(input_parts)
    match_threshold = 2 if len(reg_parts) >= 2 else 1
    
    if len(common_parts) < match_threshold:
        logger.warning(f"Name Match Fail: Reg({reg_name}) vs Input({input_name})")
        raise HTTPException(status_code=400, detail="Name mismatch. Please provide your full registered names.")
    # ---------------------------------

    phone_list = student.get("phone_numbers", [])
    if not phone_list:
        raise HTTPException(status_code=400, detail="No phone found.")

    if len(phone_list) > 1 and data.phone_index is None:
        return {"status": "needs_selection", "masked_numbers": [f"{p[:6]}****{p[-2:]}" for p in phone_list]}

    idx = data.phone_index if data.phone_index is not None else 0
    raw_phone = phone_list[idx]
    otp = str(random.randint(100000, 999999))

    # --- NEW PERSONALIZATION LOGIC ---
    db_name = student.get("full_name", "Voter")
    first_name = db_name.split()[0].capitalize() 

    message = f"Hello {first_name}, your KYUCCU 2026 voting code is {otp}. Your vote is secret. Do not share this code with anyone. Your voice, your power!"
    # ---------------------------------
    
    if await send_sms_via_egosms(raw_phone, message):
        # --- NEW: INCREMENT OTP COUNT ON SUCCESSFUL SEND ---
        await db.voters.update_one(
            {"student_id": student["student_id"]}, 
            {
                "$set": {"last_status": "otp_sent"},
                "$inc": {"otp_count": 1}  # Adds 1 to the count every time an SMS is sent
            }
        )
        # ---------------------------------------------------
        await db.otps.update_one({"student_id": student["student_id"]}, {"$set": {"code": otp, "created_at": now}}, upsert=True)
        return {"status": "success", "phone": f"{raw_phone[:6]}****{raw_phone[-2:]}"}
    
    raise HTTPException(status_code=500, detail="SMS Delivery Failed")


@app.post("/verify-otp")
async def verify_otp(data: OTPCheck):
    search = get_forgiving_filter(data.student_id)
    voter = await db.voters.find_one(search)
    
    if not voter:
        raise HTTPException(status_code=404, detail="Voter not found")
        
    # --- FIX 1: Check existing count immediately ---
    record = await db.otps.find_one(search) or await db.admin_otps.find_one(search)
    
    # SUCCESS PATH
    if record and record["code"] == data.code:
        await db.voters.update_one(search, {
            "$set": {"last_status": "authenticated", "otp_count": 0} 
        })
        await db.otps.delete_one(search)
        return {"status": "success"}

   # FAILURE PATH: We do NOT increment otp_count here.
    # We simply tell the user it's wrong.
    raise HTTPException(
        status_code=400, 
        detail="Invalid OTP. Please check your messages and try again."
    )
    
@app.post("/vote")
async def cast_vote(data: VoteRequest):
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student or student.get("has_voted"):
        raise HTTPException(status_code=400, detail="Ineligible voter")
    await db.voters.update_one({"_id": student["_id"]}, {"$set": {"has_voted": True, "last_status": "completed"}})
    await db.candidates.update_one({"_id": ObjectId(data.candidate_id)}, {"$inc": {"votes": 1}})
    return {"status": "success"}

class BulkVoteRequest(BaseModel):
    student_id: str
    candidate_ids: list[str] # Matches your frontend's selectedIds

@app.post("/vote-bulk")
async def cast_bulk_vote(data: BulkVoteRequest):
    # 1. Identity Check
    student = await db.voters.find_one(get_forgiving_filter(data.student_id))
    if not student:
        raise HTTPException(status_code=404, detail="Voter not found")
    if student.get("has_voted"):
        raise HTTPException(status_code=400, detail="You have already cast your vote.")

    # 2. Atomic Update: Mark as voted immediately
    # This prevents the 'double-tab' exploit if a user clicks fast
    await db.voters.update_one(
        {"_id": student["_id"]}, 
        {"$set": {"has_voted": True, "last_status": "completed"}}
    )

    # 3. Increment votes for all selected candidates
    # Even if they only selected 1 out of 5 positions, this loop handles it.
    for c_id in data.candidate_ids:
        try:
            await db.candidates.update_one(
                {"_id": ObjectId(c_id)}, 
                {"$inc": {"votes": 1}}
            )
        except Exception:
            # Skip invalid IDs but continue the loop
            continue

    return {"status": "success", "message": "Ballot cast successfully"}


@app.get("/candidates")
async def get_candidates():
    candidates = []
    async for cand in db.candidates.find({}).sort("order", 1):
        cand["_id"] = str(cand["_id"])
        candidates.append(cand)
    return candidates

# --- ADMIN ROUTES ---
@app.post("/admin/toggle-election")
async def toggle_election():
    # 1. Look for the configuration document
    current = await db.settings.find_one({"name": "election_config"})
    
    # 2. If it doesn't exist, we assume it's currently "Open" and we want to close it
    # If it does exist, we flip the current 'is_open' boolean
    new_status = not (current.get("is_open", True) if current else True)
    
    # 3. Update the database
    await db.settings.update_one(
        {"name": "election_config"}, 
        {"$set": {"is_open": new_status}}, 
        upsert=True
    )
    
    logger.info(f"🗳️ Election toggled to: {'OPEN' if new_status else 'CLOSED'}")
    
    return {"is_open": new_status}

@app.post("/verify-admin")
async def verify_admin(data: AdminIdentityCheck):
    # 1. Master Admin Bypass (No OTP needed)
    if data.student_id == MASTER_ADMIN_ID and data.full_name == MASTER_ADMIN_NAME:
        return {
            "status": "success", 
            "message": "Master Admin Bypass Active",
            "bypass": True  # <--- Logic for Frontend to skip OTP
        }

    # 2. Regular Admin (Still needs OTP)
    admin = await db.voters.find_one({
        "student_id": {"$regex": f"^{re.escape(data.student_id)}$", "$options": "i"}, 
        "is_admin": True
    })
    
    if not admin:
        raise HTTPException(status_code=404, detail="Admin access denied")
    
    otp = str(random.randint(100000, 999999))
    if await send_sms_via_egosms(admin["phone_numbers"][0], f"Admin Auth Code: {otp}"):
        await db.admin_otps.update_one(
            {"student_id": data.student_id}, 
            {"$set": {"code": otp, "created_at": datetime.utcnow()}}, 
            upsert=True
        )
        return {"status": "success", "bypass": False}
    
    raise HTTPException(status_code=500, detail="SMS Error")
    
@app.get("/admin/sms-balance")
async def get_sms_balance():
    return {"balance": "Check EgoSMS Portal", "currency": "UGX"}

@app.post("/admin/schedule-election")
async def schedule_election(data: ElectionSchedule):
    await db.settings.update_one({"name": "election_config"}, {"$set": {"start_time": data.start, "end_time": data.end, "is_open": True}}, upsert=True)
    return {"status": "scheduled"}

@app.post("/admin/clear-schedule")
async def clear_schedule():
    await db.settings.update_one({"name": "election_config"}, {"$unset": {"start_time": "", "end_time": ""}})
    return {"status": "cleared"}

@app.post("/admin/reset-election")
async def reset_election():
    await db.otps.delete_many({})
    await db.voters.update_many({}, {"$set": {"has_voted": False, "last_status": "idle"}})
    await db.candidates.update_many({}, {"$set": {"votes": 0}})
    return {"status": "success"}

@app.post("/admin/toggle-certification")
async def toggle_certification():
    current = await db.settings.find_one({"name": "election_config"})
    # Default to False if not set
    new_status = not (current.get("is_certified", False) if current else False)
    
    await db.settings.update_one(
        {"name": "election_config"}, 
        {"$set": {"is_certified": new_status}}, 
        upsert=True
    )
    return {"is_certified": new_status}

@app.post("/admin/import-voters")
async def import_voters(file: UploadFile = File(...)):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    
    count = 0
    now = datetime.utcnow()

    for row in reader:
        sid = row.get('student_id', '').strip()
        name = row.get('full_name', '').strip()
        raw_phone_field = row.get('phone', '').strip()
        
        if sid and name:
            # 1. Split by slash in case there are multiple numbers
            # This handles "0705.../0771..."
            raw_numbers = raw_phone_field.split('/')
            formatted_numbers = []

            for num in raw_numbers:
                # Clean each number (remove non-digits)
                clean = re.sub(r'\D', '', num.strip())
                
                if not clean:
                    continue

                # Automatic 256 formatting
                if clean.startswith('0'):
                    clean = '256' + clean[1:]
                elif len(clean) == 9 and (clean.startswith('7') or clean.startswith('4')):
                    clean = '256' + clean
                
                # Avoid adding duplicates if the same number is listed twice
                if clean not in formatted_numbers:
                    formatted_numbers.append(clean)

            # 2. Save using your required schema
            await db.voters.update_one(
                {"student_id": sid}, 
                {"$set": {
                    "full_name": name, 
                    "phone_numbers": formatted_numbers, # Array of cleaned numbers
                    "is_admin": False,
                    "has_voted": False,
                    "last_active": None,
                    "last_status": "idle",
                    "updated_at": now
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

@app.post("/admin/test-connection")
async def test_egosms_connection(data: AdminTestSMS):
    """Admin tool to verify EgoSMS credentials and route"""
    # 1. Trigger the SMS
    success = await send_sms_via_egosms(data.phone, "EgoSMS Connection Verified for BallotBox!")
    
    # 2. Return a proper FastAPI response based on the result
    if success:
        return {
            "status": "success", 
            "message": f"Test message delivered to {data.phone}"
        }
    else:
        # If it failed, we throw a 400 error instead of a 500 crash
        raise HTTPException(
            status_code=400, 
            detail="EgoSMS rejected the request. Check Railway logs for the reason."
        )

@app.post("/candidates")
async def add_candidate(candidate: CandidateCreate):
    result = await db.candidates.insert_one(candidate.dict())
    return {"id": str(result.inserted_id)}

@app.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, data: dict):
    upd = {"name": data.get("name"), "position": data.get("position"), "order": int(data.get("order", 0))}
    if data.get("image_url"): upd["image_url"] = data["image_url"]
    await db.candidates.update_one({"_id": ObjectId(candidate_id)}, {"$set": upd})
    return {"status": "success"}

@app.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str):
    await db.candidates.delete_one({"_id": ObjectId(candidate_id)})
    return {"status": "deleted"}

@app.get("/election-results")
async def get_election_results():
    # 1. Calculate turnout
    voter_turnout = await db.voters.count_documents({"has_voted": True})
    
    # 2. Fetch candidates sorted by 'order' (the priority set in your dashboard)
    results = []
    async for cand in db.candidates.find({}).sort("order", 1):
        results.append({
            "id": str(cand["_id"]),
            "name": cand["name"],
            "position": cand["position"],
            "votes": cand.get("votes", 0),
            "order": cand.get("order", 0) # Keep the order value for the frontend
        })
        
    return {
        "voter_turnout": voter_turnout,
        "results": results
    }

@app.post("/apply")
async def submit_application(data: ApplicationSubmit):
    # Block duplicate applications for the same position
    existing = await db.applications.find_one({
        "student_id": data.student_id,
        "position_id": data.position_id
    })
    if existing:
        raise HTTPException(400, "You have already applied for this position.")
    
    await db.applications.insert_one({
        **data.dict(),
        "status": "pending",
        "submitted_at": datetime.utcnow()
    })
    return {"status": "submitted"}

@app.get("/admin/applications")
async def list_applications(status: str = None):
    query = {}
    if status:
        query["status"] = status
    apps = []
    async for a in db.applications.find(query).sort("submitted_at", -1):
        a["_id"] = str(a["_id"])
        # Resolve position title
        if a.get("position_id"):
            pos = await db.positions.find_one({"_id": ObjectId(a["position_id"])})
            a["position_title"] = pos["title"] if pos else a.get("position_id", "")
        apps.append(a)
    return apps

@app.post("/admin/applications/{app_id}/decide")
async def decide_application(app_id: str, data: ApplicationDecision):
    app_doc = await db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc:
        raise HTTPException(404, "Application not found")
    
    await db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"status": data.decision, "decided_at": datetime.utcnow(), "reason": data.reason}}
    )
    
    # If approved → auto-create the candidate (shows on ballot immediately)
    if data.decision == "approved":
        pos = await db.positions.find_one({"_id": ObjectId(app_doc["position_id"])})
        await db.candidates.insert_one({
            "name": app_doc["full_name"],
            "position": pos["title"] if pos else app_doc.get("position_id", ""),
            "image_url": app_doc.get("image_url", ""),
            "order": pos.get("order", 0) if pos else 0,
            "votes": 0,
            "application_id": app_id
        })
    
    return {"status": data.decision}
