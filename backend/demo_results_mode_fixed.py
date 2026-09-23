"""
Proves the FIX: on one running backend, org A can be 'live' (public/transparent)
while org B is 'certified' (gated) at the same time — via a per-org PUT, not env.
"""
import asyncio, os
os.environ.setdefault("SUPER_ADMIN_ID", "root")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "x")
os.environ.setdefault("JWT_SECRET_KEY", "demo-secret")
os.environ.setdefault("DEBUG_MODE", "true")
os.environ["PUBLIC_RESULTS_MODE"] = "certified"   # process-wide DEFAULT only, org A will override it

import httpx
from mongomock_motor import AsyncMongoMockClient
import main
from auth import create_access_token


async def make_org(db, slug, name):
    org = await db.organizations.insert_one({"slug": slug, "name": name})
    org_id = str(org.inserted_id)
    await db.settings.insert_one({"name": "branding", "org_id": org_id, "org_name": name,
                                   "support_phone": "256700000000"})
    await db.candidates.insert_one({"name": "Cand A", "position": "President", "org_id": org_id, "order": 1})
    await db.settings.insert_one({"name": "election_config", "org_id": org_id,
                                   "is_open": False, "is_certified": False})
    sa_token = create_access_token(subject="root", role="superadmin", org_id=org_id)
    return org_id, sa_token


async def main_demo():
    main.client = None
    db = AsyncMongoMockClient()["demo2"]
    main.db = db
    org_a, tok_a = await make_org(db, "kyuccu", "Org A (kyuccu)")
    org_b, tok_b = await make_org(db, "ask", "Org B (ask)")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as client:
        print(f"Process default (PUBLIC_RESULTS_MODE env) = {os.environ['PUBLIC_RESULTS_MODE']!r}\n")

        # Org A superadmin explicitly sets THEIR org to 'live' (transparency), org B left on default.
        put = await client.put("/superadmin/security-settings",
                                json={"reason": "org A wants live public results", "public_results_mode": "live"},
                                headers={"Authorization": f"Bearer {tok_a}", "X-Org-Slug": "kyuccu"})
        print(f"PUT org A public_results_mode=live -> {put.status_code}")
        print(f"  org A settings now: public_results_mode={put.json()['settings']['public_results_mode']}\n")

        r_a = await client.get("/election-results", headers={"X-Org-Slug": "kyuccu"})
        r_b = await client.get("/election-results", headers={"X-Org-Slug": "ask"})
        print("Same running process, same env var, different per-org outcome:")
        print(f"  org A (kyuccu, set to live)          public /election-results -> {r_a.status_code} {'(open)' if r_a.status_code==200 else r_a.json()}")
        print(f"  org B (ask, left on env default=certified) public /election-results -> {r_b.status_code} {'(open)' if r_b.status_code==200 else r_b.json()}")

if __name__ == "__main__":
    asyncio.run(main_demo())
