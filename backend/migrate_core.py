"""Safe, idempotent Mongo database migration used by the CLI and admin UI."""
from __future__ import annotations
import asyncio
import hashlib
import inspect
import time
from urllib.parse import urlparse
from bson import json_util
from pymongo import ReplaceOne, IndexModel

BATCH = 500
PAUSE_S = 0.05
SECURITY_ONLY = {"otps", "admin_otps", "otp_attempts", "login_attempts", "revoked_tokens",
                 "ip_rate_limits", "otp_send_state", "otp_guess_state", "ip_send_stats"}

class MigrationRefused(RuntimeError):
    pass

def host_of(uri: str) -> str:
    return (urlparse(uri).hostname or "").lower()

def line(doc) -> bytes:
    return (json_util.dumps(doc, json_options=json_util.CANONICAL_JSON_OPTIONS) + "\n").encode()

async def digest(coll) -> tuple[int, str]:
    h, count = hashlib.sha256(), 0
    async for doc in coll.find({}).sort("_id", 1).batch_size(BATCH):
        h.update(line(doc)); count += 1
    return count, h.hexdigest()

async def _call_progress(progress, payload):
    if progress:
        value = progress(payload)
        if inspect.isawaitable(value):
            await value

async def assert_different_clusters(src_db, dst_db, source_url: str | None = None, target_url: str | None = None):
    if source_url and target_url and host_of(source_url) == host_of(target_url):
        raise MigrationRefused("Source and target are the same cluster. Refusing.")
    try:
        sclient, dclient = src_db.client, dst_db.client
        # Force server selection then compare actual resolved replica-set nodes to catch SRV aliases.
        await sclient.admin.command("ping")
        await dclient.admin.command("ping")
        snodes, dnodes = set(sclient.nodes or ()), set(dclient.nodes or ())
        if not snodes or not dnodes:
            raise MigrationRefused("Could not verify source/target replica-set members. Refusing migration.")
        if snodes.intersection(dnodes):
            raise MigrationRefused("Source and target share replica-set members. Refusing.")
    except MigrationRefused:
        raise
    except Exception as exc:
        raise MigrationRefused("Unable to verify that both migration clusters are reachable and distinct.") from exc
    if src_db.name == dst_db.name and src_db.client is dst_db.client:
        raise MigrationRefused("Source and target are the same database handle. Refusing.")

async def copy_indexes(src, dst):
    infos = await src.index_information()
    for name, info in infos.items():
        if name == "_id_":
            continue
        options = {k: info[k] for k in ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression", "collation", "name") if k in info}
        await dst.create_indexes([IndexModel(info["key"], **options)])

async def collection_plan(src_db, dst_db, names=None):
    src_names = names if names is not None else await src_db.list_collection_names()
    out = []
    for name in sorted(n for n in src_names if not n.startswith("system.")):
        sn, dn = await src_db[name].count_documents({}), await dst_db[name].count_documents({})
        out.append({"collection": name, "source": sn, "target": dn, "would_copy": sn, "would_remove": max(0, dn - sn)})
    return out

async def migrate_database(src_db, dst_db, *, mode="copy", include_security=False, force=False,
                           source_url=None, target_url=None, progress=None) -> dict:
    """mode=plan is read-only; copy upserts; final also mirrors deletions before upsert."""
    if mode not in {"plan", "copy", "final", "verify"}:
        raise ValueError("mode must be plan, copy, final or verify")
    if dst_db.name in {"mirror", "restore_test"}:
        raise MigrationRefused(f"Migration target database {dst_db.name!r} is reserved for mirror/restore-test and is not allowed.")
    await assert_different_clusters(src_db, dst_db, source_url, target_url)
    names = [n for n in await src_db.list_collection_names() if not n.startswith("system.")]
    if not include_security:
        names = [n for n in names if n not in SECURITY_ONLY]
    plans = await collection_plan(src_db, dst_db, names)
    if mode == "plan":
        return {"status": "planned", "mode": mode, "collections": plans}
    mismatches = []
    total = len(names)
    for pos, name in enumerate(sorted(names), 1):
        src, dst = src_db[name], dst_db[name]
        source_count, target_count = await src.count_documents({}), await dst.count_documents({})
        if target_count > source_count and not force and mode not in {"final", "verify"}:
            raise MigrationRefused(f"{name}: target has MORE documents than source ({target_count}>{source_count}). Wrong direction? Use --force.")
        await _call_progress(progress, {"collection": name, "index": pos, "total": total, "phase": "copying" if mode != "verify" else "verifying"})
        if mode in {"copy", "final"}:
            if mode == "final":
                # Delete target-only ids in chunks *before* upserting to protect unique-key reuse.
                source_ids = {d["_id"] async for d in src.find({}, {"_id": 1}).batch_size(BATCH)}
                stale = [d["_id"] async for d in dst.find({}, {"_id": 1}).batch_size(BATCH) if d["_id"] not in source_ids]
                for start in range(0, len(stale), BATCH):
                    await dst.delete_many({"_id": {"$in": stale[start:start + BATCH]}})
            ops = []
            async for doc in src.find({}).batch_size(BATCH):
                ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                if len(ops) >= BATCH:
                    await dst.bulk_write(ops, ordered=False); ops = []; await asyncio.sleep(PAUSE_S)
            if ops:
                await dst.bulk_write(ops, ordered=False)
            await copy_indexes(src, dst)
        (sn, sh), (dn, dh) = await digest(src), await digest(dst)
        ok = sn == dn and sh == dh
        plans_entry = next((x for x in plans if x["collection"] == name), {})
        plans_entry.update({"verified": ok, "source": sn, "target": dn, "source_digest": sh, "target_digest": dh})
        if not ok:
            mismatches.append(name)
        await _call_progress(progress, {"collection": name, "index": pos, "total": total, "phase": "verified" if ok else "mismatch", "ok": ok})
    if mismatches:
        return {"status": "failed", "mode": mode, "collections": plans, "mismatches": mismatches}
    return {"status": "passed", "mode": mode, "collections": plans, "mismatches": []}
