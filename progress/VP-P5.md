# VP-P5: non-member hardening
source: VETTING_PANEL_CHANGE_GUIDE section 9, row P5
status: built, not deployed; frontend not compiled and backend tests not run (no network in the sandbox)

changes:
- Token-subject audit (6.6): panel tokens are confined by area in the auth guard. Anything under /admin/, /commission/, /overseer/, /superadmin/, /it-admin/ or /financial-controller/ is refused for role vetting, except the panel's own routes (/admin/applications, /admin/vetting-*, /admin/approval-policy, /admin/switch-hat, /admin/set-password, /admin/logout). This covers commissioners' roster, student changes, audit log, SMS usage, roster ledger and live results. Vote and tie-break handlers already require the panel token and resolve identity from the panel record.
- Access expiry (6.4 rule 6): one helper computes the earlier of the fixed date and the live end of the chosen phase. Used on login, on every request, when acting as a panelist, and on the hat switch. Token expiry is capped at the access end.
- Confidentiality gate (6.4 rule 5): externals must accept CONFIDENTIALITY_VERSION before any route other than GET /admin/vetting-me, POST /admin/vetting-confidentiality/accept and logout. The panel screen shows the notice and the access end.
- Audit (6.4 rule 4): log_action adds is_member for any panel-member actor.
- Conflict of interest (6.5): a panelist cannot vote on their own application; an applicant (not denied or removed) cannot be appointed or activated on the panel; a panelist cannot apply while active.

assumptions to confirm:
- "Applicant" means any application not denied or removed, so an approved candidate also cannot sit on the panel.
- The conflict checks match on student ID. Externals have no voter row, so an external who applies is not caught.
- A phase-based expiry whose phase has no end date set does not end access until that date exists.

not done:
- Recusal (decision 8: not in this change).
- Automated tests for these rules (guide section 10).

HUMAN: npm run build, frontend tests, backend pytest; then test an external end to end: login, notice, accept, vote, expiry.
