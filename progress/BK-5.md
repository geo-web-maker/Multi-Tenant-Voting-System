# BK-5 — Persisted jobs and B2 restore test

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/backup_jobs.py`, `backend/restore_check.py`, `backend/restore_check.py`, `backend/backup_admin_routes.py`, `.github/workflows/restore-test.yml`

## Implemented / prepared
Added shared 180-day job records, one-job-at-a-time coordination, guarded `restore_test` flushes (at start and normally end), B2 manifest/checksum/count/org checks, restored-data Chain Verify, uncheckpointed event reporting, missing-vote-id hard failure, asset/coverage warnings and election-aware scheduled behavior.

## Not done / outstanding
A full restore against actual B2 objects and a physically separate Mongo cluster has not run. Automated tests are blocked by missing test dependencies.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
