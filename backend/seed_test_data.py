"""
Seeds local Mongo with test data for load-testing / manual multi-org testing.
Run this AFTER the local backend is up and running (uvicorn main:app --reload).

Creates:
  - Three orgs: "kyuccu", "ask", "umosan" (for multi-org testing)
  - A legacy/no-org dataset (no X-Org-Slug header — tests single-tenant fallback)
  - Positions + candidates for each of the four (skipped if already seeded —
    see org_already_seeded() — so re-running this script doesn't duplicate them)
  - N voters per dataset, imported via CSV (same real path ASK's IT admin uses)
  - One IT Admin, Commissioner, Financial Controller, and Overseer per org,
    promoted from the imported voter pool via the real toggle/set-credentials
    endpoints, so you can see the org/role split working end to end

NOTE: /admin/import-voters does one unbatched DB write per CSV row. At 5000
rows this import will be genuinely slow (observe and time it) — that's
useful data in itself, not a bug in this script. Override VOTERS_PER_ORG via
the SEED_VOTERS_PER_ORG env var for faster local iteration.

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

# Override with SEED_VOTERS_PER_ORG=50 (etc.) for fast local iteration —
# 5000 is the realistic stress-test number, not what you want while
# checking role/org isolation by hand.
VOTERS_PER_ORG = int(os.getenv("SEED_VOTERS_PER_ORG", "5000"))

POSITIONS = ["President", "Vice President", "Treasurer"]

# Every role in the system, seeded per-org so you can see the org split
# working (or breaking) across all of them at once, not just voters.
# Each entry pulls one already-imported voter into that role via the same
# toggle -> set-credentials flow the Superadmin portal uses, so this is
# exercising the real code path, not a DB shortcut.
ROLE_SEEDS = [
    # (role label for printing, toggle endpoint, set-credentials endpoint, email local-part)
    ("IT Admin",              "it-admins",             "it-admins",             "itadmin"),
    ("Commissioner",          "commissioners",         "commissioners",         "commissioner"),
    ("Financial Controller",  "financial-controllers", "financial-controllers", "finance"),
    ("Overseer",              "overseers",              "overseers",             "overseer"),
]


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


async def org_already_seeded(client: httpx.AsyncClient, headers: dict) -> bool:
    """
    Best-effort idempotency check so re-running this script (interrupted
    run, or just wanting fresh voters) doesn't duplicate positions and
    candidates — that's what happened when the script got run twice against
    the same org without this check: 6 positions and 12 candidates instead
    of 3 and 6. Uses GET /candidates as the signal since it's a confirmed
    existing read endpoint scoped by X-Org-Slug — if this org already has
    any candidates, assume seed_positions_and_candidates already ran.
    """
    r = await client.get(f"{API_BASE}/candidates", headers=headers)
    if r.status_code >= 400:
        return False
    try:
        return len(r.json()) > 0
    except Exception:
        return False


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


async def seed_org_roles(client: httpx.AsyncClient, headers: dict, label: str, voter_ids: list[str]) -> dict:
    """
    Pulls the first few voters already imported for this org into each
    non-voter role (IT admin, Commissioner, Financial Controller, Overseer)
    using the actual toggle -> set-credentials endpoints — same path the
    Superadmin portal uses, so this exercises the real permission logic
    instead of writing role flags straight into Mongo.

    Needs at least 1 imported voter per role (4 total) to have something to
    promote — safe no-op with a printed warning if voter import failed.
    """
    created = {}
    if len(voter_ids) < len(ROLE_SEEDS):
        print(f"  [{label}] not enough voters to seed roles, skipping")
        return created

    for i, (role_label, toggle_prefix, cred_prefix, email_local) in enumerate(ROLE_SEEDS):
        sid = voter_ids[i]
        toggle_resp = await client.post(
            f"{API_BASE}/superadmin/{toggle_prefix}/{sid}/toggle", headers=headers
        )
        if toggle_resp.status_code >= 400:
            print(f"  [{label}] {role_label} toggle for {sid} failed: {toggle_resp.status_code} {toggle_resp.text[:100]}")
            continue

        email = f"{email_local}+{label}@test.local"
        cred_resp = await client.post(
            f"{API_BASE}/superadmin/{cred_prefix}/{sid}/set-credentials",
            json={"email": email},
            headers=headers,
        )
        if cred_resp.status_code >= 400:
            print(f"  [{label}] {role_label} set-credentials for {sid} failed: {cred_resp.status_code} {cred_resp.text[:100]}")
            continue

        created[role_label] = {"student_id": sid, "email": email}
        print(f"  [{label}] {role_label}: {sid} / {email} (temp password logged on backend console under DEBUG_MODE)")

    return created


async def seed_org(client: httpx.AsyncClient, token: str, org: dict) -> dict:
    print(f"\n=== Seeding {org['name']} ({org['slug']}) ===")
    await create_org(client, token, org)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": org["slug"]}

    if await org_already_seeded(client, headers):
        print(f"  [{org['slug']}] candidates already exist, skipping positions/candidates re-seed")
    else:
        await seed_positions_and_candidates(client, headers, org["slug"])

    voter_ids = await seed_voters(client, headers, org["slug"], org["slug"])
    roles = await seed_org_roles(client, headers, org["slug"], voter_ids)
    return {"voter_ids": voter_ids, "roles": roles}


async def seed_legacy_no_org(client: httpx.AsyncClient, token: str) -> list[str]:
    """No X-Org-Slug header at all — tests the legacy/single-tenant fallback
    path where request.state.org_id stays None throughout."""
    print(f"\n=== Seeding legacy/no-org dataset ===")
    headers = {"Authorization": f"Bearer {token}"}  # no X-Org-Slug

    if await org_already_seeded(client, headers):
        print("  [legacy] candidates already exist, skipping positions/candidates re-seed")
    else:
        await seed_positions_and_candidates(client, headers, "legacy")

    return await seed_voters(client, headers, "legacy", "legacy")


async def main():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print("Logging in as superadmin...")
        token = await login_superadmin(client)
        print("Logged in.\n")

        all_data = {}
        for org in ORGS:
            all_data[org["slug"]] = await seed_org(client, token, org)

        legacy_voter_ids = await seed_legacy_no_org(client, token)
        all_data["_legacy_no_org"] = {"voter_ids": legacy_voter_ids, "roles": {}}

        print("\n=== Done ===")
        total = 0
        for slug, data in all_data.items():
            ids = data["voter_ids"]
            if ids:
                print(f"{slug}: {len(ids)} voters, e.g. {ids[0]}")
                total += len(ids)
            else:
                print(f"{slug}: 0 voters (import failed — check errors above)")
        print(f"\nTotal voters seeded across all datasets: {total}")

        print("\n=== Role split (per org, so you can see isolation across the boundary) ===")
        for slug, data in all_data.items():
            if not data["roles"]:
                continue
            print(f"\n{slug}:")
            for role_label, info in data["roles"].items():
                print(f"  {role_label:<22} student_id={info['student_id']:<20} email={info['email']}")

        print(
            "\nNote: seeded voters still need OTP verification before /vote "
            "will accept them — DEBUG_MODE=true logs the OTP to the backend "
            "console instead of sending real SMS. The same applies to the "
            "temp passwords issued to IT Admin / Commissioner / Financial "
            "Controller / Overseer accounts above — check the backend "
            "console output from this run for each one's temp password."
        )
        print(
            "\nTo check isolation manually: log in as one org's Commissioner "
            "(or any role) and confirm you cannot see/act on another org's "
            "candidates, applications, or voters — that's the actual thing "
            "worth glitch-hunting here, not just that the accounts exist."
        )


if __name__ == "__main__":
    asyncio.run(main())