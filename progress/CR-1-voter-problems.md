# CR-1 · Voter-side problem reports, and template reconciliation of the bot-check UI work

**Date:** 16 October 2026

## What changed
- **Voter-side problem reports (new).** `frontend/src/clientReport.js` sends a short note to `POST /client-report` when the browser hits a problem the server cannot see: bot check script blocked, widget error (with Cloudflare's code), no token after 20 s, JavaScript error, unhandled promise rejection, blank screen (inline script in `index.html`, existing 20 s check). Sent: problem type, short code, page name (same names as analytics), 120-character error text with digit runs of 5+ masked. Never sent: names, student numbers, phone numbers, codes. Browser family and version come from the User-Agent on the server. Not sent for staff sessions or the superadmin live widget test.
- **Backend** (`main.py`): public `POST /client-report` (always answers 202; 20 reports per IP per 10 minutes; ignored without an organisation header), `GET /superadmin/client-reports?minutes=` (counts, top browsers, latest 10), collection `client_reports` (TTL 6 h), email alert through `alert_warning` when a type crosses its threshold in 10 minutes: bot check types 10, JavaScript errors 15, blank screen 1. `write_freeze.py` lets `/client-report` through a freeze.
- **Security tab:** new "Voter-side problems" card (range selector, counts per type, most affected browsers, latest reports, polls every 30 s).
- **Template reconciliation:** the earlier bot-check health card and the unopposed-candidates box used the old inline `box` / `note` / `inp` surfaces, which ignore Blueprint. All Security-panel tiles now use `perf-card card-pad`, `perf-note`, `perf-field` and `perf-tile-label` (manual section 3), so they follow both templates. The widget's Retry button follows the voter-flow pattern of `LoginErrorActions`: Blueprint class in Blueprint, tokenised inline style in the default look.
- **Guard:** `SecurityPanel` added to `KIT_PANELS` and a test that the old surfaces do not return (`uiTemplateRules.test.js`).
- Also fixed: a React lint error (`setState` in an effect) in `TurnstileWidget.jsx`.

## Not changed
`Results.jsx`, `FinalReport.jsx`, `SharedAdminPanels.jsx` (unopposed rule): text and numbers only, no styling; print documents keep their fixed colours by design (guide R8).

## What I ran
- Backend `pytest tests`: 1041 passed (includes 6 new in `tests/test_client_reports.py`).
- Frontend `vitest run`, default and `VITE_UI_TEMPLATE=blueprint`: 854 passed, 3 failed. The same 3 fail on the uploaded zip before this change: `ApplicantPortal.apply` "pressing Enter twice", `tokens.test.js` NEUTRALISERS count (18 vs 20), and `uiTemplateRules` "every perf-* class is defined" (`perf-btn-card` has a Blueprint rule only).
- ESLint on the changed files: clean. Both Vite builds succeed; the default build has no Blueprint assets. Built `index.html` carries the real API URL and organisation slug when the env vars are set.
- Root-level `backend/test_flows.py` has 28 failures before and after (it runs without the `tests/conftest.py` setup); not touched.

## Not run
No browser or phone check in either template (light/dark, 1100 px and 390 px). The new card and the Retry button need a look. Not tested against a live Cloudflare script block.
