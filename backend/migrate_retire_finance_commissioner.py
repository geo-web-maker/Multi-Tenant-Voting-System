"""
One-time migration for the "candidate payments move to the Financial Controller" patch.

Commissioners no longer clear candidate payments (the backend ignores is_finance_commissioner), so
this script takes the leftover flag off every voter and tells you, per organization, whether the
Financial Controller queue is ready to receive the applications that were waiting on a commissioner.

Applications that were waiting for finance clearance need NO data change: they are simply
status="pending" with finance_cleared=False, and the Financial Controller's "Candidate payments" tab
lists exactly those.

Usage (dry run is the default and changes nothing):
    python migrate_retire_finance_commissioner.py
    python migrate_retire_finance_commissioner.py --apply
    python migrate_retire_finance_commissioner.py --apply --org-id <org_id>

Env: MONGO_URL, MONGO_DB_NAME (same as the backend / wipe_election_data.py).
"""
import argparse
import asyncio
import os
from datetime import datetime

import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "electiondbaccounting")

AWAITING = {"status": "pending", "finance_cleared": {"$ne": True}}


async def main(apply: bool, only_org: str | None):
    db = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    org_names = {str(o["_id"]): o.get("name") or o.get("slug") or str(o["_id"])
                 async for o in db.organizations.find({})}

    holder_q = {"is_finance_commissioner": True}
    if only_org:
        holder_q["org_id"] = only_org
    holders = [v async for v in db.voters.find(holder_q, {"student_id": 1, "full_name": 1, "org_id": 1})]

    org_ids = sorted({h.get("org_id") for h in holders} | (
        {only_org} if only_org else {str(k) for k in org_names}), key=lambda x: str(x))

    print(f"{'APPLYING' if apply else 'DRY RUN'} on {DB_NAME}\n")
    warnings = 0
    for org_id in org_ids:
        label = org_names.get(org_id, org_id or "(no org)")
        mine = [h for h in holders if h.get("org_id") == org_id]
        awaiting = await db.applications.count_documents({**AWAITING, "org_id": org_id})
        controllers = await db.voters.count_documents({"org_id": org_id, "is_financial_controller": True})
        both = await db.voters.count_documents(
            {"org_id": org_id, "is_financial_controller": True, "is_commissioner": True})

        print(f"[{label}]  finance commissioners: {len(mine)}  |  awaiting payment clearance: {awaiting}  |  "
              f"Financial Controllers: {controllers}")
        for h in mine:
            print(f"    - {h.get('full_name', '?')} ({h.get('student_id')}) loses finance-clearing power")
        if awaiting and controllers == 0:
            warnings += 1
            print(f"    !! {awaiting} application(s) are waiting and this org has NO Financial Controller. "
                  f"Grant the role (Superadmin > Financial Controllers) or use force-finance-clear.")
        if both:
            print(f"    note: {both} Financial Controller(s) also hold the commissioner role (allowed; each role "
                  f"has its own login, and their payment decisions are logged as decider_also_commissioner).")

        if apply and mine:
            res = await db.voters.update_many(
                {"org_id": org_id, "is_finance_commissioner": True},
                {"$unset": {"is_finance_commissioner": ""}})
            await db.audit_log.insert_one({
                "action": "finance_commissioner_retired", "actor": "migration",
                "details": {"cleared": [h.get("student_id") for h in mine], "awaiting_clearance": awaiting},
                "org_id": org_id, "timestamp": datetime.utcnow()})
            print(f"    flag removed from {res.modified_count} voter(s); audit entry written")
        print()

    if not apply:
        print("Nothing changed. Re-run with --apply to remove the flag.")
    if warnings:
        print(f"{warnings} warning(s) above need a decision before the election uses this.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually remove the flag (default: dry run)")
    ap.add_argument("--org-id", help="limit to one organization (string _id)")
    a = ap.parse_args()
    asyncio.run(main(a.apply, a.org_id))
