"""Backfill: apply normalize_name() to person names already stored in the database.

Shared by the CLI (backfill_names.py) and the superadmin endpoint
POST /superadmin/maintenance/normalize-names, so both behave identically.

Only letter case / whitespace changes — never ids, phones, roles or votes.
Each write is guarded on the OLD value ({_id, field: old}), so a name that was
edited by someone else mid-run is skipped rather than overwritten.
Audit-log and roster-ledger history is intentionally left untouched (append-only records).
"""
from pymongo import UpdateOne
from name_utils import normalize_name

# (collection, field) pairs that hold a person's name.
TARGETS = [
    ("voters",          "full_name"),   # the register: also commissioners / admins, they are voter docs
    ("applications",    "full_name"),   # candidacy applications
    ("candidates",      "name"),        # published ballot candidates
    ("student_changes", "full_name"),   # pending/processed add & remove requests
]

BATCH = 500
SAMPLE_LIMIT = 15


async def run_backfill(db, org_id: str | None = None, dry_run: bool = True) -> dict:
    """Returns {dry_run, total_changed, collections: {coll: {scanned, changed}}, samples: [...]}.
    org_id=None means every organisation (CLI only; the endpoint always passes its own org)."""
    report = {"dry_run": dry_run, "total_changed": 0, "collections": {}, "samples": []}

    for coll_name, field in TARGETS:
        coll = db[coll_name]
        query = {field: {"$type": "string"}}
        if org_id is not None:
            query["org_id"] = org_id

        scanned = changed = 0
        ops: list[UpdateOne] = []

        async for doc in coll.find(query, {field: 1}):
            scanned += 1
            old = doc[field]
            new = normalize_name(old)
            if new == old:
                continue
            changed += 1
            if len(report["samples"]) < SAMPLE_LIMIT:
                report["samples"].append({"collection": coll_name, "old": old, "new": new})
            if not dry_run:
                ops.append(UpdateOne({"_id": doc["_id"], field: old}, {"$set": {field: new}}))
                if len(ops) >= BATCH:
                    await coll.bulk_write(ops, ordered=False)
                    ops = []
        if ops:
            await coll.bulk_write(ops, ordered=False)

        report["collections"][coll_name] = {"scanned": scanned, "changed": changed}
        report["total_changed"] += changed

    return report
