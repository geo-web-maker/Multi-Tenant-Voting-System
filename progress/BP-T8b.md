# BP-T8b — Commission + Overseer console content
status: done (Tier A scope; HUMAN visual checks pending)
branch: improvements/BP-T8b (no git repo in the supplied zip; delivered as BP-T8b.patch + zip)
tests added: components/ConsoleT8b.template.test.jsx (18: Commission outcomes 2, Commission live results 2, Overseer 5, AlertPanel 6, TurnoutBreakdown 3); 557 total
results (default):   frontend 557 passed, 0 failed · lint 0/0 · build ok, entry gz 34,942 B (+1)
results (blueprint): frontend 557 passed, 0 failed · build ok, entry gz 35,577 B, blueprint chunk gz 11,060 B
baseline at branch cut: frontend 539 (BP-T8a) · entry gz 34,941 B
gates: G1 pass · G2 pass · G3 pass (557 = 557) · G4 `data-track labels OK` · G5 lint 0/0
done:
- CommissionDashboard / OverseerDashboard: local `StatusBadge` wrapper (default = the same <span>, blueprint = shared `StatusPill`) at every badge site (outcomes, student changes, applications). Overseer also gets `ChangeTypeBadge` (add = ok pill, remove = muted pill).
- Live-results rows (both dashboards): `Row = bp ? bp.Meter : 'div'`, same pattern as Results.jsx. Default keeps the original div and inline bar (the bar is rendered only when `!bp`); blueprint shows a meter (leader = accent, width = `pct_of_position`).
- Overseer summary row: blueprint renders new `SummaryCards` (templates/blueprint/SummaryCards.jsx, `bp-grid bp-g4 bp-k2` of `bp-card bp-stat`); same four labels and values, panel card still only when `panel_count != null`. Default branch is the original markup.
- AlertPanel: blueprint = `bp-card`, state pill (ok/warn/neg), list items as `bp-alt` (critical) or `bp-ban bp-warn` (warning). Text unchanged. The default render is unchanged.
- TurnoutBreakdown: group rows become meters (width clamped to 100), "public after close" becomes a muted pill, both panels become `bp-card`; public footnote `#64748b` -> `var(--bp-mu, #64748b)`.
- S2 on remaining literals: `#2ecc71` (turnout and lead text, 4 sites) -> `var(--bp-ok, #2ecc71)`; `#e74c3c`/`#e74c3c40` (Overseer session warning); `#95a5a620`/`#95a5a6`/`#7f8c8d` (removed/cancelled/remove-tag) -> `--bp-mu-tint` / `--bp-mu`. Fallbacks equal the old literals, so default pixels are identical.
- CSS: one rule, `.bp-big.bp-sm` (24/32) for text-valued stat cards. Nothing added to the neutraliser fence.
decisions applied: R1 (default DOM identical: flat-overseer.default.html snapshot still passes), R4 (copy frozen), R12 (wrappers, no hook early returns), R6 (no new hex in blueprint files).
deviations from the card:
- New file templates/blueprint/SummaryCards.jsx and an index.js export (inside the template folder, not in the card's FILES list; same approach as T8a's VoterStatsView).
- No `data-l` / `bp-table` work: neither dashboard renders a <table> (they are card lists), so there was nothing to convert.
- Commission has no summary cards; its "Voter turnout" strip is Tier B (tokens + S2 only).
not done (left for T9):
- Commission/Overseer panel cards (`appCard`, `outcomeCard`, `tallyRow`) are not converted to `bp-card`; they inherit through the bridge and N6.
- ContactChangesQueue / ResetOtpLimitsPanel / SharedTabPanels (other cards own them).
- Remaining hex in the T8b files: the default-branch bar fill `#2ecc71` (kept so the default stays identical) and the `branding`-free style consts.
HUMAN checks pending: Commission (Outcomes, Live Results, Student Changes) and Overseer (summary row, Applications, Student Changes, Candidate Results) at 1280/390, light + dark; Alerts and "Turnout by group" inside Super Admin Site usage; summary cards at 768-1023 px (D7 band: 2 columns). Mockup deep links `#p=com`, `#p=ov`.
next step: BP-T8c, then T9.
