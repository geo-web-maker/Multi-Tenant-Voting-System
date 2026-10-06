# Security audit: BallotBox after Vetting Panel phases 5 and 6

Scope: the combined codebase (phase 5 full tree + phase 6 overlay), audited against `VETTING_PANEL_CHANGE_GUIDE`.
Method: manual code review of auth, middleware, panel/vote/tie-break/hat-switch, audit log, voting, uploads, public
endpoints, exports, scripts, config and frontend sinks; AST route inventory (169 routes); pattern sweeps; extracted-function
execution of the changed logic.
**Not done (sandbox has no network and no FastAPI/Mongo):** the backend/frontend test suites, `npm run build`, a dependency CVE
scan, and dynamic testing. The ~170 handlers were not each read line by line (OTP/SMS budget, student-change workflows,
analytics internals and `backup.py` were pattern-scanned or sampled). Treat this as a strong review, not a certification.

## What is solid
Fail-closed auth middleware with an explicit public allowlist; per-request tenant check on tokens; session cut-off on password
reset; temp-password tokens confined to set-password; atomic vote claim inside a transaction; voter token bound to student, org
and a per-login jti; OTP guess limiter with constant-time compare; `secrets` for all randomness; no eval/exec/pickle/shell;
escaped regexes on public inputs; spreadsheet formula-injection guard; zip-bomb guard on imports; B2 object-lock anchoring of the
audit chain. A replay of the guard over every route confirmed a `vetting` token reaches only its own routes (the three
unguarded ones, finance-clear/reject and vote-remove, are rejected by in-body identity checks).

## Fixed in this zip
| ID | Sev | Finding | Fix |
|---|---|---|---|
| SEC-01 | High | `_login_token_for` used `student_id` as the token subject for a *member* panelist (their panel record carries one). The guard looks up `panel_member_id`, so every member panelist logging in directly got 401 on every request. Reproduced by running the real function. Existing tests missed it (fixtures use `student_id=None`). | Subject is now `panel_member_id` first |
| SEC-02 | Med | `application_approved/denied` audit rows from a tie-break carried `tie_break: true` and the Chair's PM id as actor, visible to every admin role (guide 7.1/7.2 forbids). | Actor masked; marker removed (overseer keeps the marker only) |
| SEC-03 | Med | `/admin/audit-log?actor=` filtered on the stored actor, so a commissioner could learn which panelist voted on which application despite redaction. | Vote events not searchable by actor for non-superadmin |
| SEC-04 | Med | Any unauthenticated request to a protected path wrote an audit row (log flooding, and the log is read by every role). | One row per IP per 30 s |
| SEC-05 | Med | Both upload routes read the whole body before the 5 MB check (memory DoS). | Bounded read |
| SEC-06 | Med | `/apply` and `/apply/check-eligibility` had no rate limit; the 404/400 split lets the roll and names be enumerated. | Per-IP limits (120 and 60 per 10 min, campus-NAT friendly) |
| SEC-07 | Med | Public `/apply` accepted unbounded strings and any URL scheme for `image_url` / `payment_proof_url` (opened later by the Financial Controller and panel: phishing / IP leak). Vote `reason` unbounded into the audit log. | Length bounds; https-only (matches the existing superadmin edit rule) |
| SEC-08 | Med | An external panelist set to expire "with phase" whose phase has no end date never expires. | Rejected at creation; new logins refused while no end resolves |
| SEC-09 | Low | DEBUG_MODE (OTPs and temp passwords logged) had no startup signal. | Critical-level log line |
| SEC-10 | Med | Panel login branch precedes the commissioner branch; a panel email equal to any role's login email captures that person's login. `set-credentials` also skipped the duplicate-email check. | Cross-role + duplicate email check on add and set-credentials |
| SEC-11 | Low | Admin tokens without exp/iat/jti would be accepted (non-expiring / unrevocable). Short JWT secrets unflagged. | `require` claims; warning under 32 chars |
| misc | Low | Seed scripts write known passwords to whatever DB is configured; frontend allowed 6-char passwords (server needs 10); frontend host sent no security headers; env files contained secrets. | Local-only guard (`ALLOW_SEED_NON_LOCAL`); min 10; `vercel.json` headers; env values blanked |

New tests: `backend/tests/test_vetting_panel_security_audit.py` (not executed here; run before deploying).

## Open: needs your action or decision
1. **Rotate the Cloudinary API key and secret now (Critical).** `backend/.env` held real values (cloud `dyn2729ou`). Also check whether
   they ever reached git history; the `.gitignore` is correct but the file was in the archive. Blanked in this zip. Rotate the JWT
   secret too if it was ever reused outside local testing.
2. **Cutover is not "invisible" as the guide (5.3) promises (High, operational).** `migrate_create_vetting_panel.py` creates
   every panel record with `active: False`. With 0 active panelists nothing resolves (`_resolve_application` returns early) and
   hat switch returns 403 for every commissioner. Activation is blocked while vetting is open (freeze rule). Either migrate linked
   commissioners as active (they have no password, so this is safe) or run it and activate at least 3 before vetting opens.
   The existing migration test asserts inactive, so I left it for your call.
3. **[DONE, see progress/SEC-OPEN-3-4-5.md] Ballot secrecy against an insider (Med).** `vote_events` stores a precise `cast_at` and a time-ordered `_id`; `audit_log`
   stores `vote_cast` with the voter id a few ms apart (visible to every admin role; also both in B2 backups). Someone with DB or
   backup access can pair voters to ballots. Fix: round `cast_at` to a coarse bucket and use a random id for events (the hash chain
   needs adjusting), and drop timestamps from `vote_cast` entries.
4. **[PARTLY DONE: per-email counter added; TOTP items still open] Login throttling (Med).** Keyed by (email, IP): rotating IPs gives unlimited guesses per account. Add a per-email counter.
   Superadmin login returns 428 only after the password is correct, so password guessing is not slowed by TOTP; require
   password and code in one request. TOTP codes can be replayed inside the window.
5. **[DONE] Data minimisation (Med).** `/admin/applications` returns payment proof URL, method and finance notes to every role including
   external panelists (the dashboard never uses them). Strip for `vetting`, and arguably `overseer` / `it_admin`.
6. **Hardening (Low):** panel confinement is a prefix denylist (a new authenticated route outside `/admin/` would be open to the
   panel; convert to an allowlist); `vote-remove` and the Financial Controller student-change decision rely on in-body checks, not
   `require_role` (guide says leave vote-remove untouched; the endpoint is still live by API); hat switch refreshes the session
   lifetime; view-as has no `vetting` role yet (guide 8.1); login does up to five unindexed case-insensitive regex scans (store
   lowercased emails); `/superadmin/audit-log` takes an unescaped regex; no global request-body limit; admin JWT lives in
   sessionStorage (add a real CSP to the frontend once you can test it); `Dockerfile` copies `requirements.txt` from the wrong
   path and runs as root; `requirements.txt` is unpinned (pin and run `pip-audit` / `npm audit`); `/internal/backup/*` is public
   behind a shared token (add an IP allowlist or rate limit).
7. **Guide section 10 tests for P5** (confidentiality gate, expiry cut-off, conflict of interest) are still absent; only the
   items above gained tests.

## Run before deploying
`pytest` (all, especially the new file and `test_vetting_panel_p1/p2`), `npm ci && npm run build && npm test`, then an
end-to-end pass: member panelist direct login, external login to notice to vote to expiry, tie-break, audit-log as commissioner.
