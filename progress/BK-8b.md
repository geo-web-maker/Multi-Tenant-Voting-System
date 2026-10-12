# BK-8b — Backblaze, Second DB and Staging sub-tabs

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `frontend/src/components/BackupB2.jsx`, `BackupMirror.jsx`, `BackupRestoreTest.jsx`, `BackupJobList.jsx`

## Implemented / prepared
Added B2 backup summaries and actions, mirror counts/state/sync/Chain Verify, restore-test progress/history/checklist and reusable job list, using existing shared chart/list components and confirmation patterns.

## Not done / outstanding
Behavioral UI tests for every normal/error/running/empty state and live browser checks were not added/run in full; source conformance and basic cross-tab smoke tests are blocked with the frontend test command.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
