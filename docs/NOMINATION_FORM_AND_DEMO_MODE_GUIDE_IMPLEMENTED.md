# BallotBox — Nomination Form + Demo Mode (implementation guide)

Two features, both configurable at runtime by the superadmin. Nothing is hardcoded to a client.

**Decisions locked in the chat**
- Demo mode is **switchable on any org** (not a dedicated demo org).
- The nomination-form **download button sits directly under the instructions**.
- Nomination form is a settings-driven section (enable, require, instructions, template, accepted types, size) that the superadmin fills in.
- Build order: **Nomination form first**, then Demo mode (so the demo covers the form).

**Baseline to beat:** backend `pytest` = 476 passed, 0 failed (step-3 overlay + test fixes). Every phase card below ends with "no new failures + its own tests green".

Everything below was checked against the code in `Multi-Tenant Voting System/`. Line numbers are from the current `backend/main.py` and will drift, so search by function name.

---

## 0. Corrections to my earlier ideas (found while reading the code)

| Earlier claim | What the code actually shows | Consequence |
|---|---|---|
| "Reuse `demo_results_mode.py` for seeding" | It is a **results-gating demo** on an in-memory Mongo (`mongomock`), not a seeder. | Only `seed_test_data.py` (HTTP-driven: orgs, positions, voters via CSV, role accounts via toggle → set-credentials) is a seed source. For in-app seeding, write an in-process seeder (Card D3). |
| "Demo reset can call reset-election" | `/admin/reset-election` **aborts if the B2 safety snapshot fails** and **refuses certified elections**. | Demo reset needs its own path that skips the snapshot (demo data is worthless) and is fenced to demo mode only. |
| "Show nomination form to the panel like other fields" | `payment_proof_url` is in `_FINANCE_ONLY_APPLICATION_FIELDS`; only the Financial Controller receives it. | Do **not** put the nomination form in that tuple. The vetting panel is who needs it. |
| "Reuse the existing upload route" | `/apply/upload-image` shares one rate-limit bucket (8 per 10 min per IP, `UPLOAD_RATE_LIMIT`). | An application already uses 2 uploads (photo + proof). A third would cut a campus NAT to 2 applicants per 10 min. Use a **separate bucket**. |
| "Switchable on any org" is safe as is | A demo inbox exposes OTPs to whoever opens the page. | See the safety model in Part B. This is the most important design point. |

---

# PART A — NOMINATION FORM

## A1. How it fits the existing code

- **Settings pattern to copy: `payment_info`.** A settings doc read through `tdb(request).settings`, a public `GET /payment-info` (listed in `_is_public`), a superadmin `PUT /superadmin/payment-info` that requires a `reason`, writes with `org_stamp`, and logs via `log_action`. Frontend: `paymentInfo.js` (`usePaymentInfo` with polling) and `PaymentInfoPanel.jsx`, mounted in `SuperAdminDashboard.jsx` (~line 1489).
- **Application submit:** `POST /apply` (`submit_application`) validates, snapshots `fee_required` at submit time, inserts into `applications`. The frontend (`ApplicantPortal.jsx`) uploads files to `/apply/upload-image` **first**, then posts the URLs to `/apply`.
- **Role shaping:** `shape_application_for_role` is the single place that decides what each role sees.
- **Tenant safety:** any new collection must be added to `TENANT_COLLECTIONS` in `tenant_db.py`, and `tests/test_tenant_scoping_lint.py` fails on raw `db.<tenant_collection>` access.

## A2. Data model

**Settings doc** `settings` where `name = "nomination_form"` (tenant-scoped):

```json
{
  "name": "nomination_form",
  "enabled": false,
  "required": true,
  "title": "Nomination Form",
  "instructions": "Download the form, fill it in, sign it, and upload the scan.",
  "template_file": { "url": "https://...", "filename": "nomination-form.pdf" },
  "accepted_types": ["pdf"],
  "max_mb": 5,
  "updated_at": "..."
}
```

Rules: `title` ≤ 80 chars, `instructions` ≤ 2000 chars, **plain text only** (render with newlines → paragraphs, never as HTML). `accepted_types` is a subset of `{"pdf","docx"}`; default PDF only. `max_mb` between 1 and 10.

**New tenant collection `nomination_uploads`** (register in `TENANT_COLLECTIONS`; add an index on `(org_id, created_at)` and a TTL on `created_at`, about 24 h):

```json
{ "org_id": "...", "storage_id": "ballotbox/nominations/<org>/<random>", "filename": "...", "content_type": "application/pdf",
  "size": 123456, "sha256": "...", "created_at": "...", "used": false }
```

**On the `applications` doc** (added by `/apply`):

```json
"nomination_form": { "storage_id": "...", "filename": "...", "size": 123456, "content_type": "...", "uploaded_at": "..." },
"nomination_form_required": true
```

`nomination_form_required` is a **snapshot at submit time**, exactly like `fee_required`, so later toggling the setting never rewrites history.

**Why an upload record instead of sending a URL:** `/apply` is public. If the client sent a URL or storage id directly, an applicant could attach someone else's file or another org's. With `nomination_uploads`, the client sends only the opaque upload id returned by the upload route, and `/apply` consumes that record (same org, unused, recent) and copies the metadata.

## A3. Backend

**1. Settings routes** (next to the payment-info routes):
- `GET /nomination-form` — public. Add `"/nomination-form"` to the GET set in `_is_public`. Return only what an applicant needs: `enabled, required, title, instructions, template_file.{url,filename}, accepted_types, max_mb`. If disabled, return `{"enabled": false}` and nothing else.
- `PUT /superadmin/nomination-form` — body model with `reason` required (≥3 chars), same shape as `PaymentInfoUpdate`. Validate lengths and enums, require `https://` for any template URL, reject "Nothing to change" like payment-info does, `invalidate_settings(request.state.org_id)` after the write, `log_action("nomination_form_changed", ..., {"reason", "old", "new"})`.
- `POST /superadmin/nomination-form/template` — superadmin uploads the **blank form** (PDF/DOCX). This file is public by nature, so a normal public Cloudinary raw upload is fine. Store `{url, filename}` in the settings doc, not in the application.

**2. Applicant upload route** `POST /apply/upload-document`:
- Add to `PUBLIC_PATHS` (the set near line 476, where `/apply/upload-image` already is).
- `await _check_rate_limit(request, bucket="upload_doc", limit=8, window_s=600, ...)`: its **own** bucket.
- `await assert_phase_open(request, "applications")`.
- Read the settings doc. If not `enabled`, return 404 "No nomination form is required."
- Read at most `max_mb * 1024 * 1024 + 1` bytes (never buffer unbounded, as `upload-image` does).
- **Magic-byte check** (mirror `_assert_real_image`): PDF must start with `%PDF-`. DOCX is a ZIP, so it must start with `PK\x03\x04`. A zip prefix alone also matches any zip, so for DOCX additionally open it with `zipfile` and require `[Content_Types].xml` and `word/document.xml`; refuse anything containing `vbaProject.bin`. Honour `accepted_types`.
- Ignore the client's `Content-Type` and filename for decisions (both attacker-controlled). Sanitise the stored filename (strip path, control characters, cap length).
- **Storage: private.** Nomination forms carry signatures and IDs. Upload to Cloudinary as `resource_type="raw"` with `type="authenticated"` (not a public URL), under a per-org folder, with a random public id. Reading back goes through a **signed, expiring** link (A3.4). *Check the exact SDK call against the installed `cloudinary` version before relying on it: the intent is `cloudinary.uploader.upload(..., resource_type="raw", type="authenticated")` and `cloudinary.utils.private_download_url(...)` or a signed `cloudinary_url(..., sign_url=True)`; I have not run these here.* If you would rather not use Cloudinary raw storage, the same interface works over B2 (already used by `backup.py`).
- On success insert into `nomination_uploads` and return `{"upload_id": "...", "filename": "...", "size": n}`. Never return a storage URL.
- On storage failure, `alert_critical(...)` like the image route, and return 502.

**3. Change `/apply` and `ApplicationSubmit`:**
- Add `nomination_upload_id: str = Field("", max_length=64)` to `ApplicationSubmit` (line ~895).
- In `submit_application`, after the existing checks and **before** the insert: read the settings doc. If `enabled and required` and no `nomination_upload_id`, return 400 "The nomination form is required." If an id is given, atomically consume it (`find_one_and_update` on `{_id, org_id, used: False}` → `used: True`); if it is missing, used, or expired, return 400 "Please upload the nomination form again."
- Insert `nomination_form` and `nomination_form_required` on the application. If the setting is disabled, ignore any id and store `nomination_form_required: False`.
- Do **not** add the form to `application_snapshot` (that feeds the public candidate status page and the printed snapshot).
- Add `"nomination_form_required": ...` to the `log_action("application_submitted", ...)` details.

**4. Reading the form back (vetting panel and admins)**
- `GET /admin/applications/{id}/nomination-form` returns a short-lived signed URL (about 5 min) plus filename. The prefix `/admin/applications` is already in `PANEL_ALLOWED_PREFIXES`, so panel tokens can reach it; route guards still apply inside.
- Allowed roles: `vetting`, `superadmin`, `overseer`. Deny `commission` unless it is a resolved application (same rule `list_applications` already uses).
- `log_action("nomination_form_viewed", actor, {"application_id"})` on every call. The panel is told its views are confidential, so views should be auditable.
- In `list_applications` / `shape_application_for_role`: strip `nomination_form.storage_id` from every role's response and expose only `has_nomination_form`, `nomination_form_filename`, `nomination_form_required`. Never send the storage id to a browser.

**5. Out of scope for v1 (note it, don't build it):** correcting a nomination form via the IT-admin edit route (`APPLICATION_EDITABLE_FIELDS` stays unchanged), and letting an applicant add the form after submitting. If the setting is switched to "required" after applications exist, those older applications show "Not required at submission".

## A4. Frontend

1. **`nominationForm.js`** (hook, same shape as `usePaymentInfo`): `useNominationForm(pollMs)` calls `GET /nomination-form`. Poll like payment info so a change made mid-application is picked up.
2. **`NominationFormPanel.jsx`** (superadmin), modelled on `PaymentInfoPanel.jsx`: enable toggle, require toggle, title, instructions textarea, template-file upload (calls the template route), accepted types checkboxes, max size, reason field, Save. Mount in `SuperAdminDashboard.jsx` beside `<PaymentInfoPanel />`.
3. **`ApplicantPortal.jsx`**: render a new section only when `enabled`, in this order inside the section:
   1. heading (the configured `title`, plus `*` if required)
   2. the instructions text
   3. **the Download button, immediately under the instructions** (a normal link to `template_file.url` with `download`)
   4. the upload dropzone and the chosen filename

   Place the section after Manifesto and before Proof of Payment.
4. Wire the upload into `onSubmit`: upload the document to `/apply/upload-document` (multipart), keep the returned `upload_id` in the existing `uploadedRef` cache so a retry doesn't re-upload, and include `nomination_upload_id` in the `/apply` body. **Recompute the progress step numbers**: today `upload(form.image, 2)`, `upload(paymentProof, hasPhoto ? 3 : 2)` and `setStep(hasPhoto ? 4 : 3)` assume at most two uploads.
5. `applyErrors.js`: add `nomination_form` to `missingFields` (only when enabled and required) and a friendly message to `mapApplyError` for the new 400s.
6. Draft saving (`savedDraft`) already skips files, so no change.
7. **Vetting dashboard** (`VettingDashboard.jsx`): a "Nomination form" row on each application with a View button that calls the A3.4 route and opens the signed link. Show "Not required at submission" when `nomination_form_required` is false and nothing was uploaded.
8. **Template seam.** `ApplicantPortal` has class hooks from the blueprint templates (`k?.sec`, `k?.lbl`, `sx(...)`) with snapshot tests (`ApplicantPortal.template.test.jsx`, `__snapshots__`). Use the same hooks for the new section and update snapshots **deliberately**, not blindly. Check `BLUEPRINT_TEMPLATE_GUIDE.md` first.

## A5. Tests (backend, in `backend/tests/`)

New file `test_nomination_form.py`, using the shared env fixture (it already seeds four voters, as the legacy-data fix found):
- Settings: public read hides everything when disabled; PUT needs a reason; rejects non-https template URL, bad types, size out of range; nothing-to-change returns 400; audit row written; settings cache invalidated (a read right after PUT shows the new value).
- Upload: wrong magic bytes with a `.pdf` name rejected; oversize rejected; DOCX without `word/document.xml` rejected; disabled → 404; closed applications phase → rejected; separate rate-limit bucket (8 document uploads don't consume the image bucket).
- Submit: required + missing → 400; required + valid upload → stored with `nomination_form_required: True`; upload id reused → 400; upload id from **another org** → 400; disabled setting ignores an id; toggling `required` later does not change an existing application's snapshot.
- Read-back: storage id never appears in any role's list response; each allowed role gets a signed link; `commission` is denied for a pending application; every view writes an audit row.
- Lint: `nomination_uploads` is in `TENANT_COLLECTIONS`, and `test_tenant_scoping_lint.py` still passes with no new `ALLOWED` entries.

Frontend (`npm test`): panel renders and saves; applicant section hidden when disabled; download link is directly after the instructions in DOM order; submit blocked with the right message when required and missing.

## A6. Phase cards (one session, one branch each)

| Card | Scope | Files |
|---|---|---|
| **N1** | Settings doc + public GET + superadmin PUT + template upload + tests | `main.py`, `tests/test_nomination_form.py` |
| **N2** | `nomination_uploads` collection, `/apply/upload-document`, `/apply` changes + tests | `main.py`, `tenant_db.py`, `models` (ApplicationSubmit) |
| **N3** | Read-back route, role shaping, audit + tests | `main.py` |
| **N4** | Frontend: hook, superadmin panel, applicant section, errors, vetting row, template snapshots | `ApplicantPortal.jsx`, new panel, `applyErrors.js`, `VettingDashboard.jsx` |

N1 → N2 → N3 are sequential (same file). N4 can start once N1's response shapes are fixed.

---

# PART B — DEMO MODE

## B1. The idea in one paragraph

Every OTP, candidate status link, admin temp password and notice already goes through **one function**, `send_sms_status` (~line 1232), which even has a `DEBUG_MODE` branch today. Add a per-org demo check there: in demo mode, save the message to a `demo_inbox` collection instead of calling a provider, skip the SMS budget, return `"ok"`. Everything downstream (OTP storage, verification, cooldowns, status tokens) behaves normally, so the client tests the real flow. A floating message icon shows the inbox. A superadmin "Demo controls" panel handles phase jumping, seeding and reset.

Callers that matter, all of which flow through that one function: voter OTP (`~3546`, `send_sms_status` directly), admin temp passwords (`~1633`, `kind="admin"`), candidate status link on apply (`~4296`) and resend (`~4474`), notices (`~1712`, `~10232`), and the test-SMS route (`~5010`).

## B2. The safety model (read this before coding)

The inbox shows OTP codes to **anyone who opens the page**. That is fine for fake voters and dangerous for real ones. Because you chose "switchable on any org", these rules make that safe:

1. **Enable only on an org whose election has not started:** 0 applications, 0 vote events, not certified. The enable route checks and returns 409 otherwise. This also guarantees that everything created *during* demo is demo data.
2. **Only fake numbers are captured.** Seeded demo voters get numbers in a reserved range (e.g. `256700000NNN`, constant `DEMO_PHONE_PREFIX`). In demo mode, a message to a number **with that prefix** goes to the inbox. A message to **any other number is refused** (return `"failed"`, log it, never store the text). So a real student's OTP is never exposed, and no real SMS is spent, even if a real roster is already imported.
3. **Exit/reset is fenced.** It is only callable while demo is on. It removes demo-tagged rows (`is_demo: true` on seeded voters, positions, role accounts, panel members) plus the election-activity collections that were empty at enable time (applications, candidates, vote events, OTPs, candidate tokens, certificates, exception grants, demo inbox). It **never touches** untagged roster voters, branding, or anything that existed before. It restores the schedule/`election_config` snapshot taken at enable time.
4. **Auto-expire.** Enable sets `expires_at` (default 3 days, max 14). A check in `_demo_active` treats an expired demo as off, so a forgotten demo cannot linger.
5. **Loud banner.** A "DEMO: no real SMS sent" strip appears on every page while on.
6. **Audit.** `demo_enabled`, `demo_extended`, `demo_reset`, `demo_disabled` via `log_action`, each with a required reason.

## B3. Backend

**State:** settings doc `name = "demo_mode"` = `{enabled, enabled_at, expires_at, enabled_by, snapshot: {election_phases, election_config}}`. Read via `cached_setting` (short TTL), so **call `invalidate_settings(org_id)` after every change** (a stale cache would keep intercepting, or keep sending, for up to the TTL).

```python
async def _demo_active(org_id) -> bool:
    doc = await cached_setting(org_id, "demo_mode") or {}
    exp = doc.get("expires_at")
    return bool(doc.get("enabled") and exp and exp > datetime.utcnow())
```

**Hook (the only change to existing SMS code):** in `send_sms_status`, **before** the `DEBUG_MODE` branch:

```python
if org and await _demo_active(org):
    return await _demo_capture(org, to_number, message_text, kind)   # "ok" for fake numbers, "failed" otherwise
```

`_demo_capture` checks the number prefix (B2 rule 2), inserts `{org_id, to, kind, message, created_at}` through `tdb_for(org).demo_inbox`, caps the inbox per org (keep the newest ~200), and does **not** call `_safe_count_sms` or either provider. Register `demo_inbox` in `TENANT_COLLECTIONS`.

**Routes** (superadmin routes are guarded automatically by the fail-closed middleware, but the inbox read is public and needs its own rules):
- `GET /demo/inbox` — **public**, add to `_is_public`'s GET set. Return **404 unless `_demo_active`**, so on a normal org the route simply doesn't exist. Rate-limit it (the icon polls). Newest first, last 50.
- `POST /superadmin/demo/enable` `{reason, days}` — checks B2 rule 1; saves the snapshot; sets the flag; invalidates cache; logs.
- `POST /superadmin/demo/disable` `{reason}` — runs the fenced reset (B2 rule 3), restores the snapshot, clears the flag.
- `POST /superadmin/demo/seed` — idempotent in-process seeder (B4).
- `POST /superadmin/demo/phase` `{phase}` — jump phase (B4).
- `POST /superadmin/demo/reset` — fenced reset, stays in demo.
- `GET /superadmin/demo/status` — enabled, expiry, counts, role credentials for the demo accounts.

Every `/superadmin/demo/*` handler first requires `_demo_active` (except `enable`), as a second guard on top of the role check.

**Refactor needed:** `/admin/schedule/phases` (`set_phase_schedule`) contains the schedule write inline. Extract the write itself into a helper (`_write_phase_schedule(org_id, phases, tz)`) so phase-jump reuses it. Do **not** call the route handler from the demo code: it carries validation for real elections (early-end reason, 3-panelist minimum).

## B4. "Test all sections": Demo controls

Phases are `applications → vetting → campaign → voting → results` (`PHASE_NAMES`). A phase-jump sets the window so that phase is "active now" and the earlier ones are closed, via the extracted helper. Details that will bite if missed:
- **Vetting needs ≥3 active panelists** (409 in `set_phase_schedule`). The seeder creates 3 demo panel members first.
- **Voting needs approved, finance-cleared candidates** (`finance_cleared` gate) and `election_config.is_open`. The seeder creates applicants in several states and, for the "voting" jump, approves and clears the demo ones through the same code paths the real approval flow uses, not by writing status directly.
- **Results**: certification refuses an open election (`toggle_certification`); the "results" jump closes voting first.

The seeder (`/superadmin/demo/seed`) creates, all tagged `is_demo`: ~40 voters with fake-prefix phones, positions if none exist, one demo account per role (IT admin, commissioner, financial controller, overseer, 3 panelists) with generated passwords returned to the panel, and a few sample applications. `seed_test_data.py` shows which roles and endpoints are involved, but it drives them over HTTP; do the equivalent in-process.

Because the superadmin already has a read-only **View** (`ViewAsButton` → `/superadmin/view-as`) for admin dashboards, clients may not need the demo credentials at all for a guided demo. The credentials are for letting a client click around **themselves**.

Panel buttons: Enable/Disable (with reason and days), Seed, Jump to phase (5 buttons), Reset, Extend, and an expiry countdown.

## B5. Frontend

- **`DemoInbox.jsx`** (floating icon): mounted once in `App.jsx`, shown **only when demo is on**. Detecting that: call `GET /demo/inbox` once; a 404 means "not demo" and the component renders nothing and stops polling. When on, poll about every 5 s, with a badge for unread. List newest first: OTP messages get a **Copy code** button (detect the 6-digit code with a regex in the client), messages with a link get a clickable **Open** (detect `https?://` with a regex). Nothing needs parsing on the server.
- **Banner:** "DEMO: no real SMS sent" while on. Don't reuse `FloatingHelpMenu` (it is a help launcher with its own modal); build a sibling button and offset them so they don't overlap on mobile.
- **`DemoControlsPanel.jsx`** (superadmin), mounted in `SuperAdminDashboard.jsx`.
- Template seam: same rule as A4.8.

## B6. Tests (`tests/test_demo_mode.py`)

- Inbox: 404 when demo off; 404 after expiry; available when on; capped at the limit.
- Interceptor: OTP request on a demo voter lands in the inbox, **no provider is called** (monkeypatch `_sms_try_provider` to fail the test if invoked), `sms_usage` unchanged; the OTP then verifies normally.
- **Real number in demo mode is refused** and its text is **never stored**.
- Enable refused when applications or votes exist, or certified; allowed otherwise.
- Candidate status link on `/apply` and admin temp password both reach the inbox.
- Reset removes tagged rows and activity, leaves untagged roster voters and branding intact, and restores the schedule snapshot.
- Disable and reset refuse when demo is off.
- Settings cache: toggling takes effect immediately (guards the `invalidate_settings` requirement).
- Nomination form (after Part A): the demo seed applicants can submit with a document and the vetting role can read it.
- Lint stays green; `demo_inbox` is registered in `TENANT_COLLECTIONS`.

## B7. Phase cards

| Card | Scope | Files |
|---|---|---|
| **D1** | `_demo_active`, interceptor in `send_sms_status`, `demo_inbox`, `GET /demo/inbox`, enable/disable with B2 guards + tests | `main.py`, `tenant_db.py` |
| **D2** | Extract `_write_phase_schedule`, phase-jump route + tests | `main.py` |
| **D3** | In-process seeder, fenced reset, role credentials + tests | `main.py` (or a new `demo_seed.py` imported by it) |
| **D4** | Frontend: `DemoInbox.jsx`, banner, `DemoControlsPanel.jsx`, snapshots | `App.jsx`, `SuperAdminDashboard.jsx`, new components |

---

## C. Order of work and acceptance

1. **N1 → N2 → N3**, then **N4**.
2. **D1 → D2 → D3**, then **D4**.
3. Final acceptance for each card: full `pytest` still 476 + the card's new tests, `npm test`, `npm run lint`, `npx vite build` all clean.

## D. Decisions I made that you may want to change

- **Private storage + signed links** for nomination forms (vs. public Cloudinary URLs like photos). It costs one extra route; it avoids signed IDs sitting at guessable-ish public URLs.
- **PDF only by default**, DOCX opt-in per org.
- **Fake-number-only capture** in demo mode. Stricter than "capture everything"; it is what makes "any org" safe.
- **Demo requires an org that hasn't started its election.** If you need to demo on an org that already has applications, use a dedicated sandbox org instead.
- Nomination form is **not editable after submit** in v1.

## E. Not verified

I did not run any of this. Specifically unconfirmed: the exact Cloudinary SDK calls for authenticated raw upload and signed download URLs (check against the installed version), and the shape of the `ApplicantPortal` template snapshot tests after the new section is added.

---

# IMPLEMENTATION RECORD — 2026-10-07

All guide cards N1–N4 and D1–D4 have been implemented in the supplied BallotBox codebase.

## Completed work

**N1–N3:** The nomination-form runtime settings, template upload, private completed-form upload, tenant-scoped temporary upload record, atomic submission consumption, required-at-submission snapshot, signed vetting/admin read-back, response shaping, and audit logging are implemented. The document upload limiter was separated from the existing image-upload limiter as required.

**N4:** The applicant nomination section, direct-under-instructions Download button, upload handling/cache, progress-step recalculation, error messages, superadmin settings panel, vetting View action, and frontend tests are implemented. Existing blueprint template hooks are used. Existing snapshots were intentionally left unchanged because the template fixture keeps the runtime feature disabled.

**D1:** Per-organisation demo state, expiry, safety gates, fake-number-only SMS interception, public inbox, inbox cap/rate limit, cache invalidation, and demo audit actions are implemented.

**D2:** `_write_phase_schedule()` was extracted and demo phase jumping was implemented for applications, vetting, campaign, voting, and results.

**D3:** An idempotent in-process seeder, reserved-ID collision protection, demo role/panel credentials, demo tagging, real finance-clear/application-resolution paths, and fenced reset/restore behavior are implemented.

**D4:** The global demo inbox/banner and superadmin Demo Controls panel with seed/reset/extend/disable, phase controls, credentials, counts, and expiry countdown are implemented.

## Additional safety fixes made during implementation

- Pre-existing voter IDs are protected from demo seeding collisions.
- Reset deletes only demo-tagged voter/position/panel/application/candidate/vote/certificate/token/exception/nomination data and demo OTP/inbox state.
- Pre-demo SMS usage accounting is left untouched.
- Reset clears temporary demo credentials until the next seed.
- Bulk vote events are tagged consistently with single vote events.

## Verification

Static verification completed successfully:

- all backend Python files parse and compile;
- all frontend JS/JSX/TS/TSX files parse successfully;
- tenant-scoping lint logic reports no unexpected violations and no stale allow-list entries.

The environment could not execute `pytest`, Vitest, ESLint, or Vite because the uploaded project lacks installed dependency directories and the execution environment could not download missing packages. No claim is made that the original 476-test baseline was re-run successfully.
