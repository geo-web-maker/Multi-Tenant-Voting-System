"""
Check (and optionally repair) registration numbers that are not stored in canonical form.

Usage:
    python check_reg_numbers.py                  # CHECK ONLY, all organisations
    python check_reg_numbers.py --org <org_id>   # check one organisation
    python check_reg_numbers.py --fix            # repair what is safe to repair
Conflicts and voters who already voted are only reported. Take a backup before --fix on a live election.
"""
import argparse, asyncio, os
import motor.motor_asyncio
from dotenv import load_dotenv
from regno_audit import audit_reg_numbers

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")


async def main(org_id, fix):
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    r = await audit_reg_numbers(client["electiondbaccounting"], org_id=org_id, fix=fix)
    v = r["voters"]
    print(("FIX" if fix else "CHECK ONLY"), "- scope:", org_id or "all organisations")
    print(f"voters: scanned={v['scanned']} non_canonical={v['non_canonical']} fixable={v['fixable']} "
          f"fixed={v['fixed']} conflicts={v['conflicts']} voted_review={v['voted_review']}")
    for k, c in r["other"].items():
        print(f"{k}: scanned={c['scanned']} non_canonical={c['non_canonical']} fixed={c['fixed']}")
    for s in r["samples"]:
        print(f"  [{s['kind']}] {s['collection']}: {s['old']!r} -> {s['new']!r}")
    if not fix and r["issues_found"]:
        print("\nRe-run with --fix to repair the fixable ones.")
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", default=None)
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.org, a.fix))
