# BK-6 — Time-limited write freeze

- **Date:** 12 October 2026
- **Status:** Implementation added; acceptance gate blocked.
- **Files:** `backend/write_freeze.py`, `backend/main.py`, `backend/tests/test_backup_mirror_restore_guide.py`

## Implemented / prepared
Added process-local, auto-expiring write freeze with a 20-minute default, 30-minute maximum, fail-open restart semantics, write-method middleware exemptions for operational paths, and refusal to freeze while an election is open through the admin API.

## Not done / outstanding
Runtime behavior under the deployed middleware order and real election states still needs the full backend test suite.

## Gates
- `python -m compileall -q backend`: **PASS** (syntax compilation only).
- `python -m pytest -q tests/test_backup_mirror_restore_guide.py` from `backend/`: **BLOCKED before test collection**; `backend/tests/conftest.py` imports `mongomock.collection`, but `mongomock` is not installed (`ModuleNotFoundError`).
- `npm run test -- --run` from `frontend/`: **BLOCKED**; `vitest: not found` because Node dependencies are not installed.
- `npm run lint` from `frontend/`: **BLOCKED**; `eslint: not found` for the same reason.
- No live Atlas/Render/B2 connection test or browser visual test was run in this environment.
