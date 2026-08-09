"""
Seeds local Mongo with test data for load-testing / manual multi-org testing.
Run this AFTER the local backend is up and running (uvicorn main:app --reload).

Creates:
  - Three orgs: "kyuccu", "ask", "umosan" (for multi-org testing)
  - A legacy/no-org dataset (no X-Org-Slug header — tests single-tenant fallback)
  - Positions + candidates for each of the four
  - N voters per dataset, imported via CSV (same real path ASK's IT admin uses)

NOTE: /admin/import-voters does one unbatched DB write per CSV row. At 5000
rows this import will be genuinely slow (observe and time it) — that's
useful data in itself, not a bug in this script.

Usage:
    python seed_test_data.py
"""
import asyncio
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("SEED_API_BASE", "http://127.0.0.1:8000")
SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID", "localadmin")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "LocalTest123!")

ORGS = [
    {"name": "KYUCCU Test Org", "slug": "kyuccu"},
    {"name": "ASK Test Org",    "slug": "ask"},
    {"name": "UMOSAN Test Org", "slug": "umosan"},
]

VOTERS_PER_ORG = 5000  # thousands per institution, to genuinely stress-test at scale

POSITIONS = ["President", "Vice President", "Treasurer"]


async def login_superadmin(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{API_BASE}/verify-admin", json={
        "email": SUPER_ADMIN_ID,
        "password": SUPER_ADMIN_PASSWORD,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


async def create_org(client: httpx.AsyncClient, token: str, org: dict) -> str:
    resp = await client.post(
        f"{API_BASE}/superadmin/orgs",
        json={"name": org["name"], "slug": org["slug"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 400 and "already taken" in resp.text:
        print(f"  org '{org['slug']}' already exists, skipping create")
        listing = await client.get(f"{API_BASE}/superadmin/orgs", headers={"Authorization": f"Bearer {token}"})
        for o in listing.json():
            if o["slug"] == org["slug"]:
                return o.get("org_id") or o.get("_id")
        raise RuntimeError(f"Could not find existing org '{org['slug']}' after 400")
    resp.raise_for_status()
    return resp.json()["org_id"]


async def seed_positions_and_candidates(client: httpx.AsyncClient, headers: dict, label: str):
    for i, pos_name in enumerate(POSITIONS):
        r = await client.post(f"{API_BASE}/positions", json={"title": pos_name, "order": i}, headers=headers)
        if r.status_code >= 400:
            print(f"  [{label}] position '{pos_name}' skipped/failed: {r.status_code} {r.text[:100]}")

    for pos_name in POSITIONS:
        for j in range(2):
            cand = {
                "name": f"{pos_name} Candidate {j+1}",
                "position": pos_name,
                "image_url": "https://placehold.co/200x200",
                "order": j,
            }
            r = await client.post(f"{API_BASE}/candidates", json=cand, headers=headers)
            if r.status_code >= 400:
                print(f"  [{label}] candidate '{cand['name']}' skipped/failed: {r.status_code} {r.text[:100]}")

    print(f"  [{label}] {len(POSITIONS)} positions, {len(POSITIONS) * 2} candidates created")


async def seed_voters(client: httpx.AsyncClient, headers: dict, label: str, prefix: str) -> list[str]:
    csv_lines = ["student_id,full_name,phone"]
    voter_ids = []
    for i in range(VOTERS_PER_ORG):
        sid = f"{prefix}-voter-{i:05d}"
        voter_ids.append(sid)
        csv_lines.append(f"{sid},Test Voter {i},2567{i:08d}")
    csv_content = "\n".join(csv_lines)

    files = {"file": ("voters.csv", csv_content, "text/csv")}
    print(f"  [{label}] importing {VOTERS_PER_ORG} voters, this may take a while (unbatched writes)...")
    start = time.monotonic()
    r = await client.post(f"{API_BASE}/admin/import-voters", files=files, headers=headers)
    elapsed = time.monotonic() - start
    if r.status_code >= 400:
        print(f"  [{label}] voter import failed after {elapsed:.1f}s: {r.status_code} {r.text[:200]}")
        return []
    print(f"  [{label}] {VOTERS_PER_ORG} voters imported in {elapsed:.1f}s ({VOTERS_PER_ORG/elapsed:.1f} rows/sec)")
    return voter_ids


async def seed_org(client: httpx.AsyncClient, token: str, org: dict) -> list[str]:
    print(f"\n=== Seeding {org['name']} ({org['slug']}) ===")
    await create_org(client, token, org)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": org["slug"]}
    await seed_positions_and_candidates(client, headers, org["slug"])
    return await seed_voters(client, headers, org["slug"], org["slug"])


async def seed_legacy_no_org(client: httpx.AsyncClient, token: str) -> list[str]:
    """No X-Org-Slug header at all — tests the legacy/single-tenant fallback
    path where request.state.org_id stays None throughout."""
    print(f"\n=== Seeding legacy/no-org dataset ===")
    headers = {"Authorization": f"Bearer {token}"}  # no X-Org-Slug
    await seed_positions_and_candidates(client, headers, "legacy")
    return await seed_voters(client, headers, "legacy", "legacy")


async def main():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print("Logging in as superadmin...")
        token = await login_superadmin(client)
        print("Logged in.\n")

        all_voter_ids = {}
        for org in ORGS:
            all_voter_ids[org["slug"]] = await seed_org(client, token, org)

        all_voter_ids["_legacy_no_org"] = await seed_legacy_no_org(client, token)

        print("\n=== Done ===")
        total = 0
        for slug, ids in all_voter_ids.items():
            if ids:
                print(f"{slug}: {len(ids)} voters, e.g. {ids[0]}")
                total += len(ids)
            else:
                print(f"{slug}: 0 voters (import failed — check errors above)")
        print(f"\nTotal voters seeded across all datasets: {total}")
        print(
            "\nNote: seeded voters still need OTP verification before /vote "
            "will accept them — DEBUG_MODE=true logs the OTP to the backend "
            "console instead of sending real SMS."
        )


if __name__ == "__main__":
    asyncio.run(main())