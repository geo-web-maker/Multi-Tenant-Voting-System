# BK-7 — Superadmin and scheduler API

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/backup_admin_routes.py`, `backend/backup_routes.py`, `backend/main.py`, `backend/backup_jobs.py`

## Implemented / prepared
Added superadmin backup routes for summary, connections, B2, mirror, jobs, stats, migration readiness/config, manual checks/backup/verify/selftest/sync/restore/Chain Verify/migration/freeze; writes go through audit callback. Added token-protected scheduler endpoints and org/public path registration. Secrets are redacted from returned error text.

## Not done / outstanding
Role/403, view-as, cache-control/no-store, secret-redaction and end-to-end endpoint tests could not be executed because backend test dependencies are missing.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
