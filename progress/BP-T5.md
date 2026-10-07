# BP-T5 — Results
status: done
branch: improvements/BP-T5 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: components/Results.template.test.jsx (14: default no-bp, 8 states same text in both templates, print-only identical, bar widths, headings, banner tones, pills)
results (default):   frontend 445 passed, 0 failed · lint 0/0 · build ok, entry gz 34,929 B
results (blueprint): frontend 445 passed, 0 failed · build ok, entry gz 35,534 B, blueprint chunk gz 7,796 B
baseline at branch cut: frontend 431 (BP-T4) · entry gz 34,929 B
gates: G1 pass · G2 pass · G3 pass (445 = 445) · G4 `data-track labels OK` · G5 lint 0/0
files:
- Results.jsx (seams only): `bp = getTemplate()` after all hooks; banner -> `bp.Stat`; position heading -> `bp.PositionHeading` (from T4); rows -> `bp.Meter` (same `cand-row`/`cand-top`/`cand-name`/`cand-votes`/`cand-pct` hooks, children unchanged); status badges via a local `badge()` helper (default branch emits the original span + `badgeStyle`); LEADING/DEADLOCK -> pill in blueprint; the default progress bar is skipped when `bp`. S2 swaps: h2, not-started / unreleased boxes, "No votes yet.", tie banner, DEADLOCK colour. `.print-only` block untouched.
- templates/blueprint/: primitives.jsx (+Pill, +Stat, +Meter), index.js, blueprint.css (bar transition, stat spacing, .bp-mu).
decisions applied: E2-style tones (ELECTED / MANDATE GAINED / LEADING -> ok; TIE / DEADLOCK -> warn; UNDERMANDATED -> neg), winner/top = accent bar, others muted; certified and live -> ok banner pill, provisional -> warn.
proof that default is unchanged: before editing, the default Results page was rendered in 8 states (live, provisional, certified, tie, live tie, not started, embargoed, no votes) and the HTML saved; after editing, the same render matches exactly once S2 `var(--bp-x, #lit)` is read as its literal and the "Last update" clock text is masked (throwaway script, not committed).
deviations from the card:
- `Results` stays `max-width: 700px` inline inside the 720 px `bp-wide` column (no neutraliser added; widths nearly equal). Tune in HUMAN pass if it looks off.
- Voter Participation Roll, search box, turnout breakdown and Final Report UI are Tier B (bridge only), not restyled here.
- Bar track/tint use existing tokens only; no new hex.
not covered by jsdom (HUMAN): print preview of Results identical to default in both themes (R8); bar animation and reduced-motion; long candidate names wrapping next to the vote count; 40+ candidates; light/dark readability of the LEADING / ELECTED pills on the page background; mockup deep link `#p=results`.
HUMAN checks pending: the list above, with `VITE_UI_TEMPLATE=blueprint npm run dev`.
next step: BP-T6 (apply form). Still open from T4: the vote-recorded view in App.jsx needs a seam.
