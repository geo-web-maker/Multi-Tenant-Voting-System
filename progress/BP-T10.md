# BP-T10 — Hardening and handover
status: done (code, docs, tests); HUMAN checks pending (listed below)
branch: improvements/BP-T10 (no git repo in the supplied zip; delivered as zip)
tests added: src/templates/blueprint/hardening.test.js (6: focus-ring selector coverage, ring never removed, selected-candidate ring, reduced-motion dot + bar, global net present); 574 total
results (default):   574 passed, 0 failed · lint 0/0 · build ok, entry gz 34,996 B
results (blueprint): 574 passed, 0 failed · build ok, entry gz 35,628 B · blueprint chunk gz 11,191 B
baseline at branch cut: frontend 568 (BP-T9) · entry gz 34,990 B
gates: G1 pass · G2 pass · G3 pass (574 = 574) · G4 `data-track labels OK` (run from repo root) · G5 lint 0/0
deviations: none

## Done
- blueprint.css: the keyboard focus ring now also covers `summary`, `[role="button"]` and `[tabindex]` (not -1); a selected `.bp-cand` (which already has a 2px accent outline) gets a larger ring offset so focus stays visible on it.
- blueprint.css: `.bp-bar i` width transition stops under `prefers-reduced-motion` (next to the existing `.bp-dot` rule). `index.css` already has a global reduced-motion net for everything else; a test pins it.
- frontend/README.md: "UI templates" section. DEVIATIONS.md: BP final table appended.
- No default-path change: no JS touched; default DOM and pixels identical (G1).

## Findings (not changed)
- `check_data_track.py` must be run from the repo root; from `frontend/` it scans the wrong path and reports all labels missing.
- Elements with `tabIndex={-1}` (apply radiogroups, upload tiles) are focus targets for error scrolling only, intentionally not keyboard stops; the upload tile shows `:focus-within` ring.

## HUMAN checks pending (no AI can do these; guide §12)
- Keyboard-only walk: login → OTP → ballot → review → done → results, and one console per role; focus ring visible on every stop, in light and dark.
- Screen reader: login, OTP (one field, not six), ballot.
- 200 % zoom on Tier A screens; 360, 390, 768, 1280 widths; notched iPhone safe areas.
- Print preview of Results, Final Report and certificate: compare PDFs default vs blueprint.
- OS "reduce motion" on: status dot static, meter bars do not animate.
- Tier B register "ok" columns (progress/BP-T9.md) and the 18 pages × 4 variants against the mockup deep links.
- D1–D9 owner sign-off (§3) and a strongly branded tenant shown in blueprint (D1).
- Low-end Android on Slow 3G; real-phone OTP autofill/paste.

## §13 acceptance
- [x] Default build G1; default suite = baseline + new tests; lint 0/0.
- [x] Blueprint suite passes (G3); G2, G4 pass.
- [x] Contrast and D2/D3 enforced by tests; token drift test green.
- [ ] Every Tier A screen checked against its mockup deep link (HUMAN).
- [ ] Tier B register "ok" columns (HUMAN); hex ratchet recorded (394).
- [ ] §7 deviations reviewed; D1–D9 answered (owner).
- [ ] Print previews identical; device checks (HUMAN).
- [x] README "UI templates"; `.env.example` documents `VITE_UI_TEMPLATE`.
