# BK-3 — Connection probes and backup metrics

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/backup_probes.py`, `backend/backup_routes.py`, `backend/backup_admin_routes.py`, `.github/workflows/backup-probe.yml`

## Implemented / prepared
Added redacted connection probes, guard checks, 15-minute metric samples with a 30-day TTL, B2 backup-bucket and nomination-bucket checks, cached B2 listing summary, configured latency thresholds, and the token-protected probe endpoint/workflow.

## Not done / outstanding
Actual B2, Postgres and second-cluster results, scheduled workflow secrets and consecutive-probe alert behavior need a configured deployment to validate.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
