"""Registration-number health check (and optional repair).

Canonical stored form = normalize_student_id(): lowercase, no spaces, no quotes. Every lookup
in the app is an exact match on that form, so a record stored any other way (e.g. saved as
'2021/U/001' by an old code path) exists on the register but can never be found.

Shared by the CLI (check_reg_numbers.py) and POST /superadmin/maintenance/check-reg-numbers.
Display capitalisation is a frontend/masking concern only and is NOT stored.

Repair rules (conservative):
  voters           fixed unless (a) another voter in the same org already holds the canonical id
                   (conflict: two people would collide) or (b) has_voted is true (vote records
                   may reference the old id) -> both are reported for manual review, never touched.
  applications /   student_id rewritten to canonical form (guarded on the old value).
  student_changes
audit_log / roster_ledger / vote history are append-only and never rewritten.
"""
from pymongo import UpdateOne

SAMPLE_LIMIT = 20
BATCH = 500


def _canon(sid: str) -> str:
    # imported lazily so this module stays importable without booting main.py
    return sid.strip().strip('"').replace(" ", "").lower()


async def audit_reg_numbers(db, org_id: str | None = None, fix: bool = False) -> dict:
    report = {
        "fix": fix,
        "voters": {"scanned": 0, "non_canonical": 0, "fixable": 0, "fixed": 0, "conflicts": 0, "voted_review": 0},
        "other": {},
        "samples": [],
    }

    def sample(kind, coll, old, new):
        if len(report["samples"]) < SAMPLE_LIMIT:
            report["samples"].append({"kind": kind, "collection": coll, "old": old, "new": new})

    # ---- voters -------------------------------------------------------------------------
    vq = {"student_id": {"$type": "string"}}
    if org_id is not None:
        vq["org_id"] = org_id
    rows = [d async for d in db["voters"].find(vq, {"student_id": 1, "org_id": 1, "has_voted": 1})]
    report["voters"]["scanned"] = len(rows)

    taken: dict = {}                       # (org, canonical) -> count of docs already holding that id
    for d in rows:
        taken[(d.get("org_id"), _canon(d["student_id"]))] = taken.get((d.get("org_id"), _canon(d["student_id"])), 0) + 1
    exact = {(d.get("org_id"), d["student_id"]) for d in rows}

    ops: list[UpdateOne] = []
    claimed = set()
    for d in rows:
        old, new = d["student_id"], _canon(d["student_id"])
        if old == new:
            continue
        report["voters"]["non_canonical"] += 1
        key = (d.get("org_id"), new)
        # conflict: someone else already stored under the canonical id, or two bad docs map to the same id
        if key in exact or taken[key] > 1 or key in claimed:
            report["voters"]["conflicts"] += 1
            sample("conflict", "voters", old, new)
            continue
        if d.get("has_voted"):
            report["voters"]["voted_review"] += 1
            sample("voted_review", "voters", old, new)
            continue
        report["voters"]["fixable"] += 1
        claimed.add(key)
        sample("fixable", "voters", old, new)
        if fix:
            ops.append(UpdateOne({"_id": d["_id"], "student_id": old}, {"$set": {"student_id": new}}))
            if len(ops) >= BATCH:
                res = await db["voters"].bulk_write(ops, ordered=False)
                report["voters"]["fixed"] += res.modified_count
                ops = []
    if ops:
        res = await db["voters"].bulk_write(ops, ordered=False)
        report["voters"]["fixed"] += res.modified_count

    # ---- collections that just carry a copy of the id ---------------------------------------
    for coll in ("applications", "student_changes"):
        q = {"student_id": {"$type": "string"}}
        if org_id is not None:
            q["org_id"] = org_id
        scanned = bad = fixed = 0
        ops = []
        async for d in db[coll].find(q, {"student_id": 1}):
            scanned += 1
            old, new = d["student_id"], _canon(d["student_id"])
            if old == new:
                continue
            bad += 1
            sample("fixable", coll, old, new)
            if fix:
                ops.append(UpdateOne({"_id": d["_id"], "student_id": old}, {"$set": {"student_id": new}}))
                if len(ops) >= BATCH:
                    fixed += (await db[coll].bulk_write(ops, ordered=False)).modified_count
                    ops = []
        if ops:
            fixed += (await db[coll].bulk_write(ops, ordered=False)).modified_count
        report["other"][coll] = {"scanned": scanned, "non_canonical": bad, "fixed": fixed}

    v = report["voters"]
    report["issues_found"] = v["non_canonical"] + sum(c["non_canonical"] for c in report["other"].values())
    report["needs_review"] = v["conflicts"] + v["voted_review"]
    report["total_fixed"] = v["fixed"] + sum(c["fixed"] for c in report["other"].values())
    return report
