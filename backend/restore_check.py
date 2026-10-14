"""Guarded restore-test workflow: rebuild the isolated restore_test DB from locked B2 backups."""
from __future__ import annotations
import asyncio
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
import backup
from backup_jobs import now_utc
from chain_verify import chain_verify_db, count_uncheckpointed_events
from restore_core import (plan_restore, read_manifest, list_backups, ts_of, fetch_collection, apply_restore, restore_filter,
                          open_restore_stream, stream_apply)
from alerts import alert_critical, alert_warning

SCRATCH_NAME = "restore_test"
_run_lock = asyncio.Lock()

class ScratchRefused(RuntimeError):
    pass

def host_of(uri: str | None) -> str:
    return (urlparse(uri or "").hostname or "").lower()

def assert_scratch_safe(live_url: str, live_db: str, scratch_url: str | None, scratch_db: str) -> None:
    if scratch_db != SCRATCH_NAME:
        raise ScratchRefused(f"Scratch db must be exactly {SCRATCH_NAME!r}, got {scratch_db!r}.")
    if not scratch_url:
        raise ScratchRefused("SECOND_MONGO_URL is not set.")
    if not host_of(live_url) or host_of(scratch_url) == host_of(live_url):
        raise ScratchRefused("Scratch cluster URL equals the live cluster URL.")
    if scratch_db == live_db:
        raise ScratchRefused("Scratch db name equals the live db name.")

async def assert_not_same_nodes(live_client, scratch_client) -> None:
    """After connecting, resolved replica-set members must not overlap (catches SRV aliases)."""
    await asyncio.gather(live_client.admin.command("ping"), scratch_client.admin.command("ping"))
    live_nodes, scratch_nodes = set(live_client.nodes or ()), set(scratch_client.nodes or ())
    if not live_nodes or not scratch_nodes:
        raise ScratchRefused("Could not verify distinct live and scratch replica-set members; refusing to flush scratch.")
    if live_nodes.intersection(scratch_nodes):
        raise ScratchRefused("Scratch and live clusters share replica-set members.")

async def flush_scratch(scratch_client, live_url, live_db, scratch_db, live_client=None) -> int:
    """Drop collections only after repeated exact-name and distinct-cluster checks."""
    assert_scratch_safe(live_url, str(live_db), os.getenv("SECOND_MONGO_URL"), scratch_db)
    if live_client is not None:
        await assert_not_same_nodes(live_client, scratch_client)
    db = scratch_client[scratch_db]
    names = [name for name in await db.list_collection_names() if not name.startswith("system.")]
    for name in names:
        # Do not ever pass a user-supplied database name to drop_database.
        await db.drop_collection(name)
    return len(names)

LIVE_ID_CHUNK = 2000

async def _live_ids(coll, ids, owner_filter) -> set:
    """Which of `ids` exist in live. Chunked so a large election never builds one huge $in query."""
    found = set()
    for start in range(0, len(ids), LIVE_ID_CHUNK):
        chunk = ids[start:start + LIVE_ID_CHUNK]
        async for d in coll.find({"_id": {"$in": chunk}, **owner_filter}, {"_id": 1}):
            found.add(d["_id"])
    return found

def _parse_created(value):
    if not value: return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def _prefix_age_hours(manifest):
    created = _parse_created(manifest.get("created_at"))
    if not created: return None
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 3600)

async def run_restore_test(live_db, trigger="manual", *, override_election_guard=False, progress=None) -> dict:
    """Return passed/warning/failed/skipped with the step-by-step evidence."""
    if _run_lock.locked():
        return {"status": "warning", "error": "Another restore test is already running; this request did not run a second restore."}
    async with _run_lock:
        live_url = os.getenv("MONGO_URL", "")
        live_name = os.getenv("MONGO_DB_NAME", live_db.name)
        scratch_url = os.getenv("SECOND_MONGO_URL")
        scratch_name = os.getenv("RESTORE_TEST_DB_NAME", SCRATCH_NAME)
        if scratch_name != SCRATCH_NAME:
            raise ScratchRefused(f"RESTORE_TEST_DB_NAME must be exactly {SCRATCH_NAME!r}.")
        assert_scratch_safe(live_url, live_name, scratch_url, scratch_name)
        tenants = await backup.list_tenants(live_db)
        open_tenants = []
        for org in tenants:
            flags = await backup._election_flags(live_db, org.get("org_id"))
            if backup._active(flags): open_tenants.append(org.get("slug") or backup.tenant_key(org.get("org_id")))
        if trigger == "schedule" and open_tenants:
            return {"status": "skipped", "reason": "An election is open; scheduled restore test skipped.", "open_tenants": open_tenants}
        if trigger == "manual" and open_tenants and not override_election_guard:
            return {"status": "warning", "requires_confirmation": True,
                    "reason": "An election is open. Confirm the extra restore-test load before overriding."}

        steps = []
        warnings = []
        failures = []
        def safe_detail(value):
            return str(value)[:450]
        async def record(name, status, detail):
            item = {"name": name, "status": status, "detail": safe_detail(detail), "at": now_utc()}
            steps.append(item)
            if progress:
                try: await progress(name, status, safe_detail(detail), len(steps), 11)
                except Exception: pass
        client = None
        keep_data = os.getenv("RESTORE_TEST_KEEP_DATA", "false").lower() == "true"
        flushed_start = False
        run_result = {"status": "failed", "steps": steps, "warnings": warnings, "failures": failures}
        try:
            await record("guards", "running", "Checking scratch name and cluster separation")
            client = AsyncIOMotorClient(scratch_url, maxPoolSize=2, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
            await assert_not_same_nodes(live_db.client, client)
            await record("guards", "passed", "Live and scratch point at separate clusters; scratch name is restore_test")
            deleted = await flush_scratch(client, live_url, live_name, scratch_name, live_client=live_db.client)
            flushed_start = True
            await record("flush_start", "passed", f"Cleared {deleted} old scratch collections")

            cfg = backup.load_config()
            s3 = backup.make_client(cfg)
            per_tenant = []
            restored_ids: dict[str, dict] = {}
            manifests_by_tenant: dict[str, dict] = {}
            for org in tenants:
                tenant = backup.tenant_key(org.get("org_id"))
                try:
                    prefixes = await asyncio.to_thread(list_backups, s3, cfg, tenant, "routine")
                    fulls = [p for p in prefixes if "/full-" in p]
                    if not fulls:
                        raise RuntimeError("No routine full backup exists.")
                    full_prefix = max(fulls, key=ts_of)
                    manifest = await asyncio.to_thread(read_manifest, s3, cfg, full_prefix)
                    age_hours = _prefix_age_hours(manifest)
                    active = backup._active(await backup._election_flags(live_db, org.get("org_id")))
                    max_age = float(os.getenv("BACKUP_MAX_FULL_AGE_HOURS", "36" if active else "192"))
                    if age_hours is None or age_hours > max_age:
                        raise RuntimeError(f"Newest full backup age {age_hours if age_hours is not None else 'unknown'} h exceeds {max_age:g} h.")
                    # Streamed: documents flow S3 -> scratch DB a batch at a time. Only the _ids are kept (the old
                    # plan_restore held every document of every tenant at once, which a 512 MB instance cannot).
                    org_id, stream = await asyncio.to_thread(open_restore_stream, s3, cfg, tenant, full_prefix, None, False)
                    if org_id != org.get("org_id"):
                        stream.close()
                        raise RuntimeError(f"Manifest org_id {org_id!r} does not match live tenant {org.get('org_id')!r}.")
                    merged = await stream_apply(client[scratch_name], org_id, stream, replace=True, tenant=tenant)
                    counts = {name: len(found) for name, found in merged.items()}
                    restored_ids[tenant] = merged
                    count_errors = []
                    for collection, docs in merged.items():
                        have = await client[scratch_name][collection].count_documents(restore_filter(collection, org_id))
                        if have != len(docs): count_errors.append(f"{collection} expected {len(docs)}, found {have}")
                    if count_errors:
                        raise RuntimeError("Restored count mismatch: " + "; ".join(count_errors[:5]))
                    await record(f"restore_{tenant}", "passed", f"{len(merged)} collections restored and counts matched; backup age {age_hours:.1f} h")
                    manifests_by_tenant[tenant] = manifest
                    per_tenant.append({"tenant": tenant, "org_id": org_id, "full_prefix": full_prefix,
                                       "age_hours": round(age_hours, 2), "counts": counts,
                                       # asset lists can run to hundreds of entries; they bloat the job document
                                       # and every /summary response, so keep only the summary fields.
                                       "manifest": {**{k: v for k, v in manifest.items() if k not in ("assets", "asset_failures", "collections")},
                                                    "asset_count": len(manifest.get("assets", []))}})
                except Exception as exc:
                    failures.append({"tenant": tenant, "error": safe_detail(exc)})
                    await record(f"restore_{tenant}", "failed", exc)

            # Restore platform_settings from a separate _global full. Never blend global settings into a tenant restore.
            try:
                global_prefixes = await asyncio.to_thread(list_backups, s3, cfg, "_global", "routine")
                global_fulls = [p for p in global_prefixes if "/full-" in p]
                if not global_fulls: raise RuntimeError("No global platform_settings full backup exists.")
                global_prefix = max(global_fulls, key=ts_of)
                _, global_stream = await asyncio.to_thread(open_restore_stream, s3, cfg, "_global", global_prefix, None, True)
                global_docs = await stream_apply(client[scratch_name], None, global_stream, replace=True, tenant="_global")
                for name, docs in global_docs.items():
                    have = await client[scratch_name][name].count_documents({})
                    if have != len(docs): raise RuntimeError(f"{name} expected {len(docs)}, found {have}")
                await record("global_settings", "passed", "Global platform_settings backup verified and loaded")
            except Exception as exc:
                failures.append({"tenant": "_global", "error": safe_detail(exc)})
                await record("global_settings", "failed", exc)

            # Chain verify and live-id comparison for every tenant whose backup loaded.
            chain_results = []
            for org in tenants:
                tenant = backup.tenant_key(org.get("org_id")); merged = restored_ids.get(tenant)
                if merged is None: continue
                org_id = org.get("org_id")
                chain = await chain_verify_db(client[scratch_name], org_id)
                uncheckpointed = await count_uncheckpointed_events(client[scratch_name], org_id)
                chain_results.append({"tenant": tenant, **chain, "uncheckpointed_events": uncheckpointed})
                if not chain.get("valid"):
                    failures.append({"tenant": tenant, "error": "Chain Verify invalid on restored copy"})
                    await record(f"chain_{tenant}", "failed", chain.get("first_mismatch_checkpoint_id", "Invalid chain"))
                else:
                    await record(f"chain_{tenant}", "passed", f"{chain.get('checkpoints_verified', 0)} checkpoints; {uncheckpointed} uncheckpointed events")
                    if uncheckpointed:
                        warnings.append({"tenant": tenant, "uncheckpointed_events": uncheckpointed})
                vote_ids = list(merged.get("vote_events", ()))
                if vote_ids:
                    live_ids = await _live_ids(live_db.vote_events, vote_ids, {"org_id": org_id})
                    missing = [str(i) for i in vote_ids if i not in live_ids]
                    if missing:
                        failures.append({"tenant": tenant, "error": f"{len(missing)} backup vote id(s) are missing from live"})
                        await record(f"live_vote_ids_{tenant}", "failed", f"{len(missing)} vote id(s) present in backup but missing from live")
                # Other collections missing a backup row from live are warnings, not hard failures.
                for name, doc_map in merged.items():
                    if name in {"vote_events", "organizations", "platform_settings"} or not doc_map: continue
                    ids = list(doc_map)
                    owner = {"org_key": tenant} if name == "sms_usage" else {"org_id": org_id}
                    live_ids = await _live_ids(live_db[name], ids, owner)
                    missing_n = sum(1 for i in ids if i not in live_ids)
                    if missing_n:
                        warnings.append({"tenant": tenant, "collection": name, "missing_from_live": missing_n})
                # At most five S3 asset heads per tenant. Missing assets are warnings.
                assets = manifests_by_tenant.get(tenant, {}).get("assets", [])
                for asset in assets[:5]:
                    try:
                        await asyncio.to_thread(s3.head_object, Bucket=cfg["bucket"], Key=asset["key"])
                    except Exception:
                        warnings.append({"tenant": tenant, "asset_missing": True})
            await record("live_comparison", "failed" if any("vote id" in x.get("error", "") for x in failures) else "passed",
                         "Checked restored vote ids against live; other missing rows are warnings")
            uncovered = await backup.coverage_audit(live_db)
            if uncovered:
                warnings.append({"uncovered_collections": uncovered})
                await record("coverage_audit", "warning", "Uncovered tenant-data collections: " + ", ".join(uncovered))
            else:
                await record("coverage_audit", "passed", "No uncovered tenant-data collections detected")
            run_result = {"status": "failed" if failures else ("warning" if warnings else "passed"),
                          "steps": steps, "warnings": warnings, "failures": failures,
                          "tenants": per_tenant, "chain_verify": chain_results,
                          "uncovered_collections": uncovered, "keep_data": keep_data}
        except Exception as exc:
            failures.append({"error": safe_detail(exc)})
            await record("restore_test", "failed", exc)
            run_result = {"status": "failed", "steps": steps, "warnings": warnings, "failures": failures}
        finally:
            if client:
                if not keep_data:
                    try:
                        removed = await flush_scratch(client, live_url, live_name, scratch_name, live_client=live_db.client)
                        await record("flush_end", "passed", f"Cleared {removed} scratch collections")
                    except Exception as exc:
                        failures.append({"error": "Scratch cleanup failed: " + safe_detail(exc)})
                        await record("flush_end", "failed", exc)
                        run_result["status"] = "failed"
                client.close()
        run_result["steps"] = steps
        run_result["warnings"] = warnings
        run_result["failures"] = failures
        if run_result.get("status") == "failed":
            await alert_critical("[BallotBox] Restore test failed", str(failures[:10]))
        elif run_result.get("status") == "warning":
            await alert_warning("[BallotBox] Restore test completed with warnings", str(warnings[:10]))
        return run_result
