# BP-T7b — Flat dashboards frame
status: done
branch: improvements/BP-T7b (no git repo in the supplied zip; changes are in the working tree, delivered as BP-T7b.patch)
commits: n/a
tests added: components/ConsoleFrame.test.jsx (14: 4 unit [default passthrough, null nav, blueprint siblings, null nav in blueprint], 4 dashboards x [default byte-identical snapshot, blueprint nav + content siblings in .dash-body, toolbar outside the frame, one aria-current], 2 static CSS) + 4 committed pre-edit snapshots in components/__snapshots__/flat-*.default.html; 511 total
results (default):   frontend 511 passed, 0 failed · lint 0/0 · build ok, entry gz 34,941 B
results (blueprint): frontend 511 passed, 0 failed · build ok, entry gz 35,578 B, blueprint chunk gz 10,242 B
baseline at branch cut: frontend 497 (BP-T7a) · entry gz 34,921 B
gates: G1 pass (entry +20 B, budget +1,536) · G2 pass · G3 pass (511 = 511) · G4 `data-track labels OK` · G5 lint 0/0
files:
- NEW components/ConsoleFrame.jsx (default = `<>{nav}{children}</>`; no hooks, R12), NEW templates/blueprint/ConsoleFrame.jsx (`div.dash-body.bp-frame > nav + div.dash-main.bp-frame-main`), templates/blueprint/index.js (export), templates/blueprint/blueprint.css (desktop rail for the flat pill row, spacer hide).
- Call sites (insert-only diffs, import + open/close tag): ITAdminDashboard, FinancialControllerDashboard, OverseerDashboard, VettingDashboard. AdminDashboard.jsx untouched (F17).
decisions applied: R1 (default DOM identical, proven by the snapshots captured BEFORE the call-site edits), R12, R11 (768 px, the existing .dash-body stacking rules are reused).
deviations from the card/guide:
- Overseer: its TabBar sits inside `{data && (<>…</>)}` while the contact-changes view and the shared panels sit outside it, so one frame cannot wrap "TabBar + content" as written. The fragment is split in two (summary cards, then the frame); element order, conditions and therefore the default DOM are unchanged (snapshot proves it). The nav is `data ? <TabBar/> : null`.
- The empty `<div style={{marginBottom:'20px'}}/>` spacer stays as the first child inside the frame (moving it would change default DOM). Blueprint hides it with `.bp-frame-main > div:first-child:empty`.
- Vetting: the frame is inside `Shell` (so `.outer-wrap > .dashboard-shell` is unchanged); the loading, error and confidentiality-gate screens never reach the frame.
- Per the card the frame sits inside `.dashboard-shell`, so on desktop the rail is a card inside the content card (header toolbar above it). Easy to flatten later if you dislike nested cards.
findings (not fixed):
- `AnalyticsPanel.range.test` ("switches to Last 24 hours…") failed once in a loaded default full run and passed on rerun and in isolation (x2). Timing-sensitive waitFor under load; unrelated to this card.
- Pre-existing: the flat-dashboard test fixtures need stable `useToast`/`useConfirm` identities (Vetting puts them in useCallback deps); a fresh function per render loops.
not covered by jsdom (HUMAN): IT Admin, Finance, Overseer and Vetting at 1280/768/390 in light and dark: rail height vs short content, sticky offset under the header, bottom pill row vs Help FAB and safe area, the nested-card look, Overseer with no data yet (frame with no nav), Vetting with the Switch-back button.
HUMAN checks pending: the list above, with `VITE_UI_TEMPLATE=blueprint npm run dev`.
next step: BP-T8a / T8b / T8c (parallel). Still open from T4: the vote-recorded view in App.jsx needs a seam.
