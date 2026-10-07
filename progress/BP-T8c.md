# BP-T8c — IT Admin + Finance + Vetting console content
status: done (Tier A scope; HUMAN visual checks pending)
branch: improvements/BP-T8c (no git repo in the supplied zip; delivered as BP-T8c.patch + zip)
tests added: components/ConsoleT8c.template.test.jsx (8: IT Admin requests 2, Finance 2, Vetting panel manager 2, S2 literal guard 1, IT Edit Student CSS guard 1); 565 total
results (default):   frontend 565 passed, 0 failed · lint 0/0 · build ok, entry gz 34,944 B (+2)
results (blueprint): frontend 565 passed, 0 failed · build ok, entry gz 35,585 B, blueprint chunk gz 11,144 B
baseline at branch cut: frontend 557 (BP-T8b) · entry gz 34,942 B
gates: G1 pass · G2 pass · G3 pass (565 = 565) · G4 `data-track labels OK` · G5 lint 0/0
done:
- ITAdminDashboard / FinancialControllerDashboard: local `StatusBadge` wrapper (default = the same <span> as before, blueprint = shared `StatusPill`, tone from the one `statusTone` map) at every badge site: IT "My Requests" (incl. the ` · SA` suffix), Finance voter-register requests and candidate payments. Finance's derived state (denied/approved/pending) is passed as the status.
- VettingPanelManager: new `InactiveBadge` (default = the original span, blueprint = `StatusPill tone="neg"`). Member / External / Chairperson / Chief are roles, not statuses, so they stay as tags.
- S2 on every hex literal in the five files: `#2ecc71` -> `var(--bp-ok, #2ecc71)`, `#e74c3c`(+`40`) -> `var(--bp-no, ...)`, `#2ecc7110` -> `var(--bp-ok-tint, ...)`, `#95a5a6`(+`20`) -> `--bp-mu` / `--bp-mu-tint`, button ink `#fff` -> `var(--bp-ai, #fff)` (IT, Finance, Vetting dashboard and panel manager). Fallbacks equal the old literals, so default pixels are identical. Solid fills use ok/no with ink `--bp-ai` (same pairing T8a verified >= 4.5 in both themes).
- ITAdminDashboard.css (used by Edit Student): the same S2 swaps on `.itadmin-btn`, `.green`, `.red`.
- blueprint.css: one block `BP-T8c` (screen only, tokens only, no `!important`, outside the neutraliser fence): `.itadmin-card` = mockup card, `.itadmin-input` / `.itadmin-pick` = `bp-in` look with the D2 control border and a focus ring, `.itadmin-btn` pill with 48 px target, ghost border, kv/change dividers. It works by specificity (`html[data-template="blueprint"] .itadmin-x`) because that CSS is class-based.
- ConsoleFrame.test.jsx: its `norm()` now maps each `var(--bp-x, #hex)` back to the `rgb(...)` jsdom printed before the swap. The committed `__snapshots__/flat-*.default.html` files are NOT edited, so the "default DOM is byte-identical to the pre-seam snapshot" proof stays strict. Needed because the IT Admin and Finance snapshots contain buttons whose colours were swapped.
decisions applied: R1 (default DOM identical), R4 (copy frozen; the mockup's "Every change is audited." banner on Edit Student was NOT added), R6 (no hex in blueprint files), R7 (no new `!important`), R12 (wrappers, no hook early returns).
deviations from the card:
- No `bp-table` / `data-l` work: none of the five files renders a <table> (card lists; the IT Voters tab uses `VoterList`, done in T8a).
- No `bp-meter` work: VettingDashboard shows vote progress as plain text/notes and no tally rows, so there was nothing to convert. The mockup's "Panel votes" bars have no counterpart in today's UI.
- Card-level conversions (`appCard`, `payBox`, `promptBox`, form `inp`) to `bp-card` / `bp-in` are not done; they inherit through the bridge and N6 (Tier B behaviour), as in T8a/T8b. The Edit Student form is the exception (CSS bridge above).
- `shared_*` tabs, ContactChangesQueue and ResetOtpLimitsPanel belong to other cards.
not done (left for T9):
- Remaining hex in the T8c files: only the new `var(--bp-x, <literal>)` fallbacks (same pixels in default). Nothing bare.
- IT Admin `force_denied` badge: the old map drew them as warn, the shared map says neg. Follows the shared map; flag if you want warn.
HUMAN checks pending: IT Admin (My Requests, Edit Student two-card layout and live summary, Add/Remove forms), Finance (Voter payments, Candidate payments, status filter pills), Vetting (Applications buttons ink on green/red fills, Panel tab Inactive pill) at 1280/390, light + dark. Mockup deep links `#p=it`, `#p=fin`, `#p=vet`.
next step: BP-T9 (Tier B sweep + hex ratchet).
