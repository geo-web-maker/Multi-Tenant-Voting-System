# VP-P1 — Vetting Panel vs Commissioners, Phase One
status: done (pending George's review; not deployed)
source: VETTING_PANEL_CHANGE_GUIDE section 9, row P1
branch: not created (zip handoff; commit on your side)
tests added: backend/tests/test_vetting_panel_p1.py (27)
results: backend 333 passed · 4 failed (pre-existing, see below) · 0 new failures
change summary:
- auth.py: `vetting` added to ADMIN_ROLES (now six).
- main.py login: new Vetting Panel branch in `_verify_admin_credentials`, before the commissioner branch. Reads `panel_members`; externals need no voter row. Refuses inactive or expired accounts.
- main.py `_login_token_for`: subject falls back to `panel_member_id` when there is no `student_id`.
- main.py auth guard: for role `vetting`, checks the `panel_members` record (active, not expired, `sessions_valid_after`) instead of `voters`.
- main.py `/admin/set-password`: panel branch added, self-only (keyed by panel_member_id).
- main.py superadmin routes: GET/POST `/superadmin/vetting-panel`, POST `.../{id}/set-credentials`, POST `.../{id}/active`. Min 3 active enforced on deactivate. Add and deactivate blocked while vetting is enforced and open.
- main.py `POST /admin/switch-hat`: commissioner linked to an active panelist gets a `vetting` token; old token revoked. Reverse switch on the panel token.
- migrate_create_vetting_panel.py: dry run by default, `--apply`, `--org-id`. Creates one inactive linked member per commissioner, idempotent, writes audit entry, warns on orgs under 3.
decisions to confirm:
(1) Migrated panelists start INACTIVE until credentials are issued (guide 5.3 says "made a panelist"; inactive avoids an accidental login path). Flip to active if you want them live on migration.
(2) Panel freeze applies only to an ENFORCED vetting window (an unconfigured timeline never freezes), so orgs without a timeline can still appoint panelists.
(3) Externals must have an access end (date or phase); an access end is also enforced on each request, not only at login.
bugs found and fixed during build:
- set-password panel branch lacked a self-only check (any panelist could change another's password). Fixed.
- session guard skipped panel tokens (looked up voters by student_id), so deactivation/expiry would not cut them off. Fixed.
- freeze guard used `_phase_is_open`, which treats an unenforced window as open, so it blocked all appointments by default. Fixed.
test-harness notes:
- the test ASGI client does not run app lifespan, so the revocation hook (`auth.set_revocation_check`) is never installed in tests. The new test file installs it explicitly. Existing suite has no revocation coverage.
- migration accepts an injected `db` so it runs against the in-memory fixture.
pre-existing failures (unchanged by this work, also fail on the original code):
- tests/test_voter_fields.py: 4 tests (TypeError in import/fill paths)
not done in P1 (by design, later phases):
- vote endpoints gated to panel, get_panel_count, shape_application_for_role, audit redaction (P2)
- VettingDashboard, hat-switch button, panel management tab (P3)
- commissioner slimming, outcomes feed (P4)
- token-subject audit across remaining call sites, first-login confidentiality gate, conflict-of-interest check (P5)
HUMAN: run `python migrate_create_vetting_panel.py` (dry run) against staging before any `--apply`. Confirm the superadmin creates credentials for panelists before vetting opens.
