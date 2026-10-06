"""
Load test simulating real voter behavior: verify-identity -> verify-otp ->
vote-bulk. Each task iteration claims a fresh, never-repeated seeded voter,
so the test generates continuous real vote traffic for the whole run instead
of every simulated user voting once and then idly re-hitting "Already voted".

Each simulated user is pinned to one org for its whole session (picked
randomly in on_start), so a single run generates real concurrent
cross-tenant traffic — the actual condition worth testing for a multi-tenant
system, not just sequential single-org checks.

Reads the OTP directly from local Mongo (bypassing SMS entirely) rather than
adding any DEBUG_MODE response field to main.py — keeps the tested app code
byte-for-byte identical to what runs in production.

Requires:
  - Local backend running (uvicorn main:app --port 8000), with DEBUG_MODE=true
    in its .env so it never calls the real EgoSMS API.
  - Local Mongo running as a single-node replica set (required for
    session.with_transaction to work), with seed_test_data.py already run
    against it.
  - pip install locust pymongo

Usage:
    locust -f locustfile.py --host http://127.0.0.1:8000

Then open http://localhost:8089 in a browser to set user count / spawn rate
and start the test, or run headless (see notes at the bottom of this file).

If you seeded a smaller pool for fast local iteration
(SEED_VOTERS_PER_ORG=50 python seed_test_data.py), set the same env var
here so the two scripts stay in sync:
    SEED_VOTERS_PER_ORG=50 locust -f locustfile.py --host http://127.0.0.1:8000
"""
import random
import os
import itertools
from threading import Lock
from pymongo import MongoClient
from locust import HttpUser, task, between, events

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "electiondbaccounting")

# Which seeded datasets to spread load across. Each simulated user picks one
# at random in on_start() — this generates real concurrent cross-tenant
# traffic in a single run, which is the actual thing worth load-testing for
# a multi-tenant system (does org isolation hold under concurrent load, not
# just sequential manual checks). "" = the legacy/no-org dataset.
ORGS_TO_TEST = ["kyuccu", "ask", "umosan", ""]

# Reads the same SEED_VOTERS_PER_ORG env var seed_test_data.py uses, so the
# two scripts can't silently drift — set it once, both pick it up. Falls
# back to 5000 (the stress-test number) if unset, matching the seed
# script's own default.
VOTERS_PER_ORG = int(os.getenv("SEED_VOTERS_PER_ORG", "5000"))

mongo_client = MongoClient(MONGO_URL)
db = mongo_client[DB_NAME]

# One counter per org, not one shared counter — otherwise whichever org a
# user happens to draw first would burn through the shared index space and
# other orgs would be under-represented relative to how random.choice
# actually split the users. Each org's voter pool is consumed independently.
_voter_counters = {org: itertools.count() for org in ORGS_TO_TEST}
_counter_locks = {org: Lock() for org in ORGS_TO_TEST}


def claim_next_voter_index(org_slug: str) -> int:
    with _counter_locks[org_slug]:
        idx = next(_voter_counters[org_slug])
    return idx % VOTERS_PER_ORG  # wrap around if the run outlasts the pool


def get_org_id(slug: str):
    if not slug:
        return None
    org = db.organizations.find_one({"slug": slug})
    return str(org["_id"]) if org else None


# Resolved once at startup for every org in the list, not per-request.
ORG_IDS = {slug: get_org_id(slug) for slug in ORGS_TO_TEST}


def read_otp_from_db(student_id: str, org_id) -> str | None:
    """Reads the OTP the real /verify-identity call just wrote to db.otps —
    same collection, same document shape the app itself uses. No app code
    touched; this only reads, mirroring what a person checking their own
    phone would receive."""
    query = {"student_id": student_id}
    if org_id:
        query["org_id"] = org_id
    record = db.otps.find_one(query)
    return record["code"] if record else None


class VoterUser(HttpUser):
    """Each task iteration claims a fresh, never-repeated seeded voter and
    casts one vote as them — simulating continuous new voters arriving
    throughout the test, not one voter per simulated user for the whole run.
    wait_time mimics a real person reading the ballot rather than every
    user hammering instantly.

    Each simulated user is pinned to one org for its whole lifetime (picked
    once in on_start) — a real voter never switches institutions mid-session
    either, and pinning per-user rather than per-task keeps the counters in
    claim_next_voter_index() meaningful (each org's index space advances
    independently of how often that org gets drawn)."""
    wait_time = between(1, 3)

    def on_start(self):
        self.org_slug = random.choice(ORGS_TO_TEST)
        self.org_id = ORG_IDS[self.org_slug]
        self.voter_prefix = self.org_slug if self.org_slug else "legacy"
        self.headers = {"X-Org-Slug": self.org_slug} if self.org_slug else {}

    @task
    def full_voting_flow(self):
        idx = claim_next_voter_index(self.org_slug)
        student_id = f"{self.voter_prefix}-voter-{idx:05d}"
        full_name = f"Test Voter {idx}"

        # Step 1: verify identity -> triggers OTP "send" (mocked, DEBUG_MODE)
        with self.client.post(
            "/verify-identity",
            json={"student_id": student_id, "full_name": full_name},
            headers=self.headers,
            name="/verify-identity",
            catch_response=True,
        ) as resp:
            if resp.status_code == 400 and "Already voted" in resp.text:
                # Only possible now if the pool wraps around mid-run —
                # not a failure, just an already-used voter recycled.
                resp.success()
                return
            if resp.status_code != 200:
                resp.failure(f"verify-identity failed: {resp.status_code} {resp.text[:150]}")
                return
            resp.success()

        # Step 2: read the OTP straight from Mongo (stands in for "checking
        # your phone") and verify it through the real endpoint
        otp = read_otp_from_db(student_id, self.org_id)
        if not otp:
            return  # OTP not written yet / race — skip this iteration

        with self.client.post(
            "/verify-otp",
            json={"student_id": student_id, "code": otp},
            headers=self.headers,
            name="/verify-otp",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"verify-otp failed: {resp.status_code} {resp.text[:150]}")
                return
            try:
                voter_token = resp.json()["voter_token"]
            except Exception:
                resp.failure("verify-otp response had no voter_token")
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
        chosen_ids = [random.choice(cands)["_id"] for cands in by_position.values()]

        with self.client.post(
            "/vote-bulk",
            json={"student_id": student_id, "candidate_ids": chosen_ids},
            headers={**self.headers, "X-Voter-Token": voter_token},
            name="/vote-bulk",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"vote-bulk failed: {resp.status_code} {resp.text[:150]}")
            else:
                resp.success()


class ResultsViewerUser(HttpUser):
    """Simulates someone with the public results page open: polls /election-status
    every 60 s and /election-results every 10 s, matching the real frontend's
    polling intervals (see PERFORMANCE_AUDIT.md section 4). This is the load the
    audit flagged as the actual risk on a free Atlas M0 tier — it scales with how
    many people are *watching*, not with how many students vote, so it is the one
    traffic shape the original VoterUser-only test never exercised. Spawn these
    alongside VoterUser (not instead of it) to see the combined ops/sec headroom
    the 5 s _RESULTS_TTL / _SETTINGS_TTL caches leave under the 100 ops/s cap."""
    wait_time = between(9, 11)   # ~ the frontend's 10 s results-poll cadence

    def on_start(self):
        self.org_slug = random.choice(ORGS_TO_TEST)
        self.headers = {"X-Org-Slug": self.org_slug} if self.org_slug else {}
        self._ticks = 0

    @task
    def poll_results(self):
        self.client.get("/election-results", headers=self.headers, name="/election-results")
        self._ticks += 1
        if self._ticks % 6 == 0:   # /election-status polls ~6x less often (60 s vs 10 s)
            self.client.get("/election-status", headers=self.headers, name="/election-status")


@events.quitting.add_listener
def _(environment, **kwargs):
    mongo_client.close()


# -----------------------------------------------------------------------------
# Scenario for THIS election: ~200 voters spread across one voting day, not a
# concurrency stress run. Run headless, scoped to one org, with a handful of
# results-watchers open at once (the realistic case — a few screens showing
# live turnout in a student union office, not 100 simultaneous viewers):
#
#   locust -f locustfile.py --host https://<your-render-app>.onrender.com \
#       --headless -u 25 -r 2 --run-time 10m \
#       VoterUser:5 ResultsViewerUser:1
#
# Read as: 25 total simulated clients, weighted 5 VoterUser : 1 ResultsViewerUser
# (so about 4 viewers in the mix), ramping 2/s, sustained for 10 minutes — this
# compresses "200 voters trickling in over 8 hours" into a worst-case burst far
# denser than the real day will ever be, which is the right direction to err for
# a capacity check. Watch Atlas's Operations/sec panel during the run (section 7
# of the audit) rather than trusting locust's own latency numbers alone, since
# the M0 cap is what actually bites, not request latency.
#
# Analytically, before running: 200 voters x 26 ops (section 0 of the audit) =
# 5,200 ops for the whole day's voting — about 0.18 ops/sec averaged over 8
# hours. Even compressed into a 10-minute burst that is only ~8.7 ops/sec from
# voting itself. Each results-watcher costs at most 1 cached-miss op per 5 s
# (the _RESULTS_TTL window) no matter how many people are looking, so a handful
# of open results tabs adds well under 1 op/sec combined. The free tier's
# 100 ops/sec cap is not the binding constraint for this scenario; the Render
# free-tier cold-start sleep is the more likely real-world failure mode, which
# is why the keep-warm /health ping during voting hours (see
# BALLOTBOX_PHASE_RUNBOOK.md) matters more here than the Atlas tier does.
# -----------------------------------------------------------------------------