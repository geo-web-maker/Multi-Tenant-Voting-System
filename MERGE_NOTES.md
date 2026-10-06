# Merge notes: combined (security audit) + phase6 (vetting audit fixes)

## These were not a frontend zip + a backend zip — they're two diverged branches
Both zips are full stacks (frontend + backend), branched from the same point and then
edited independently:

- **ballotbox-vetting-panel-combined.zip** = that point + `SECURITY_AUDIT_VETTING_PANEL.md`'s
  SEC-01…SEC-11 fixes (auth.py hardening, upload/rate-limit guards, audit redaction, etc).
  Its own audit doc says plainly, under "Hardening (Low)": **"view-as has no `vetting` role yet"**.
- **vetting-panel-phase6-audit-fixes.zip** = that same point + the round-2 frontend fixes
  (`VP-AUDIT-FIXES.md`) *and* the matching backend piece — `/superadmin/view-as` now has a
  `role == "vetting"` branch, and `/admin/vetting-me` exempts a read-only "View as" session
  from the confidentiality gate. This is **not in combined at all**.

Since the screenshot shows the "View as (Vetting Panel)" banner actually rendering with
Ssegawa's name, the live backend has to already be running phase6's `/superadmin/view-as` —
combined's version doesn't know the word "vetting" and would 400 before a tab ever opened.
So whatever's deployed is some splice of the two, and a 483-line, route-by-route diff between
two branches is exactly the kind of merge where one helper function gets left on the wrong
side and a route starts throwing instead of returning a normal error body — which is
consistent with the generic "Could not load your panel details." fallback the frontend only
shows when the response has **no** `.detail` field (network error / unhandled exception),
not a real rejection message.

## One confirmed, live bug (independent of the screenshot)
`backend/main.py`, the panelist login subject line, had **silently reverted** between the
two zips:

```python
# phase6 (bug, re-introduced from before the security audit):
subject = voter.get("student_id") or voter.get("panel_member_id")
# combined (SEC-01 fix):
subject = voter.get("panel_member_id") or voter.get("student_id")
```

A **member** panelist's record carries both ids. With phase6's ordering, their token's
`sub` becomes `student_id`, but every guard and `/admin/vetting-me` look the account up by
`panel_member_id` — so a member panelist who logs in to the Vetting Panel *directly* (not
via "View as") gets rejected on every request. "View as" happens to dodge this because
`/superadmin/view-as` sets `subject=p["panel_member_id"]` explicitly — which is also why
testing through "View as" can look fine (or fail differently) from testing a real panelist
login. **Fixed in this merge** — restored to `panel_member_id` first.

## What this merge does
Took phase6 as the base (it's the only one with the vetting view-as + round-2 frontend work)
and re-applied the combined-only fixes on top, without touching anything phase6 added:

- `auth.py`: restored the `require: [exp, iat, jti]` check and the short-secret warning (SEC-11).
- `main.py`: restored the `panel_member_id`-first subject fix (SEC-01); bounded upload reads on
  both image endpoints (SEC-05); the `DEBUG_MODE` boot warning (SEC-09).
- `frontend/vercel.json`: restored the security headers (CSP/X-Frame-Options/etc.) combined added.
- `frontend/src/App.jsx`: restored the 10-character password minimum (matches what the server
  already requires — phase6's frontend had regressed this to 6).
- Brought back `backend/tests/test_vetting_panel_security_audit.py` and `progress/SEC-AUDIT.md`
  from combined so both audit trails exist side by side.

## SEC-02/03/04/06/07/08/10 — now reconciled
All of these are ported into this merge on top of phase6, same approach as SEC-01/05/09/11:

- **SEC-02** `_redact_panel_audit` takes `role` again and masks the Chair's identity on a
  tie-break row (marker kept only for `overseer`); the `/admin/audit-log` call site passes
  `current_role(request)`.
- **SEC-03** `/admin/audit-log`: when a non-superadmin passes `actor=`, `application_vote_cast`
  is added to the hidden-actions filter, so vote events aren't searchable by actor.
- **SEC-04** `_should_log_guard_401` + the per-IP 30s gate restored around the `admin_guard_401`
  log line in the auth middleware.
- **SEC-06** `_check_apply_rate_limit` restored and called from both `/apply/check-eligibility`
  (120/10min) and `/apply` (60/10min).
- **SEC-07** `/apply` now rejects a non-`https://` `image_url` / `payment_proof_url`; both fields
  plus `student_id`, `full_name`, `position_id` on `ApplicationSubmit`, and `commissioner_id` /
  `vote` / `reason` on `CommissionerVote`, are back to bounded `Field(max_length=...)`.
- **SEC-08** `_external_has_no_end` restored and checked both at panel login (refuses a login
  that can never expire) and at panel creation (`POST /superadmin/vetting-panel` now rejects a
  phase-based expiry whose phase has no end date yet, via `get_phase_schedule`).
- **SEC-10** `_PANEL_LOGIN_EMAIL_FIELDS` + `_panel_email_conflict` restored; both
  `POST /superadmin/vetting-panel` (create) and `.../set-credentials` (update, excluding the
  panelist's own record) now check panel emails against every other role's login email, not
  just other panelists. `set-credentials` also rejects an empty email again.

All of it compiles clean (`python3 -m py_compile main.py auth.py`) and no helper was defined
twice. I could not run `pytest`/`npm test` here (no network, no Mongo in this sandbox) — run
the full suite, especially `test_vetting_panel_security_audit.py` and `test_vetting_audit_fixes.py`
together, before deploying.

## Still open — the audit's own "needs your decision" items
Unrelated to this merge, still outstanding per `SECURITY_AUDIT_VETTING_PANEL.md`'s "Open"
section: rotating the Cloudinary key/secret and the JWT secret (both were committed in plain
text in one of the zips you sent me — do this regardless of the merge), the ballot-secrecy
timing issue, per-email login throttling and data minimisation on `/admin/applications` have since been
applied (see progress/SEC-OPEN-3-4-5.md). Superadmin TOTP ordering/replay is still a decision for you.

## To actually find the screenshot's root cause
Reproduce the "View as → Vetting Panel" click with the browser's Network tab open (or the
backend console) and read the **status code and body** of the failing `GET /admin/vetting-me`
call. That one piece of information — which this static diff can't produce — will tell you
immediately whether it's a 401/403/404 with a real `.detail` the toast is swallowing, or a
500/network failure from a leftover mismatched helper. Given everything above, my strongest
guess is a 500 from exactly that kind of leftover mismatch; restarting the backend on this
merged `main.py` + `auth.py` is the fastest way to confirm or rule that out.
