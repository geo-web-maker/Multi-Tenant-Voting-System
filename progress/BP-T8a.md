# BP-T8a — Super Admin console content
status: partial (see "not done")
branch: improvements/BP-T8a (no git repo in the supplied zip; delivered as BP-T8a.patch + zip)
tests added: components/SuperAdmin.template.test.jsx (24: statusTone 15, StatusPill 5, VoterStats 2, VoterList 2) + 4 contrast rows (ai on ok/wn, both themes); 539 total
results (default):   frontend 539 passed, 0 failed · lint 0/0 · build ok, entry gz 34,941 B (+0)
results (blueprint): frontend 539 passed, 0 failed · build ok, entry gz 35,584 B, blueprint chunk gz 11,001 B
baseline at branch cut: frontend 511 (BP-T7b) · entry gz 34,941 B
gates: G1 pass · G2 pass · G3 pass (539 = 539) · G4 `data-track labels OK` · G5 lint 0/0
done:
- Shared status map: `statusTone()` (labels.js) + `StatusPill` (primitives.jsx). One map for every console; T8b/T8c reuse it.
- VoterStats: seam -> `VoterStatsView` (7 stat cards, per-section `bp-meter` bars; same labels/values; no-phone count flagged).
- VoterList: `table.bp-rs` + `data-l` on every td (mobile card-rows), status as pill. Both added only when the template is on (default DOM unchanged; test asserts no `bp-`/`data-l`). Neutralisers N8 (inline minWidth 760) and N9 (inline cell borders on phones).
- SuperAdminDashboard: `StatusBadge` wrapper (default = same <span>) at both badge sites (applications, student changes); S2 `var(--bp-x, <old hex>)` on 21 literals (election buttons, filters, EDITED tag, Danger Zone, remove-reason, hints, OPEN/CERTIFIED chips, btn/redBtn/redLink ink); SuperAdminStudentEdit btn/greenBtn; SharedAdminPanels primaryBtn ink. Solid fills use `--bp-ok|wn|no` with ink `--bp-ai` (verified >= 4.5 both themes).
- UsageCharts / HeatmapOverlay: no change needed. Their colours are `var(--brand-primary|accent|success|danger)`, which the bridge and N1 already map.
not done (left for T9 / a follow-up, none are blockers):
- Super Admin form fields and the ~370 inline-styled controls are not converted to `bp-in`/`bp-card`; they inherit through the bridge and N6 only (Tier B behaviour). Needs a screen-by-screen look to decide what is worth converting.
- SharedAdminPanels (1,614 lines) beyond the one button ink: the student-changes list, Timeline, Final Report UI.
- statusBadge copies in Commission/Overseer/IT/Finance are T8b/T8c.
- Remaining hex in the T8a files are the new fallbacks (same pixels in default), `branding` defaults (data), the print-only `chainFooter`, and the nav-bar preview's `#fff` (a literal preview of the public nav).
HUMAN checks pending: Super Admin at 1280/390, light+dark: Voters tab (stats + list, card-rows on phone), Applications (pills, filter buttons), Election controls (button ink on orange/green/amber fills in dark), Student changes, Site usage chart colours. Mockup deep links `#p=sa`, `#p=voters`, `#p=chg`, `#p=usage`.
next step: T8b / T8c (parallel); then T9 sweep.
