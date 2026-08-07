"""
Seeds local Mongo with test data for load-testing / manual multi-org testing.
Run this AFTER the local backend is up and running (uvicorn main:app --reload).

Creates:
  - Two orgs: "kyuccu" and "ask" (for multi-org testing)
  - Positions + candidates for each org
  - N normalized, pre-authenticated voters per org (so Locust/manual testing
    can skip OTP entirely and go straight to /vote or /vote-bulk)

For single-org testing, just point your frontend .env at one slug and ignore
the other. To also test the legacy/no-org path, omit X-Org-Slug entirely
when calling the API (works automatically — org_id stays None).

Usage:
    python seed_test_data.py
"""
import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("SEED_API_BASE", "http://127.0.0.1:8000")
SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID", "localadmin")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "LocalTest123!")

ORGS = [
    {"name": "KYUCCU Test Org", "slug": "kyuccu"},
    {"name": "ASK Test Org",    "slug": "ask"},
]

VOTERS_PER_ORG = 50  # bump for a bigger Locust pool later

POSITIONS = ["President", "Vice President", "Treasurer"]


async def login_superadmin(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{API_BASE}/verify-admin", json={
        "student_id": SUPER_ADMIN_ID,
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
        # look it up instead
        listing = await client.get(f"{API_BASE}/superadmin/orgs", headers={"Authorization": f"Bearer {token}"})
        for o in listing.json():
            if o["slug"] == org["slug"]:
                return o["org_id"] if "org_id" in o else o["_id"]
        raise RuntimeError(f"Could not find existing org '{org['slug']}' after 400")
    resp.raise_for_status()
    return resp.json()["org_id"]


async def seed_org(client: httpx.AsyncClient, token: str, org: dict):
    print(f"\n=== Seeding {org['name']} ({org['slug']}) ===")
    org_id = await create_org(client, token, org)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": org["slug"]}

    # Positions
    for i, pos_name in enumerate(POSITIONS):
        r = await client.post(f"{API_BASE}/positions", json={"name": pos_name, "order": i}, headers=headers)
        if r.status_code >= 400:
            print(f"  position '{pos_name}' skipped/failed: {r.status_code} {r.text[:100]}")

    # Two candidates per position
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
                print(f"  candidate '{cand['name']}' skipped/failed: {r.status_code} {r.text[:100]}")

    print(f"  {len(POSITIONS)} positions, {len(POSITIONS) * 2} candidates created")

    # Voters — imported via CSV upload, matching the real ASK IT-admin flow
    csv_lines = ["student_id,full_name,phone_numbers"]
    voter_ids = []
    for i in range(VOTERS_PER_ORG):
        sid = f"{org['slug']}-voter-{i:04d}"
        voter_ids.append(sid)
        csv_lines.append(f"{sid},Test Voter {i},256700000{i:03d}")
    csv_content = "\n".join(csv_lines)

    files = {"file": ("voters.csv", csv_content, "text/csv")}
    r = await client.post(f"{API_BASE}/admin/import-voters", files=files, headers=headers)
    if r.status_code >= 400:
        print(f"  voter import failed: {r.status_code} {r.text[:200]}")
    else:
        print(f"  {VOTERS_PER_ORG} voters imported")

    return voter_ids


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Logging in as superadmin...")
        token = await login_superadmin(client)
        print("Logged in.\n")

        all_voter_ids = {}
        for org in ORGS:
            voter_ids = await seed_org(client, token, org)
            all_voter_ids[org["slug"]] = voter_ids

        print("\n=== Done ===")
        for slug, ids in all_voter_ids.items():
            print(f"{slug}: {len(ids)} voters, e.g. {ids[0]}")
        print(
            "\nNote: seeded voters still need OTP verification (or a direct "
            "DB/Locust flow) to reach 'authenticated' status before /vote will "
            "accept them — DEBUG_MODE=true logs the OTP to the backend console "
            "instead of sending real SMS."
        )


if __name__ == "__main__":
    asyncio.run(main())