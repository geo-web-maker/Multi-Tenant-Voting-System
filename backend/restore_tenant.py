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
import gzip
import hashlib
import json
import os
import sys

from bson import ObjectId, json_util
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

import backup

load_dotenv()


def read_manifest(client, cfg, prefix):
    obj = client.get_object(Bucket=cfg["bucket"], Key=f"{prefix}/manifest.json")
    return json.loads(obj["Body"].read())


def list_backups(client, cfg, tenant, cls):
    prefixes = []
    pager = client.get_paginator("list_objects_v2")
    for page in pager.paginate(Bucket=cfg["bucket"], Prefix=f"{cls}/{tenant}/", Delimiter="/"):
        prefixes += [p["Prefix"].rstrip("/") for p in page.get("CommonPrefixes", [])]
    return sorted(p for p in prefixes if not p.endswith("/assets") and not p.endswith("assets"))


def ts_of(prefix):
    return prefix.rsplit("-", 1)[-1]


def fetch_collection(client, cfg, prefix, name, entry):
    """Download one collection file and verify BOTH checksums and the record count."""
    body = client.get_object(Bucket=cfg["bucket"], Key=f"{prefix}/{entry['file']}")["Body"].read()
    if hashlib.sha256(body).hexdigest() != entry["sha256_gz"]:
        raise SystemExit(f"CHECKSUM MISMATCH (compressed) {prefix}/{entry['file']} — do not restore from this backup.")
    raw = gzip.decompress(body)
    if hashlib.sha256(raw).hexdigest() != entry["sha256_uncompressed"]:
        raise SystemExit(f"CHECKSUM MISMATCH (uncompressed) {prefix}/{entry['file']}")
    docs = [json_util.loads(line) for line in raw.decode().splitlines() if line]
    if len(docs) != entry["count"]:
        raise SystemExit(f"COUNT MISMATCH {prefix}/{name}: manifest {entry['count']}, file {len(docs)}")
    return docs


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
    base = read_manifest(s3, cfg, a.backup)
    if base["tenant"] != a.tenant:
        sys.exit(f"Manifest tenant {base['tenant']!r} != --tenant {a.tenant!r}")
    org_id = base["org_id"]          # None for the legacy default tenant

    steps = [(a.backup, base)]
    if base["kind"] == "full" and base["lock_class"] == "routine":
        for p in list_backups(s3, cfg, a.tenant, "routine"):
            if "/incr-" in p and ts_of(p) >= ts_of(a.backup) and (not a.until or ts_of(p) <= a.until):
                steps.append((p, read_manifest(s3, cfg, p)))

    # Download + verify everything first. Nothing is written until all checksums pass.
    merged: dict[str, dict] = {}
    for prefix, man in steps:
        for name, entry in man["collections"].items():
            if name == "organizations" and not a.include_org:
                fetch_collection(s3, cfg, prefix, name, entry)   # still verify
                continue
            for d in fetch_collection(s3, cfg, prefix, name, entry):
                if name != "organizations" and d.get("org_id") != org_id:
                    sys.exit(f"Refusing: {name} doc {d['_id']} has org_id {d.get('org_id')!r}, expected {org_id!r}")
                merged.setdefault(name, {})[d["_id"]] = d       # later incr overwrites, idempotent
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
        flt = {"_id": org_id and ObjectId(org_id)} if name == "organizations" else {"org_id": org_id}
        if a.replace:
            db[name].delete_many(flt)
        ops = [ReplaceOne({"_id": i}, d, upsert=True) for i, d in docs.items()]
        for i in range(0, len(ops), 500):
            db[name].bulk_write(ops[i:i + 500], ordered=False)

    print("Restore written. Confirming counts against the backup:")
    bad = 0
    for name, docs in merged.items():
        flt = {"_id": org_id and ObjectId(org_id)} if name == "organizations" else {"org_id": org_id}
        have = db[name].count_documents(flt)
        ok = have == len(docs) if a.replace else have >= len(docs)
        bad += 0 if ok else 1
        print(f"  {name:<18} expected {len(docs):>7}  in db {have:>7}  {'OK' if ok else 'MISMATCH'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
