# BK-8c — Migration sub-tab and Settings

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `frontend/src/components/BackupMigration.jsx`, `BackupSettings.jsx`, `BackupOverview.jsx`, `frontend/src/components/BackupsPanel.jsx`

## Implemented / prepared
Added ordered Plan → Copy → Freeze → Final pass → Verify controls, readiness checklist, freeze status, configuration editing and read-only `RESTORE_TEST_KEEP_DATA` display. Tightened enablement around predecessor jobs and the election guard.

## Not done / outstanding
A full set of per-check readiness/button behavior tests and template/browser rendering tests remains outstanding; frontend test/lint cannot run without installed modules.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
