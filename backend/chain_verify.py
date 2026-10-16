"""Audit-chain verification against an arbitrary Mongo database handle."""
from __future__ import annotations
import hashlib

async def chain_verify_db(db, org_id) -> dict:
    tenant_filter = {"org_id": org_id}
    checkpoints = await db.audit_checkpoints.find(tenant_filter).sort("to_id", 1).to_list(length=None)
    chain = "GENESIS"
    for cp in checkpoints:
        rng = {"$gt": cp["from_id"], "$lte": cp["to_id"]} if cp.get("from_id") else {"$lte": cp["to_id"]}
        events = await db.vote_events.find({"org_id": org_id, "_id": rng}).sort("_id", 1).to_list(length=None)
        current = chain
        for ev in events:
            if int(ev.get("chain_version", 1) or 1) >= 2:
                # V2 commits the round label so a ballot cannot be reclassified between rounds.
                payload = f"{current}|{ev['_id']}|{ev['candidate_id']}|{ev['cast_at'].isoformat()}|{ev.get('round_id', 'round-1')}"
            else:
                # Preserve verification of historic V1 checkpoints.
                payload = f"{current}|{ev['_id']}|{ev['candidate_id']}|{ev['cast_at'].isoformat()}"
            current = hashlib.sha256(payload.encode()).hexdigest()
        if current != cp.get("chain_hash"):
            return {"valid": False, "first_mismatch_checkpoint_id": str(cp.get("_id")),
                    "expected": cp.get("chain_hash"), "recomputed": current}
        chain = cp["chain_hash"]
    return {"valid": True, "checkpoints_verified": len(checkpoints), "head_hash": chain}

async def count_uncheckpointed_events(db, org_id) -> int:
    last = await db.audit_checkpoints.find_one({"org_id": org_id}, {"to_id": 1}, sort=[("to_id", -1)])
    query = {"org_id": org_id}
    if last and last.get("to_id") is not None:
        query["_id"] = {"$gt": last["to_id"]}
    return await db.vote_events.count_documents(query)
