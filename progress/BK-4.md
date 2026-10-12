# BK-4 — Warm mirror database

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/backup_mirror.py`, `backend/backup.py`, `backend/backup_routes.py`, `backend/backup_admin_routes.py`

## Implemented / prepared
Added best-effort mirror synchronization from live, separate low-pool Motor client without performance listeners, reserved-db/same-cluster guards, digest-based small-collection skip, append-only watermark overlap, full reconciliation/pruning, second-host fingerprint reset, and failure alerting. Wired after scheduled and manual backup triggers.

## Not done / outstanding
Incremental/full behavior, M0 load impact, and the post-cutover full sync need real-cluster testing; the mirror was not connected here.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
