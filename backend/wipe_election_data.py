"""
DESTRUCTIVE: wipes all election data so the current deployment can start
clean under a new org slug (no migration needed — new data gets stamped
with the right org_id automatically once VITE_ORG_SLUG is set).

Run BEFORE setting VITE_ORG_SLUG on the frontend. Does NOT touch the
`organizations` collection itself.

Usage:
    python wipe_election_data.py                # wipes everything below,
                                                  # keeps branding/settings
    python wipe_election_data.py --keep-nothing  # also wipes settings
                                                  # (branding, election config)
    python wipe_election_data.py --dry-run       # report counts only,
                                                  # no deletes
"""
import asyncio
import sys
import motor.motor_asyncio
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# Always wiped — this is the actual election data.
ALWAYS_WIPE = [
    "voters", "candidates", "positions", "applications",
    "student_changes", "audit_log", "otps", "admin_otps",
]
# Only wiped with --keep-nothing (branding, election open/closed/certified state).
SETTINGS_COLLECTION = "settings"

CONFIRM_PHRASE = "WIPE ELECTION DATA"

async def main(keep_nothing: bool, dry_run: bool):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client["electiondbaccounting"]

    targets = ALWAYS_WIPE + ([SETTINGS_COLLECTION] if keep_nothing else [])

    print("This will permanently delete ALL documents in:")
    for t in targets:
        print(f"  - {t}")
    if not keep_nothing:
        print(f"  (keeping: {SETTINGS_COLLECTION} — branding & election config)")
    print()

    if dry_run:
        for name in targets:
            count = await db[name].count_documents({})
            print(f"  {name:<16} would delete {count}")
        client.close()
        return

    typed = input(f'Type "{CONFIRM_PHRASE}" to proceed: ')
    if typed != CONFIRM_PHRASE:
        print("Aborted — confirmation phrase did not match.")
        client.close()
        return

    total = 0
    for name in targets:
        result = await db[name].delete_many({})
        print(f"  {name:<16} deleted={result.deleted_count}")
        total += result.deleted_count

    print(f"\nDone. {total} documents deleted.")
    print("Now: create the org, set VITE_ORG_SLUG on the frontend, and redeploy.")
    client.close()

if __name__ == "__main__":
    keep_nothing = "--keep-nothing" in sys.argv
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(keep_nothing, dry_run))
