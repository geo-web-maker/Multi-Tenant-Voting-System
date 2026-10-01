"""
One-time migration: backfill org_id on all pre-multi-tenancy documents so the
current live election keeps working once VITE_ORG_SLUG is set on its frontend.

Run this AFTER creating the org (via Superadmin > Organizations, or
POST /superadmin/orgs) and BEFORE setting VITE_ORG_SLUG on the frontend deploy.

Usage:
    python migrate_assign_org.py <org_id>

<org_id> is the string _id returned when you created the organization
(same value org_query stamps into org_id — a string, not an ObjectId).
"""
import asyncio
import sys
import motor.motor_asyncio
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# Every collection org_query() is ever called against.
COLLECTIONS = [
    "voters", "candidates", "positions", "applications",
    "settings", "student_changes", "audit_log", "otps", "admin_otps",
]

async def main(org_id: str):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client["electiondbaccounting"]

    print(f"Backfilling org_id = {org_id!r} onto legacy documents...\n")
    total = 0
    for name in COLLECTIONS:
        coll = db[name]
        # Matches docs with no org_id field AND docs explicitly stamped org_id: None
        result = await coll.update_many(
            {"$or": [{"org_id": {"$exists": False}}, {"org_id": None}]},
            {"$set": {"org_id": org_id}}
        )
        print(f"  {name:<16} matched={result.matched_count:<6} modified={result.modified_count}")
        total += result.modified_count

    print(f"\nDone. {total} documents updated.")
    print("Now safe to set VITE_ORG_SLUG on the frontend deployment and redeploy.")
    client.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python migrate_assign_org.py <org_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
