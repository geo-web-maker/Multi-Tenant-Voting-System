"""Chain Verify: valid, tampered, and identical head_hash after a backup-format round trip."""
import hashlib
from datetime import datetime
import pytest
from bson import ObjectId, json_util
from mongomock_motor import AsyncMongoMockClient

import backup
import chain_verify

pytestmark = pytest.mark.asyncio
ORG = "org-1"


async def _seed(db, n=4):
    prev, ids = "GENESIS", []
    for i in range(n):
        eid = ObjectId()
        cast = datetime(2026, 10, 12, 10, 0, i, 123000)
        await db.vote_events.insert_one({"_id": eid, "org_id": ORG, "candidate_id": f"c{i % 2}", "cast_at": cast})
        prev = hashlib.sha256(f"{prev}|{eid}|c{i % 2}|{cast.isoformat()}".encode()).hexdigest()
        ids.append(eid)
    await db.audit_checkpoints.insert_one({"_id": ObjectId(), "org_id": ORG, "from_id": None,
                                           "to_id": ids[-1], "chain_hash": prev})
    return prev


async def test_round_trip_through_backup_encoding_keeps_head_hash():
    src, dst = AsyncMongoMockClient()["a"], AsyncMongoMockClient()["b"]
    head = await _seed(src)
    assert (await chain_verify.chain_verify_db(src, ORG))["head_hash"] == head
    for name in ("vote_events", "audit_checkpoints"):
        raw = b"".join([backup._dump_line(d) async for d in src[name].find({})])
        docs = [json_util.loads(l) for l in raw.decode().splitlines() if l]
        if docs:
            await dst[name].insert_many(docs)
    res = await chain_verify.chain_verify_db(dst, ORG)
    assert res["valid"] is True and res["head_hash"] == head


async def test_tampering_after_restore_is_detected():
    db = AsyncMongoMockClient()["t"]
    await _seed(db)
    await db.vote_events.update_one({}, {"$set": {"candidate_id": "evil"}})
    assert (await chain_verify.chain_verify_db(db, ORG))["valid"] is False


async def test_uncheckpointed_events_are_counted():
    db = AsyncMongoMockClient()["u"]
    await _seed(db)
    await db.vote_events.insert_one({"_id": ObjectId(), "org_id": ORG, "candidate_id": "c0", "cast_at": datetime.utcnow()})
    assert await chain_verify.count_uncheckpointed_events(db, ORG) == 1


async def test_other_tenants_events_do_not_affect_the_chain():
    db = AsyncMongoMockClient()["o"]
    head = await _seed(db)
    await db.vote_events.insert_one({"_id": ObjectId(), "org_id": "other", "candidate_id": "x", "cast_at": datetime.utcnow()})
    assert (await chain_verify.chain_verify_db(db, ORG))["head_hash"] == head


def test_main_verify_audit_chain_delegates_to_shared_function():
    src = open("main.py", encoding="utf-8").read()
    assert "from chain_verify import chain_verify_db" in src


async def test_round_label_is_bound_into_v2_checkpoint_hash():
    db = AsyncMongoMockClient()["round-aware"]
    cast_at = datetime(2026, 10, 16, 10, 0, 0)
    events = [
        {"_id": ObjectId(), "org_id": ORG, "candidate_id": "candidate-a",
         "cast_at": cast_at, "round_id": "round-1", "chain_version": 2},
        {"_id": ObjectId(), "org_id": ORG, "candidate_id": "candidate-b",
         "cast_at": cast_at, "round_id": "by-election-1", "chain_version": 2},
    ]
    events.sort(key=lambda ev: ev["_id"])
    await db.vote_events.insert_many(events)
    head = "GENESIS"
    for event in events:
        head = hashlib.sha256(
            f"{head}|{event['_id']}|{event['candidate_id']}|{event['cast_at'].isoformat()}|{event['round_id']}".encode()
        ).hexdigest()
    await db.audit_checkpoints.insert_one({
        "_id": ObjectId(), "org_id": ORG, "from_id": None,
        "to_id": events[-1]["_id"], "chain_hash": head,
    })

    assert (await chain_verify.chain_verify_db(db, ORG))["valid"] is True
    await db.vote_events.update_one(
        {"_id": events[1]["_id"]}, {"$set": {"round_id": "round-1" if events[1]["round_id"] == "by-election-1" else "by-election-1"}}
    )
    assert (await chain_verify.chain_verify_db(db, ORG))["valid"] is False
