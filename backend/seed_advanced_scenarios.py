"""
Seeds two extra orgs on top of whatever seed_test_data.py already created:

  "nomtest"   Nomination / consensus-policy testing.
              5 commissioners (so majority-of-total actually diverges from
              unanimity), a chief + deputy chief, a finance commissioner, an
              IT admin and a financial controller. Several applications in
              flight, DELIBERATELY left at different vote counts (0 votes,
              short of majority, contested) so you can log in as each
              commissioner yourself and cast the deciding vote through the
              UI rather than finding everything pre-resolved. Also seeds one
              in-progress candidate removal, four contact-change requests
              (one of each status), and three exception grants (active,
              timed, already-expired).

  "racetest"  Live Results / mobile-layout stress testing.
              5 positions engineered as: a tight race, a landslide, an
              unopposed seat, a 3-way split, and a pair of candidates with
              deliberately long names (the thing that broke the mobile card
              layout before). ~100 of the imported voters actually cast
              real ballots through /verify-identity -> /verify-otp ->
              /vote-bulk (not DB inserts) so vote_events, has_voted and the
              live tallies are all real. The remaining voters are left
              untouched for your own manual/search testing.

Both orgs also get distinct branding (name/colors) so the boot-splash and
official-report signature paths get exercised against more than one config.

WHERE THIS SCRIPT CUTS CORNERS (documented, not hidden):
  - Commissioner/IT-admin/financial-controller passwords are set through the
    real POST .../set-credentials endpoints (real code path, real temp
    password issued) and then IMMEDIATELY overwritten with a known password
    by writing directly to Mongo. That's the one piece of this script that
    is NOT going through the API — everything else (positions, candidates,
    applications, votes, contact changes, exception grants, actual ballots)
    goes through the real endpoints, so it lands in the activity log for
    real. This shortcut only exists so the script itself (and you) can log
    in without grepping the backend console for a random temp password.
  - OTP codes for the ~100 simulated voters are read directly out of
    db.otps after calling /verify-identity, for the same reason: DEBUG_MODE
    only logs them to the console, it doesn't return them from the API.

Needs direct Mongo access (MONGO_URL/MONGO_DB_NAME from backend/.env), same
as the backend process itself — run this on the same machine/network as
your local backend.

Usage:
    python seed_advanced_scenarios.py
"""
import asyncio
import os
import time
from datetime import datetime, timedelta

import bcrypt
import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

API_BASE = os.getenv("SEED_API_BASE", "http://127.0.0.1:8000")
SUPER_ADMIN_ID = os.getenv("SUPER_ADMIN_ID", "localadmin")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "LocalTest123!")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "electiondbaccounting")

# Known password used ONLY for seeded test accounts in this script.
# It satisfies MIN_PASSWORD_LENGTH (10) in main.py.
SEED_PASSWORD = "SeedTest123!"
SEED_PASSWORD_HASH = bcrypt.hashpw(SEED_PASSWORD.encode(), bcrypt.gensalt()).decode()

mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo[MONGO_DB_NAME]


# =============================================================================
# Shared helpers
# =============================================================================

async def login_superadmin(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{API_BASE}/verify-admin", json={
        "email": SUPER_ADMIN_ID, "password": SUPER_ADMIN_PASSWORD,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


async def create_org(client: httpx.AsyncClient, token: str, name: str, slug: str):
    resp = await client.post(f"{API_BASE}/superadmin/orgs", json={"name": name, "slug": slug},
                              headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 400 and "already taken" in resp.text:
        print(f"  org '{slug}' already exists, reusing it")
        return
    resp.raise_for_status()


def admin_headers(token: str, slug: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def import_voters_csv(client: httpx.AsyncClient, headers: dict, rows: list[str], label: str):
    csv_content = "\n".join(["student_id,full_name,phone"] + rows)
    files = {"file": ("voters.csv", csv_content, "text/csv")}
    r = await client.post(f"{API_BASE}/admin/import-voters", files=files, headers=headers)
    if r.status_code >= 400:
        print(f"  [{label}] voter import failed: {r.status_code} {r.text[:200]}")
    else:
        body = r.json()
        print(f"  [{label}] imported voters: {body.get('imported', body)}")


async def set_known_password(role: str, student_id: str, org_slug: str):
    """Overwrite the random temp password set by .../set-credentials with a
    known one so the script (and you) can log in deterministically. See the
    module docstring for why this one step bypasses the API."""
    field_map = {
        "commissioner": ("commissioner_password_hash", "commissioner_must_change_password"),
        "it_admin": ("it_admin_password_hash", "it_admin_must_change_password"),
        "financial_controller": ("financial_controller_password_hash", "financial_controller_must_change_password"),
        "overseer": ("overseer_password_hash", "overseer_must_change_password"),
    }
    hash_field, must_change_field = field_map[role]
    org = await db.organizations.find_one({"slug": org_slug})
    query = {"student_id": student_id}
    if org:
        query["org_id"] = str(org["_id"])
    await db.voters.update_one(
        query,
        {"$set": {hash_field: SEED_PASSWORD_HASH, must_change_field: False}},
    )


async def login_role(client: httpx.AsyncClient, org_slug: str, email: str) -> str:
    resp = await client.post(f"{API_BASE}/verify-admin",
                              json={"email": email, "password": SEED_PASSWORD},
                              headers={"X-Org-Slug": org_slug})
    resp.raise_for_status()
    return resp.json()["access_token"]


async def read_live_otp(org_slug: str, student_id: str) -> str | None:
    org = await db.organizations.find_one({"slug": org_slug})
    org_id = str((org or {}).get("_id", ""))
    doc = await db.otps.find_one({"org_id": org_id, "student_id": student_id})
    if not doc:
        doc = await db.otps.find_one({"student_id": student_id})  # legacy/no-org fallback
    return (doc or {}).get("code")


# =============================================================================
# PART A — "nomtest": consensus / nomination-queue testing
# =============================================================================

NOMTEST_SLUG = "nomtest"
NOMTEST_NAME = "Nomination Consensus Test Org"

# 12 voters: enough to cover 5 commissioners + it admin + finance controller
# + a handful of plain applicants, with a spread of phone edge cases.
NOMTEST_VOTER_ROWS = [
    "nom-voter-00,Grace Nabirye,0771000001",
    "nom-voter-01,Peter Okello,0772000002",
    "nom-voter-02,Sarah Kintu,0773000003",
    "nom-voter-03,David Mugisha,0774000004",
    "nom-voter-04,Esther Namuli,0775000005",
    "nom-voter-05,Brian Ssekandi,",                              # zero phone numbers
    "nom-voter-06,Doreen Achieng,0771111111/0771111111",         # duplicate number, should dedupe to 1
    "nom-voter-07,Kenneth Atim,0771222222/0779333333",           # two distinct numbers
    "nom-voter-08,Faith Nansubuga,12345",                        # malformed, should warn not reject
    "nom-voter-09,Moses Byaruhanga,0771444444",
    "nom-voter-10,Irene Nakato,0771555555",
    "nom-voter-11,Samuel Wanyama,0771666666",
]

COMMISSIONER_IDS = [f"nom-voter-0{i}" for i in range(5)]   # 00-04
IT_ADMIN_ID = "nom-voter-09"
FINANCE_CONTROLLER_ID = "nom-voter-10"
APPLICANT_IDS = {
    "president_a": "nom-voter-05",
    "president_b": "nom-voter-06",
    "secgen":       "nom-voter-07",
    "treasurer":    "nom-voter-08",
}


async def seed_nomtest_roles(client: httpx.AsyncClient, token: str) -> dict:
    headers = admin_headers(token, NOMTEST_SLUG)
    commissioner_emails = {}

    for i, sid in enumerate(COMMISSIONER_IDS):
        await client.post(f"{API_BASE}/superadmin/commissioners/{sid}/toggle", headers=headers)
        email = f"commissioner{i}@nomtest.local"
        r = await client.post(f"{API_BASE}/superadmin/commissioners/{sid}/set-credentials",
                               json={"email": email}, headers=headers)
        if r.status_code >= 400:
            print(f"  [nomtest] set-credentials failed for {sid}: {r.status_code} {r.text[:150]}")
            continue
        await set_known_password("commissioner", sid, NOMTEST_SLUG)
        commissioner_emails[sid] = email
        print(f"  [nomtest] commissioner {sid} / {email} / password={SEED_PASSWORD}")

    if commissioner_emails:
        chief, deputy, finance_comm = COMMISSIONER_IDS[0], COMMISSIONER_IDS[1], COMMISSIONER_IDS[2]
        await client.post(f"{API_BASE}/superadmin/commissioners/{chief}/set-chief", headers=headers)
        await client.post(f"{API_BASE}/superadmin/commissioners/{deputy}/set-deputy-chief", headers=headers)
        await client.post(f"{API_BASE}/superadmin/commissioners/{finance_comm}/set-finance-commissioner",
                           headers=headers)
        print(f"  [nomtest] chief={chief} deputy={deputy} finance-commissioner={finance_comm}")

    await client.post(f"{API_BASE}/superadmin/it-admins/{IT_ADMIN_ID}/toggle", headers=headers)
    it_email = "itadmin@nomtest.local"
    r = await client.post(f"{API_BASE}/superadmin/it-admins/{IT_ADMIN_ID}/set-credentials",
                           json={"email": it_email}, headers=headers)
    if r.status_code < 400:
        await set_known_password("it_admin", IT_ADMIN_ID, NOMTEST_SLUG)
        print(f"  [nomtest] it_admin {IT_ADMIN_ID} / {it_email} / password={SEED_PASSWORD}")

    await client.post(f"{API_BASE}/superadmin/financial-controllers/{FINANCE_CONTROLLER_ID}/toggle",
                       headers=headers)
    fc_email = "finance@nomtest.local"
    r = await client.post(f"{API_BASE}/superadmin/financial-controllers/{FINANCE_CONTROLLER_ID}/set-credentials",
                           json={"email": fc_email}, headers=headers)
    if r.status_code < 400:
        await set_known_password("financial_controller", FINANCE_CONTROLLER_ID, NOMTEST_SLUG)
        print(f"  [nomtest] financial_controller {FINANCE_CONTROLLER_ID} / {fc_email} / password={SEED_PASSWORD}")

    return {
        "commissioner_emails": commissioner_emails,
        "it_admin_email": it_email,
        "finance_controller_email": fc_email,
    }


async def seed_nomtest_positions(client: httpx.AsyncClient, token: str) -> dict:
    headers = admin_headers(token, NOMTEST_SLUG)
    ids = {}
    for i, title in enumerate(["President", "Secretary General", "Treasurer"]):
        r = await client.post(f"{API_BASE}/positions", json={"title": title, "order": i}, headers=headers)
        if r.status_code < 400:
            body = r.json()
            ids[title] = body.get("id") or body.get("_id")
    # /positions may not echo the id in every version — fall back to a read.
    if not all(ids.values()):
        r = await client.get(f"{API_BASE}/positions", headers=headers)
        if r.status_code < 400:
            for p in r.json():
                ids[p.get("title")] = p.get("id") or p.get("_id")
    print(f"  [nomtest] positions: {ids}")
    return ids


async def submit_application(client: httpx.AsyncClient, headers: dict, student_id: str,
                              full_name: str, position_id: str, manifesto: str) -> None:
    r = await client.post(f"{API_BASE}/apply", json={
        "student_id": student_id, "full_name": full_name,
        "position_id": position_id, "manifesto": manifesto,
    }, headers=headers)
    if r.status_code >= 400:
        print(f"  [nomtest] application for {full_name} failed: {r.status_code} {r.text[:150]}")


async def find_application_id(client: httpx.AsyncClient, headers: dict, student_id: str) -> str | None:
    r = await client.get(f"{API_BASE}/admin/applications", headers=headers)
    if r.status_code >= 400:
        return None
    for a in r.json():
        if a.get("student_id") == student_id:
            return a.get("id") or a.get("_id")
    return None


async def finance_clear(client: httpx.AsyncClient, headers: dict, app_id: str, finance_comm_id: str):
    r = await client.post(f"{API_BASE}/admin/applications/{app_id}/finance-clear",
                           json={"commissioner_id": finance_comm_id}, headers=headers)
    if r.status_code >= 400:
        print(f"  [nomtest] finance-clear failed for {app_id}: {r.status_code} {r.text[:150]}")


async def cast_commissioner_vote(client: httpx.AsyncClient, org_slug: str, commissioner_email: str,
                                  commissioner_id: str, app_id: str, vote: str, endpoint: str = "vote"):
    token = await login_role(client, org_slug, commissioner_email)
    headers = admin_headers(token, org_slug)
    r = await client.post(f"{API_BASE}/admin/applications/{app_id}/{endpoint}",
                           json={"commissioner_id": commissioner_id, "vote": vote}, headers=headers)
    if r.status_code >= 400:
        print(f"  [nomtest] {endpoint} by {commissioner_id} on {app_id} failed: {r.status_code} {r.text[:150]}")


async def seed_nomtest_applications(client: httpx.AsyncClient, token: str, position_ids: dict,
                                     commissioner_emails: dict, finance_email: str):
    headers = admin_headers(token, NOMTEST_SLUG)
    applicant_headers = {"X-Org-Slug": NOMTEST_SLUG}  # /apply is a voter-facing route, no admin token needed

    await submit_application(client, applicant_headers, APPLICANT_IDS["president_a"], "Brian Ssekandi",
                              position_ids["President"], "A short manifesto for president candidate A.")
    await submit_application(client, applicant_headers, APPLICANT_IDS["president_b"], "Doreen Achieng",
                              position_ids["President"], "A short manifesto for president candidate B.")
    await submit_application(client, applicant_headers, APPLICANT_IDS["secgen"], "Kenneth Atim",
                              position_ids["Secretary General"], "Running unopposed for Secretary General.")
    await submit_application(client, applicant_headers, APPLICANT_IDS["treasurer"], "Faith Nansubuga",
                              position_ids["Treasurer"], "Manifesto for the treasurer seat.")

    app_headers = admin_headers(token, NOMTEST_SLUG)
    app_a = await find_application_id(client, app_headers, APPLICANT_IDS["president_a"])
    app_b = await find_application_id(client, app_headers, APPLICANT_IDS["president_b"])
    app_sg = await find_application_id(client, app_headers, APPLICANT_IDS["secgen"])
    app_tr = await find_application_id(client, app_headers, APPLICANT_IDS["treasurer"])

    finance_comm_id = COMMISSIONER_IDS[2]
    for app_id in (app_a, app_b, app_sg, app_tr):
        if app_id:
            await finance_clear(client, app_headers, app_id, finance_comm_id)

    # President A: 2 of 5 commissioners approved — short of the 3-vote
    # majority. Left for you to log in as a 3rd commissioner and decide it.
    if app_a:
        await cast_commissioner_vote(client, NOMTEST_SLUG, commissioner_emails[COMMISSIONER_IDS[0]],
                                      COMMISSIONER_IDS[0], app_a, "approve")
        await cast_commissioner_vote(client, NOMTEST_SLUG, commissioner_emails[COMMISSIONER_IDS[1]],
                                      COMMISSIONER_IDS[1], app_a, "approve")
        print(f"  [nomtest] President A ({app_a}): 2/5 approve — one vote short of majority (3).")

    # President B: contested, 1 approve + 1 deny, still short either way.
    if app_b:
        await cast_commissioner_vote(client, NOMTEST_SLUG, commissioner_emails[COMMISSIONER_IDS[2]],
                                      COMMISSIONER_IDS[2], app_b, "approve")
        await cast_commissioner_vote(client, NOMTEST_SLUG, commissioner_emails[COMMISSIONER_IDS[3]],
                                      COMMISSIONER_IDS[3], app_b, "deny")
        print(f"  [nomtest] President B ({app_b}): 1 approve / 1 deny — contested, undecided.")

    # Secretary General: left completely untouched (not even finance-cleared
    # voting-wise beyond the clear above) so you can walk the whole flow —
    # vote, watch it resolve unopposed — from scratch.
    if app_sg:
        print(f"  [nomtest] Secretary General ({app_sg}): finance-cleared, 0 votes cast. Untouched for you.")

    # Treasurer: fully resolved by the script (3/5 approve) so there's an
    # approved candidate to test a removal vote against, below.
    treasurer_candidate_app_id = None
    if app_tr:
        for i in range(3):
            await cast_commissioner_vote(client, NOMTEST_SLUG, commissioner_emails[COMMISSIONER_IDS[i]],
                                          COMMISSIONER_IDS[i], app_tr, "approve")
        treasurer_candidate_app_id = app_tr
        print(f"  [nomtest] Treasurer ({app_tr}): 3/5 approve — resolved, candidate created.")

    # Removal in progress: 1 of 5 commissioners has voted to remove the
    # Treasurer candidate. Left short of majority for you to finish.
    if treasurer_candidate_app_id:
        await cast_commissioner_vote(client, NOMTEST_SLUG, commissioner_emails[COMMISSIONER_IDS[4]],
                                      COMMISSIONER_IDS[4], treasurer_candidate_app_id, "approve",
                                      endpoint="vote-remove")
        print(f"  [nomtest] Removal vote on Treasurer candidate: 1/5 — left in progress for you.")


async def seed_nomtest_contact_changes(client: httpx.AsyncClient, token: str, it_email: str,
                                        commissioner_emails: dict):
    # Roster freeze is required for contact-change requests to be accepted
    # at all (voting_frozen phase) — and roster_freeze_enabled defaults to
    # True, so opening ANY election on this org later also needs this set.
    headers = admin_headers(token, NOMTEST_SLUG)
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
    r = await client.put(f"{API_BASE}/superadmin/security-settings",
                          json={"roster_freeze_enabled": True, "roster_freeze_at": past,
                                "contact_change_required": True, "reason": "seed: enable contact-change testing"},
                          headers=headers)
    if r.status_code >= 400:
        print(f"  [nomtest] could not enable roster freeze for contact-change testing: "
              f"{r.status_code} {r.text[:150]}")
        return

    it_token = await login_role(client, NOMTEST_SLUG, it_email)
    it_headers = admin_headers(it_token, NOMTEST_SLUG)

    requests_to_make = [
        ("nom-voter-00", "phone_change", 0, "0771000001", "0771000099", "id_card", "pending"),
        ("nom-voter-01", "phone_change", 0, "0772000002", "0772000099", "id_card", "approve"),
        ("nom-voter-02", "phone_change", 0, "0773000003", "0773000099", "id_card", "deny"),
        ("nom-voter-03", "phone_add",   None, None, "0774000099", "id_card", "cancel"),
    ]

    chief_email = commissioner_emails.get(COMMISSIONER_IDS[0])
    comm_token = await login_role(client, NOMTEST_SLUG, chief_email) if chief_email else None
    comm_headers = admin_headers(comm_token, NOMTEST_SLUG) if comm_token else None

    for sid, change_type, index, expected_old, new_value, evidence_type, outcome in requests_to_make:
        payload = {
            "student_id": sid, "change_type": change_type, "new_value": new_value,
            "evidence_type": evidence_type, "evidence_note": "Verified against printed student ID at the desk.",
        }
        if index is not None:
            payload["index"] = index
        if expected_old is not None:
            payload["expected_old"] = expected_old
        r = await client.post(f"{API_BASE}/it-admin/contact-changes/request", json=payload, headers=it_headers)
        if r.status_code >= 400:
            print(f"  [nomtest] contact-change request for {sid} failed: {r.status_code} {r.text[:150]}")
            continue
        change_id = r.json().get("id")

        if outcome == "pending":
            print(f"  [nomtest] contact-change {change_id} for {sid}: left pending for you.")
        elif outcome == "cancel":
            cr = await client.post(f"{API_BASE}/it-admin/contact-changes/{change_id}/cancel",
                                    json={"reason": "Voter changed their mind."}, headers=it_headers)
            print(f"  [nomtest] contact-change {change_id} for {sid}: cancelled "
                  f"({'ok' if cr.status_code < 400 else cr.status_code}).")
        elif comm_headers:
            dr = await client.post(f"{API_BASE}/admin/contact-changes/{change_id}/decide",
                                    json={"decision": outcome, "note": "Reviewed evidence."}, headers=comm_headers)
            print(f"  [nomtest] contact-change {change_id} for {sid}: {outcome}d "
                  f"({'ok' if dr.status_code < 400 else dr.status_code}).")


async def seed_nomtest_exception_grants(client: httpx.AsyncClient, commissioner_emails: dict):
    chief_email = commissioner_emails.get(COMMISSIONER_IDS[0])
    if not chief_email:
        return
    async with httpx.AsyncClient(timeout=60.0) as client2:
        token = await login_role(client2, NOMTEST_SLUG, chief_email)
        headers = admin_headers(token, NOMTEST_SLUG)

        grants = [
            {"student_id": "nom-voter-11", "phase": "applications", "reason": "Late submission, network outage.",
             "expires_at": None, "label": "active, no expiry"},
            {"student_id": "nom-voter-11", "phase": "voting", "reason": "Travel documented, needs a late window.",
             "expires_at": (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z",
             "label": "active, expires in 2h"},
            {"student_id": "nom-voter-11", "phase": "results", "reason": "Short-lived grant to demonstrate expiry.",
             "expires_at": (datetime.utcnow() + timedelta(seconds=3)).isoformat() + "Z",
             "label": "will be expired by the time you look"},
        ]
        for g in grants:
            label = g.pop("label")
            r = await client2.post(f"{API_BASE}/admin/exception-grants", json=g, headers=headers)
            status = "ok" if r.status_code < 400 else f"{r.status_code} {r.text[:120]}"
            print(f"  [nomtest] exception grant ({label}): {status}")
        time.sleep(4)  # let the short-lived one actually expire before the script ends


async def seed_nomtest(client: httpx.AsyncClient, token: str):
    print(f"\n=== Seeding {NOMTEST_NAME} ({NOMTEST_SLUG}) ===")
    await create_org(client, token, NOMTEST_NAME, NOMTEST_SLUG)
    headers = admin_headers(token, NOMTEST_SLUG)
    await import_voters_csv(client, headers, NOMTEST_VOTER_ROWS, NOMTEST_SLUG)

    role_info = await seed_nomtest_roles(client, token)
    position_ids = await seed_nomtest_positions(client, token)
    await seed_nomtest_applications(client, token, position_ids,
                                     role_info["commissioner_emails"], role_info["finance_controller_email"])
    await seed_nomtest_contact_changes(client, token, role_info["it_admin_email"],
                                        role_info["commissioner_emails"])
    await seed_nomtest_exception_grants(client, role_info["commissioner_emails"])

    await client.post(f"{API_BASE}/superadmin/branding", json={
        "logo_url": "https://placehold.co/200x200?text=NOM",
        "primary_color": "#5b21b6", "accent_color": "#f59e0b",
        "org_name": "Nomination Consensus Test Org", "commissioner_name": "Grace Nabirye",
        "support_phone": "0771000001", "cc_list": ["registrar@nomtest.local"], "signatories": [],
    }, headers=headers)


# =============================================================================
# PART B — "racetest": Live Results / mobile-layout stress testing
# =============================================================================

RACETEST_SLUG = "racetest"
RACETEST_NAME = "Live Results Race Test Org"
RACE_VOTER_COUNT = 120
RACE_VOTERS_TO_ACTUALLY_VOTE = 100  # rest are left untouched for your own manual testing


async def seed_racetest_candidates(client: httpx.AsyncClient, token: str) -> dict:
    """Returns {position_title: [candidate_id, ...]} in creation order."""
    headers = admin_headers(token, RACETEST_SLUG)
    races = [
        ("Tight Race — President", ["Alina Kobusingye", "Martin Otieno"]),
        ("Landslide — Vice President", ["Rachel Tumusiime", "Joel Wamala"]),
        ("Unopposed — General Secretary", ["Patricia Namutebi"]),
        ("Three-Way — Treasurer", ["Vincent Mubiru", "Josephine Alupo", "Fahad Ssentongo"]),
        ("Long Names — Publicity Secretary", [
            "Nakiwala-Bbosa Prossy Immaculate Kirabo",
            "Ssebugwawo Emmanuel Christopher Junior",
        ]),
    ]
    position_ids, candidate_ids = {}, {}
    for i, (title, _) in enumerate(races):
        r = await client.post(f"{API_BASE}/positions", json={"title": title, "order": i}, headers=headers)
        body = r.json() if r.status_code < 400 else {}
        position_ids[title] = body.get("id") or body.get("_id")

    for title, names in races:
        candidate_ids[title] = []
        for j, name in enumerate(names):
            r = await client.post(f"{API_BASE}/candidates", json={
                "name": name, "position": title, "image_url": "https://placehold.co/200x200", "order": j,
            }, headers=headers)
            if r.status_code < 400:
                candidate_ids[title].append(r.json().get("id"))
            else:
                print(f"  [racetest] candidate '{name}' failed: {r.status_code} {r.text[:120]}")
    print(f"  [racetest] {sum(len(v) for v in candidate_ids.values())} candidates across {len(races)} positions")
    return candidate_ids


async def open_racetest_election(client: httpx.AsyncClient, token: str):
    headers = admin_headers(token, RACETEST_SLUG)
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
    await client.put(f"{API_BASE}/superadmin/security-settings",
                      json={"roster_freeze_enabled": True, "roster_freeze_at": past,
                            "reason": "seed: open racetest for ballot casting"}, headers=headers)
    r = await client.post(f"{API_BASE}/admin/toggle-election", headers=headers)
    if r.status_code >= 400:
        print(f"  [racetest] could not open election: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [racetest] election open: {r.json()}")


def race_voter_rows() -> list[str]:
    rows = []
    for i in range(RACE_VOTER_COUNT):
        rows.append(f"race-voter-{i:04d},Race Voter {i:04d},07{70000000 + i:08d}")
    return rows


def build_ballot_plan(candidate_ids: dict) -> list[list[str]]:
    """One candidate_id list per voter, engineered to produce:
    - a tight President race (52/48 over 100 voters)
    - a landslide VP race (90/10)
    - an unopposed Sec-Gen (everyone who votes picks the only option)
    - a 3-way Treasurer split (50/30/20)
    - a 2-candidate Publicity Secretary race with long names (55/45)
    All five picks are bundled per voter via /vote-bulk, same as a real ballot.
    """
    pres = candidate_ids["Tight Race — President"]
    vp = candidate_ids["Landslide — Vice President"]
    sg = candidate_ids["Unopposed — General Secretary"]
    tr = candidate_ids["Three-Way — Treasurer"]
    pub = candidate_ids["Long Names — Publicity Secretary"]

    plans = []
    for i in range(RACE_VOTERS_TO_ACTUALLY_VOTE):
        ballot = [
            pres[0] if i < 52 else pres[1],
            vp[0] if i < 90 else vp[1],
            sg[0],
            tr[0] if i < 50 else (tr[1] if i < 80 else tr[2]),
            pub[0] if i < 55 else pub[1],
        ]
        plans.append(ballot)
    return plans


async def cast_one_ballot(client: httpx.AsyncClient, student_id: str, full_name: str, ballot: list[str]):
    headers = {"X-Org-Slug": RACETEST_SLUG}
    r = await client.post(f"{API_BASE}/verify-identity",
                           json={"student_id": student_id, "full_name": full_name}, headers=headers)
    if r.status_code == 200 and r.json().get("status") == "needs_selection":
        r = await client.post(f"{API_BASE}/verify-identity",
                               json={"student_id": student_id, "full_name": full_name, "phone_index": 0},
                               headers=headers)
    if r.status_code >= 400:
        return False

    code = await read_live_otp(RACETEST_SLUG, student_id)
    if not code:
        return False
    r = await client.post(f"{API_BASE}/verify-otp", json={"student_id": student_id, "code": code}, headers=headers)
    if r.status_code >= 400:
        return False

    r = await client.post(f"{API_BASE}/vote-bulk",
                           json={"student_id": student_id, "candidate_ids": ballot}, headers=headers)
    return r.status_code < 400


async def cast_racetest_ballots(client: httpx.AsyncClient, candidate_ids: dict):
    plans = build_ballot_plan(candidate_ids)
    ok, failed = 0, 0
    start = time.monotonic()
    for i, ballot in enumerate(plans):
        sid, name = f"race-voter-{i:04d}", f"Race Voter {i:04d}"
        if await cast_one_ballot(client, sid, name, ballot):
            ok += 1
        else:
            failed += 1
    elapsed = time.monotonic() - start
    print(f"  [racetest] {ok} ballots cast, {failed} failed, in {elapsed:.1f}s "
          f"({RACE_VOTER_COUNT - RACE_VOTERS_TO_ACTUALLY_VOTE} voters left untouched for manual testing)")


async def seed_racetest(client: httpx.AsyncClient, token: str):
    print(f"\n=== Seeding {RACETEST_NAME} ({RACETEST_SLUG}) ===")
    await create_org(client, token, RACETEST_NAME, RACETEST_SLUG)
    headers = admin_headers(token, RACETEST_SLUG)
    await import_voters_csv(client, headers, race_voter_rows(), RACETEST_SLUG)

    candidate_ids = await seed_racetest_candidates(client, token)
    await open_racetest_election(client, token)
    await cast_racetest_ballots(client, candidate_ids)

    await client.post(f"{API_BASE}/superadmin/branding", json={
        "logo_url": "https://placehold.co/200x200?text=RACE",
        "primary_color": "#065f46", "accent_color": "#dc2626",
        "org_name": "Live Results Race Test Org", "commissioner_name": "Alina Kobusingye",
        "support_phone": "0770000000", "cc_list": [], "signatories": [],
    }, headers=headers)


# =============================================================================
async def main():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print("Logging in as superadmin...")
        token = await login_superadmin(client)
        print("Logged in.")

        await seed_nomtest(client, token)
        await seed_racetest(client, token)

    print("\n=== Done ===")
    print(f"All seeded test-account passwords: {SEED_PASSWORD}")
    print("See VOTING_CONSENSUS_SETUP.md for what's left open for you to test by hand.")

    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
