"""One-off, restartable migration of Mongo analytics history into Neon.

Required environment variables:
  MONGO_URL, MONGO_DB_NAME, ANALYTICS_POSTGRES_URL
Optional:
  ANALYTICS_POSTGRES_POOLED=true when the URL contains Neon's -pooler hostname.

Run outside voting hours after switching the app to Postgres, with --cutoff set to
the switch day (UTC, YYYY-MM-DD). Counter rows are copied for the last 400 days up to
and INCLUDING the cutoff day: Mongo stops receiving writes at the switch, so its cutoff-day
document holds only the pre-switch part of that day and is added to what Postgres has
already recorded since the switch (each Mongo document is applied once, by the ledger).
The verification compares only the days strictly before the cutoff, because the cutoff
day legitimately differs (it also holds live Postgres counts). Heat docs have no day dimension, so all are copied using the
Postgres import ledger to make retries idempotent without losing pre-cutover counts.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from analytics_store import PostgresAnalyticsStore, flatten_counter_document


def _parse_id(value: str | None):
    if not value:
        return None
    try:
        from bson import ObjectId
        return ObjectId(value)
    except Exception:
        return value


async def copy_history(db, store, cutoff: date, *, batch_size: int = 500, pause: float = 0.75, after_id=None,
                       heat_after_id=None, say=print, progress=None) -> tuple[int, dict]:
    """Copy and verify Mongo analytics history into `store`. Shared by the command line and the Performance tab.

    Returns (exit_code, summary). 0 = copied and verified, 3 = verification failed. Errors propagate to the caller.
    `progress(summary)` is called after every batch so a caller can show a live count.
    """
    lower_day = (cutoff - timedelta(days=400)).isoformat()
    counter_coll, heat_coll = db.analytics_counters, db.analytics_heat
    summary: dict[str, Any] = {"counter_docs": 0, "counter_rows": 0, "heat_docs": 0, "heat_rows": 0,
                               "already_imported": 0, "verify": None, "mismatches": 0}

    def tick():
        if progress:
            progress(dict(summary))

    counter_estimate = await counter_coll.estimated_document_count()
    heat_estimate = await heat_coll.estimated_document_count()
    say(f"Mongo counters estimate: {counter_estimate}")
    say(f"Mongo heat estimate: {heat_estimate}")
    counter_filter_sample = {"day": {"$gte": lower_day, "$lte": cutoff.isoformat()}}
    sample = await counter_coll.find(counter_filter_sample).limit(100).to_list(length=100)
    sample_rows = [len(flatten_counter_document(doc)) for doc in sample]
    average_fields = (sum(sample_rows) / len(sample_rows)) if sample_rows else 0
    say(f"Preflight sample: {len(sample)} counter docs, average {average_fields:.1f} numeric fields/doc.")
    say(f"Rough counter row estimate (all retained counter docs, sample-based): {counter_estimate * average_fields:.0f}; measure Neon storage after a first batch.")
    say(f"Copying counter docs where {lower_day} <= day <= {cutoff.isoformat()} (the cutoff day is added to, not overwritten).")
    say("Copying all heat docs (the schema has no day field); import ledger prevents double-add on rerun.")

    counter_filter: dict[str, Any] = {"day": {"$gte": lower_day, "$lte": cutoff.isoformat()}}
    verify_filter: dict[str, Any] = {"day": {"$gte": lower_day, "$lt": cutoff.isoformat()}}
    after = after_id
    last_id = str(after) if after is not None else ""
    while True:
        query = dict(counter_filter)
        if after is not None:
            query["_id"] = {"$gt": after}
        batch = await counter_coll.find(query).sort("_id", 1).limit(batch_size).to_list(length=batch_size)
        if not batch:
            break
        result = await store.copy_history_batch(batch, [])
        summary["counter_docs"] += len(batch)
        summary["counter_rows"] += result["counter_rows"]
        summary["already_imported"] += result["skipped_documents"]
        after = batch[-1]["_id"]
        last_id = str(after)
        say(f"counter docs={summary['counter_docs']} rows={summary['counter_rows']} skipped={summary['already_imported']} last_id={last_id}")
        tick()
        await asyncio.sleep(pause)

    # Heat documents are cumulative. A document-level ledger entry and data upsert
    # share a transaction, so retries add each old count once and only once.
    heat_after = heat_after_id
    heat_skipped = 0
    while True:
        query = {"_id": {"$gt": heat_after}} if heat_after is not None else {}
        batch = await heat_coll.find(query).sort("_id", 1).limit(batch_size).to_list(length=batch_size)
        if not batch:
            break
        result = await store.copy_history_batch([], batch)
        summary["heat_docs"] += len(batch)
        summary["heat_rows"] += result["heat_rows"]
        heat_skipped += result["skipped_documents"]
        heat_after = batch[-1]["_id"]
        say(f"heat docs={summary['heat_docs']} rows={summary['heat_rows']} skipped={heat_skipped} last_id={heat_after}")
        tick()
        await asyncio.sleep(pause)
    summary["already_imported"] += heat_skipped

    # Independent check after the import: sums by org/kind/field must match over the
    # exact retained, pre-cutoff day range. This adds a second paced scan of Mongo.
    expected = defaultdict(int)
    scanned = 0
    async for doc in counter_coll.find(verify_filter):
        for row in flatten_counter_document(doc):
            expected[(row[0], row[2], row[7])] += row[8]
        scanned += 1
        if scanned % 500 == 0:
            await asyncio.sleep(pause)       # keep the verification scan as gentle as the copy
    actual_rows = await store.counter_totals(cutoff.isoformat(), lower_day)
    actual = {(str(row["org_id"]), str(row["kind"]), str(row["field"])): int(row["total"])
              for row in actual_rows}
    mismatches = [(key, expected.get(key, 0), actual.get(key, 0))
                  for key in (set(expected) | set(actual)) if expected.get(key, 0) != actual.get(key, 0)]
    # Heat has no day field and Postgres keeps counting live, so the check is one-sided: for every org the
    # Postgres heat total must be at least the Mongo total (live clicks only add to it).
    heat_expected = defaultdict(int)
    async for doc in heat_coll.find({}, {"org_id": 1, "n": 1}):
        heat_expected[str(doc.get("org_id"))] += int(doc.get("n", 0))
    heat_actual = await store.heat_totals()
    heat_short = [(k, v, heat_actual.get(k, 0)) for k, v in heat_expected.items() if heat_actual.get(k, 0) < v]
    if heat_short:
        say(f"VERIFY FAILED (heat): {len(heat_short)} orgs have a lower Postgres total than Mongo, e.g. {heat_short[:5]}")
        summary.update(verify="failed", mismatches=len(heat_short))
        return 3, summary
    say("Migration batch complete.")
    say(f"COUNTERS: docs_seen={summary['counter_docs']}, numeric_rows_inserted={summary['counter_rows']}, already_imported={summary['already_imported']}, last_id={last_id or '(none)'}")
    say(f"HEAT: docs_seen={summary['heat_docs']}, heat_docs_added={summary['heat_rows']}, already_imported={heat_skipped}, last_id={heat_after or '(none)'}")
    if mismatches:
        say(f"VERIFY FAILED: {len(mismatches)} org/kind/field totals differ. First mismatches:")
        for key, mongo_total, pg_total in mismatches[:10]:
            say(f"  {key}: Mongo={mongo_total}, Postgres={pg_total}")
        summary.update(verify="failed", mismatches=len(mismatches))
        return 3, summary
    say(f"VERIFY PASSED: {len(expected)} org/kind/field totals match for {lower_day} <= day < {cutoff.isoformat()}; heat totals are at least the Mongo totals.")
    say("Still compare dashboard summaries for three orgs/date ranges before dropping Mongo collections.")
    summary["verify"] = "passed"
    return 0, summary


async def _copy(args) -> int:
    load_dotenv()
    mongo_url = os.getenv("MONGO_URL", "").strip()
    db_name = os.getenv("MONGO_DB_NAME", "").strip()
    pg_url = os.getenv("ANALYTICS_POSTGRES_URL", "").strip()
    if not mongo_url or not db_name or not pg_url:
        print("ERROR: MONGO_URL, MONGO_DB_NAME and ANALYTICS_POSTGRES_URL are required.", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    db = client[db_name]
    pooled = os.getenv("ANALYTICS_POSTGRES_POOLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    store = PostgresAnalyticsStore(pg_url, pooled=pooled)
    try:
        # This utility is an operator tool, so run sql/analytics_postgres_schema.sql
        # as the Neon owner first, and pass an app URL with only CRUD privileges here.
        await store.ensure_schema(create=False)
        code, _ = await copy_history(db, store, date.fromisoformat(args.cutoff), batch_size=args.batch_size, pause=args.pause,
                                     after_id=_parse_id(args.after_id), heat_after_id=_parse_id(args.heat_after_id))
        return code
    except Exception as exc:
        print(f"ERROR: migration stopped safely: {store.safe_error(exc)}", file=sys.stderr)
        return 1
    finally:
        await store.close()
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True, help="UTC cutoff day (YYYY-MM-DD), normally the flip day")
    parser.add_argument("--batch-size", type=int, default=500, choices=range(500, 1001), metavar="500..1000")
    parser.add_argument("--pause", type=float, default=0.75, help="seconds between batches (default 0.75)")
    parser.add_argument("--after-id", help="resume counter scan after this Mongo _id (ObjectId hex or string)")
    parser.add_argument("--heat-after-id", help="resume heat scan after this Mongo _id (ObjectId hex or string)")
    args = parser.parse_args()
    if args.pause < 0 or args.pause > 30:
        parser.error("--pause must be between 0 and 30 seconds")
    return asyncio.run(_copy(args))


if __name__ == "__main__":
    raise SystemExit(main())
