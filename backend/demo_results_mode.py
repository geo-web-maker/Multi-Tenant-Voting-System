"""
Live demo, run against an in-memory Mongo (no real network, no real services):
  1. Proves PUBLIC_RESULTS_MODE=certified actually gates /election-results
     (403 before certify, 200 after, using the real toggle-certification endpoint).
  2. Proves it is ONE setting for the whole process, not per-org: two tenants
     ("kyuccu" and "ask") on the same running backend both get the SAME
     gate, even though only one of them has been certified.

Run: python demo_results_mode.py
"""
import asyncio, os
os.environ.setdefault("SUPER_ADMIN_ID", "root")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "x")
os.environ.setdefault("JWT_SECRET_KEY", "demo-secret")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["PUBLIC_RESULTS_MODE"] = "certified"   # the setting under test

import httpx
from mongomock_motor import AsyncMongoMockClient
import main
from auth import create_access_token


async def make_org(db, slug, name):
    org = await db.organizations.insert_one({"slug": slug, "name": name})
    org_id = str(org.inserted_id)
    await db.settings.insert_one({"name": "branding", "org_id": org_id, "org_name": name,
                                   "support_phone": "256700000000"})
    # chief commissioner voter record, so the certify endpoint's auth passes
    await db.voters.insert_one({"student_id": "chief", "full_name": "Chief Commissioner",
                                 "phone_numbers": ["256700000099"], "has_voted": False,
                                 "org_id": org_id, "is_commissioner": True, "is_chief_commissioner": True})
    await db.candidates.insert_one({"name": "Cand A", "position": "President", "org_id": org_id, "order": 1})
    # election_config: closed, not certified — required before certify is allowed
    await db.settings.insert_one({"name": "election_config", "org_id": org_id,
                                   "is_open": False, "is_certified": False})
    chief_token = create_access_token(subject="chief", role="commission", org_id=org_id)
    return org_id, chief_token


async def main_demo():
    main.client = None  # not used in this demo path
    db = AsyncMongoMockClient()["demo"]
    main.db = db

    org_a, tok_a = await make_org(db, "kyuccu", "Org A (kyuccu)")
    org_b, tok_b = await make_org(db, "ask", "Org B (ask)")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as client:

        print(f"PUBLIC_RESULTS_MODE = {main.PUBLIC_RESULTS_MODE!r}\n")

        # --- Step 1: before certifying, public results blocked for BOTH orgs ---
        r_a = await client.get("/election-results", headers={"X-Org-Slug": "kyuccu"})
        r_b = await client.get("/election-results", headers={"X-Org-Slug": "ask"})
        print("BEFORE certifying org A:")
        print(f"  org A (kyuccu) public /election-results -> {r_a.status_code} {r_a.json()}")
        print(f"  org B (ask)    public /election-results -> {r_b.status_code} {r_b.json()}\n")

        # --- Step 2: certify ONLY org A, via the real endpoint ---
        cert = await client.post("/admin/toggle-certification",
                                  headers={"Authorization": f"Bearer {tok_a}", "X-Org-Slug": "kyuccu"})
        print(f"Certifying org A via POST /admin/toggle-certification -> {cert.status_code} {cert.json()}\n")

        # --- Step 3: check both orgs again ---
        r_a2 = await client.get("/election-results", headers={"X-Org-Slug": "kyuccu"})
        r_b2 = await client.get("/election-results", headers={"X-Org-Slug": "ask"})
        print("AFTER certifying ONLY org A:")
        print(f"  org A (kyuccu) public /election-results -> {r_a2.status_code} {r_a2.json()}")
        print(f"  org B (ask)    public /election-results -> {r_b2.status_code} {r_b2.json()}\n")

        print("--- What this shows ---")
        print("Org A is certified, org B is not — the DATA (is_certified) is correctly per-org.")
        print("But the GATE MODE itself (PUBLIC_RESULTS_MODE=certified) is one process-wide")
        print("setting read once from the environment (main.py:4160). There is no way, with")
        print("this env var alone, to have org A run in 'live' (always public) while org B")
        print("runs in 'certified' (gated) on the same deployment — every tenant is stuck on")
        print("whatever mode the environment variable says, and only the is_certified FLAG")
        print("is per-org.")

if __name__ == "__main__":
    asyncio.run(main_demo())
