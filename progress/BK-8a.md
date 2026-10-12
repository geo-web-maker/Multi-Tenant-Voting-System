# BK-8a — Backups tab shell, Overview and Connections

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `frontend/src/components/BackupsPanel.jsx`, `BackupOverview.jsx`, `BackupConnections.jsx`, `BackupUI.jsx`, `SuperAdminDashboard.jsx`, `frontend/src/backupsTabPattern.test.js, `frontend/src/components/BackupsPanel.test.jsx``

## Implemented / prepared
Mounted Backups after Performance within Platform; added seven-subtab shell, shared Site Usage/Performance loading/toast/polling conventions, health status, connection cards, guard summaries, refresh and job polling.

## Not done / outstanding
Browser verification at phone/desktop, light/dark and default/Blueprint templates remains pending. Source-level conformance and cross-tab behavior smoke tests are added but not run due to missing `vitest`.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
