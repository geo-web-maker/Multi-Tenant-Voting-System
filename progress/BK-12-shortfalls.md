# BK-12 — Shortfall remediation

- **Date:** 12 October 2026
- **Status:** Tests written and one code change made; **nothing executed** (no pytest, vitest, mongomock or network here). Only `py_compile` was run.

## Code change
`restore_check.py`: live-vs-backup id comparison is now chunked (`_live_ids`, 2000 ids per query) instead of one huge `$in`.

## Tests added
Backend: `_fakes.py`, `test_restore_core.py`, `test_chain_verify.py`, `test_migrate_core.py`, `test_backup_mirror.py`, `test_restore_check.py`, `test_backup_probes.py`, `test_backup_metrics.py`, `test_backup_jobs.py`, `test_migration_readiness.py` (baseline + 9 blocking conditions against the real `_migration_state`), `test_backup_admin_routes.py` (HTTP: 403 for other roles, 200 without X-Org-Slug, no secrets in responses, no metrics write on read, stats window, freeze/final guards, token endpoints, alert emails), `test_restore_tenant_cli_pin.py` (dry-run, checksum, foreign org, --until, --replace, target required), `test_backup_jobs_and_routes.py`.
Frontend: `components/BackupsPanel.behaviour.test.jsx`.

## Still outstanding (human)
- Run `pytest`, `npm run test -- --run`, `npm run lint` and fix failures; test doubles and the 8-row expand button text are assumptions.
- Browser check of both templates, phone and desktop width, light and dark, no horizontal overflow, 44 px tap targets.
- Restore test still holds all tenants' restored documents in memory (fine at current size; revisit if data grows).
- The `restore_tenant` pins were written after the refactor, so they guard future changes rather than prove the refactor preserved behaviour.

## Template follow-up (UI)
Audit found nested tiles (Backblaze lock classes, Second DB tiles, Migration source/target, Overview tiles) and the job-details dialog hard-coded `perf-card`, so in Blueprint they would have rendered with the default look. Added `cardClass()` / `tileClass()` to `BackupUI.jsx` (Blueprint: `bp.cls.card` / `bp.cls.alt`) and switched those uses to them. `BackupCard` and `BackupPill` already used `getTemplate()`.
Added `components/BackupUI.template.test.jsx` (default vs fake Blueprint, word-not-colour, no hard-coded card/bp- classes). **Not run; not viewed in a browser.** Still to verify by eye: `.perf-btn` / `.perf-field` sizing under Blueprint (blueprint.css has no `perf-` rules, so it relies on the global index.css 44 px rule), and how `bp.cls.alt` looks as a tile surface.

## Template follow-up 2 (CSS)
Found by reading blueprint.css: (1) `bp.cls.alt` is Blueprint's RED error block, so using it for tiles (my previous change) would have made every tile look like an error. `tileClass()` now returns a plain `perf-tile` in Blueprint. (2) `blueprint.css` had no `perf-*` rules, and selected/primary buttons used white text on the dark-theme orange accent (poor contrast). Added a scoped block inside `@media screen` (before the print block, no `!important`): 48 px (`--bp-tap`) for `.perf-btn`, `.perf-actions button`, `.perf-check`, `.perf-field`; selected/primary buttons use `--bp-ai` on `--bp-ac`; neutral `.perf-tile` surface. CSS brace balance checked with node; test added in `BackupUI.template.test.jsx`. **Still not seen in a browser.**

## Static-scan fixes
- `tests/test_tenant_scoping_lint.py` (existing ratchet) would have FAILED: BK-1 added raw `db[name]` accesses in `backup.coverage_audit` and `backup.ownerless_preflight`. Added both to `ALLOWED` with the existing `_BACKUP` reason (backup.py is the cross-tenant operator tool). Verified by running the lint's own logic standalone with stubbed imports: no new violations, no stale entries.
- AST undefined-name scan of all new/changed backend modules and tests: clean. Frontend: every `./BackupUI` import resolves to a real export.
