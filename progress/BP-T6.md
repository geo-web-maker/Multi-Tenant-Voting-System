# BP-T6 — Apply form
status: done
branch: improvements/BP-T6 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: components/ApplicantPortal.template.test.jsx (11: default no-bp/no-ids, same text + data-field + data-track in both templates, 6 cards + bp-in + labels, empty-submit same alert/markers/focus, option rows tick + one bp-on, StepBar 3 and 4 segments + gone after, default has no StepBar, success view same text, submit button attrs)
results (default):   frontend 456 passed, 0 failed · lint 0/0 · build ok, entry gz 34,925 B
results (blueprint): frontend 456 passed, 0 failed · build ok, entry gz 35,535 B, blueprint chunk gz 8,401 B
baseline at branch cut: frontend 445 (BP-T5) · entry gz 34,929 B
gates: G1 pass · G2 pass · G3 pass (456 = 456) · G4 `data-track labels OK` · G5 lint 0/0
files:
- components/ApplicantPortal.jsx (seams only): `bp = getTemplate()` after the last hook; `k = bp?.cls`; `sx(default, bpStyle)` keeps today's inline style in default and drops it in blueprint; ids/htmlFor/aria-labelledby only when `bp`. Cards -> `k.card`; fields -> `k.in` (+ `k.ta` for the manifesto); notices -> `k.accBan/ban/warnBan/alt`; option rows -> `k.opt` + `bp.Tick`; upload tiles keep `<label data-track data-field tabIndex>` and gain `k.upload`; remove buttons -> `k.del`; submit/cancel -> `k.btn/k.sm`; `bp.StepBar` above the submit button while `uploading`.
- templates/blueprint/: labels.js (+13 class hooks), primitives.jsx (+Tick), index.js (export Tick), blueprint.css (apply block, no raw px in spacing, no hex, no !important).
decisions applied: E9 info -> accent tint banner; D3 (links/text inside tints use --bp-tx, never accent); D2 (field/upload borders use line-ui, invalid = --bp-no); selected option = tick + accent outline (not colour alone).
deviations from the card:
- StepBar has 3 segments with no photo and 4 with one (same count as `stepLabel`), not always 4. Filled = `step`.
- Layout-only inline styles (flex rows, 12 px gaps, preview image sizes) stay inline in both templates; only colour/shape/opacity styles are dropped in blueprint.
- ClosedNotice (shared, hard-coded yellow hex) is not touched here; it is Tier B / T9 (S2 swap).
- MobileMoneyNumber (shared) still receives its inline `margin` style; Tier B.
- Helper text loses its `opacity` in blueprint (opacity .4–.7 on muted text fails AA); it uses --bp-mu instead.
findings (not fixed, R3: visual layer only):
- Position and payment option rows are `div onClick` with no role/tabIndex; keyboard users cannot choose them (default too).
- Both file inputs are `display:none` inside a `<label tabIndex=-1>`; keyboard users cannot open the picker (default too).
- Both belong in the T10 keyboard walk-through / a separate accessibility card.
proof that default is unchanged: default tests assert no `bp-` class and no `apply-*` ids; `sx(s)` returns the very same style object; full default suite 456/456; default build has no `bp-` string (G1).
not covered by jsdom (HUMAN): 360x640 with keyboard open; photo + payment-proof upload on a phone; slow-network note look; invalid-state outlines in light and dark; 200 % zoom; mockup deep link `#p=apply`; Help button vs Submit clearance (96 px bottom room).
HUMAN checks pending: the list above, with `VITE_UI_TEMPLATE=blueprint npm run dev`.
next step: BP-T7a (console shell). Still open from T4: the vote-recorded view in App.jsx needs a seam.
