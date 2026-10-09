# BallotBox — AI Implementation & Verification Playbook

**Purpose.** Instructions for an AI coding agent to apply `IMPROVEMENT_GUIDE.md` to the BallotBox codebase (`Multi-Tenant Voting System`), plus one **new change (WP-12: IT Admin voter-register export)** that is *not* in the original guide. Every work package (WP) says what to change, how to prove it works, and what must not break.

**Read this whole Part A before touching any file.**

---

## Part A — Operating rules

### A1. Non-negotiable rules

1. **Never read, print, log, commit or paste the contents of any `*.env` file** (`backend.env`, `frontend.env`, `backend/.env`, `backend/loadtest.env`, `backend/loadtest/.env`, `frontend/.env`, `frontend/.env.org-b`). Key names are fine; values are not. Do not `cat` them, do not `grep` them without `-l`, do not include them in test output or reports.
2. **Work on a branch** (`improvements/<wp-id>`), one WP per branch or one commit per WP. Never mix WPs in one commit. Commit message: `WP-<n>: <what>`.
3. **Re-verify before you edit.** The guide's "✅ Code-verified" claims were true for a snapshot. Line numbers drift. Before each WP run the **Pre-check** commands. If the code does not match the guide's claim, **stop that WP**, write the mismatch in `DEVIATIONS.md` (see A6) and do not guess.
4. **Do not do anything tagged ⚠️ "Needs data" as if it were fact.** Those need the user's live data or devices. Implement only the parts that are safe regardless (the WP says which) and list the rest in `DEVIATIONS.md` as "needs human check".
5. **The server is the authority.** Never hide or disable a security-relevant control *only* in the browser. Every permission in this playbook is enforced on the server first; the UI is a convenience.
6. **Multi-tenant safety.** Every DB query on tenant data must be scoped with `org_query(request, ...)` (or `_oq(org_id, ...)` outside a request). Every cache must be keyed by org. Every new test must include a cross-tenant case where the data is tenant-scoped.
7. **Do not widen scope.** Do not refactor, rename, reformat, or "improve" code outside the WP. Do not upgrade dependencies. Do not delete files except where a WP says so, and then only after the stated diff check.
8. **Do not run anything against production** (no real SMS, no real Mongo Atlas, no deployed URLs). Tests use `mongomock-motor` and `httpx.ASGITransport`. Load tests are run by the human.
9. **If a test fails, fix the code or the test for a stated reason.** Never delete or weaken an existing test to make a suite pass. Never mark a test `skip`/`xfail` without an entry in `DEVIATIONS.md`.
10. **Audit-log hygiene.** `/admin/audit-log` is visible to *every* admin role (Overseer, Commission, Finance, IT). Audit entries you add must contain **no voter names, no phone numbers, no search text, no registration numbers of voters**. Counts, modes, formats and booleans only.

### A2. Environment setup (do once, record results)

The sandbox may not have the backend dependencies. Check, then install into a virtualenv (ask the human if network is blocked).

```bash
cd "Multi-Tenant Voting System/backend"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio mongomock-motor
export SUPER_ADMIN_ID=root SUPER_ADMIN_PASSWORD=x JWT_SECRET_KEY=test-secret DEBUG_MODE=true   # same defaults tests/conftest.py uses
pytest -q 2>&1 | tail -30
```

```bash
cd ../frontend
npm ci            # package-lock.json is the lockfile to keep (see WP-H)
npm run lint
npx vite build    # record the size of dist/assets/index-*.js
```

**Record a BASELINE block** at the top of `DEVIATIONS.md` before any change:

| Item | Value |
|---|---|
| `pytest -q` result | `N passed, M failed, K skipped` (list failing test names) |
| `npm run lint` | error / warning counts |
| `vite build` entry chunk | raw KB / gzip KB |
| Node / Python versions | |

Any test already failing at baseline is **pre-existing**: note it, do not "fix" it unless a WP touches that code. Final acceptance is **"no new failures vs baseline"** plus all new tests green.

> The original guide notes the route tests could not be run in its sandbox because `mongomock_motor` was missing. Do not assume the suite is green: run it.

### A3. Test strategy (layers)

| Layer | Tool | Use for |
|---|---|---|
| L1 Static | `grep`/`rg`, `python -m py_compile`, `npm run lint` | Proving a string/pattern is (not) present; syntax |
| L2 Backend integration | `pytest` + `mongomock-motor` + `httpx.ASGITransport` (the `env` fixture in `backend/tests/test_flows.py`) | Every endpoint, permission, tenant isolation, audit, data shape |
| L3 Frontend logic | **Vitest** + jsdom + `@testing-library/react` (devDependencies only) | Components, hooks, pure helpers |
| L4 Build | `npx vite build` | Bundle/chunk assertions, no import errors |
| L5 Manual/browser | A scripted checklist the WP provides | Things only a real browser/device shows; clearly labelled **HUMAN** |

**Frontend test tooling (one dedicated commit, `WP-0: add vitest`).** There is no frontend test runner today. Add devDependencies only:

```bash
cd frontend
npm i -D vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom
```
Add to `package.json` scripts: `"test": "vitest run"`. Add to `vite.config.js` a `test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.js' }` block (keep existing config intact). `src/test/setup.js`: `import '@testing-library/jest-dom';`.
If adding devDependencies is forbidden, fall back: test pure helpers with Node's built-in runner (`node --test`) and move component behaviours to the L5 checklist, recording that in `DEVIATIONS.md`.

**Backend tests** live in `backend/tests/`, named `test_<wp>_*.py`, and reuse the fixture exactly like `tests/test_security_regressions.py` does:

```python
import pytest
import main
from tests.test_flows import env, START, Clock  # noqa: F401  (fixture + helpers)
pytestmark = pytest.mark.asyncio
```
`env` provides: `e.client` (httpx, header `X-Org-Slug: t1`), `e.db`, `e.org_id`, `e.tok(sub, role)` (returns auth headers), `e.it` (IT admin `it1` headers), `e.sa` (superadmin headers), `e.com1/e.com2/e.over`, and `await e.voter(sid, name, phones, **extra_fields)`. The fixture already creates voters `com1`, `com2`, `it1` (`is_it_admin=True`) and `v1`.

**Every WP has a "Done when" list. A WP is done only when: (a) its automated tests pass, (b) the full suites show no new failures vs baseline, (c) its L5 items are either ticked by a human or listed in `DEVIATIONS.md` as pending.**

### A4. Dependency map and order (conflicts to respect)

The original guide's order (Section 8) stands, with WP-12 inserted. Cross-WP interactions the AI must honour:

| If you do… | …then remember |
|---|---|
| WP-6 axios timeout (guide 3.6) | The export download (WP-12) needs a **per-request** `timeout: 120000` override. GET auto-retry must never retry POST. |
| WP-7 settings cache (guide 3.4) | **Never** cache the IT-admin export mode. It is read fresh from the voter document on every export and permission request (WP-12 §12.4). Do not route it through `cached_setting`. |
| WP-7 GZip | Register GZip *before* CORS so CORS stays outermost. WP-12 adds `expose_headers` to the same CORS block: edit that one call, do not add a second `CORSMiddleware`. |
| WP-2 lazy loading (guide 3.1) | New WP-12 component is imported inside `ITAdminDashboard.jsx`, which is already a lazy chunk. Do not import it from `App.jsx`. |
| WP-4/5 `data-track` names (guide 4.6) | Add `export-register`, `export-register-format` to the same naming list; names are `a-z0-9_-`, never include IDs. |
| WP-9 `seg` tagging (guide 5.4) | Export requests carry an `Authorization` header so they tag as `staff`. |
| Item 4.8 lost-response handling | Independent of WP-12, but both rely on the axios timeout from WP-6. |

---

## Part B — Work-package index

| WP | Guide § | Title | Effort | Risk |
|---|---|---|---|---|
| WP-0 | — | Test tooling + baseline | S | low |
| WP-1 | 2 | Secrets hygiene | S | low (human rotates) |
| WP-2 | 3.1 | Lazy-load dashboards | M | med |
| WP-3 | 3.2 | Skip fixed splash | S | low |
| WP-4 | 3.3 | Polling | M | med |
| WP-5 | 3.4, 3.5 | Backend caching, indexes, GZip, CORS max_age | M | med |
| WP-6 | 3.6, 4.4, 4.8 | Axios timeout/retry, client costs, apply form, voting flow | M–L | med |
| WP-7 | 4.1, 4.1a, 4.1b, 4.2, 4.3, 4.5, 4.6 | Phase banner, Help, Results states, login errors, data-track | M | low |
| WP-8 | 5.x | Analytics instrumentation + dashboard | M | med |
| WP-9 | 6.x | Admin insights | M | low |
| WP-H | 7 | Housekeeping | S | low |
| **WP-12** | **new** | **IT Admin voter-register export (none / redacted / full)** | **M–L** | **high (PII) — highest test rigour** |

Recommended execution order: WP-0 → WP-1 → WP-3 → WP-6(timeout part) → WP-7(login errors) → WP-8(button contrast) → WP-2 → WP-4 → WP-5 → WP-7(rest) → WP-6(rest) → **WP-12** → WP-8/9 → WP-H. WP-12 can be done any time after WP-0; it does not depend on the performance work.


---

# Part C — WP-12: IT Admin voter-register export (NEW)

> **Not in the original Improvement Guide.** Add it to that guide as a new §4.9 and as row 12 of its summary table: *"IT Admin voter-register export, controlled per IT admin (Off / Redacted / Full)"*.

## 12.0 Requirement (exact)

The IT admin needs to **export the voter register** because it is needed for their daily running. When allowed to see everything, **nothing may be redacted**. But this must **not be on by default or for everyone**: it is an option the **superadmin selects for each IT admin**, with three states:

| State | Meaning |
|---|---|
| **Off** (`none`) | The IT admin has **no export option at all**: no button, and the server refuses the request. **This is the default.** |
| **Redacted** (`redacted`) | The IT admin can export, with sensitive data masked. |
| **Full** (`full`) | The IT admin can export the register with **no information redacted** (complete phone numbers). |

## 12.1 Decisions already made (do not re-decide; do not expand)

| # | Decision | Reason |
|---|---|---|
| D1 | The setting is **per IT admin account**, changed **only by the superadmin**, in the **IT Admins** tab of the SuperAdmin dashboard, on that IT admin's card. | "Under the IT admin selected". |
| D2 | Stored on the IT admin's voter document as `it_admin_export_mode` ∈ `none\|redacted\|full`. **Missing, empty, wrong case or any other value means `none`** (fail closed). Also stored: `it_admin_export_mode_set_by`, `it_admin_export_mode_set_at`. | IT admins are voter documents with `is_it_admin: true` (see `toggle_it_admin`). |
| D3 | **Redacted** = *exactly what that IT admin already sees in their on-screen voter list*: full name, full registration number, **phones masked with `_mask_phone`**, enabled optional fields. The export must never reveal more than the screen does. **Full** = the stored values, unmasked. | Makes "redacted" precisely testable (export == list). If the owner later wants stricter redaction, change it in one function (`_export_row`) and the equality test. |
| D4 | Columns (both modes): `Registration Number`, `Full Name`, `Phone 1…Phone N` (N = most phone numbers any voter has, min 1), then one column per **enabled** voter field (label as configured). **Never** exported: `has_voted`, `last_status`, OTP data, tokens/JTIs, password hashes, staff-role flags, `added_by`, anything not in the allowlist. | Voting status must not leak to IT admins (the existing list hides it for them; only superadmin sees it). |
| D5 | HTTP method is **POST** `/admin/voters/export`. | The auth guard blocks non-GET for "View as" (read-only) tokens, so a superadmin previewing an IT admin **cannot** trigger a download. POST is also never cached or prefetched and puts nothing in URLs/logs. |
| D6 | v1 exports the **whole register of the caller's organisation** (no filters, no paging). | Daily-running use; fewer parameters = smaller attack surface. |
| D7 | Formats: `xlsx` (default) and `csv`. | Excel mangles long phone numbers in CSV (shows `2.56701E+11`); XLSX with text cells is safe. |
| D8 | **Only the `it_admin` role** can call the export. Superadmin and all other roles get 403 on these endpoints. | The request is about IT admins. Do not add superadmin export. |
| D9 | Every export, and every refused attempt, is **audit-logged** with no PII (see 12.4.7). The audit row is written **before** bytes are returned; if the write fails the request fails. | Accountability. |
| D10 | Rate limit **6 exports per 10 minutes** per admin+IP; register size cap **50,000** rows (`VOTER_EXPORT_MAX_ROWS`). | Limits bulk scraping with a stolen session. |
| D11 | Revoking *or* re-granting the IT admin role **resets** the mode (removes the three fields). A newly granted IT admin starts at **Off**. | Prevents stale permission coming back. |

## 12.2 Pre-checks (run and record the output; stop on mismatch)

```bash
cd "Multi-Tenant Voting System"
# 1. `_mask_phone` is defined TWICE in main.py. The later definition wins at runtime (Python binds names at call time).
grep -n "^def _mask_phone" backend/main.py          # expect two hits (~830 and ~6686)
sed -n 6686,6688p backend/main.py                  # effective: "*"*(len-3) + last 3 digits
# 2. IT-admin token subject is the stored student_id
grep -n "def _login_token_for" -A10 backend/main.py | grep "subject="
# 3. Existing list endpoint masks phones with _mask_phone and hides has_voted for IT admin
grep -n "_admin_voter_projection" -A6 backend/main.py | head -12
# 4. csv and io already imported in main.py (no new import needed); openpyxl is in requirements.txt
grep -n "^import csv\|^import io" backend/main.py ; grep -n openpyxl backend/requirements.txt
# 5. Superadmin namespace guard exists (non-superadmin gets 403 on /superadmin/*)
grep -n 'startswith("/superadmin")' backend/main.py
# 6. View-as tokens are GET-only at the guard
grep -n "view_only" backend/main.py | head -5
# 7. UIFeedbackProvider wraps the whole app (useToast/useConfirm usable in both dashboards)
grep -n UIFeedbackProvider frontend/src/main.jsx
```

**Do not delete either `_mask_phone`** (out of scope). The export calls `_mask_phone` by name, like the list endpoint, so both always agree; test T3 guards that.

## 12.3 Data model

No migration. Existing IT admins have no field, so they are **Off**. Documents gain, only after the superadmin acts:

```json
{ "it_admin_export_mode": "full",
  "it_admin_export_mode_set_by": "<superadmin id>",
  "it_admin_export_mode_set_at": "<UTC datetime>" }
```

These fields must **never** be returned by any voter-facing or voter-list endpoint (all use explicit projections; T19 proves it).

## 12.4 Backend (all in `backend/main.py`)

Place the new block **directly after `toggle_it_admin`** (the "SUPERADMIN — IT ADMIN MANAGEMENT" section) for the superadmin endpoint, and the export block **after `get_all_voters`** (`/admin/voters`). Do not reorder existing code.

### 12.4.1 Constants and pure helpers

```python
# ── IT admin voter-register export ───────────────────────────────────────────
EXPORT_MODES = ("none", "redacted", "full")
EXPORT_MAX_ROWS = int(os.getenv("VOTER_EXPORT_MAX_ROWS", "50000"))
EXPORT_RATE_LIMIT = 6
EXPORT_RATE_WINDOW_S = 600
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")   # spreadsheet formula-injection triggers


def normalize_export_mode(raw) -> str:
    """Fail closed: anything other than exactly 'redacted' or 'full' is 'none'."""
    return raw if raw in ("redacted", "full") else "none"


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection: a cell that would be read as a formula gets a leading '."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def _export_row(v: dict, mode: str, enabled_fields: list[dict], max_phones: int) -> list[str]:
    if mode not in ("redacted", "full"):          # explicit raise, not assert (asserts vanish under python -O)
        raise ValueError("export mode must be redacted or full")
    phones = [str(p) for p in (v.get("phone_numbers") or [])]
    if mode == "redacted":
        phones = [_mask_phone(p) for p in phones]   # SAME function the on-screen list uses (decision D3)
    phones += [""] * (max_phones - len(phones))
    attrs = v.get("attrs") or {}
    return [str(v.get("student_id", "")).upper(), v.get("full_name", "") or "", *phones,
            *[attrs.get(f["key"], "") for f in enabled_fields]]


async def _it_admin_export_mode(request: Request, admin: dict) -> str:
    """Read the caller's mode from the DB on EVERY call. Never from the JWT, never cached (see A4)."""
    doc = await db.voters.find_one(
        org_query(request, {"student_id": admin.get("sub"), "is_it_admin": True}),
        {"_id": 0, "it_admin_export_mode": 1})
    return normalize_export_mode((doc or {}).get("it_admin_export_mode"))
```

### 12.4.2 Superadmin: set the mode

```python
class ExportModeUpdate(BaseModel):
    mode: str


@app.put("/superadmin/it-admins/{student_id:path}/export-mode")
async def set_it_admin_export_mode(student_id: str, data: ExportModeUpdate, request: Request,
                                   admin: dict = Depends(require_role("superadmin"))):
    if data.mode not in EXPORT_MODES:
        raise HTTPException(400, "Mode must be none, redacted or full.")
    voter = await db.voters.find_one(org_query(request, {**get_forgiving_filter(student_id), "is_it_admin": True}))
    if not voter:
        raise HTTPException(404, "That person is not an IT admin.")
    old = normalize_export_mode(voter.get("it_admin_export_mode"))
    if data.mode == old:
        return {"student_id": voter["student_id"], "it_admin_export_mode": old, "changed": False}
    await db.voters.update_one({"_id": voter["_id"]}, {"$set": {
        "it_admin_export_mode": data.mode,
        "it_admin_export_mode_set_by": current_actor(request),
        "it_admin_export_mode_set_at": datetime.utcnow()}})
    await log_action("it_admin_export_mode_changed", current_actor(request),
                     {"student_id": voter["student_id"], "old": old, "new": data.mode},
                     org_id=request.state.org_id)
    return {"student_id": voter["student_id"], "it_admin_export_mode": data.mode, "changed": True}
```
(The `:path` converter with a fixed suffix is the same pattern as the existing `/superadmin/it-admins/{student_id:path}/toggle`. Registration numbers contain `/`.)

### 12.4.3 Superadmin: list returns the mode; toggle resets it

In `list_it_admins`: add `"it_admin_export_mode": 1` to the projection and normalise:

```python
    async for v in db.voters.find(org_query(request, {"is_it_admin": True}),
                                  {"_id": 0, "student_id": 1, "full_name": 1, "it_admin_email": 1, "it_admin_export_mode": 1}):
        v["it_admin_export_mode"] = normalize_export_mode(v.get("it_admin_export_mode"))
        result.append(v)
```
In `toggle_it_admin`, change the `update_one` so **both** directions reset the mode (D11):

```python
    await db.voters.update_one(
        {"_id": voter["_id"]},
        {"$set": {"is_it_admin": new_val, **(await _invalidate_sessions(voter["_id"]))},
         "$unset": {"it_admin_export_mode": "", "it_admin_export_mode_set_by": "", "it_admin_export_mode_set_at": ""}})
```

### 12.4.4 IT admin: permission probe (for the UI)

```python
@app.get("/admin/voters/export/permission")
async def voter_export_permission(request: Request, admin: dict = Depends(require_role("it_admin"))):
    mode = await _it_admin_export_mode(request, admin)
    return {"mode": mode, "formats": ["xlsx", "csv"] if mode != "none" else [], "max_rows": EXPORT_MAX_ROWS}
```
No audit row (read-only, no data). It is a GET so "View as" can read it; the UI then shows the button but the POST is blocked (correct; see T7).

### 12.4.5 IT admin: the export

```python
class VoterExportRequest(BaseModel):
    format: str = "xlsx"


@app.post("/admin/voters/export")
async def export_voter_register(data: VoterExportRequest, request: Request,
                                admin: dict = Depends(require_role("it_admin"))):
    org_id, actor = request.state.org_id, current_actor(request)
    fmt = (data.format or "").strip().lower()
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(400, "Format must be csv or xlsx.")

    mode = await _it_admin_export_mode(request, admin)           # fresh DB read, every call
    if mode == "none":
        await log_action("voter_register_export_denied", actor, {"reason": "mode_none"}, org_id=org_id)
        raise HTTPException(403, "Voter register export is not enabled for your account. Ask the superadmin to enable it.")

    await _check_rate_limit(request, bucket=f"voter_export:{actor}", limit=EXPORT_RATE_LIMIT,
                            window_s=EXPORT_RATE_WINDOW_S,
                            message="Too many exports. Please wait a few minutes and try again.")

    query = org_query(request)                                   # tenant scope: mandatory
    if await db.voters.count_documents(query) > EXPORT_MAX_ROWS:
        await log_action("voter_register_export_denied", actor, {"reason": "too_many_rows"}, org_id=org_id)
        raise HTTPException(413, f"The register is larger than the {EXPORT_MAX_ROWS:,}-row export limit.")

    fields = await get_voter_fields(request)
    enabled = [f for f in fields["fields"] if f.get("enabled")]
    projection = {"_id": 0, "full_name": 1, "student_id": 1, "phone_numbers": 1, "attrs": 1}   # allowlist (D4)
    voters = [v async for v in db.voters.find(query, projection).sort([("full_name", 1), ("student_id", 1)])]

    max_phones = max([1] + [len(v.get("phone_numbers") or []) for v in voters])
    header = ["Registration Number", "Full Name", *[f"Phone {i}" for i in range(1, max_phones + 1)],
              *[f["label"] for f in enabled]]
    rows = [_export_row(v, mode, enabled, max_phones) for v in voters]

    if fmt == "csv":
        buf = io.StringIO(newline="")
        w = csv.writer(buf)
        w.writerow([_csv_safe(h) for h in header])
        for r in rows:
            w.writerow([_csv_safe(c) for c in r])
        body = buf.getvalue().encode("utf-8-sig")                # BOM so Excel reads UTF-8 names correctly
        media = "text/csv; charset=utf-8"
    else:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Voter register")

        def _text_row(values):
            cells = []
            for x in values:
                c = WriteOnlyCell(ws, value="" if x is None else str(x))
                c.data_type = "s"                                # force TEXT: never a formula, never a number
                cells.append(c)
            return cells
        ws.append(_text_row(header))
        for r in rows:
            ws.append(_text_row(r))
        bio = io.BytesIO()
        wb.save(bio)
        body = bio.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Audit BEFORE releasing data. No names/phones/reg numbers/search text: this log is readable by every admin role.
    await log_action("voter_register_export", actor, {"mode": mode, "format": fmt, "rows": len(rows)}, org_id=org_id)

    slug = re.sub(r"[^a-z0-9-]", "", (getattr(request.state, "org_slug", "") or "org").lower()) or "org"
    filename = f"voter-register-{slug}-{mode}-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.{fmt}"
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Export-Mode": mode, "X-Export-Rows": str(len(rows)),
    })
```
**Import required:** `main.py` line 3 currently reads `from fastapi.responses import JSONResponse`. Change it to `from fastapi.responses import JSONResponse, Response` (verified: `Response` is not imported today). `csv`, `io`, `re`, `os` and `datetime` are already imported; `request.state.org_slug` is set by the org middleware (it is `None` when no `X-Org-Slug` header was sent, which the `or "org"` fallback covers).

### 12.4.6 CORS: expose the download headers

The frontend (Vercel) and API (Render) are different origins, so the browser hides `Content-Disposition` unless exposed. **Edit the existing single `CORSMiddleware` call** (keep it registered last):

```python
    allow_headers=["Authorization", "Content-Type", "X-Org-Slug", "X-Voter-Token"],
    expose_headers=["Content-Disposition", "X-Export-Mode", "X-Export-Rows"],
    max_age=600,   # WP-5 may raise this; do not conflict
```

### 12.4.7 Audit-log vocabulary

| `action` | `details` (exactly these keys) | When |
|---|---|---|
| `voter_register_export` | `mode`, `format`, `rows` | after a successful build, before bytes are returned |
| `voter_register_export_denied` | `reason` ∈ `mode_none`, `too_many_rows` | refusals that reach the handler |
| `it_admin_export_mode_changed` | `student_id`, `old`, `new` | superadmin changed the mode |

### 12.4.8 Security invariants (each is covered by a test in 12.6)

| ID | Invariant |
|---|---|
| I1 | Default, missing or corrupt mode ⇒ no export (403). |
| I2 | Only role `it_admin`; superadmin, commission, overseer, finance ⇒ 403. |
| I3 | "View as" tokens cannot export (POST blocked). |
| I4 | Mode is read fresh each request: a superadmin downgrade applies to the IT admin's **existing session** on its next request. |
| I5 | Redacted output never contains a complete stored phone number, and equals the on-screen list's phones. |
| I6 | Full output equals stored values (no information dropped). |
| I7 | Output never contains `has_voted`, `last_status`, OTP/token/password/role data, or disabled optional fields. |
| I8 | Only the caller's organisation's voters appear; token from org A is useless on org B. |
| I9 | Formula-injection is neutralised in CSV and XLSX. |
| I10 | Audit row exists per export/refusal, contains no PII, and is written before data is released. |
| I11 | Rate limit and row cap enforced. |
| I12 | `it_admin_export_mode*` never appears in any voter-facing response. |

## 12.5 Frontend

### 12.5.1 New file `frontend/src/registerExport.js` (pure helpers + API; testable)

```js
import api from './api';

export const EXPORT_MODES = ['none', 'redacted', 'full'];
export const MODE_LABEL = { none: 'Off', redacted: 'Redacted', full: 'Full' };
export const MODE_HELP = {
  none: 'This IT admin has no export option.',
  redacted: 'Can export, with phone numbers masked (same as their on-screen list).',
  full: 'Can export the complete register with full phone numbers. No information is hidden.',
};

export const fetchExportPermission = () =>
  api.get('/admin/voters/export/permission').then((r) => r.data);

export const setItAdminExportMode = (studentId, mode) =>
  api.put(`/superadmin/it-admins/${encodeURIComponent(studentId)}/export-mode`, { mode }).then((r) => r.data);

// Content-Disposition: attachment; filename="x.csv"  ->  x.csv   (fallback when the header is hidden/absent)
export function filenameFromDisposition(header, fallback) {
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header || '');
  const name = m ? decodeURIComponent(m[1]).replace(/[\\/]/g, '_').trim() : '';
  return name || fallback;
}

// With responseType:'blob' an error body arrives as a Blob, not JSON. Also handles the "View as" pre-flight
// rejection (plain object) and network failures (no response).
export async function exportErrorMessage(e, fallback = 'Export failed. Please try again.') {
  if (!e?.response) return 'No response from the server. Check your connection and try again.';
  let data = e.response.data;
  try {
    if (typeof Blob !== 'undefined' && data instanceof Blob) data = JSON.parse(await data.text());
  } catch { data = null; }
  const d = data?.detail;
  if (typeof d === 'string' && d.trim()) return d;
  return fallback;
}

export async function downloadRegister(format) {
  const res = await api.post('/admin/voters/export', { format }, { responseType: 'blob', timeout: 120000 });
  const fallback = `voter-register.${format}`;
  const name = filenameFromDisposition(res.headers?.['content-disposition'], fallback);
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.style.display = 'none';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return { name, rows: Number(res.headers?.['x-export-rows'] ?? NaN), mode: res.headers?.['x-export-mode'] || '' };
}
```

### 12.5.2 New file `frontend/src/components/ExportModeControl.jsx` (SuperAdmin control)

A small presentational component so it can be unit-tested without the 2,300-line dashboard.

```jsx
import React from 'react';
import { EXPORT_MODES, MODE_LABEL, MODE_HELP } from '../registerExport';

export default function ExportModeControl({ name, mode, onChange, disabled }) {
  return (
    <div role="group" aria-label={`Voter register export for ${name}`} style={{ display: 'grid', gap: 6 }}>
      <b style={{ fontSize: 13 }}>Voter register export</b>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {EXPORT_MODES.map((m) => (
          <button key={m} type="button" data-track={`export-mode-${m}`} disabled={disabled}
            aria-pressed={mode === m} onClick={() => mode !== m && onChange(m)}
            style={{ minHeight: 44, padding: '0 14px', borderRadius: 8, fontWeight: 700, fontSize: 14,
                     border: '1px solid var(--border-color)', cursor: disabled ? 'not-allowed' : 'pointer',
                     background: mode === m ? 'var(--brand-primary)' : 'var(--card-bg)',
                     color: mode === m ? '#fff' : 'var(--text-color)' }}>
            {MODE_LABEL[m]}
          </button>
        ))}
      </div>
      <small style={{ opacity: 0.75 }}>{MODE_HELP[mode] || MODE_HELP.none}</small>
    </div>
  );
}
```
(Active text is `#fff`, **not** `var(--card-bg)`: that is exactly the dark-mode contrast bug described in guide §5.6.)

### 12.5.3 Wire it into `SuperAdminDashboard.jsx` (IT Admins tab)

1. `import ExportModeControl from './ExportModeControl';` and `import { setItAdminExportMode } from '../registerExport';`
2. State: `const [exportSaving, setExportSaving] = useState({});`
3. Handler next to `handleToggleItAdmin`:
```jsx
const handleSetExportMode = async (a, mode) => {
  if (mode === 'full' && !(await confirm(
    `Allow ${a.full_name} to export the FULL voter register, including complete phone numbers? ` +
    `Every export is recorded in the activity log.`))) return;
  setExportSaving((p) => ({ ...p, [a.student_id]: true }));
  try {
    await setItAdminExportMode(a.student_id, mode);
    toast(`Export for ${a.full_name}: ${mode === 'none' ? 'turned off' : mode}.`, { kind: 'success' });
    await fetchItAdmins();
  } catch (e) {
    toast(e?.response?.data?.detail || 'Could not change the export setting.', { kind: 'error' });
  } finally {
    setExportSaving((p) => ({ ...p, [a.student_id]: false }));
  }
};
```
4. In the `itAdmins.map` card, **after** the email / Send-Credentials row add:
```jsx
<ExportModeControl name={a.full_name} mode={a.it_admin_export_mode || 'none'}
  disabled={!!exportSaving[a.student_id]} onChange={(m) => handleSetExportMode(a, m)} />
```
Confirm the `toast` kinds the project uses (`grep -n "kind:" frontend/src/components/SuperAdminDashboard.jsx | head`) and reuse the same names.

### 12.5.4 New file `frontend/src/components/VoterRegisterExport.jsx` (IT admin)

```jsx
import React, { useEffect, useRef, useState } from 'react';
import { useToast, useConfirm } from './UIFeedback';
import { fetchExportPermission, downloadRegister, exportErrorMessage } from '../registerExport';

export default function VoterRegisterExport() {
  const toast = useToast();
  const confirm = useConfirm();
  const [perm, setPerm] = useState(null);          // null = unknown (render nothing), else {mode}
  const [format, setFormat] = useState('xlsx');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);                       // a state flag alone does not stop a fast double tap

  const loadPerm = () => fetchExportPermission().then(setPerm).catch(() => setPerm({ mode: 'none' }));
  useEffect(() => { loadPerm(); }, []);

  if (!perm || perm.mode === 'none') return null;   // "they don't have the option": nothing is shown at all

  const full = perm.mode === 'full';
  const onExport = async () => {
    if (lock.current) return;
    lock.current = true;
    setError('');
    try {
      if (full && !(await confirm(
        'This file contains COMPLETE phone numbers for every voter. Store it securely and do not share it. Continue?'))) return;
      setBusy(true);
      const r = await downloadRegister(format);
      toast(`Exported ${Number.isFinite(r.rows) ? r.rows + ' voters' : 'register'} (${r.mode || perm.mode}).`, { kind: 'success' });
    } catch (e) {
      setError(await exportErrorMessage(e));
      if (e?.response?.status === 403) loadPerm();     // permission changed while the page was open: the button disappears
    } finally {
      setBusy(false);
      lock.current = false;
    }
  };

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 14 }}>
        Format
        <select data-track="export-register-format" value={format} disabled={busy}
          onChange={(e) => setFormat(e.target.value)} style={{ minHeight: 44, fontSize: 16 }}>
          <option value="xlsx">Excel (.xlsx)</option>
          <option value="csv">CSV (.csv)</option>
        </select>
      </label>
      <button type="button" data-track="export-register" onClick={onExport} disabled={busy} aria-busy={busy}
        style={{ minHeight: 44, padding: '0 16px', borderRadius: 8, fontWeight: 700, border: 0,
                 background: full ? '#b45309' : 'var(--brand-primary)', color: '#fff',
                 cursor: busy ? 'wait' : 'pointer' }}>
        {busy ? 'Preparing…' : full ? 'Export register (full details)' : 'Export register (phones hidden)'}
      </button>
      {format === 'csv' && (
        <small style={{ opacity: 0.75, flexBasis: '100%' }}>
          Opening a CSV in Excel can turn long phone numbers into 2.5E+11. Choose Excel (.xlsx) to keep them exact.
        </small>
      )}
      {error && <p role="alert" style={{ color: 'var(--danger, #c0392b)', margin: 0, flexBasis: '100%' }}>{error}</p>}
    </div>
  );
}
```
In `ITAdminDashboard.jsx`, in the `activeTab === 'voters'` block render it **above** `<VoterList …>` (wrap both in a fragment): `import VoterRegisterExport from './VoterRegisterExport';`. Do not touch `VoterList`.

## 12.6 Tests

### 12.6.1 Backend — create `backend/tests/test_voter_export.py`

Adapt names to the real fixture if the pre-check shows differences. Run with `pytest tests/test_voter_export.py -q`.

```python
"""WP-12: IT admin voter-register export. Invariants I1-I12 (see playbook 12.4.8)."""
import csv, io
import pytest
from openpyxl import load_workbook

import main
from auth import create_access_token
from tests.test_flows import env, START, Clock  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

FULL_PHONE = "256700111222"


async def seed(e):
    """Voters with data that MUST and MUST NOT appear, including hostile values."""
    await e.db.settings.insert_one({"name": "voter_fields", "org_id": e.org_id, "fields": [
        {"key": "hostel", "label": "Hostel", "enabled": True},
        {"key": "secretnote", "label": "Secret Note", "enabled": False}]})
    await e.voter("23/u/001", "Alpha One", (FULL_PHONE, "256700333444"), has_voted=True, last_status="authenticated",
                  attrs={"hostel": "Block A", "secretnote": "DISABLED-FIELD-VALUE"},
                  otp_hash="OTPHASHVALUE", vote_jti="JTIVALUE", it_admin_password_hash="PWHASHVALUE", added_by="zzz-added-by")
    await e.voter("23/u/002", "=HYPERLINK(\"http://evil\",\"x\")", ("256700555666",), attrs={"hostel": "@cmd"})


async def set_mode(e, mode):
    await e.db.voters.update_one({"student_id": "it1", "org_id": e.org_id}, {"$set": {"it_admin_export_mode": mode}})


async def export(e, headers=None, fmt="csv"):
    return await e.client.post("/admin/voters/export", json={"format": fmt}, headers=headers or e.it)


def csv_rows(resp):
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))


# I1 -----------------------------------------------------------------------------------------------
async def test_T1_default_is_off_and_refused(env):
    await seed(env)
    assert (await env.client.get("/admin/voters/export/permission", headers=env.it)).json()["mode"] == "none"
    r = await export(env)
    assert r.status_code == 403 and FULL_PHONE not in r.text and "Alpha" not in r.text
    a = await env.db.audit_log.find_one({"action": "voter_register_export_denied"})
    assert a and a["details"] == {"reason": "mode_none"}


@pytest.mark.parametrize("bad", ["FULL", "Full", " full", "yes", "", None, ["full"], 1, True, "none"])
async def test_T2_corrupt_mode_fails_closed(env, bad):
    await seed(env); await set_mode(env, bad)
    assert main.normalize_export_mode(bad) == "none"
    assert (await export(env)).status_code == 403


# I5 + D3 ------------------------------------------------------------------------------------------
async def test_T3_redacted_hides_phones_and_equals_on_screen_list(env):
    await seed(env); await set_mode(env, "redacted")
    r = await export(env)
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert FULL_PHONE not in text and "256700333444" not in text and "256700555666" not in text
    rows = csv_rows(r)
    assert rows[0][:4] == ["Registration Number", "Full Name", "Phone 1", "Phone 2"]
    listed = (await env.client.get("/admin/voters/list", headers=env.it, params={"page_size": 50})).json()["results"]
    by_id = {v["student_id"].upper(): v for v in listed}
    for row in rows[1:]:
        assert row[2:4][:len(by_id[row[0]]["phone_numbers"])] == by_id[row[0]]["phone_numbers"]   # export == screen


async def test_T3b_mask_function_pinned():
    # `_mask_phone` is defined twice in main.py; the LATER one is effective. If someone removes the duplicate this
    # fails on purpose: confirm the new masking is acceptable, then update this line.
    assert main._mask_phone(FULL_PHONE) == "*********222"


# I6 + I7 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
@pytest.mark.parametrize("mode", ["redacted", "full"])
async def test_T4_T5_allowlist_no_leaks_in_any_mode_or_format(env, mode, fmt):
    await seed(env); await set_mode(env, mode)
    r = await export(env, fmt=fmt)
    assert r.status_code == 200
    blob = r.content.decode("utf-8-sig", "ignore") if fmt == "csv" else " ".join(
        str(c.value) for row in load_workbook(io.BytesIO(r.content)).active.iter_rows() for c in row)
    for forbidden in ["has_voted", "last_status", "authenticated", "OTPHASHVALUE", "JTIVALUE", "PWHASHVALUE",
                      "zzz-added-by", "DISABLED-FIELD-VALUE", "Secret Note", "is_it_admin", "it_admin_export_mode"]:
        assert forbidden not in blob, forbidden
    assert "Block A" in blob and "Hostel" in blob            # enabled optional field IS included


async def test_T4_full_contains_every_stored_value(env):
    await seed(env); await set_mode(env, "full")
    rows = csv_rows(await export(env))
    alpha = next(r for r in rows if r[0] == "23/U/001")
    assert alpha[1] == "Alpha One" and alpha[2] == FULL_PHONE and alpha[3] == "256700333444"
    assert len(rows) - 1 == await env.db.voters.count_documents({"org_id": env.org_id})   # no row dropped


# I2 / I3 ------------------------------------------------------------------------------------------
async def test_T6_only_it_admin_role(env):
    await seed(env); await set_mode(env, "full")
    for hdr in (env.sa, env.com1, env.over, env.tok("fc1", "financial_controller")):
        assert (await export(env, headers=hdr)).status_code == 403
        assert (await env.client.get("/admin/voters/export/permission", headers=hdr)).status_code == 403
    assert (await env.client.post("/admin/voters/export", json={"format": "csv"})).status_code in (401, 403)  # no token


async def test_T7_view_as_token_cannot_export(env):
    await seed(env); await set_mode(env, "full")
    tok = create_access_token(subject="it1", role="it_admin", org_id=env.org_id, extra_claims={"view_only": True})
    h = {"Authorization": f"Bearer {tok}", "X-Org-Slug": "t1"}
    assert (await env.client.get("/admin/voters/export/permission", headers=h)).status_code == 200
    r = await export(env, headers=h)
    assert r.status_code == 403 and "Read-only" in r.json()["detail"]
    assert await env.db.audit_log.count_documents({"action": "voter_register_export"}) == 0


# I4 -----------------------------------------------------------------------------------------------
async def test_T8_downgrade_applies_to_existing_session(env):
    await seed(env); await set_mode(env, "full")
    assert (await export(env)).status_code == 200                      # same token ...
    r = await env.client.put("/superadmin/it-admins/it1/export-mode", json={"mode": "none"}, headers=env.sa)
    assert r.status_code == 200 and r.json()["changed"] is True
    assert (await export(env)).status_code == 403                      # ... refused immediately, no re-login


# Superadmin control ------------------------------------------------------------------------------
async def test_T9_superadmin_setter_rules_and_audit(env):
    put = lambda mode, hdr=None, sid="it1": env.client.put(f"/superadmin/it-admins/{sid}/export-mode", json={"mode": mode}, headers=hdr or env.sa)
    assert (await put("everything")).status_code == 400
    assert (await put("full", sid="v1")).status_code == 404            # not an IT admin
    assert (await put("full", hdr=env.it)).status_code == 403          # IT admin cannot grant themselves
    assert (await put("full", hdr=env.com1)).status_code == 403
    assert (await put("full")).json()["changed"] is True
    assert (await put("full")).json()["changed"] is False             # idempotent, not re-logged
    logs = [a async for a in env.db.audit_log.find({"action": "it_admin_export_mode_changed"})]
    assert len(logs) == 1 and logs[0]["details"] == {"student_id": "it1", "old": "none", "new": "full"}
    doc = await env.db.voters.find_one({"student_id": "it1"})
    assert doc["it_admin_export_mode"] == "full" and doc["it_admin_export_mode_set_by"]


async def test_T10_toggle_resets_mode_both_directions(env):
    await set_mode(env, "full")
    await env.client.post("/superadmin/it-admins/it1/toggle", headers=env.sa)   # revoke
    await env.client.post("/superadmin/it-admins/it1/toggle", headers=env.sa)   # re-grant
    doc = await env.db.voters.find_one({"student_id": "it1"})
    assert doc["is_it_admin"] is True and "it_admin_export_mode" not in doc


async def test_T11_list_reports_mode_normalised(env):
    await set_mode(env, "WEIRD")
    row = next(a for a in (await env.client.get("/superadmin/it-admins", headers=env.sa)).json() if a["student_id"] == "it1")
    assert row["it_admin_export_mode"] == "none"
    await set_mode(env, "redacted")
    row = next(a for a in (await env.client.get("/superadmin/it-admins", headers=env.sa)).json() if a["student_id"] == "it1")
    assert row["it_admin_export_mode"] == "redacted"


# I8 -----------------------------------------------------------------------------------------------
async def test_T12_tenant_isolation(env):
    await seed(env); await set_mode(env, "full")
    org2 = await env.db.organizations.insert_one({"slug": "t2", "name": "T2"})
    await env.db.voters.insert_one({"student_id": "99/u/999", "full_name": "Other Org Person", "phone_numbers": ["256799999999"],
                                    "org_id": str(org2.inserted_id)})
    text = (await export(env)).content.decode("utf-8-sig")
    assert "Other Org Person" not in text and "256799999999" not in text
    cross = await env.client.post("/admin/voters/export", json={"format": "csv"},
                                  headers={"Authorization": env.it["Authorization"], "X-Org-Slug": "t2"})
    assert cross.status_code == 403                                      # token from org A on org B


# I9 -----------------------------------------------------------------------------------------------
async def test_T13_formula_injection_neutralised(env):
    await seed(env); await set_mode(env, "full")
    evil = next(r for r in csv_rows(await export(env)) if r[0] == "23/U/002")
    assert evil[1].startswith("'=") and evil[-1] == "'@cmd"
    ws = load_workbook(io.BytesIO((await export(env, fmt="xlsx")).content)).active
    cells = {c.value: c for row in ws.iter_rows() for c in row if c.value}
    c = cells['=HYPERLINK("http://evil","x")']
    assert c.data_type == "s"                                            # stored as text, NOT a formula ('f')


async def test_T14_xlsx_roundtrip_phones_are_text(env):
    await seed(env); await set_mode(env, "full")
    r = await export(env, fmt="xlsx")
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = [[c.value for c in row] for row in ws.iter_rows()]
    alpha = next(x for x in rows if x[0] == "23/U/001")
    assert alpha[2] == FULL_PHONE and isinstance(alpha[2], str)


# I11 ----------------------------------------------------------------------------------------------
async def test_T15_row_cap(env, monkeypatch):
    await seed(env); await set_mode(env, "full")
    monkeypatch.setattr(main, "EXPORT_MAX_ROWS", 1)
    r = await export(env)
    assert r.status_code == 413
    assert (await env.db.audit_log.find_one({"action": "voter_register_export_denied"}))["details"] == {"reason": "too_many_rows"}


async def test_T16_rate_limit(env, monkeypatch):
    await seed(env); await set_mode(env, "full")
    monkeypatch.setattr(main, "EXPORT_RATE_LIMIT", 2)
    assert [(await export(env)).status_code for _ in range(3)] == [200, 200, 429]


# I10 ----------------------------------------------------------------------------------------------
async def test_T17_audit_has_no_pii(env):
    await seed(env); await set_mode(env, "full")
    await export(env); await export(env, fmt="xlsx")
    logs = [a async for a in env.db.audit_log.find({"action": "voter_register_export"})]
    assert len(logs) == 2 and all(set(a["details"]) == {"mode", "format", "rows"} for a in logs)
    dump = str([{k: v for k, v in a.items() if k != "_id"} async for a in env.db.audit_log.find({})])
    for pii in (FULL_PHONE, "Alpha One", "23/u/001", "23/U/001", "Block A"):
        assert pii not in dump


async def test_T17b_no_data_if_audit_write_fails(env, monkeypatch):
    await seed(env); await set_mode(env, "full")
    real = main.log_action
    async def boom(action, *a, **k):
        if action == "voter_register_export":
            raise RuntimeError("db down")
        return await real(action, *a, **k)
    monkeypatch.setattr(main, "log_action", boom)
    with pytest.raises(Exception):                                       # RuntimeError, or an ExceptionGroup wrapping it
        await export(env)                                                # the point: no 200 response carrying data


async def test_T18_headers_and_cors_expose(env):
    await seed(env); await set_mode(env, "redacted")
    h = {**env.it, "Origin": "http://localhost:5173"}                    # default allowed origin in tests
    r = await export(env, headers=h)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith('attachment; filename="voter-register-t1-redacted-')
    assert r.headers["content-disposition"].endswith('.csv"')
    assert r.headers["x-export-mode"] == "redacted"
    assert r.headers["x-export-rows"] == str(await env.db.voters.count_documents({"org_id": env.org_id}))
    exposed = r.headers.get("access-control-expose-headers", "").lower()
    assert "content-disposition" in exposed and "x-export-rows" in exposed
    assert r.content.startswith(b"\xef\xbb\xbf")                         # UTF-8 BOM for Excel


async def test_T18b_bad_format(env):
    await set_mode(env, "full")
    assert (await export(env, fmt="pdf")).status_code == 400


# I12 + regression ---------------------------------------------------------------------------------
async def test_T19_field_never_leaks_and_existing_endpoints_unchanged(env):
    await seed(env); await set_mode(env, "full")
    lst = await env.client.get("/admin/voters/list", headers=env.it)
    old = await env.client.get("/admin/voters", headers=env.it)
    pub = await env.client.get("/voter-register")
    for r in (lst, old, pub):
        assert r.status_code == 200 and "it_admin_export_mode" not in r.text
    for v in lst.json()["results"]:
        assert "has_voted" not in v and "last_status" not in v                     # IT admin still cannot see voting status
        assert all("*" in p for p in v["phone_numbers"])                            # list still masked for IT admin
    assert FULL_PHONE not in lst.text and FULL_PHONE not in old.text
```

### 12.6.2 Frontend — Vitest

`frontend/src/registerExport.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { filenameFromDisposition, exportErrorMessage } from './registerExport';

describe('filenameFromDisposition', () => {
  it('reads a quoted filename', () =>
    expect(filenameFromDisposition('attachment; filename="voter-register-assk-full-20260930-1200.xlsx"', 'x')).toBe('voter-register-assk-full-20260930-1200.xlsx'));
  it('falls back when header is missing/hidden by CORS', () => expect(filenameFromDisposition(undefined, 'voter-register.csv')).toBe('voter-register.csv'));
  it('strips path separators', () => expect(filenameFromDisposition('attachment; filename="../../x.csv"', 'f')).not.toMatch(/[\\/]/));
});

describe('exportErrorMessage', () => {
  it('parses a JSON Blob body', async () => {
    const blob = new Blob([JSON.stringify({ detail: 'Voter register export is not enabled for your account.' })]);
    expect(await exportErrorMessage({ response: { status: 403, data: blob } })).toMatch(/not enabled/);
  });
  it('handles the view-only pre-flight rejection (plain object)', async () =>
    expect(await exportErrorMessage({ response: { status: 403, data: { detail: 'Read-only view: this action is disabled.' } } })).toMatch(/Read-only/));
  it('handles no response (network/timeout)', async () =>
    expect(await exportErrorMessage({})).toMatch(/No response/));
  it('falls back on an unparseable blob', async () =>
    expect(await exportErrorMessage({ response: { status: 500, data: new Blob(['<html>']) } }, 'fallback')).toBe('fallback'));
});
```

`frontend/src/components/VoterRegisterExport.test.jsx` (mock the helpers and UI hooks):
```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const confirm = vi.fn(); const toast = vi.fn();
vi.mock('./UIFeedback', () => ({ useToast: () => toast, useConfirm: () => confirm }));
vi.mock('../registerExport', () => ({
  fetchExportPermission: vi.fn(), downloadRegister: vi.fn(),
  exportErrorMessage: vi.fn(async () => 'Voter register export is not enabled for your account.'),
}));
import * as api from '../registerExport';
import VoterRegisterExport from './VoterRegisterExport';

beforeEach(() => { vi.clearAllMocks(); confirm.mockResolvedValue(true); });

describe('VoterRegisterExport', () => {
  it('renders NOTHING when mode is none', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'none' });
    const { container } = render(<VoterRegisterExport />);
    await waitFor(() => expect(api.fetchExportPermission).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
  it('renders nothing if the permission call fails (fail closed)', async () => {
    api.fetchExportPermission.mockRejectedValue(new Error('x'));
    const { container } = render(<VoterRegisterExport />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
  it('redacted: shows "phones hidden" button, no confirm, downloads', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'redacted' });
    api.downloadRegister.mockResolvedValue({ rows: 10, mode: 'redacted', name: 'a.xlsx' });
    render(<VoterRegisterExport />);
    await userEvent.click(await screen.findByRole('button', { name: /phones hidden/i }));
    expect(confirm).not.toHaveBeenCalled();
    expect(api.downloadRegister).toHaveBeenCalledWith('xlsx');
  });
  it('full: asks to confirm; cancelling downloads nothing', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'full' });
    confirm.mockResolvedValue(false);
    render(<VoterRegisterExport />);
    await userEvent.click(await screen.findByRole('button', { name: /full details/i }));
    expect(confirm).toHaveBeenCalled();
    expect(api.downloadRegister).not.toHaveBeenCalled();
  });
  it('double click triggers only ONE download', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'redacted' });
    let resolve; api.downloadRegister.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<VoterRegisterExport />);
    const btn = await screen.findByRole('button', { name: /phones hidden/i });
    await userEvent.dblClick(btn);
    expect(api.downloadRegister).toHaveBeenCalledTimes(1);
    resolve({ rows: 1, mode: 'redacted' });
  });
  it('403 shows the message and re-checks permission (button can disappear)', async () => {
    api.fetchExportPermission.mockResolvedValueOnce({ mode: 'redacted' }).mockResolvedValueOnce({ mode: 'none' });
    api.downloadRegister.mockRejectedValue({ response: { status: 403 } });
    const { container } = render(<VoterRegisterExport />);
    await userEvent.click(await screen.findByRole('button', { name: /phones hidden/i }));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(api.fetchExportPermission).toHaveBeenCalledTimes(2);
  });
  it('csv shows the Excel phone-number warning', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'redacted' });
    render(<VoterRegisterExport />);
    await userEvent.selectOptions(await screen.findByRole('combobox'), 'csv');
    expect(screen.getByText(/2\.5E\+11/)).toBeInTheDocument();
  });
});
```

`frontend/src/components/ExportModeControl.test.jsx`:
```jsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExportModeControl from './ExportModeControl';

describe('ExportModeControl', () => {
  it('shows three options and marks the current one', () => {
    render(<ExportModeControl name="A" mode="redacted" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Off' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Redacted' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Full' })).toHaveAttribute('aria-pressed', 'false');
  });
  it('calls onChange only when the mode differs', async () => {
    const onChange = vi.fn();
    render(<ExportModeControl name="A" mode="none" onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Off' }));
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Full' }));
    expect(onChange).toHaveBeenCalledWith('full');
  });
  it('is inert while saving', async () => {
    const onChange = vi.fn();
    render(<ExportModeControl name="A" mode="none" disabled onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Full' }));
    expect(onChange).not.toHaveBeenCalled();
  });
  it('active button text is white (dark-mode contrast)', () => {
    render(<ExportModeControl name="A" mode="full" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Full' }).style.color).toBe('rgb(255, 255, 255)');
  });
});
```

### 12.6.3 Static checks (L1)

```bash
# export must not project anything outside the allowlist
python - <<'PY'
import re,sys
s=open("backend/main.py").read()
blk=s[s.index("async def export_voter_register"):s.index("async def export_voter_register")+6000]
assert '"_id": 0, "full_name": 1, "student_id": 1, "phone_numbers": 1, "attrs": 1' in blk
assert "has_voted" not in blk and "last_status" not in blk
assert "org_query(request)" in blk
print("allowlist + tenant scope OK")
PY
grep -n "it_admin_export_mode" backend/main.py            # only in: helpers, set/list/toggle, permission, export
grep -rn "it_admin_export_mode" frontend/src | grep -v test  # only registerExport/ExportModeControl/SuperAdminDashboard
grep -n 'methods=\["GET"\].*voters/export\|@app.get("/admin/voters/export"' backend/main.py && echo "FAIL: export must be POST" || echo "export is not a GET: OK"
```

### 12.6.4 Manual / browser checklist (**HUMAN**; run on staging with `DEBUG_MODE=true`)

| # | Step | Expected |
|---|---|---|
| H1 | Log in as superadmin → IT Admins tab | Each IT admin card shows **Off / Redacted / Full**; existing IT admins show **Off** |
| H2 | Log in as that IT admin (separate browser) → Edit/Voters tab | **No export button, no mention of export** |
| H3 | Superadmin sets **Redacted**; IT admin clicks Refresh on the page or reopens the tab | Button "Export register (phones hidden)" appears |
| H4 | Export xlsx; open in Excel | Phones masked (`*********222`); names/reg numbers as on screen; no Status/has-voted column |
| H5 | Superadmin sets **Full**; IT admin exports xlsx | Phones complete and exact (not 2.56E+11); a confirm dialog appears first |
| H6 | Export csv; open by double-click in Excel | Names correct (accents); phones may show E+ notation: the UI warns about this |
| H7 | Superadmin sets **Off** while the IT admin's tab is open; IT admin clicks Export | Clear message; button disappears; nothing downloaded |
| H8 | Superadmin → "View as" that IT admin → try Export | Button may show; click is refused with the read-only message; no file |
| H9 | Open the activity log as Overseer | Rows `voter_register_export` / `it_admin_export_mode_changed` visible, **no names or phones** |
| H10 | Click Export 7 times quickly | Max 6 succeed in 10 min; then "Too many exports" |
| H11 | Android Chrome (Slow 3G): export | Spinner "Preparing…", file saves; no timeout for a 2,000-row register |
| H12 | Dark mode: superadmin control | Selected option readable (white on blue) |
| H13 | Revoke then re-grant the IT admin | Mode is **Off** again |

## 12.7 Done when (WP-12)

- [ ] Pre-checks recorded; any mismatch in `DEVIATIONS.md`.
- [ ] `pytest tests/test_voter_export.py -q` all green.
- [ ] Full `pytest -q`: no new failures vs baseline.
- [ ] `npm test` (Vitest) green; `npm run lint` no new errors; `npx vite build` succeeds.
- [ ] L1 static checks pass.
- [ ] `Response` import added; CORS `expose_headers` added to the **existing** middleware; no second CORS registration.
- [ ] H1–H13 ticked by a human, or listed as pending.
- [ ] Improvement Guide updated with §4.9 and summary row 12.

## 12.8 Pitfalls (each one has bitten this codebase's pattern before)

1. **Do not read the mode from the JWT or a cache** (I4). The settings cache from WP-5 must not wrap it.
2. **Do not make export a GET** (it would work inside read-only "View as").
3. **Do not add `has_voted`** "because superadmin sees it". IT admins must not learn who voted.
4. **Do not log filters, names, phones or IDs** in the audit row.
5. **`:path` routes**: `/superadmin/it-admins/{student_id:path}/export-mode` must be registered so it does not get shadowed; run T9 to prove it.
6. **Axios blob errors** arrive as a `Blob`; `errMsg()` from `studentEdit.js` will not parse them. Use `exportErrorMessage`.
7. **Axios timeout** from WP-6 is 20 s; the export passes `timeout: 120000` explicitly.
8. **CORS**: without `expose_headers` the filename silently falls back to `voter-register.<ext>` and row counts are missing; that is a bug, not a cosmetic.
9. **Do not "helpfully" also export for superadmin**, add filters, or add PDF. Out of scope (D6, D8).

---

# Part D — Work packages for the original Improvement Guide

Each WP follows the same shape: **Pre-check → Changes → Tests → Done when**. Section numbers (§) refer to `IMPROVEMENT_GUIDE.md`. Where a WP needs a pure function to be testable, it says **extract**: that is the only refactor allowed.

**Facts confirmed while preparing this playbook** (re-confirm with the Pre-checks):
- All 12 components the guide wants lazy-loaded already have `export default` (required by `React.lazy`).
- `LoadingBlock` is a **named** export of `./components/Spinner.jsx` and `App.jsx` does **not** import it yet.
- Exact server error strings: `Student ID not found.` (404), `Name mismatch. Please provide your full registered names.` (400), `Already voted.` (400, `/verify-identity`), `No phone found.` (400), `Election is closed.` (403), and on `/vote-bulk`: `You have already cast your vote.` (400).
- Analytics label regex: `^[a-z0-9_-]{2,40}$` (`LABEL_RE`, `backend/analytics.py`).
- `frontend/usePolling.js` and `frontend/src/hooks/usePolling.js` are byte-identical (checked with `diff -q`).
- `CORSMiddleware` has `max_age=600`; there is no `GZipMiddleware`.

---

## WP-1 — Secrets hygiene (§2)

**The AI must not read secret values and cannot rotate secrets. It only fixes ignore rules and templates; a human rotates.**

**Pre-check**
```bash
cat .gitignore | grep -n "env"                                   # see what is ignored today
ls -a | grep -i "env"; ls backend | grep -i env; ls frontend -a | grep -i env
ls -a | grep "^.git$" || echo "no .git directory in this copy: history check must be done by the human"
```
**Changes**
1. Append to the **root** `.gitignore`:
```
# env files (never commit secrets)
*.env
.env
.env.*
!*.env.example
!.env.example
```
2. Create `*.env.example` files with **key names only**, produced without revealing values:
```bash
for f in backend.env frontend.env backend/loadtest.env; do
  cut -d= -f1 "$f" | grep -E '^[A-Za-z_][A-Za-z0-9_]*$' | sed 's/$/=/' > "${f}.example"   # names only, empty values
done
```
3. Do **not** delete the real env files from the working tree (the developer's machine needs them). Tell the human to run `git rm --cached` for any that are tracked.

**Tests (no secrets involved; dummy files in a throwaway dir)**
```bash
T=$(mktemp -d) && cp .gitignore "$T/" && cd "$T" && git init -q && mkdir -p backend frontend backend/loadtest
touch backend.env frontend.env backend/loadtest.env backend/.env frontend/.env frontend/.env.org-b backend.env.example
for f in backend.env frontend.env backend/loadtest.env backend/.env frontend/.env frontend/.env.org-b; do
  git check-ignore -q "$f" && echo "ignored OK: $f" || { echo "NOT IGNORED: $f"; exit 1; }; done
git check-ignore -q backend.env.example && { echo "example wrongly ignored"; exit 1; } || echo "example tracked OK"
```
Also: `grep -rn "=" *.env.example | grep -v "=$"` must print **nothing** (proves no value was copied).

**Done when:** the script prints OK for all six; `.example` files contain only `KEY=`; `DEVIATIONS.md` lists **HUMAN actions**: check history (`git log --all -- backend.env frontend.env backend/loadtest.env`), rotate Mongo user, `JWT_SECRET_KEY`, superadmin password, Cloudinary, B2, both SMS gateways if ever committed/shared; never share a zip containing `*.env` (§2.2).

---

## WP-2 — Lazy-load dashboards (§3.1)

**Pre-check**
```bash
cd frontend/src
grep -n "^import .* from './components/" App.jsx                   # static imports to convert
grep -c "export default" components/{SuperAdminDashboard,AdminDashboard,CommissionDashboard,ITAdminDashboard,FinancialControllerDashboard,OverseerDashboard,CandidateStatusPortal,VerifyCertificate,HeatmapOverlay,Results,ApplicantPortal,BallotBox}.jsx   # each must be >=1
grep -n "lazy(\|Suspense" App.jsx || echo "no lazy yet"
cd .. && npx vite build 2>&1 | grep -E "index-.*\.js"              # baseline size
```
**Changes** (exactly as §3.1, plus):
- Add `import { LoadingBlock } from './components/Spinner.jsx';` (named export; `App.jsx` does not import it today) and keep `OtpInput` + the login form eager.
- Wrap the **routed area once** in `<Suspense fallback={<LoadingBlock text="Loading…" />}>`; do not wrap the boot splash.
- Prefetch: `import('./components/BallotBox')` when identity is accepted (step becomes 2); `onPointerEnter` on nav buttons for `ApplicantPortal`.
- Render `HeatmapOverlay` only when `sessionStorage.getItem('admin_role') === 'superadmin'`.
- `vite.config.js`: add the `manualChunks` from §3.1 **inside** the existing `build` config (merge; keep the `test` block from WP-0).

**Tests**
1. L4: `npx vite build`; then
```bash
ls -l dist/assets/*.js | awk '{print $5, $9}' | sort -n
python3 - <<'PY'
import glob,os,re
entry=[f for f in glob.glob("dist/assets/index-*.js")]
assert entry, "no entry chunk"
size=max(os.path.getsize(f) for f in entry)
print("entry bytes:",size)
assert size < 250_000, f"entry chunk {size} >= 250 KB"
assert len(glob.glob("dist/assets/*.js")) >= 6, "expected several chunks"
PY
```
2. L3 (Vitest): render a tiny harness with `lazy(() => import('./components/Spinner.jsx'))` inside `Suspense` to prove the fallback shows, then the content (guards the wiring pattern, not the whole App).
3. L5 **HUMAN**: voter login → DevTools Network shows no `SuperAdminDashboard`/chart chunks; log in as admin → the dashboard chunk loads on demand with the "Loading…" block; vote flow shows no visible wait after identity (prefetch).

**Done when:** entry chunk < 250 KB raw (≈80 KB gzip; report both), build and lint clean, all lazy components load in L5.

---

## WP-3 — Skip the fixed splash when the server is warm (§3.2)

**Pre-check:** `sed -n 236,280p frontend/src/App.jsx` — confirm `COLD_HINT_MS = 1500`, the 800 ms / 600 ms / `EXIT_ANIM_MS` stages and `setBootReady`.

**Changes**
1. **Extract** `frontend/src/bootPlan.js`:
```js
export const COLD_HINT_MS = 1500;
/** elapsedMs = time until /health answered. Returns 'instant' (no splash stages) or 'staged'. */
export const bootPlan = (elapsedMs) => (elapsedMs < COLD_HINT_MS ? 'instant' : 'staged');
```
2. In the boot effect: when `/health` answers and `bootPlan(Date.now() - startedAt) === 'instant'` → `setBootReady(true)` immediately and skip the 800/600/350 ms stages. Keep the staged path unchanged otherwise. Reuse the existing `COLD_HINT_MS` (import it; delete the duplicate constant).
**Tests:** Vitest `bootPlan`: `0→instant`, `1499→instant`, `1500→staged`, `30000→staged`. L5 **HUMAN**: warm server ⇒ login form visible in well under 1 s; cold (stop the backend, start the page, start the backend) ⇒ staged splash still appears. **HUMAN (not AI):** schedule a `GET /health` ping every 10 min (cron-job.org/UptimeRobot) during the election window.
**Done when:** unit + L5 pass, no unused-variable lint errors.

---

## WP-4 — Polling (§3.3)

**Pre-check**
```bash
cd frontend/src
grep -rn "usePolling(" --include=*.jsx --include=*.js . | grep -v "hooks/usePolling.js"    # every call site + interval
grep -n "setInterval" components/Results.jsx                                                # expect line ~111
grep -n "usePaymentInfo" -r . | head
```
**Changes**

1. Replace `src/hooks/usePolling.js` with (keeps the old signature; 4th arg optional):
```js
import { useEffect, useRef } from 'react';

export default function usePolling(fn, intervalMs = 20000, enabled = true, { minGapMs = 15000 } = {}) {
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });

  useEffect(() => {
    if (!enabled || !intervalMs) return undefined;
    let running = false, stopped = false, last = 0, fails = 0, timer = null;

    const run = async () => {
      running = true; last = Date.now();
      try { await fnRef.current(); fails = 0; } catch { fails += 1; } finally { running = false; }
    };
    const schedule = () => {
      if (stopped) return;
      const base = intervalMs * Math.min(4, 2 ** fails);          // backoff x1, x2, x4 (cap) after failures
      const jitter = base * (Math.random() * 0.2 - 0.1);          // +-10 %
      timer = setTimeout(async () => {
        if (!stopped && !running && !document.hidden) await run();
        schedule();
      }, base + jitter);
    };
    const onEvent = () => {                                        // visibilitychange / online
      if (stopped || running || document.hidden) return;
      if (Date.now() - last < minGapMs) return;                    // blocks return-from-payment-app bursts
      run();
    };
    schedule();
    document.addEventListener('visibilitychange', onEvent);
    window.addEventListener('online', onEvent);
    return () => {
      stopped = true; clearTimeout(timer);
      document.removeEventListener('visibilitychange', onEvent);
      window.removeEventListener('online', onEvent);
    };
  }, [intervalMs, enabled, minGapMs]);
}
```
2. Call-site changes exactly as §3.3 items 2-4: `App.jsx` `/election-status` 30 s → **60 s** and fetch `/candidates` only when `showGuide` becomes true; `ApplicantPortal` fetch `/positions` once on mount and on tab return after ≥ 5 min, poll `/election-status` at 60 s, and re-fetch `/payment-info` on tab return and **just before the submit button becomes enabled** (never rely on a stale payment number); `Results.jsx` replace `setInterval(fetchData, 5000)` with `usePolling` at **10 s while `is_open`, 60 s otherwise, stopped when certified**.
3. Only **after** steps 1-2 pass tests, apply §3.3 item 4's backend part (return `is_open`/`is_certified` in `/election-results` and drop the extra `/election-status` call from `Results`) — it touches a public response shape, so add a backend test that the new keys exist **and** that existing keys are unchanged.
4. Optional item 5 (`/public/bootstrap`) is **out of scope** unless the human asks.

**Tests (Vitest, `renderHook`, `vi.useFakeTimers()`; set `document.hidden` via `Object.defineProperty`)**

| # | Scenario | Expect |
|---|---|---|
| P1 | interval 20 s, advance 60 s | fn called 3 times (±jitter tolerance: advance in steps and assert 2-4 calls) |
| P2 | fire `visibilitychange` 1 s after a run | **not** called (minGap) |
| P3 | fire `visibilitychange` 20 s after last run | called once |
| P4 | 10 `visibilitychange` events in 1 s | at most 1 call |
| P5 | `document.hidden = true` | timer ticks do nothing |
| P6 | `fn` rejects twice | next delays are ~2x then ~4x the interval; success resets to 1x |
| P7 | `fn` slower than the interval | never two concurrent calls |
| P8 | `enabled=false` | zero calls; unmount clears timers (`vi.getTimerCount() === 0`) |
| P9 | `fn` identity changes each render | latest `fn` is used; timer not restarted |

L5 **HUMAN**: open Apply and leave it idle → DevTools shows **< 4 requests/minute** (§3.3 acceptance); switch to the payment app and back → at most one refetch burst, not one per event.

**Done when:** P1-P9 green; static check `grep -rn "setInterval" frontend/src/components/Results.jsx` returns nothing; call-site intervals match the table in §3.3.

---

## WP-5 — Backend settings cache, indexes, GZip, CORS, cache headers (§3.4, §3.5)

**Pre-check**
```bash
cd backend
grep -n '"name": "election_config"\|"name": "election_phases"\|"name": "security_settings"' main.py      # every reader AND writer
grep -n "db.settings\.\(update_one\|replace_one\|insert_one\|delete_one\|find_one_and_update\)" main.py   # every writer
grep -n "create_index" main.py | sed -n 1,20p                                                             # startup index block ~120-170
grep -n "GZip" main.py || echo "no GZip"; grep -n "max_age" main.py
cat tests/conftest.py | sed -n 10,20p                                                                     # the autouse cache-reset fixture
```
**Changes (as §3.4/§3.5)**
1. Implement `cached_setting`/`invalidate_settings` with a 5 s TTL keyed by `(str(org_id), name)`. **Every writer found by the grep above that touches `election_config`, `election_phases` or `security_settings` must call `invalidate_settings(org_id, name)` immediately after the write.** Produce a table in `DEVIATIONS.md`: writer endpoint → invalidation line. A writer without an invalidation is a failed WP.
2. **Add `main._settings_cache.clear()` to the autouse fixture in `tests/conftest.py`** (same pattern as `main._ORG_CACHE.clear()`), otherwise tests leak state through the cache.
3. Indexes in the existing startup block, exactly the three from §3.4. `voters` index: **do not add** (⚠️ needs Atlas check); list it as a HUMAN item.
4. `GZipMiddleware(minimum_size=500)` registered **before** `CORSMiddleware` so CORS remains outermost.
5. `max_age=600` → `7200` **in the existing** `CORSMiddleware` call (WP-12 edits the same call for `expose_headers`; merge, do not duplicate).
6. `Cache-Control: public, max-age=15, stale-while-revalidate=30` + `Vary: Origin, X-Org-Slug` on `GET /positions` **only**. Never on `/election-status` (beyond a few seconds), never `/payment-info` (≤ 10 s), never any authenticated route.

**Tests** (`tests/test_wp5_cache.py`, fixture `env`)

| # | Test | Assertion |
|---|---|---|
| C1 | call `/election-status` twice | `db.settings.find_one` reads drop (wrap `env.db.settings.find_one` with a counter; second call adds 0 reads for cached docs) |
| C2 | TTL | advance `time.monotonic` (monkeypatch) by > 5 s → re-read |
| C3 | **invalidation, one test per writer** found in Pre-check | prime cache → call the admin endpoint that changes it → `/election-status` reflects the change **immediately** |
| C4 | tenant isolation | org t1 and t2 have different `election_config`; each `/election-status` returns its own; cache keys differ |
| C5 | `/positions` headers | `Cache-Control` as above; `Vary` contains `X-Org-Slug`; two orgs return their own positions |
| C6 | no caching leak | `/election-status`, `/payment-info`, `/admin/*` responses have **no** `public` Cache-Control |
| C7 | GZip | request with `Accept-Encoding: gzip` for a body > 500 bytes returns `content-encoding: gzip`; tiny body is not compressed |
| C8 | CORS still outermost | preflight `OPTIONS` with `Origin: http://localhost:5173` and `Access-Control-Request-Method: GET` returns `access-control-allow-origin`; `access-control-max-age == "7200"`; 401/403 responses also carry CORS headers |
| C9 | indexes | after running the startup hook, `await db.settings.index_information()` contains `org_id_1_name_1` (same for positions/candidates with `order`) |
| C10 | computed phase not cached | `/election-status` phase changes when the fake clock crosses a boundary **without** any invalidation (raw docs cached, result computed per call) |

**Done when:** C1-C10 green, full suite no new failures, writer→invalidation table complete.

---

## WP-6 — Client resilience, apply form, voting flow (§3.6, §4.4, §4.8)

Split into sub-packages; commit each separately.

### WP-6a — axios timeout and GET-only retry (§3.6)

**Pre-check:** `sed -n 28,36p frontend/src/api.js` (only `baseURL` today) and `sed -n 76,102p frontend/src/api.js` (the response interceptor that dispatches `an:api`, `an:netfail`, and handles 401).

**Changes**
1. `axios.create({ baseURL: API_BASE, timeout: 20000 })`.
2. New `src/retry.js` (pure, testable):
```js
export const RETRY_DELAYS_MS = [500, 1500];
const RETRYABLE_STATUS = new Set([502, 503, 504]);
/** GET/HEAD only. Never POST/PUT/DELETE (would double-submit /verify-identity, /vote-bulk, /apply ...). */
export function shouldRetry(error) {
  const cfg = error?.config;
  if (!cfg || cfg.noRetry) return false;
  if (!['get', 'head'].includes((cfg.method || 'get').toLowerCase())) return false;
  if ((cfg.__retries || 0) >= RETRY_DELAYS_MS.length) return false;
  if (error.code === 'ERR_CANCELED') return false;
  const noResponse = !error.response;                       // timeout or network failure
  return noResponse || RETRYABLE_STATUS.has(error.response.status);
}
```
3. In the response **error** interceptor (`api.js`), as the **first** statement: if `shouldRetry(error)`: `cfg.__retries = (cfg.__retries||0)+1; await sleep(RETRY_DELAYS_MS[cfg.__retries-1]); return api.request(cfg);`. Because the retry returns before the analytics dispatch, intermediate attempts do not emit `an:netfail` (this also serves WP-8 §5.2). Keep the 401 handling untouched.
4. Slow-connection signal: in the request interceptor set `config.__slowTimer = setTimeout(() => window.dispatchEvent(new CustomEvent('api:slow')), 6000)` and `clearTimeout(config.__slowTimer)` in both response handlers. UI components that need it (apply submit, vote submit) listen for `api:slow` and show *"Slow connection, still trying…"*.
5. Long operations pass their own timeout (`{ timeout: 120000 }`): the register export (WP-12) and file uploads.

**Tests (Vitest; replace `api.defaults.adapter` with a scripted fake; `vi.useFakeTimers()` + `await vi.advanceTimersByTimeAsync(...)`)**

| # | Scenario | Expect |
|---|---|---|
| R1 | `api.defaults.timeout` | `20000` |
| R2 | GET fails (network) twice then succeeds | resolves; adapter called **3** times; delays 500 ms then 1500 ms |
| R3 | GET fails 3 times | rejects after **3** calls (1 + 2 retries) |
| R4 | GET returns 503 once | retried; 404 and 400 are **not** retried |
| R5 | **POST** `/verify-identity` network failure | adapter called **exactly 1** time |
| R6 | POST `/vote-bulk` timeout | **exactly 1** call |
| R7 | per-request `timeout: 120000` | honoured (not overridden by the default) |
| R8 | `noRetry: true` on a GET | no retry |
| R9 | 401 with a token still clears the session as before | existing behaviour preserved |
| R10 | retries do not add `an:netfail` events | spy on `window.dispatchEvent`: at most one `an:netfail` after final failure |

**Done when:** R1-R10 green; `grep -rn "axios.create" frontend/src` shows only `api.js`.

### WP-6b — Stop the typing placeholder re-rendering all of `App` (§3.6)

**Pre-check:** `sed -n 304,352p frontend/src/App.jsx` and lines ~880/889 (the two `placeholder=` attributes). The effect calls `setPlaceholderText`/`setTypingSpeed` every 40-120 ms while both fields are empty, re-rendering the whole `App`.

**Change (default, lowest risk: §3.6 "drop it and use a static example")**: delete the effect and the four states (`placeholderText`, `isDeleting`, `loopNum`, `typingSpeed`) and use static placeholders built from `examples[0]` (`Student Registration Number e.g. …`, `Full Name e.g. …`). If the human prefers to keep the animation, instead **extract** the effect and state into a child component that renders only the two inputs; `App` must not own any animation state.
**Tests:** static check `grep -n "setPlaceholderText\|setTypingSpeed\|setIsDeleting\|setLoopNum" frontend/src/App.jsx` returns **nothing** (default option); lint clean; L5 **HUMAN**: React DevTools Profiler shows no `App` re-renders while idle on the login screen.

### WP-6c — Shared cache for `/positions` and `/payment-info` (§3.6)

New `src/sharedCache.js`:
```js
const store = new Map();   // key -> { at, promise }
export function cachedPromise(key, loader, ttlMs = 60000) {
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return hit.promise;
  const promise = loader().catch((e) => { store.delete(key); throw e; });   // never cache a failure
  store.set(key, { at: Date.now(), promise });
  return promise;
}
export const clearSharedCache = () => store.clear();
```
Use it in `FeeSchedule.jsx` for `/positions` (60 s) and for `/payment-info` **only for display** (≤ 10 s, **never** at submit time, see WP-4). **Key must include the org slug** (`${slug}:positions`) because one browser tab can switch orgs (superadmin override key).
**Tests:** same key within TTL → loader called once; after TTL → twice; rejected loader → next call retries; different org keys → separate entries; `clearSharedCache` works.

### WP-6d — Resize photos on the phone (§3.6, §4.4 gap 2)  ⚠️ needs devices

Add `src/imageResize.js` exporting `async resizeImage(file, {maxSide=1600, quality=0.8})` using `createImageBitmap` + canvas → JPEG blob. **Any failure returns the original file** (never block an application). Skip non-images and files already < 1 MB. Unit-test the pure geometry helper (`fitWithin(w,h,max)`) and the fallback-on-error path with mocked `createImageBitmap`. **HUMAN**: test on real Android Chrome with HEIC/AVIF-capable phones.

### WP-6e — Apply form (§4.4)

**Pre-check**
```bash
cd frontend/src/components
grep -n 'accept=' ApplicantPortal.jsx            # receipt: "image/*,application/pdf" (line ~435); photo: "image/*" (~469)
grep -n "handleSubmit" ApplicantPortal.jsx
grep -n "ALLOWED\|image/jpeg\|Only JPEG" ../../../backend/main.py | head
```
**Changes (numbers are the gap numbers in §4.4)**
1. Receipt `accept` → `image/jpeg,image/png,image/webp,image/gif` (restrict picker; the backend allows exactly these four). Do **not** change the backend.
2. Client size check on selection: `file.size > 5 * 1024 * 1024` → inline error, file rejected (after WP-6d resize, rarely triggered).
3. Double-submit lock: `const busy = useRef(false)`; at the top of `handleSubmit`: `if (busy.current) return; busy.current = true;` and release in `finally`.
4/1. Step labels (`Checking your details (1/4)` … `Submitting (4/4)`, skip the photo step when none chosen) on the button + a status line; upload percent via `onUploadProgress`; `beforeunload` warning while uploading; "Slow connection…" on `api:slow`; **Cancel** via `AbortController`.
5. Validate **all** fields at once; list every missing item; mark each (`aria-invalid`, red border); scroll to the first.
6. Keep uploaded URLs in a `useRef` keyed by `name+size+lastModified`; skip files already uploaded on retry.
7. Extract **`src/applyErrors.js`** `mapApplyError(err, {online})` implementing the §4.4 table.
8. Send the failure reason with `submit_blocked` (`missing_field`, `bad_file_type`, `too_large`). Reasons are fixed labels; never include values.
9. When a draft is restored, show "Re-attach your receipt".
Also trim + uppercase the registration number via `regNo.js` before sending.

**Tests (Vitest)**

| # | Scenario | Expect |
|---|---|---|
| A1 | `mapApplyError` with: no response; `online:false`; 400 over 5 MB; 400 already applied; 403; 429; 502 | exactly the messages in §4.4 (table-driven test) |
| A2 | receipt input `accept` attribute | equals the four image types; contains no `pdf` |
| A3 | pick a 6 MB file | error shown; **no** API call made |
| A4 | press Enter twice / `dblClick` submit | `/apply/check-eligibility` called once |
| A5 | submit empty form | message lists **all** missing fields; each has `aria-invalid="true"`; focus/scroll moves to the first |
| A6 | receipt upload fails after photo succeeded, retry | photo upload API called **once in total**; receipt called twice |
| A7 | form disabled while busy | inputs/pickers inert; button `aria-busy` |
| A8 | draft restored | "Re-attach your receipt" visible |

### WP-6f — Voting flow (§4.8)

**Pre-check:** read `handleVerifyIdentity` (`App.jsx` ~458), `OtpInput.jsx`, the submit code in `BallotBox.jsx`, `/verify-otp` response keys (`reason`, `retry_after`, `attempts_remaining`), and `_assert_voter_session` (`main.py` ~3088).

**Changes**
1. **OTP feedback (gap 1):** keep the last `/verify-otp` error and pass it as `feedback` to `OtpInput`; stop clearing the field on a wrong code. **Extract** `src/otpFeedback.js` `toFeedback(errResponse)` → `{ kind, message, retryAfter, triesLeft }` for `no_live_code`, `wrong_code`, `guess_lock`, `session_expired`.
2. **Lost response (gaps 2-4):** (a) on `/vote-bulk` failure with *"You have already cast your vote."* **within the same ballot session**, show success ("Your vote has been recorded"); (b) after a network error with no response show *"We could not confirm your vote. Do not vote again; tap Check status"* and call the new `GET /vote-status`; (c) after 6 s (`api:slow`) show *"Still sending. Do not close this page or vote again."*; (d) add a `useRef` lock on "Confirm & Cast Vote".
3. **Backend `GET /vote-status`** (new; answers the guide's ⚠️ about the cleared `vote_jti`). Design, from reading `_assert_voter_session`: the server clears `vote_jti` when a vote succeeds, so the normal session check would reject the very token that just voted. Therefore:
   - add `"/vote-status"` to `PUBLIC_PATHS` (the auth guard is **fail-closed**; without this it demands an admin token);
   - in `auth.py` add `peek_voter_token(request, org_id)`: verify signature, expiry, `role == "voter"`, `org_id`; return the payload (do **not** bind to a student id);
   - handler: `payload = peek_voter_token(...)`; load the voter by `payload["sub"]` **scoped to the org**; if `has_voted` → `{"has_voted": true}`; else require the stored `vote_jti` to equal the token's `jti` (live session) and return `{"has_voted": false}`; else 401;
   - `_check_rate_limit(bucket="vote_status", limit=30, window_s=60, ...)`; return **nothing else**, ever.
4. **Resend (gap 5):** store the chosen `phone_index`; pass it on resend so the server does not return `needs_selection`.
5. **Pasted code (gap 6):** drop `maxLength`; `onChange` → `e.target.value.replace(/\D/g, '').slice(0, 6)`.
6. **SMS autofill (gap 7):** `autoComplete="one-time-code"`, `inputMode="numeric"`, `pattern="[0-9]*"`; optionally auto-submit at the 6th digit.
7. **Unconfirmed delivery (gap 8):** if the response has `delivery: "unconfirmed"`, show the "if no SMS in 2 minutes tap Resend; you will get the same code" text instead of "Code Sent!".
8. **Generic SMS failure (gap 9):** next-step text + support link (`buildSupportLink`).
9. **Turnstile (⚠️):** not implementable without devices; add a visible fallback message after 10 s of a disabled Verify button and list the real-device test as HUMAN.

**Tests**

Backend (`tests/test_vote_status.py`, use `test_security_regressions.py` helpers `_authenticate`, `_candidate`, `_FakeClient` monkeypatch; note its `_no_real_transactions` fixture):

| # | Scenario | Expect |
|---|---|---|
| S1 | authenticate, **no** vote yet | `{"has_voted": false}` |
| S2 | authenticate, vote, then `/vote-status` with the **same** token | 200 `{"has_voted": true}` (proves the cleared-jti case) |
| S3 | no token / tampered / expired | 401 |
| S4 | token for voter A | returns **A's** status only; there is no parameter to ask about B |
| S5 | token from org t1 sent with `X-Org-Slug: t2` | rejected |
| S6 | a newer OTP login invalidates the older token (not yet voted) | older token → 401 |
| S7 | response keys | exactly `{"has_voted"}` |
| S8 | 31 calls in a minute | 429 |
| S9 | `/vote-status` needs no admin token, and an admin token is **not** accepted as a voter token | verified both ways |

Frontend (Vitest): `toFeedback` table for the four reasons (+ `retry_after` → countdown text); `OtpInput` keeps the typed value after a wrong code; paste `"123 456"` → `123456`; `autocomplete="one-time-code"` present; resend sends `phone_index`; `BallotBox`: mocked `/vote-bulk` network error → "could not confirm" message and **no second POST** until Check status says `has_voted:false`; mocked 400 "already cast" → success screen; double-click confirm → one POST.

**Done when:** all of the above green; HUMAN items (Turnstile on real 3G, SMS delay per gateway) recorded as pending.

---

## WP-7 — Phase banner, Help, Results states, login errors, data-track (§4.1-4.3, §4.5, §4.6)

**Pre-check**
```bash
sed -n 2776,2800p backend/main.py                         # /election-status keys
grep -n "voting_phase\|applications_phase" frontend/src/components/ClosedNotice.jsx
sed -n 706,724p frontend/src/App.jsx                      # FabTrigger condition (~721)
grep -n "InlineHelpButton" -r frontend/src                # guide: referenced in a comment, absent from BallotBox
```
Phase values are exactly `'open' | 'not_started' | 'ended'` (from `_position`), with `voting_opens_at` / `applications_opens_at` set only while `not_started`.

### WP-7a — Phase banner + Apply now (§4.1)
1. **Extract** `src/phase.js` `derivePhase(status)` → one of `apply_open`, `voting_soon`, `voting_open`, `voting_closed` (applications open **takes priority** for the banner while voting has not opened), plus the dates to show. Dates via `fmtZoned(v, tz)` from `tz.js` in the **election** time zone.
2. `PhaseBanner.jsx` replaces the small yellow strip at the top of the voter card: one state at a time; colour **and** icon per state; text ≥ 16 px; one primary action (**Apply now**, only while applications are open, `data-track="phase-apply-now"`); countdown only for the next upcoming phase, reusing `ElectionTimeline`'s 1-second clock.
3. The login form and its button behaviour stay **unchanged** (the server decides; `ClosedNotice` documents exception grants).
**Tests (Vitest):** table-driven `derivePhase` for every combination of `applications_phase`/`voting_phase` ∈ {not_started, open, ended} (9 cases) including boundaries; banner renders exactly one state; Apply button present only for `apply_open`; clicking it switches `view` to `apply`; countdown text updates with fake timers; dates formatted in `Africa/Kampala` (assert a UTC instant near midnight renders the next local day). **HUMAN:** 360×640: banner < 25 % viewport height and the form is above the fold.

### WP-7b — Help button on Apply (§4.1a)
Render `FabTrigger` for `view === "apply"` as well; icon-only `?` on Apply and below 400 px; `HelpPanel` gets `page: 'voter' | 'apply'` and filters `items` per the §4.1a table (**extract** `helpItemsFor(page)` as a pure function); ~96 px bottom padding on the apply container; fade the FAB while an input is focused; support text becomes a `buildSupportLink` link with reasons "Application problem" / "Payment"; `data-track`: `help-fab`, `help-fees`, `help-timeline`, `help-support`.
**Tests:** `helpItemsFor('voter')` vs `('apply')` match the table exactly (Sample Ballot only on voter, Nomination Fees only on apply); FAB renders on `apply`, not on step 3 of voter. **HUMAN:** the `?` does not cover the submit button on 360×640 or the keyboard-open state.

### WP-7c — Safer "Vote Now" for logged-in admins (§4.1b)
Before `resetFlow()` runs from the nav "Vote Now" with an admin session (`sessionStorage.admin_token` present): `await confirm('You will be signed out. Continue?')`; cancelling changes nothing. **Tests:** with token + confirm=false → token still present; confirm=true → cleared; no token → no dialog.

### WP-7d — Results page states (§4.2)
**Extract** `resultsState(status, results)` → `not_started | live | no_votes | closed | embargoed`. `not_started`: "Voting opens <date>. Results will appear here live." (no "Live Tallying"); `no_votes`: "No votes yet."; hide turnout/voter-roll until data exists. **Tests:** one case per state, including `results_released === false`.

### WP-7e — Actionable login errors (§4.3)
**Extract** `src/loginErrors.js` `loginErrorGuidance(detail, {supportLink, registerLink})`; match by **exact server strings**:

| Server `detail` (exact) | Guidance contains |
|---|---|
| `Student ID not found.` | format `23/U/XXX/00000/GV`, check-the-register link, support link |
| `Name mismatch. Please provide your full registered names.` | "as they appear on the register (surname first is fine)", register link |
| `Already voted.` | "already voted", support link |
| `No phone found.` | contact-change link |
| `Election is closed.` (or any phase closed) | the phase notice with dates |
| anything else / object detail | fallback: original text (never `JSON.stringify` into the title) |

Also trim + uppercase the registration number with `regNo.js` before sending, plus inline format validation. **Tests:** table-driven over all rows; unknown string falls back; object `detail` does not crash.

### WP-7f — Name the important controls (§4.5, §4.6)
Add `data-track` to: `login-submit`, `login-switch-admin`, `apply-position-<n>`, `apply-payment-method`, `apply-proof-upload`, `apply-submit`, `apply-copy-number`, `apply-fee-link`, `help-fab`, `otp-submit`, `otp-resend`, `ballot-submit`, `results-tab-*`, plus WP-12's `export-register`, `export-register-format`, `export-mode-*`. Payment number: whole number tap-to-copy with "Tap to copy" + `document.execCommand('copy')` fallback, Copy target ≥ 44 px.
**Static test (save as `frontend/scripts/check_data_track.py`, run from the repo root):**
```python
import re, glob, sys
static, dynamic = set(), set()
for f in glob.glob("frontend/src/**/*.jsx", recursive=True):
    src = open(f, encoding="utf-8").read()
    static |= set(re.findall(r'data-track="([^"]+)"', src))
    dynamic |= set(re.findall(r'data-track=\{`([^`]+)`\}', src))
LABEL = re.compile(r"^[a-z0-9_-]{2,40}$")                       # same as backend LABEL_RE
bad = [n for n in static if not LABEL.fullmatch(n)]
bad += [n for n in dynamic if not LABEL.fullmatch(re.sub(r"\$\{[^}]*\}", "1", n))]
need = {"login-submit", "apply-submit", "help-fab", "otp-submit", "ballot-submit", "phase-apply-now", "export-register"}
missing = need - static
print(f"{len(static)} static, {len(dynamic)} dynamic labels")
if bad:     sys.exit(f"invalid labels (must match ^[a-z0-9_-]{{2,40}}$): {bad}")
if missing: sys.exit(f"missing required labels: {sorted(missing)}")
print("data-track labels OK")
```
Labels with template expressions such as `apply-position-${n}` are validated with the expression replaced by `1`. Labels must never contain IDs or names.

---

## WP-8 — Analytics instrumentation and dashboard (§1.2, §5)

**Pre-check**
```bash
sed -n 195,197p frontend/src/analytics.js          # an:api / an:netfail listeners
sed -n 128,136p frontend/src/analytics.js          # perf event (first_api_ms, load_ms)
sed -n 972,1020p backend/analytics.py              # route_audience, _record_api, outcome_middleware
sed -n 311,316p frontend/src/components/AnalyticsPanel.jsx
sed -n 36,44p frontend/src/components/UsageCharts.jsx
cd backend && pytest tests/test_analytics.py -q     # 48 tests must already pass (baseline)
```
**Changes and tests**

| § | Change | Test |
|---|---|---|
| 5.1 | `analytics.js`: `first_api_ms` ignores `/health` and failed calls; record the first **successful data-route** call (e.g. `/election-status`). Put the route in the `an:api` event detail (`api.js`). | Vitest (`vi.resetModules()` per test; dispatch `an:api` events): `/health` first → not recorded; failed call → not recorded; first successful `/election-status` → recorded once |
| 5.2 | Exclude `/health` from `an:netfail`; dedupe ≤ 1 per route per 30 s; carry page + connection type | dispatch 12 failures on `/health` → 0 logged; 5 on one route in 10 s → 1; after 31 s → 2 |
| 5.3 | `performance.mark('usable')` when the login form is interactive; send `usable_ms` | mark present after boot; value ≥ 0 |
| 5.4 | Backend: `_record_api` stores `seg="staff"` when the request has an `Authorization` header (or staff route) else `"public"` | add to `tests/test_analytics_routes.py`: call a public route and an `Authorization`-bearing route; the API table filtered by `seg=public` excludes the staff call. **Existing 48 tests must still pass** (old documents stored `seg="all"`; the query already matches `["seg","all"]`: keep that for old data) |
| 5.5 | After redeploy, confirm failures carry reasons; add labels for raw codes not in `REASONS` (`FunnelPanels.jsx`) | Vitest: every reason code the backend can set (`grep -n "set_reason(" backend/main.py` → list) has a label; unknown code renders the raw code without crashing |
| 5.6a | Dark-mode contrast: in `AnalyticsPanel.jsx` `btn`/`segOn`, `color: 'var(--card-bg)'` → `'#fff'` (or an `--on-primary` token). Search **all** files: `grep -rn "brand-primary" frontend/src \| grep "card-bg"` and fix each dark-text-on-brand case | static check returns nothing; Vitest: active button style colour is white |
| 5.6b | `UsageCharts.jsx` labels in the election time zone via `fmtZoned` instead of `getUTC*` | unit test: a UTC instant 23:30 on day X renders as day X+1 00:30 in `Africa/Kampala` |
| 5.6c | Default range "Last 24 hours" when all data is within 24 h | pure-function test |
| 5.6d | Load-test advice uses `expected_peak ≈ registered_voters × share_in_busiest_hour × (avg_vote_session_seconds/3600)`; the guide's example (1,500 voters, 40 %, 3-minute sessions) must compute to **30** | unit test of the function: `(1500, 0.40, 180) → 30`; test at 1.5-2x → 45-60 |
| 5.7 | `pageName()` returns `admin_login` when `isAdminPath` is true or path is `/admin` (backend whitelist already accepts it) | table test for `pageName(view, step, isAdminPath)` |
| 1.2 | Dashboard line "Tracking of funnel steps started on <date>" (from WP-9 `tracking_since`) | see WP-9 |

**HUMAN (not AI):** the §1.2 version-skew check (compare deployed commit on Render; look for `u` on `kind:"pv"` documents and old `kind:"fout"` documents). Do **not** "fix" analytics code for zeros before that check.
**Done when:** all rows green; `pytest tests/test_analytics.py` still 48/48.

---

## WP-9 — Admin insights (§6)

1. **Insights card (6.1).** **Extract** `buildInsights(summary)` → array of sentences: Vote→Apply %, identity failures + top reason, 3G/unknown share + p95 load, dead clicks by page/element, opened-vs-submitted. **Tests:** fixtures for each sentence; empty/zero data yields **no** misleading sentence (no `NaN%`, no division by zero); never includes IDs or names.
2. **Tagged-link builder (6.2).** Channels `whatsapp, facebook, class-group, poster-qr, sms` → `https://<host>/?src=<tag>`; tags must satisfy `^[a-z0-9_-]{2,40}$`. **Tests:** each channel builds a valid URL; invalid custom tag rejected; copy handler called.
3. **`tracking_since` (6.3).** Backend: earliest `day` in `analytics_counters` for the org, added to the summary response. **Tests:** two orgs with different first days; empty org returns `null`; frontend shows the line only when non-null.
4. **Alert panel (6.4).** Surface the existing alert thresholds' current state (healthy/degraded). **Tests:** mock each threshold state → correct label; read-only (no POST).

---

## WP-H — Housekeeping (§7)

Always **diff before delete**; never delete something that differs without a `DEVIATIONS.md` note.
```bash
diff -q frontend/usePolling.js frontend/src/hooks/usePolling.js && git rm frontend/usePolling.js          # identical at snapshot time
diff backend/test_flows.py backend/tests/test_flows.py | head                                             # review before removing the stale copy
diff backend/demo_results_mode.py backend/demo_results_mode_fixed.py | head                              # overlap: ask human which to keep
ls frontend/package-lock.json frontend/pnpm-lock.yaml                                                     # keep package-lock.json (scripts use npm); remove pnpm-lock.yaml + pnpm-workspace.yaml only with human OK
git rm -r --cached backend/__pycache__ backend/loadtest/__pycache__ 2>/dev/null
grep -n "uvicorn" Procfile Dockerfile railpack.json                                                        # list the three start commands; ASK which host is live before deleting any
```
**Tests:** after each removal run `pytest -q`, `npm run lint`, `npx vite build`; the suite count must equal baseline (or baseline minus exactly the removed duplicate's tests, noted). Add the three tests the guide lists (settings-cache invalidation, `seg` tagging, `first_api_ms` ignoring `/health`): they already exist in WP-5, WP-8.

---

# Part E — Final acceptance, reporting and hand-off

## E1. Text to add to `IMPROVEMENT_GUIDE.md` (WP-12)

Add to the summary table (§0) as row 12:

> | 12 | IT Admin voter-register export, set per IT admin by the superadmin: **Off / Redacted / Full** | IT admins need the register for daily running; it must be explicit, per person and audited, never on by default | M–L |

Add as **§4.9 IT Admin voter-register export** a short section stating: the three modes; default Off; Redacted equals the on-screen list (phones masked); Full = no redaction; superadmin-only control on the IT Admins tab; `POST /admin/voters/export` (xlsx/csv), never includes voting status; audited with no PII; rate-limited; "View as" cannot export. Point to Part C of this playbook for the implementation.

Add to §8 (order of work) under **Day 3**: "WP-12 export (after the axios timeout exists)". Add to §9 a row: *"IT admins with export enabled who were not explicitly granted it: target **0**"*, checked via the activity log (`it_admin_export_mode_changed`).

## E2. Global checks the AI must run before declaring "done"

```bash
# 1. Nothing secret was touched or committed
git status --porcelain | grep -E '\.env($|\.)' | grep -v '\.example$' && echo "FAIL: an env file changed" || echo "env files untouched OK"
git diff | grep -nEi "(password|secret|api_key|mongodb\+srv)[^\n]{0,40}[:=][ ]*['\"][^'\"]{6,}" && echo "REVIEW: possible secret in diff" || echo "no secret-like strings in diff OK"

# 2. Backend
cd backend && pytest -q                                    # no new failures vs baseline; all new tests green
python -m py_compile main.py auth.py analytics.py          # syntax
grep -n "db.voters.find" main.py | sed -n 1,80p            # every NEW voters query must carry org_query(...) (review each new one)

# 3. Frontend
cd ../frontend && npm run lint && npm test && npx vite build
python3 ../frontend/scripts/check_data_track.py 2>/dev/null || python3 scripts/check_data_track.py   # from repo root as documented

# 4. Bundle budget (WP-2)
ls -l dist/assets/index-*.js

# 5. WP-12 invariants (static)
grep -n "it_admin_export_mode" main.py | wc -l             # only in the places listed in 12.6.3
```

**Tenant-isolation sweep (mandatory):** for every endpoint or cache added in any WP, list it in `DEVIATIONS.md` with the line that scopes it to the organisation (`org_query`, `_oq`, or an org-keyed cache key). No line = not done.

**Privacy sweep (mandatory):** confirm no new audit-log entry, analytics event, label or error message contains a voter name, phone number, registration number, or free text typed by a user.

## E3. `DEVIATIONS.md` template (create at repo root; keep updated)

```markdown
# Deviations, mismatches and pending human checks

## Baseline (before any change)
| Item | Value |
|---|---|
| pytest -q | N passed / M failed / K skipped  (failing: ...) |
| npm run lint | ... |
| vite entry chunk | ... KB raw / ... KB gzip |

## Mismatches between the guide and the code (per WP)
| WP | Guide said | Code actually has | What I did |
|---|---|---|---|

## Skipped / partial items (with reason)
| WP | Item | Reason (needs device / needs data / needs human approval) |
|---|---|---|

## Writer -> cache-invalidation table (WP-5)
| Endpoint | Setting name | invalidate_settings line |
|---|---|---|

## Tenant-scoping table (new endpoints and caches)
| Thing | Scoping mechanism |
|---|---|

## HUMAN actions pending
- [ ] Rotate secrets if history shows they were ever committed/shared (WP-1)
- [ ] Keep-warm ping for GET /health every 10 min (WP-3)
- [ ] Atlas: confirm a voters index serving get_forgiving_filter + org_id (WP-5)
- [ ] Version-skew check on Render vs this code (WP-8)
- [ ] Real-device tests: 360x640, Slow 3G + 4x CPU, Turnstile, HEIC photos (WP-2, 6, 7)
- [ ] WP-12 manual checklist H1-H13
- [ ] Load test sized from the register, on staging with DEBUG_MODE=true, never production SMS
- [ ] Before/after metrics table (guide section 9)

## Final results
| Item | Value |
|---|---|
| pytest -q | ... (new tests: N) |
| npm test | ... |
| lint / build | ... |
| entry chunk | ... |
```

## E4. Final report the AI must return (and nothing more)

1. One table: every WP → **Done / Partial / Blocked**, with commit hash.
2. Test evidence: the three summary lines (`pytest`, `npm test`, `vite build`) versus baseline, and the count of **new** tests per WP.
3. The `DEVIATIONS.md` contents, verbatim.
4. For WP-12 specifically: the output of the L1 static checks, the list of tests T1-T19 with pass/fail, and a statement of which of H1-H13 still need a human.
5. **Honesty rule:** anything not executed (for example "no network, could not install dependencies", "no device") must be marked **Not verified** and never reported as passing.

## E5. What the AI must NOT do

- Do not read or print env values, rotate secrets, or push to any remote/deployment.
- Do not skip a WP's Pre-check because "the guide already says so".
- Do not merge WPs, change unrelated code, upgrade dependencies, or reformat files.
- Do not weaken security to make a test pass (for example by letting superadmin or "View as" export, or by reading the export mode from the token).
- Do not add `has_voted`, voting status, OTP data or password hashes to any export.
- Do not report a check as passing that was not run.

## E6. Traceability

| Guide § | WP | Automated evidence |
|---|---|---|
| 2 | WP-1 | `git check-ignore` script on dummy files |
| 3.1 | WP-2 | bundle size script, lazy harness test |
| 3.2 | WP-3 | `bootPlan` tests |
| 3.3 | WP-4 | `usePolling` P1-P9 |
| 3.4, 3.5 | WP-5 | C1-C10 |
| 3.6 | WP-6a-d | R1-R10, cache and resize tests |
| 4.4 | WP-6e | A1-A8 |
| 4.8 | WP-6f | S1-S9 + frontend feedback tests |
| 4.1-4.3, 4.5, 4.6 | WP-7a-f | phase/help/results/login-error table tests, data-track script |
| 5.x | WP-8 | analytics unit tests (48 existing must stay green) |
| 6.x | WP-9 | insights/link/tracking_since/alert tests |
| 7 | WP-H | suite count equals baseline |
| **new** | **WP-12** | **T1-T19 (pytest), Vitest suites, L1 checks, H1-H13** |
