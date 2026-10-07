# BP-T9 — Tier B sweep + hex ratchet
status: done (code); HUMAN "ok" columns pending
branch: improvements/BP-T9 (no git repo in the supplied zip; delivered as zip)
tests added: src/hexRatchet.test.js (3: ratchet, swept-literal guard, no static import of templates/blueprint); 568 total
results (default):   568 passed, 0 failed · lint 0/0 · entry gz 34,990 B (BP-T8c: 34,944, +46)
results (blueprint): 568 passed, 0 failed · entry gz 35,635 B · blueprint chunk gz 11,144 B
gates: G1 pass · G2 pass · G3 pass (568 = 568) · G4 `data-track labels OK` · G5 lint 0/0
HEX RATCHET: 394 hex literals in non-test src/**/*.jsx (excl. templates/blueprint/). Start of card: 391. (+3: three `'white'` inks became `var(--bp-ai, #fff)`.) Ceiling = 394 in hexRatchet.test.js; lower it when literals are removed.

## Done
1. Solid-fill audit (F-note). Contrast of every solid + ink pair, light/dark (ink = `--bp-ai`): ok 6.33/8.81 · wn 6.50/9.57 · no 6.55/8.07 · ac 5.18/6.89 · mu 5.69/7.59 (all >= 4.5). Offenders fixed with `var(--bp-ai, <old ink>)`:
   - `index.css` `.tabbar-pill.is-active` (dark ink #04231a on --success failed in light blueprint)
   - `BallotBox` gold "preview" banner (#1e293b on --warning) and Results "ELECTED" badge ink
   - white inks on token fills: ApplicantPortal btn, AnalyticsPanel btn/segOn, LinkBuilder, ExportModeControl, VoterRegisterExport, SecurityPanel, ContactChangesQueue, ResetOtpLimitsPanel, VoterImportReview, VoterFieldsPanel, ContactChangePanel, PaymentInfoPanel, UploadBypassPanel, AdminHeader logout, OtpInput, BallotBox buttons, UIFeedback toast/confirm, Results badges, CandidateStatusPortal primaryBtn.
2. S2 on the F9 hotspots (fallback = old literal, so default pixels are identical): #2ecc71/#10b981/#16a34a -> `--bp-ok`; #e74c3c/#ef4444/#dc2626 -> `--bp-no`; #e67e22/#f39c12/#b45309 -> `--bp-wn`; #3498db/#3b82f6/#2563eb -> `--bp-ac`; #64748b/#94a3b8/#334155 -> `--bp-mu`; ink #fff/white -> `--bp-ai`.
3. Ratchet + static-import fence in `src/hexRatchet.test.js`.
No new `!important`, no hex in blueprint files, no copy changes, no DOM change in default (S2 only changes inline style strings).

## Deliberately left bare (with reason)
- `AdminDashboard.jsx` (21): legacy, not rendered (F17).
- `FinalReport.jsx` (7) and the `.print-only` blocks: paper documents, forced light, must print identical (R1/T10).
- `CandidateStatusPortal.jsx` print sheet + print CSS (white paper, fixed ink).
- `icons.jsx` `dotGreen`: SVG attributes; moving to style would change default DOM.
- `PhaseBanner.jsx` `THEME`: replaced by PhaseBannerView in blueprint.
- `SuperAdminDashboard` preview nav bar (org brand colour preview) and `App.jsx` guide button (#34495e fixed bg + white ink).
- Remaining `#fff` used as a *background* (white paper/logo plates) is intentional.

## Tier B register
Screens/"light ok"/"dark ok"/"mobile ok" are HUMAN columns (jsdom cannot judge them); "static" = token/contrast verified here.
| screen | static | light | dark | mobile | hex left | notes |
|---|---|---|---|---|---|---|
| Toasts / UIFeedback | ok | HUMAN | HUMAN | HUMAN | 3 | success/error/info bg via ok/no/mu, ink ai |
| ViewAsBanner, help panel/FAB | ok (S1) | HUMAN | HUMAN | HUMAN | 0 | inherits bridge |
| Final Report UI | n/a | HUMAN | HUMAN | HUMAN | 7+ | paper doc, intentionally untouched |
| Security / SMS panel | ok | HUMAN | HUMAN | HUMAN | fallbacks only | buttons ac/ok, ink ai |
| Fee schedule / Payment info | ok | HUMAN | HUMAN | HUMAN | fallbacks only | |
| Timeline / Analytics | ok | HUMAN | HUMAN | HUMAN | fallbacks only | dangerBtn ink ai |
| Import review / ColumnMapper | ok | HUMAN | HUMAN | HUMAN | fallbacks only | |
| Heatmap overlay / icons | n/a | HUMAN | HUMAN | HUMAN | 1 (icons) | SVG attr, left |
| Vetting Panel Manager | ok (T8c) | HUMAN | HUMAN | HUMAN | fallbacks only | |
| Candidate Status portal | ok (screen) | HUMAN | HUMAN | HUMAN | print sheet only | errors/labels swept |
| Verify Certificate | ok | HUMAN | HUMAN | HUMAN | fallbacks only | |
| Contact changes / Reset OTP / Upload bypass | ok | HUMAN | HUMAN | HUMAN | fallbacks only | |
| Results (screen) | ok | HUMAN | HUMAN | HUMAN | fallbacks only | print-only block untouched |
| Ballot (preview banner, buttons) | ok | HUMAN | HUMAN | HUMAN | fallbacks only | |
next step: BP-T10 (hardening and handover).
