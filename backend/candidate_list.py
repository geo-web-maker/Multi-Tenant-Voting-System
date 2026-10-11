"""Official List of Candidates: frozen, verifiable snapshots of the approved candidates.

The system issues the list itself (nobody has to remember to):
  * the first list goes out as soon as vetting has closed and its close-out has run;
  * after that, any change to the approved candidates marks the list "dirty"; once things have been quiet for
    QUIET_SECONDS one new list is issued, unless names, positions and order came out identical (a phone-number
    edit must not supersede the list);
  * Superadmin / Commission can also issue by hand ("Issue now").

Every function takes a tenant-scoped handle `t` (main.tdb_for(org_id)), so nothing here can leave its org.
Only names and positions are stored: no registration numbers, contacts or fees.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta

try:  # pymongo is always present in the app; the guard only keeps the helpers importable on their own
    from pymongo.errors import DuplicateKeyError
except Exception:  # pragma: no cover
    class DuplicateKeyError(Exception):
        pass

QUIET_SECONDS = 120
STATE_NAME = "candidate_list_state"
ISSUE_ROLES = ("superadmin", "commission")
DOWNLOAD_ROLES = ("superadmin", "commission", "it_admin", "financial_controller")


def new_list_id() -> str:
    return f"LIST-{secrets.token_hex(6).upper()}"


def build_sections(candidates) -> list[dict]:
    """Candidates -> [{position, names: [..]}] in ballot order (position `order`, then insertion order)."""
    rows = sorted(
        candidates,
        key=lambda c: (int(c.get("order") or 0), str(c.get("position") or ""), str(c.get("_id") or "")),
    )
    sections: list[dict] = []
    by_position: dict[str, dict] = {}
    for c in rows:
        name = " ".join(str(c.get("name") or "").split())
        position = " ".join(str(c.get("position") or "").split())
        if not name:
            continue
        sec = by_position.get(position)
        if sec is None:
            sec = by_position[position] = {"position": position, "names": []}
            sections.append(sec)
        sec["names"].append(name)
    return sections


def signature(sections: list[dict]) -> str:
    """Fingerprint of names, positions and their order. Same fingerprint = nothing worth re-issuing."""
    payload = json.dumps([[s["position"], s["names"]] for s in sections], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def current_sections(t) -> list[dict]:
    return build_sections([c async for c in t.candidates.find({})])


async def latest_list(t):
    """The list that is current right now (not superseded), or None."""
    return await t.candidate_lists.find_one({"superseded_at": None}, sort=[("issued_at", -1)])


async def mark_dirty(t, reason: str, now) -> None:
    """Record that the approved candidates changed. The sweep issues one list after a quiet spell."""
    await t.settings.update_one(
        {"name": STATE_NAME},
        {"$set": {"dirty_at": now, "dirty_reason": reason}},
        upsert=True,
    )


async def issue(t, *, reason: str, actor: str, branding: dict, now, sections=None):
    """Freeze the approved candidates as a new list and supersede the earlier one. Returns the new document,
    or None when another worker issued at the same moment (the unique (org_id, seq) index decides)."""
    if sections is None:
        sections = await current_sections(t)
    last = await t.candidate_lists.find_one({}, sort=[("seq", -1)])
    doc = {
        "list_id": new_list_id(),
        "seq": int((last or {}).get("seq") or 0) + 1,
        "org_name": (branding or {}).get("org_name", ""),
        "document_template": (branding or {}).get("document_template") or "classic",   # frozen: a later change never restyles it
        "sections": sections,
        "count": sum(len(s["names"]) for s in sections),
        "signature": signature(sections),
        "issued_at": now,
        "issued_by": actor,
        "reason": reason,
        "superseded_at": None,
        "superseded_by": None,
    }
    try:
        await t.candidate_lists.insert_one(doc)
    except DuplicateKeyError:
        return None
    await t.candidate_lists.update_many(
        {"superseded_at": None, "list_id": {"$ne": doc["list_id"]}},
        {"$set": {"superseded_at": now, "superseded_by": doc["list_id"]}},
    )
    return doc


async def maybe_issue(t, *, vetting_ended: bool, closeout_complete: bool, branding: dict, now,
                      quiet_s: int = QUIET_SECONDS):
    """Issue automatically when due. Returns the new document, or None when nothing was due.

    No list before vetting closes (decisions are still moving). The first list is immediate; later ones wait
    for a quiet spell and are skipped when nothing a reader would see has changed."""
    if not (vetting_ended and closeout_complete):
        return None
    latest = await latest_list(t)
    state = await t.settings.find_one({"name": STATE_NAME}) or {}
    dirty_at = state.get("dirty_at")
    if latest is None:
        sections = await current_sections(t)
        if not sections:
            return None
        new = await issue(t, reason="Vetting closed", actor="system", branding=branding, now=now, sections=sections)
        if new is None:
            return None   # another worker issued first
    else:
        if not dirty_at or now - dirty_at < timedelta(seconds=quiet_s):
            return None
        sections = await current_sections(t)
        if not sections:
            return None   # never replace the official list with an empty one automatically
        if signature(sections) == latest.get("signature"):
            new = None    # nothing a reader would see changed: just clear the flag
        else:
            new = await issue(t, reason=state.get("dirty_reason") or "Candidates changed", actor="system",
                              branding=branding, now=now, sections=sections)
            if new is None:
                return None
    if dirty_at:
        # Only clear what we saw: a change that landed while we worked keeps the flag (dirty_at moved on).
        await t.settings.update_one({"name": STATE_NAME, "dirty_at": dirty_at},
                                    {"$unset": {"dirty_at": "", "dirty_reason": ""}})
    return new


def public_view(doc: dict) -> dict:
    """What the QR scan may learn: is it current, and when it was issued/superseded. No names."""
    return {
        "verified": True,
        "list_id": doc.get("list_id"),
        "org_name": doc.get("org_name", ""),
        "issued_at": doc.get("issued_at"),
        "current": doc.get("superseded_at") is None,
        "superseded_at": doc.get("superseded_at"),
    }


def download_view(doc: dict) -> dict:
    return {
        "list_id": doc["list_id"],
        "org_name": doc.get("org_name", ""),
        "document_template": doc.get("document_template") or "classic",
        "sections": doc.get("sections") or [],
        "count": doc.get("count", 0),
        "issued_at": doc.get("issued_at"),
        "reason": doc.get("reason", ""),
        "current": doc.get("superseded_at") is None,
        "superseded_at": doc.get("superseded_at"),
    }
