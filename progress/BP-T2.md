# BP-T2 — Public shell (header, column, boot)
status: done
branch: improvements/BP-T2 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: src/App.template.test.jsx (6), src/templates/blueprint/TitleBlockHeader.test.jsx (24), src/templates/blueprint/BootSplash.test.jsx (5) = 35 new; 401 total
results (default):   frontend 401 passed, 0 failed · lint 0/0 · build ok, entry gz 34,804 B (baseline 34,777 B, +27 B)
results (blueprint): frontend 401 passed, 0 failed · build ok, entry gz 35,159 B, blueprint chunk gz 5,378 B
baseline at branch cut: frontend 367 · entry gz 34,777 B
gates: G1 pass · G2 pass · G3 pass (401 = 401) · G4 `data-track labels OK` (17 static, 3 dynamic) · G5 lint 0/0
files:
- App.jsx (seams only): imports `getTemplate`/`derivePhase`; `bp` + `wrapPublic` before the main return; `<nav className="no-print">` kept verbatim in the `: (...)` branch of `bp ? <bp.TitleBlockHeader/> : <nav/>`; Results/Apply/voter wrapped via `wrapPublic` (returns the node untouched in default); `BootSplash` hands off to `bp.BootSplash`.
- templates/blueprint/: TitleBlockHeader.jsx, BootSplash.jsx, primitives.jsx (Stamp, StatusCell, SheetCell, PublicWrap), labels.js (initials, STATUS_LABELS), index.js exports, blueprint.css (nav/theme button styles, `.bp-logo.bp-img`, `.bp-boot-stamp`, N2, N3).
decisions applied: D5 (sheet cell = voter step n/3; hidden on results/apply and after step 3), D6 (logo image contained in the stamp, else initials), E3 (theme toggle + Back to Admin in the header), E10 (status labels), R12.
deviations from the card/guide:
- `bp-` strings may not appear in default JS (gate G1 greps for them), so the `bp-wrap`, `bp-wide`, `bp-card` class names live in `bp.PublicWrap` / `bp.BootSplash`, not in App.jsx. App only calls `bp.X`.
- `initials` and `STATUS_LABELS` live in `labels.js` (not primitives.jsx) because lint (react-refresh) forbids non-component exports from a .jsx component file. index.js re-exports them.
- Nav items are `<button>`s (not the mockup's `<a>`): existing tests find them by role=button; CSS targets both.
- Results gets `bp-wide` (720 px, class already in T1 CSS) instead of the 520 column; tune in BP-T5.
- Sheet cell: step 1.5 (choose phone) shows 01/03; step 4 (post-ballot state) shows no sheet cell.
- Header is also rendered on dashboard views for now (the old nav was too); BP-T7a swaps in the console header there.
- Boot splash uses the same inline wrapper/exit fade as today (opacity+scale); the card is `.bp-card` with the stamp in place of the ring.
- N2 cites App.jsx:1228 (containerStyle const), N3 App.jsx:740 (maxWidth). Line numbers drift as App.jsx changes.
not covered by jsdom (HUMAN): 360/390/768/1280 widths · light/dark · org with no logo / wide logo / tall logo (D6 letterboxing) · 200% zoom · notched iPhone safe area · header wrap behaviour with a very long org name · sticky header scroll feel.
HUMAN checks pending: all of the above, with `VITE_UI_TEMPLATE=blueprint npm run dev`.
next step: BP-T3 (voter flow: PhaseBanner, OtpInput/OtpCells, login fields). T4/T5/T6 can run in parallel after T2.
