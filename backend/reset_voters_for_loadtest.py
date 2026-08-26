"""
Resets voting state so you can re-run the Locust load test without a full
wipe_election_data.py + seed_test_data.py cycle.

Clears, across ALL orgs (does not touch candidates/positions/org config):
  - voters.has_voted -> False
  - voters.otp_count -> 0
  - otps collection  -> emptied

Usage:
    python reset_voters_for_loadtest.py            # prompts for confirmation
    python reset_voters_for_loadtest.py --dry-run   # report counts only
    python reset_voters_for_loadtest.py --yes       # skip confirmation prompt
"""
import asyncio
import os
import sys
import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "electiondbaccounting")

CONFIRM_PHRASE = "RESET VOTERS"


async def main(dry_run: bool, skip_confirm: bool):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    voted_count = await db.voters.count_documents({"has_voted": True})
    otp_flagged_count = await db.voters.count_documents({"otp_count": {"$gt": 0}})
    otps_count = await db.otps.count_documents({})

    print(f"Database: {DB_NAME} @ {MONGO_URL}")
    print(f"  voters with has_voted=True   : {voted_count}")
    print(f"  voters with otp_count > 0    : {otp_flagged_count}")
    print(f"  documents in otps collection : {otps_count}")
    print()

    if dry_run:
        print("Dry run only — nothing changed.")
        client.close()
        return

    if not skip_confirm:
        typed = input(f'Type "{CONFIRM_PHRASE}" to proceed: ')
        if typed != CONFIRM_PHRASE:
            print("Aborted — confirmation phrase did not match.")
            client.close()
            return

    voters_result = await db.voters.update_many(
        {},
        {"$set": {"has_voted": False, "otp_count": 0, "last_status": "idle"}},
    )
    otps_result = await db.otps.delete_many({})

    print(f"\nDone.")
    print(f"  voters reset : {voters_result.modified_count}")
    print(f"  otps deleted : {otps_result.deleted_count}")
    print("\nCandidates, positions, org config, and admin accounts were left untouched.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv, skip_confirm="--yes" in sys.argv))
