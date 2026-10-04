"""Backfill: record application edits that were made BEFORE edit tracking existed.

Applications keep an immutable `application_snapshot` (what was submitted). Corrections made through
the Edit application button also append to `edit_history`, which drives the EDITED mark and the extra
PDF pages. Corrections made earlier (straight in the database) changed the live document but left no
history, so nothing looked edited.

This finds every application whose live printed fields differ from its last known printed state
(last `edit_history[].after`, else the original snapshot) and appends ONE history entry for the drift.
Idempotent: once recorded, live == last `after`, so a re-run finds nothing.
"""
from datetime import datetime

PRINTED = ("student_id", "full_name", "position_title", "manifesto", "image_url")


def _norm(k, v):
    s = "" if v is None else str(v)
    return s.lower() if k == "student_id" else s


async def run_edit_reconcile(db, resolve_position_title, history_fn, org_id=None,
                             actor="system-backfill", dry_run=True) -> dict:
    report = {"dry_run": dry_run, "scanned": 0, "recorded": 0, "items": []}
    query = {"org_id": org_id} if org_id is not None else {}
    async for app in db.applications.find(query):
        report["scanned"] += 1
        snap = app.get("application_snapshot")
        if not snap:
            continue
        hist = history_fn(app)
        base = hist[-1]["after"] if hist else snap
        title, _ = await resolve_position_title(app.get("position_id", ""), app.get("org_id"))
        live = {"student_id": app.get("student_id"), "full_name": app.get("full_name"),
                "position_title": title, "manifesto": app.get("manifesto"),
                "image_url": app.get("image_url")}
        changes = {k: {"old": base.get(k), "new": live[k]} for k in PRINTED
                   if _norm(k, base.get(k)) != _norm(k, live[k])}
        if not changes:
            continue
        report["items"].append({"app_id": str(app["_id"]), "name": live["full_name"],
                                "fields": sorted(changes)})
        if dry_run:
            continue
        entry = {"at": datetime.utcnow(), "by": actor, "backfilled": True,
                 "reason": "Edited before edit tracking was added (recorded retroactively)",
                 "changes": changes, "after": {**live, "submitted_at": snap.get("submitted_at")}}
        # Guard on the values we read, so a concurrent real edit is skipped, not double-recorded.
        guard = {"_id": app["_id"], **{k: app.get(k) for k in ("student_id", "full_name", "manifesto", "image_url", "position_id")}}
        res = await db.applications.update_one(guard, {"$push": {"edit_history": entry}})
        report["recorded"] += res.modified_count
    return report
