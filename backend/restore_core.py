"""Shared, non-interactive backup listing, verification, restore planning and async writer."""
from __future__ import annotations
import asyncio
import gzip
import hashlib
import json
from bson import ObjectId, json_util
from pymongo import ReplaceOne
import backup

BATCH_SIZE = 500

class RestoreVerifyError(RuntimeError):
    """A downloaded backup fails its integrity or ownership checks."""


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
    """Download one file; verify compressed/raw SHA-256 and record count."""
    key = f"{prefix}/{entry['file']}"
    try:
        body = client.get_object(Bucket=cfg["bucket"], Key=key)["Body"].read()
    except Exception as exc:
        raise RestoreVerifyError(f"Unable to download {key}: {exc}") from exc
    if hashlib.sha256(body).hexdigest() != entry["sha256_gz"]:
        raise RestoreVerifyError(f"CHECKSUM MISMATCH (compressed) {key} — do not restore from this backup.")
    try:
        raw = gzip.decompress(body)
    except Exception as exc:
        raise RestoreVerifyError(f"GZIP INVALID {key}: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != entry["sha256_uncompressed"]:
        raise RestoreVerifyError(f"CHECKSUM MISMATCH (uncompressed) {key}")
    try:
        docs = [json_util.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except Exception as exc:
        raise RestoreVerifyError(f"JSONL INVALID {key}: {exc}") from exc
    if len(docs) != entry["count"]:
        raise RestoreVerifyError(f"COUNT MISMATCH {prefix}/{name}: manifest {entry['count']}, file {len(docs)}")
    return docs


def restore_filter(name: str, org_id):
    if name == "organizations":
        return {"_id": ObjectId(org_id)} if org_id else {"_id": None}
    if name == "platform_settings":
        return {}  # global collection, restored only from the _global snapshot
    return backup.collection_filter(name, org_id)


def assert_doc_owned(name: str, doc: dict, org_id, tenant: str):
    if name in {"organizations", "platform_settings"}:
        if name == "platform_settings" and tenant != "_global":
            raise RestoreVerifyError("platform_settings may only be restored from the _global backup")
        return
    if name == "sms_usage":
        if doc.get("org_key") != (tenant or "default"):
            raise RestoreVerifyError(
                f"Refusing: sms_usage doc {doc.get('_id')} has org_key {doc.get('org_key')!r}, expected {tenant or 'default'!r}")
        return
    if doc.get("org_id") != org_id:
        raise RestoreVerifyError(
            f"Refusing: {name} doc {doc.get('_id')} has org_id {doc.get('org_id')!r}, expected {org_id!r}")


def plan_restore(s3, cfg, tenant, base_prefix, until=None, include_org=False):
    """Verify newest supplied full/snapshot and subsequent routine incrementals; merge by _id."""
    base = read_manifest(s3, cfg, base_prefix)
    if base.get("tenant") != tenant:
        raise RestoreVerifyError(f"Manifest tenant {base.get('tenant')!r} != requested tenant {tenant!r}")
    org_id = base.get("org_id")
    steps = [(base_prefix, base)]
    if base.get("kind") == "full" and base.get("lock_class") == "routine":
        for prefix in list_backups(s3, cfg, tenant, "routine"):
            if "/incr-" in prefix and ts_of(prefix) >= ts_of(base_prefix) and (not until or ts_of(prefix) <= until):
                man = read_manifest(s3, cfg, prefix)
                if man.get("tenant") != tenant:
                    raise RestoreVerifyError(f"Manifest tenant mismatch in {prefix}")
                steps.append((prefix, man))
    merged: dict[str, dict] = {}
    for prefix, manifest in steps:
        for name, entry in manifest.get("collections", {}).items():
            docs = fetch_collection(s3, cfg, prefix, name, entry)
            if name == "organizations" and not include_org:
                continue
            for doc in docs:
                assert_doc_owned(name, doc, org_id, tenant)
                merged.setdefault(name, {})[doc["_id"]] = doc
    return org_id, merged


async def apply_restore(db, org_id, merged, replace=True, tenant: str | None = None):
    """Motor writer for guarded scratch/copy restores. Never selects a database by URL/name."""
    tenant = tenant or backup.tenant_key(org_id)
    counts = {}
    for name, docs in merged.items():
        flt = restore_filter(name, org_id)
        coll = db[name]
        if replace:
            await coll.delete_many(flt)
        ops = [ReplaceOne({"_id": doc_id}, doc, upsert=True) for doc_id, doc in docs.items()]
        for start in range(0, len(ops), BATCH_SIZE):
            await coll.bulk_write(ops[start:start + BATCH_SIZE], ordered=False)
            await asyncio.sleep(0)
        counts[name] = len(docs)
    return counts
