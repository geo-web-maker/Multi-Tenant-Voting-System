# BallotBox — Nomination Form + Demo Mode
## Implementation and Verification Report

**Implementation date:** 2026-10-07
**Source guide:** `NOMINATION_FORM_AND_DEMO_MODE_GUIDE.md`

## 1. Completion status

All implementation cards in the guide have been addressed:

| Card | Status | Result |
|---|---|---|
| N1 | Implemented / verified | Nomination-form settings, public GET, superadmin update, template upload, validation/audit/cache invalidation coverage. |
| N2 | Implemented / completed | Private completed-form upload, tenant-safe temporary upload records, document magic-byte/ZIP validation, atomic upload consumption, application snapshot, separate upload rate-limit bucket. |
| N3 | Implemented / verified | Signed short-lived read-back URL, role restrictions, audit logging, and response shaping that never exposes storage IDs. |
| N4 | Implemented | Applicant UI, download/upload placement, progress-step recalculation, validation/error handling, superadmin panel, vetting View action, template hooks, and frontend tests. |
| D1 | Implemented | Per-organisation demo state, expiry, fake-number-only SMS interception, inbox, safety gates, reset/disable fencing, cache invalidation, and audit logging. |
| D2 | Implemented | Shared `_write_phase_schedule()` persistence helper and demo phase jumping without invoking real-election route validation. |
| D3 | Implemented | Idempotent in-process demo seeder, reserved-ID collision protection, demo role accounts/panelists, fenced reset, phase preparation using real application resolution/finance-clear paths, and demo tagging. |
| D4 | Implemented | Floating demo inbox/banner, superadmin demo controls, phase controls, seed/reset/extend/disable, credentials display, and expiry countdown. |

## 2. Nomination Form implementation

### N1 — Settings

The runtime nomination-form configuration is already tenant-scoped and follows the existing payment-info settings pattern.

Implemented/verified behavior:

- `GET /nomination-form` is available to applicants and returns only applicant-safe fields.
- Disabled form settings return only `{"enabled": false}`.
- `PUT /superadmin/nomination-form` requires a reason, validates the configured title/instructions/types/size/template URL, rejects no-op changes, invalidates the settings cache, and writes an audit event.
- `POST /superadmin/nomination-form/template` accepts the blank PDF/DOCX template and stores the configured template reference.

### N2 — Completed-form upload and application submission

The applicant upload path uses a separate rate-limit bucket from photo/receipt uploads so the nomination form does not consume the normal image-upload allowance.

Security and validation implemented:

- maximum upload size is bounded before untrusted content can be buffered without limit;
- PDF files require the `%PDF-` magic prefix;
- DOCX files require a valid ZIP structure containing both `[Content_Types].xml` and `word/document.xml`;
- macro-enabled DOCX files containing `vbaProject.bin` are rejected;
- extension and client `Content-Type` are not trusted for file-type decisions;
- filenames are sanitized;
- upload records are tenant-scoped and expire automatically;
- `/apply` atomically consumes a recent, unused upload belonging to the same tenant;
- the application stores only the copied form metadata plus the required-at-submission snapshot;
- the nomination form is deliberately excluded from the public application snapshot.

### N3 — Vetting/admin read-back

Completed nomination forms are read through the existing private-storage abstraction with short-lived presigned download links.

Implemented/verified behavior:

- vetting, superadmin, and overseer can request the signed download link;
- commission access remains restricted to resolved applications;
- every read is audited as `nomination_form_viewed`;
- application list/shape responses expose only `has_nomination_form`, `nomination_form_filename`, and `nomination_form_required`;
- browser responses never expose the private storage identifier.

### N4 — Frontend

Added:

- `frontend/src/nominationForm.js`
- `frontend/src/components/NominationFormPanel.jsx`

Updated:

- `ApplicantPortal.jsx`
- `applyErrors.js`
- `SuperAdminDashboard.jsx`
- `VettingDashboard.jsx`

The applicant section appears only when enabled and follows the required DOM order:

1. configured heading;
2. configured plain-text instructions;
3. download button immediately after the instructions;
4. completed-form upload area and selected filename.

The section is positioned after Manifesto and before Proof of Payment. Upload progress steps are recalculated for the presence/absence of the optional photo and enabled nomination-form upload.

The existing blueprint template class hooks are used for the new elements. Existing snapshot output remains unchanged because its default fixture has the runtime nomination-form setting disabled; this was intentional rather than a blind snapshot regeneration.

## 3. Demo Mode implementation

### D1 — Safety model and SMS inbox

Implemented as a per-organisation runtime setting:

- `enabled`
- `enabled_at`
- `expires_at`
- `enabled_by`
- election phase/config snapshot

The central `send_sms_status()` path checks demo mode before the existing DEBUG/provider branch. In active demo mode:

- messages to the reserved fake-number prefix are captured in `demo_inbox`;
- real numbers are refused and their message text is never stored;
- no SMS provider is called;
- SMS budget accounting is not touched;
- inbox polling is rate-limited and returns the newest 50 entries;
- inbox data expires/gets capped automatically.

Demo enablement is rejected when the organisation already has applications, vote events, or certification state. Expiry is enforced by `_demo_active()` so an expired demo behaves as disabled.

All demo-mode changes require a reason and are audited with:

- `demo_enabled`
- `demo_extended`
- `demo_reset`
- `demo_disabled`

### D2 — Phase-jump infrastructure

The real election schedule persistence was extracted into `_write_phase_schedule()` so demo phase jumps can reuse the same persistence/cache invalidation mechanism without calling the real schedule route's production-election safeguards.

Supported demo phase targets are:

- applications
- vetting
- campaign
- voting
- results

The voting jump closes earlier phases, opens the voting window, and prepares approved/finance-cleared demo candidates first. Results closes the voting window before entering results.

### D3 — Demo seeding and fenced reset

The in-process seeder is idempotent and creates/tagges synthetic data with `is_demo: true`.

It creates:

- about 40 demo voters using reserved fake phone numbers;
- positions only when the organisation has no existing positions;
- one demo account for IT admin, commissioner, financial controller, and overseer;
- three demo panelists;
- sample applications.

Reserved demo voter IDs are checked for collisions with untagged real voters before seeding. This prevents reset from ever taking ownership of an existing real roster record.

The demo voting preparation uses the existing finance-clear core and the existing application resolution path rather than directly setting approval/finance state, so the demo follows the same business logic as the real election flow.

Reset/disable remove only demo-tagged principals and activity plus demo OTP/inbox data, restore the election schedule/config snapshot, and preserve pre-existing roster and branding data. Reset also clears previously returned demo credentials until the next seed.

### D4 — Frontend controls

Added:

- `frontend/src/components/DemoInbox.jsx`
- `frontend/src/components/DemoControlsPanel.jsx`

Updated:

- `App.jsx`
- `SuperAdminDashboard.jsx`

The inbox component:

- appears only when demo mode is active;
- polls approximately every 5 seconds;
- shows a demo warning banner;
- provides a floating inbox button and unread count;
- detects/copies six-digit OTP codes;
- detects and opens links in captured messages.

The superadmin panel provides:

- Enable / Disable;
- Seed;
- Reset;
- Extend;
- five phase-jump controls;
- demo counts;
- demo credentials;
- live expiry countdown.

## 4. Tenant-safety changes

`demo_inbox` is registered in `TENANT_COLLECTIONS` alongside the existing `nomination_uploads` collection.

A static tenant-scoping audit was run directly against the project's lint implementation:

- unexpected raw tenant-collection accesses: **0**;
- stale allow-list entries: **0**;
- stamped collections missing from `TENANT_COLLECTIONS`: **0**.

## 5. Tests added or updated

### Backend

`backend/tests/test_demo_mode.py` now covers:

- inbox off/expiry behavior;
- demo OTP interception with providers prohibited;
- unchanged SMS usage;
- real-number refusal and text non-storage;
- enable safety gates;
- idempotent seeding and role credentials;
- demo phase progression;
- finance-clear and approval preparation;
- fenced reset preserving real voter/branding data;
- inbox cap;
- settings-cache invalidation;
- nomination-form + demo integration through upload, application submission, and vetting read-back.

The existing nomination-form backend tests remain in place.

### Frontend

Added:

- `frontend/src/nominationForm.test.js`
- `frontend/src/components/NominationFormPanel.test.jsx`
- `frontend/src/components/ApplicantPortal.nomination.test.jsx`
- `frontend/src/components/DemoInbox.test.jsx`
- `frontend/src/components/DemoControlsPanel.test.jsx`

Coverage includes runtime nomination settings, saving with a reason, applicant form DOM/order/required behavior, demo inbox behavior, OTP/link handling, and demo-control operations/countdown behavior.

## 6. Verification performed in this environment

The following checks completed successfully:

- Python AST parse across all 75 backend Python files: **clean**.
- `python -m compileall -q backend`: **clean**.
- TypeScript/JSX parse/transpile check across all 193 frontend JS/JSX/TS/TSX files: **clean**.
- Tenant-scoping static audit: **clean**.

The project's full runtime test/build commands could not execute because the uploaded project does not include installed dependency directories and the environment has no network/DNS access for dependency installation:

- `pytest -q` → blocked by missing `mongomock`.
- `npm test` → blocked because `vitest` is not installed.
- `npm run lint` → blocked because `eslint` is not installed.
- `npm run build` → blocked because `vite` is not installed.

Therefore, this report does **not** claim a full 476+ backend test pass or a successful Vite build. Static compilation/syntax and tenant-lint checks did pass, while runtime integration verification is represented by the added automated tests but those tests could not be executed in this dependency-incomplete environment.

## 7. Files changed/added

### Backend

- `backend/main.py`
- `backend/tenant_db.py`
- `backend/tests/test_demo_mode.py`

### Frontend

- `frontend/src/App.jsx`
- `frontend/src/applyErrors.js`
- `frontend/src/components/ApplicantPortal.jsx`
- `frontend/src/components/DemoControlsPanel.jsx`
- `frontend/src/components/DemoControlsPanel.test.jsx`
- `frontend/src/components/DemoInbox.jsx`
- `frontend/src/components/DemoInbox.test.jsx`
- `frontend/src/components/NominationFormPanel.jsx`
- `frontend/src/components/NominationFormPanel.test.jsx`
- `frontend/src/components/ApplicantPortal.nomination.test.jsx`
- `frontend/src/components/SuperAdminDashboard.jsx`
- `frontend/src/components/VettingDashboard.jsx`
- `frontend/src/nominationForm.js`
- `frontend/src/nominationForm.test.js`

## 9. Post-review fixes

See `POST_REVIEW_FIXES.md`.

## 8. Important implementation notes

The repository's completed nomination-form storage implementation uses the existing private Backblaze B2 abstraction in `backend/nomination_storage.py`, with short-lived presigned download URLs. No unverified Cloudinary-specific authenticated-raw SDK call was introduced.

The demo mode is deliberately fake-number-only and pre-election-only, matching the guide's safety model. This is especially important because demo inbox messages expose OTPs in the browser.

The implementation therefore covers the guide's requested feature surface while preserving tenant scoping, production SMS isolation, auditability, and existing approval/finance business paths.
