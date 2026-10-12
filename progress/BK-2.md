# BK-2 — Restore, Chain Verify and migration primitives

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/restore_core.py`, `backend/restore_tenant.py`, `backend/chain_verify.py`, `backend/migrate_core.py`, `backend/migrate_mongo.py`, `backend/main.py`

## Implemented / prepared
Extracted importable restore read/verify/plan/apply logic; routed request-scoped Chain Verify through the reusable database helper; added migration copy/digest/index logic and CLI flags for dry-run, final delete reconciliation, security collections and force.

## Not done / outstanding
Full regression against the existing restore CLI tests and integration with a real Mongo replica set remain unverified. Migration was not run against live data.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
