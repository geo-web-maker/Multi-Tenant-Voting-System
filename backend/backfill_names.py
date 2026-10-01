"""
One-off: normalise existing person names (e.g. 'john OKELLO' -> 'John Okello').

Usage:
    python backfill_names.py                    # DRY RUN, all organisations (default, changes nothing)
    python backfill_names.py --org <org_id>     # DRY RUN, one organisation
    python backfill_names.py --apply            # actually write, all organisations
    python backfill_names.py --org <org_id> --apply

Always run the dry run first and read the samples. Safe to re-run (idempotent).
Take a backup first if the election is live (see docs/BACKUP_RUNBOOK.md).
"""
import argparse
import asyncio
import os

import motor.motor_asyncio
from dotenv import load_dotenv

from name_backfill import run_backfill

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")


async def main(org_id, apply):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client["electiondbaccounting"]
    report = await run_backfill(db, org_id=org_id, dry_run=not apply)

    print(("APPLIED" if apply else "DRY RUN (nothing written)"),
          f"- scope: {org_id or 'all organisations'}\n")
    for name, c in report["collections"].items():
        print(f"  {name:<16} scanned={c['scanned']:<7} would_change={c['changed']}" if not apply
              else f"  {name:<16} scanned={c['scanned']:<7} changed={c['changed']}")
    print(f"\nTotal: {report['total_changed']}")
    for s in report["samples"]:
        print(f"  [{s['collection']}] {s['old']!r} -> {s['new']!r}")
    if not apply and report["total_changed"]:
        print("\nRe-run with --apply to write these changes.")
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", default=None, help="org_id to limit to (default: all)")
    ap.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    a = ap.parse_args()
    asyncio.run(main(a.org, a.apply))
