# Backup Monitoring, Mirror and Restore-Test Implementation Report

**Date:** 12 October 2026  
**Repository:** Multi-Tenant Voting System ZIP supplied in this conversation  
**Result:** Broad implementation delivered in the source tree; automated acceptance remains incomplete because required test/frontend packages are unavailable in this execution environment. No production cutover or live-data operation was performed.

## Implemented

### Backend

- Expanded backup collection coverage and added an explicit `EXCLUDED_BY_DESIGN` list, `sms_usage` ownership filtering via `org_key`, ownerless-document preflight, coverage audit, and daily `platform_settings` global backup.
- Extracted shared restore verification/planning/apply functionality to `restore_core.py`; refactored the restore CLI to use it.
- Added database-handle Chain Verify logic in `chain_verify.py` and routed the existing request-scoped verifier through it; reports uncheckpointed vote events in restore results.
- Added safe, re-runnable migration logic in `migrate_core.py` and `migrate_mongo.py`, including dry run, index recreation, per-collection count/digest verification, reserved destination checks, optional security collection copying and final delete reconciliation.
- Added a best-effort warm mirror (`backup_mirror.py`) that writes to `mirror` only on a guarded second cluster; it uses a separate Motor client, incremental append-only watermark overlap, full reconciliation, host fingerprint reset, and failure alerts.
- Added guarded B2 restore tests that use `restore_test`, validate manifests/checksums/counts/tenant ownership, run Chain Verify, record lag, fail if backed-up vote IDs are missing from live, report asset/coverage warnings and clean up scratch collections by default.
- Added persistent backup job records, connection probes and guard checks, `backup_metrics` sampling/TTL, superadmin backup API endpoints, token-protected scheduler endpoints, migration readiness checks, and a time-bounded in-memory write freeze.
- Added environment variable examples and deployment/incident runbook documentation.

### Frontend

- Added Backups under Platform after Site Usage and Performance.
- Implemented Overview, Connections, Backblaze, Second DB, Staging (restore test), Migration, and Settings sub-tabs.
- Reused existing Site Usage/Performance loading, polling, charts, list rows, alert panel, toast/confirm patterns, styles and CSS tokens; no new chart library was introduced.
- Added source-level conformance checks in `frontend/src/backupsTabPattern.test.js` and basic BackupsPanel interaction smoke tests in `frontend/src/components/BackupsPanel.test.jsx` (sub-tab navigation, retry after load failure, view-as write disabling and health-check confirmation).

### Operations and records

- Added probe and weekly restore-test GitHub Actions workflows.
- Added `docs/BACKUP_MIRROR_RESTORE_TEST_RUNBOOK.md`, `deviations/BK-all.md`, and one progress record per guide card from BK-1 through BK-11.

## Verification results

| Check | Result | Detail |
|---|---|---|
| `python -m compileall -q backend` | **PASS** | Backend Python syntax compilation completed successfully. This is not a substitute for integration tests. |
| `python -m pytest -q tests/test_backup_mirror_restore_guide.py` | **BLOCKED** | Test collection stops in `backend/tests/conftest.py`: `ModuleNotFoundError: No module named 'mongomock'`. No tests from this invocation executed. |
| `npm run test -- --run` | **BLOCKED** | Frontend runner not available: `vitest: not found`; dependencies were not installable in this environment. |
| `npm run lint` | **BLOCKED** | `eslint: not found` because frontend dependencies are missing. |
| Application import smoke test | **BLOCKED** | Importing `backend/main.py` stops at `ModuleNotFoundError: No module named 'motor'`; runtime dependencies are not installed in this environment. |
| Real cluster, B2, Postgres and browser acceptance | **NOT RUN** | Requires deployment credentials, network access and configured environments. |

Added backend regression tests cover backup coverage/filtering, ownerless preflight, scratch guards, reserved migration destinations, same-cluster migration refusal, Chain Verify tamper detection, and write-freeze bounds/exemptions. The frontend conformance and basic BackupsPanel smoke tests are present but could not run. The richer behavioral/UI matrix specified by the guide (all sub-tab states, all readiness conditions, detailed polling lifecycle, both templates/themes and responsive overflow) is not fully implemented or verified; do not infer full acceptance from the added tests.

## Important deployment/security note

The supplied working folder includes `backend.env`, `frontend.env` and `backend/loadtest.env`. These are environment files and may contain credentials or private endpoints, so they are intentionally **excluded from the updated ZIP**. Use the included `.env.example` templates and configure actual secrets directly in the deployment environment. Do not paste connection strings or tokens into source control or this chat.

No live database was copied, no `restore_test` database was flushed, no live environment variable/domain was switched, and no Atlas database was dropped. Those steps are deliberately reserved for the staged hand-run checkpoint and production cutover.

## Required next acceptance steps

1. Install project dependencies in an environment with package access, then run the full backend test suite, frontend test suite and `npm run lint`; address all failures before calling the feature accepted.
2. Configure a physically separate second Mongo cluster, B2 buckets, Postgres analytics connection, and scheduler secrets. Use the Backups tab to test connections, B2 read-back/self-test, mirror sync, Chain Verify and a complete restore test. Confirm no secrets appear in API responses/logs.
3. Run both scheduler workflows by hand and observe at least one periodic probe and the restore-test polling completion; verify expected email alerts with an induced non-production failure.
4. Visually inspect standard and Blueprint templates at phone and desktop sizes, light and dark; complete the frontend state/confirmation/view-as/button-disable tests and verify there is no horizontal overflow.
5. Only after the above, complete the migration rehearsal and readiness checklist. Move live Mongo/Render to Frankfurt last, with no election open and the write freeze active for the final pass. Retain old service/cluster rollback until post-cutover verification passes.

See `progress/BK-1.md` through `progress/BK-11.md` for card-by-card completion and remaining gates, and `docs/BACKUP_MIRROR_RESTORE_TEST_RUNBOOK.md` for operational commands and incident handling.
