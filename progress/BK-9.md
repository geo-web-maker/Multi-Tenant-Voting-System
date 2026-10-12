# BK-9 — Control-room hand-run checkpoint

- **Date:** 12 October 2026
- **Status:** Human acceptance outstanding.
- **Files:** No production configuration changed; checklist recorded here and in the runbook.

## Implemented / prepared
Prepared the UI actions and safety checks needed to validate connections, B2 monitoring and manual triggers from the dashboard.

## Not done / outstanding
**Not performed:** no credentials were supplied to the app runtime, no live B2/second-cluster/manual UI run was executed, and no browser visual check was available. Operator must run Connections → Test now, B2 self-test/Verify newest backups, mirror sync, Chain Verify, and Run all checks (including restore test) before moving regions.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
