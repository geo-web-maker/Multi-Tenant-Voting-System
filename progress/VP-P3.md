# VP-P3: Vetting Panel UI, Phase Three
source: VETTING_PANEL_CHANGE_GUIDE section 9, row P3
status: built, not deployed; frontend not compiled (no node_modules in the handoff), backend tests not run (no network to install pytest)

changes:
- backend main.py: GET /superadmin/vetting-panel now returns panel_count and tie_risk (none / chair_resolves / superadmin_only, guide 7.2).
- frontend VettingDashboard.jsx (new): pending list with "x of y voted", own vote, Approve/Deny; Chair-only tie-break with optional deny reason and confirm; "awaiting final decision" neutral text; Resolved tab with final split (panel only), tie-break marker and final reason.
- frontend VettingPanelManager.jsx (new): superadmin tab "Vetting Panel": appoint internal/external with required reason, expiry, reissue credentials, activate/deactivate, tie_risk notice.
- frontend hatSwitch.js (new): switchHat() shared by both dashboards.
- CommissionDashboard: "Switch to Vetting Panel" header button.
- VettingDashboard: "Switch back" button, shown only in a tab that came from the commission hat.
- App.jsx, session.js: vetting view routing, lazy load, logout clears panel_linked.

not done in P3 (later phases):
- Commission Pending tab still shows the old vote buttons; backend now returns 403 for commission votes. Removed in P4.
- Vetting-open dialog tie_risk warning (only the management tab shows it).
- Commission-hat button shows for everyone; non-panelists get a toast from the 403.
- Overseer copy (P4).

HUMAN: run `npm run build` and the frontend tests; run backend pytest (test_vetting_panel_p1/p2 and full suite).
