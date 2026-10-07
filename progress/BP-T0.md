# BP-T0 — Foundations
status: done
branch: improvements/BP-T0 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: src/template.test.js (11: resolver table x7, registry x3, chrome store x1)
results (default):   frontend 295 passed, 0 failed · lint 0/0 · build ok, entry gz 34,777 B
results (blueprint): frontend 295 passed, 0 failed · build ok, entry gz 34,930 B, blueprint chunk gz 228 B (JS + CSS stub)
baseline at branch cut: frontend 284 · lint 0/0 · entry gz 34,769 B
G1: pass (entry +8 B, no blueprint chunk, no "bp-" strings in default JS) · G2: pass · G4: `data-track labels OK`
deviations:
- vite.config.js: added chunkFileNames/assetFileNames so the Blueprint chunk is named `blueprint-<hash>` (default build unaffected; nothing matches). Without it Vite names it `index-*` and G2 cannot find it.
- eslint.config.js: added `dist-blueprint` to globalIgnores (the §4.1 build output would otherwise be linted).
- scripts/check_template_build.sh created here (card T1 lists it) because T0's "done when" needs G1; also added the blueprint-entry <= default+2 KB check that §10 G2 states but Appendix E omitted.
- test helpers named use*() carry eslint-disable comments for react-hooks/rules-of-hooks (plain functions, not hooks).
- .gitignore: `dist-blueprint` added to frontend/.gitignore AND the root .gitignore (the root file is the one that ignores dist/ and *.env here).
findings:
- AdminDashboard.jsx is not imported by App.jsx (only a comment mentions it) -> legacy, out of scope (F17 confirmed).
- frontend/.gitignore does not ignore .env; the root .gitignore does. `frontend/.env.example` is not ignored (see root `!*.env.example`).
- No env file was opened.
HUMAN checks pending: none for this card. Run `VITE_UI_TEMPLATE=blueprint npm run dev` once and confirm the page looks identical to default (T0 registers the template but nothing consumes it yet) and `<html data-template="blueprint">` is present.
next step: BP-T1 (CSS foundation).
