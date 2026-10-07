"""
DESTRUCTIVE: wipes ONE organization's election data. There is no all-tenants mode: a mistake
here can only ever affect the org you name.

Does NOT touch the `organizations` collection itself, and never touches other tenants.

Usage:
    python wipe_election_data.py --org-slug <slug>                  # keeps branding/settings
    python wipe_election_data.py --org-slug <slug> --keep-nothing   # also wipes settings
                                                                    # (branding, election config)
    python wipe_election_data.py --org-slug <slug> --dry-run        # report counts only
"""
import asyncio
import re
import sys
import motor.motor_asyncio
import os
from dotenv import load_dotenv

import backup

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# Always wiped — this is the actual election data.
ALWAYS_WIPE = [
    "voters", "candidates", "positions", "applications",
    "student_changes", "audit_log", "otps", "admin_otps", "otp_send_state", "otp_guess_state", "sms_usage", "ip_send_stats", "contact_changes",
    # Added alongside the vote_events migration — without these, old vote
    # events (and, once diff #3 lands, their checkpoints) survive a wipe
    # and would bleed into whatever org reuses this deployment next.
    "vote_events", "audit_checkpoints",
]
# Only wiped with --keep-nothing (branding, election open/closed/certified state).
SETTINGS_COLLECTION = "settings"

CONFIRM_PHRASE = "WIPE ELECTION DATA"

# Collections whose tenant marker is not `org_id` (rate-limit / limiter state keyed by string).
# ip_send_stats is a short-lived per-IP throttle with no tenant field, so it is not wiped here.
KEY_PREFIX_COLLECTIONS = {"otp_send_state", "otp_guess_state"}   # key = "<org_id>:otp:..."
ORG_KEY_COLLECTIONS = {"sms_usage"}                              # org_key = "<org_id>"
GLOBAL_COLLECTIONS = {"ip_send_stats"}


def tenant_filter(name: str, org_id: str) -> dict:
    if name in KEY_PREFIX_COLLECTIONS:
        return {"key": {"$regex": f"^{re.escape(org_id)}:"}}
    if name in ORG_KEY_COLLECTIONS:
        return {"org_key": org_id}
    return {"org_id": org_id}


async def main(org_slug: str, keep_nothing: bool, dry_run: bool):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client[os.getenv("MONGO_DB_NAME", "electiondbaccounting")]

    org = await db.organizations.find_one({"slug": org_slug}, {"_id": 1})
    if not org:
        print(f"Unknown organization slug {org_slug!r}. Nothing was changed.")
        client.close()
        sys.exit(1)
    org_id = str(org["_id"])

    targets = [t for t in ALWAYS_WIPE if t not in GLOBAL_COLLECTIONS] + (
        [SETTINGS_COLLECTION] if keep_nothing else [])

    print(f"This will permanently delete {org_slug!r} ({org_id}) documents in:")
    for t in targets:
        print(f"  - {t}")
    if not keep_nothing:
        print(f"  (keeping: {SETTINGS_COLLECTION} — branding & election config)")
    print()

    if dry_run:
        for name in targets:
            count = await db[name].count_documents(tenant_filter(name, org_id))
            print(f"  {name:<16} would delete {count}")
        client.close()
        return

    typed = input(f'Type "{CONFIRM_PHRASE} {org_slug}" to proceed: ')
    if typed != f"{CONFIRM_PHRASE} {org_slug}":
        print("Aborted — confirmation phrase did not match.")
        client.close()
        return

    # Safety snapshot of this tenant before anything is deleted. Any failure aborts the wipe:
    # it never proceeds without a backup.
    try:
        snaps = await backup.snapshot_before_destructive(db, org_id, "wipe-script")
    except Exception as e:
        print(f"ABORTED: pre-wipe backup to B2 failed, nothing was deleted.\n  {e}")
        client.close()
        sys.exit(1)
    for s in snaps:
        print(f"  backed up tenant {s['tenant']}: {s['prefix']} ({s['bytes_gz']} bytes gz)")

    total = 0
    for name in targets:
        result = await db[name].delete_many(tenant_filter(name, org_id))
        print(f"  {name:<16} deleted={result.deleted_count}")
        total += result.deleted_count

    print(f"\nDone. {total} documents deleted.")
    client.close()

if __name__ == "__main__":
    if "--org-slug" not in sys.argv or sys.argv.index("--org-slug") + 1 >= len(sys.argv):
        sys.exit("--org-slug <slug> is required: this script only wipes one organization.")
    slug = sys.argv[sys.argv.index("--org-slug") + 1]
    asyncio.run(main(slug, "--keep-nothing" in sys.argv, "--dry-run" in sys.argv))
