# BK-1 — Backup collection coverage

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/backup.py`, `backend/tenant_db.py`, `backend/tests/test_backup_mirror_restore_guide.py`

## Implemented / prepared
Added required full/append-only coverage, documented exclusions, `sms_usage` `org_key` filtering for a tenant and legacy `default`, ownerless-row preflight, and coverage audit. Global `platform_settings` has a separate daily full backup path. Added initial regression tests for coverage and preflight.

## Not done / outstanding
A real-data ownerless-row audit and first full-backup size/cap check remain pending against the deployment.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
