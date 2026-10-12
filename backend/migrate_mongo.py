"""CLI fallback for a guarded, re-runnable Mongo migration.

Usage: python migrate_mongo.py [--dry-run] [--mirror-deletes] [--include-security] [--force]
Env: OLD_MONGO_URL source, MONGO_URL target, MONGO_DB_NAME database name.
"""
import argparse
import asyncio
import os
import sys
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from migrate_core import migrate_database, MigrationRefused

load_dotenv()

async def _run(args):
    old, new = os.getenv("OLD_MONGO_URL"), os.getenv("MONGO_URL")
    db_name = os.getenv("MONGO_DB_NAME", "electiondbaccounting")
    if not old or not new:
        raise SystemExit("Set OLD_MONGO_URL (source) and MONGO_URL (target).")
    src_client = AsyncIOMotorClient(old, serverSelectionTimeoutMS=15000, maxPoolSize=2)
    dst_client = AsyncIOMotorClient(new, serverSelectionTimeoutMS=15000, maxPoolSize=2)
    try:
        result = await migrate_database(src_client[db_name], dst_client[db_name],
            mode="plan" if args.dry_run else ("final" if args.mirror_deletes else "copy"),
            include_security=args.include_security, force=args.force, source_url=old, target_url=new)
        for row in result.get("collections", []):
            print(f"{row['collection']:<28} source={row.get('source', 0):<7} target={row.get('target', 0)}" +
                  (f" verified={row.get('verified')}" if "verified" in row else ""))
        if result["status"] == "failed":
            raise SystemExit(f"VERIFY FAILED for: {result.get('mismatches', [])}")
        print("Dry run: nothing written." if args.dry_run else "All collections copied and verified.")
    finally:
        src_client.close(); dst_client.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mirror-deletes", action="store_true")
    parser.add_argument("--include-security", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except MigrationRefused as exc:
        raise SystemExit(str(exc))

if __name__ == "__main__":
    main()
