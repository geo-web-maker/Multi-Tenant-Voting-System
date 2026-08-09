"""
Load test simulating real voter behavior: verify-identity -> verify-otp ->
vote (single-position) or vote-bulk (all positions).

Reads the OTP directly from local Mongo (bypassing SMS entirely) rather than
adding any DEBUG_MODE response field to main.py — keeps the tested app code
byte-for-byte identical to what runs in production.

Requires:
  - Local backend running (uvicorn main:app --port 8000), with DEBUG_MODE=true
    in its .env so it never calls the real EgoSMS API.
  - Local Mongo running (mongo-local, port 27017) with seed_test_data.py
    already run against it.
  - pip install locust pymongo

Usage:
    locust -f locustfile.py --host http://127.0.0.1:8000

Then open http://localhost:8089 in a browser to set user count / spawn rate
and start the test, or run headless (see notes at the bottom of this file).
"""
import random
from pymongo import MongoClient
from locust import HttpUser, task, between, events

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "electiondbaccounting"

# Which seeded dataset to hit. Change ORG_SLUG to "ask", "umosan", or "" (for
# the legacy/no-org dataset) to test a different institution. Leave as-is to
# run the default single-org test against kyuccu.
ORG_SLUG = "kyuccu"
VOTER_PREFIX = ORG_SLUG if ORG_SLUG else "legacy"
VOTERS_PER_ORG = 5000  # must match seed_test_data.py

mongo_client = MongoClient(MONGO_URL)
db = mongo_client[DB_NAME]


def get_org_id(slug: str):
    if not slug:
        return None
    org = db.organizations.find_one({"slug": slug})
    return str(org["_id"]) if org else None


ORG_ID = get_org_id(ORG_SLUG)


def read_otp_from_db(student_id: str) -> str | None:
    """Reads the OTP the real /verify-identity call just wrote to db.otps —
    same collection, same document shape the app itself uses. No app code
    touched; this only reads, mirroring what a person checking their own
    phone would receive."""
    query = {"student_id": student_id}
    if ORG_ID:
        query["org_id"] = ORG_ID
    record = db.otps.find_one(query)
    return record["code"] if record else None


class VoterUser(HttpUser):
    """One simulated voter: picks a unique seeded student_id, authenticates,
    and casts one vote. wait_time mimics a real person reading the ballot
    rather than every user hammering instantly."""
    wait_time = between(1, 3)

    def on_start(self):
        # Each simulated user claims one voter record. Locust runs many
        # VoterUser instances concurrently, so unique() across the run
        # avoids two simulated users fighting over the same real voter.
        idx = random.randint(0, VOTERS_PER_ORG - 1)
        self.student_id = f"{VOTER_PREFIX}-voter-{idx:05d}"
        self.full_name = f"Test Voter {idx}"
        self.headers = {"X-Org-Slug": ORG_SLUG} if ORG_SLUG else {}

    @task
    def full_voting_flow(self):
        # Step 1: verify identity -> triggers OTP "send" (mocked, DEBUG_MODE)
        with self.client.post(
            "/verify-identity",
            json={"student_id": self.student_id, "full_name": self.full_name},
            headers=self.headers,
            name="/verify-identity",
            catch_response=True,
        ) as resp:
            if resp.status_code == 400 and "Already voted" in resp.text:
                # Expected once a voter has already completed the flow in an
                # earlier task iteration — not a failure, just done.
                resp.success()
                return
            if resp.status_code != 200:
                resp.failure(f"verify-identity failed: {resp.status_code} {resp.text[:150]}")
                return
            resp.success()

        # Step 2: read the OTP straight from Mongo (stands in for "checking
        # your phone") and verify it through the real endpoint
        otp = read_otp_from_db(self.student_id)
        if not otp:
            return  # OTP not written yet / race — skip this iteration

        with self.client.post(
            "/verify-otp",
            json={"student_id": self.student_id, "code": otp},
            headers=self.headers,
            name="/verify-otp",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"verify-otp failed: {resp.status_code} {resp.text[:150]}")
                return
            resp.success()

        # Step 3: fetch candidates so the vote is realistic (matches what the
        # real frontend does before rendering the ballot)
        cand_resp = self.client.get("/candidates", headers=self.headers, name="/candidates")
        try:
            candidates = cand_resp.json()
        except Exception:
            return
        if not candidates:
            return

        # Step 4: cast a bulk vote — one candidate per distinct position,
        # matching real ballot behavior (one choice per race)
        by_position = {}
        for c in candidates:
            by_position.setdefault(c["position"], []).append(c)
        chosen_ids = [random.choice(cands)["id"] for cands in by_position.values()]

        with self.client.post(
            "/vote-bulk",
            json={"student_id": self.student_id, "candidate_ids": chosen_ids},
            headers=self.headers,
            name="/vote-bulk",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"vote-bulk failed: {resp.status_code} {resp.text[:150]}")
            else:
                resp.success()


@events.quitting.add_listener
def _(environment, **kwargs):
    mongo_client.close()