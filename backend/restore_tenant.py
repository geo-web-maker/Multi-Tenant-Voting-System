"""
Restore ONE tenant from B2 (Task 4.7). Never touches another org_id.

  python restore_tenant.py list    --tenant <org_id|default> [--cls routine|safety|milestone]
  python restore_tenant.py restore --tenant <org_id|default> --backup <prefix> \
        --target-db <name>            # restore into a COPY (recommended first)
        [--until <ts>]                # routine only: apply incrementals up to this timestamp
        [--replace]                   # delete the tenant's docs in each collection first
        [--include-org]               # also restore the organizations document
        [--dry-run]                   # download + verify checksums only, write nothing
  python restore_tenant.py restore ... --live   # target the live database (asks for RESTORE <tenant>)

<prefix> is e.g. routine/<tenant>/full-20260920T101500Z (from `list`). For routine
backups the newest full is the base and later incr-* backups are applied on top;
milestone/safety snapshots are self-contained.
"""
import argparse
import os
import sys

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

import backup
from restore_core import (RestoreVerifyError, read_manifest, list_backups, ts_of,
                          fetch_collection, plan_restore, restore_filter)

load_dotenv()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list", "restore"])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--cls", default="routine", choices=["routine", "safety", "milestone"])
    ap.add_argument("--backup")
    ap.add_argument("--until")
    ap.add_argument("--target-db")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--include-org", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = backup.load_config()
    s3 = backup.make_client(cfg)

    if a.action == "list":
        for p in list_backups(s3, cfg, a.tenant, a.cls):
            print(p)
        return

    if not a.backup:
        sys.exit("--backup <prefix> is required")
    try:
        org_id, merged = plan_restore(s3, cfg, a.tenant, a.backup, a.until, a.include_org)
        base = read_manifest(s3, cfg, a.backup)
        steps = [a.backup]
        if base.get("kind") == "full" and base.get("lock_class") == "routine":
            steps.extend(p for p in list_backups(s3, cfg, a.tenant, "routine")
                         if "/incr-" in p and ts_of(p) >= ts_of(a.backup)
                         and (not a.until or ts_of(p) <= a.until))
    except RestoreVerifyError as exc:
        sys.exit(str(exc))
    print(f"Verified {len(steps)} backup(s); checksums OK.")
    for name, docs in merged.items():
        print(f"  {name:<18} {len(docs)} records")
    if a.dry_run:
        print("Dry run: nothing written.")
        return

    if a.live:
        if input(f'Type "RESTORE {a.tenant}" to write into the LIVE database: ') != f"RESTORE {a.tenant}":
            sys.exit("Aborted.")
        db_name = os.getenv("MONGO_DB_NAME", "electiondbaccounting")
    elif a.target_db:
        db_name = a.target_db
    else:
        sys.exit("Give --target-db <copy name> (recommended) or --live.")
    db = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))[db_name]

    for name, docs in merged.items():
        flt = restore_filter(name, org_id)
        if a.replace:
            db[name].delete_many(flt)
        ops = [ReplaceOne({"_id": i}, d, upsert=True) for i, d in docs.items()]
        for i in range(0, len(ops), 500):
            db[name].bulk_write(ops[i:i + 500], ordered=False)

    print("Restore written. Confirming counts against the backup:")
    bad = 0
    for name, docs in merged.items():
        flt = restore_filter(name, org_id)
        have = db[name].count_documents(flt)
        ok = have == len(docs) if a.replace else have >= len(docs)
        bad += 0 if ok else 1
        print(f"  {name:<18} expected {len(docs):>7}  in db {have:>7}  {'OK' if ok else 'MISMATCH'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
