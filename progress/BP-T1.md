# BP-T1 — CSS foundation
status: done
branch: improvements/BP-T1 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: src/templates/blueprint/{tokens,contrast,parity}.test.js (72: tokens 20, contrast 48, parity 4)
results (default):   frontend 367 passed, 0 failed · lint 0/0 · build ok, entry gz 34,777 B (baseline 34,769 B, +8 B)
results (blueprint): frontend 367 passed, 0 failed · build ok, entry gz 34,928 B, blueprint chunk gz 3,778 B (JS 203 B raw + CSS 15.3 KB raw)
baseline at branch cut: frontend 295 · entry gz 34,777 B
gates: G1 pass · G2 pass · G3 pass (367 = 367) · G4 `data-track labels OK` · G5 lint 0/0
files: src/templates/blueprint/{blueprint.css, rename.js, cssTools.js (test-only helpers)} + the three test files
decisions applied: D2 (--bp-line-ui for control borders: inputs, OTP cells, ghost button, chips, ticks), D3 (accent text only on card surfaces; tests pin the known light-mode gaps), D7 (tablet band 769-1023: g4 -> 2 cols, two -> 1 col), E2 (.bp-ban.bp-acc / .bp-mute added)
deviations from the guide's sketches (the guide said they were unexecuted):
- Appendix D read files with `new URL(..., import.meta.url)`; that throws under jsdom ("URL must be of scheme file"). Helpers resolve from process.cwd() (vitest runs from frontend/).
- Appendix D contrast/tint maths assumed 6-digit hex; the mockup uses `#fff`. CSS keeps the mockup's `#fff` (drift guard compares like for like); the helper expands to 6 digits.
- Appendix D `mockVars` dropped the last declaration of each theme block (no trailing `;`), which hid `--grid` in light. Fixed in cssTools.js.
- Status-edge colours (35% alpha) and accent edge (60%) are tokens (--bp-*-edge) so no rgb() literal appears outside the token section; a test pins each to its status colour.
- Only the neutralisers whose target exists today are in the fence: N1 (App.jsx:316-318 brand pin) and N4 (BallotBox.jsx:405 modal radius). N2/N3 (App shell classes) belong to BP-T2 and N5/N6 (.outer-wrap/.dashboard-shell card) to BP-T7a, per their cards; adding them now would half-convert dashboards. Numbers N2/N3/N5/N6 are reserved.
- Bridge also pins --brand-primary/--brand-accent to the accent via the variable block (non-important); N1 enforces it against the inline values.
- .bp-dock is position:fixed with safe-area bottom (Appendix C step 7). The --bottom-bar-height publish happens in BP-T4 (JS).
- Extra tests beyond Appendix D: fallback block equals dark values; bridge only re-points variables that exist in index.css :root; no colour literals after the token section; top-level rules declare only custom properties; fence rules each name file:line and stay <= 25; print block is exactly the grid reset; one 768 breakpoint (+1023 tablet); reduced-motion rule; no tooling selectors or color-mix() shipped.
not covered by jsdom (HUMAN): this card is CSS only, nothing consumes the bp-* classes yet.
HUMAN checks pending: with `VITE_UI_TEMPLATE=blueprint npm run dev`, the UNCHANGED login page, results page and one dashboard must be legible in light and dark (bridge + base only): readable text, visible input borders, visible focus ring, no white-on-white. Dashboards will still look mixed until T7a.
next step: BP-T2 (public shell: header, 520 px column, boot splash; adds N2/N3).
