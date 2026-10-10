# Guide 12 — Implementation and Test Report

Date: 2026-10-11

## Implemented in this archive

- Added `backend/analytics_store.py` with Mongo and Postgres analytics-store adapters. Mongo remains the default and rollback path (`ANALYTICS_STORE=mongo`).
- Updated `backend/analytics.py` so aggregate collection and alert evaluation remain in memory while persistence and readback use the selected adapter.
- Added a Postgres schema bootstrap at `backend/sql/analytics_postgres_schema.sql`. The web process verifies pre-provisioned tables and does not run privileged DDL at startup.
- Added `backend/migrate_analytics_to_postgres.py` for a throttled, restartable history copy, with retained counter history verification and an import ledger so cumulative heat counts are only added once.
- Added `backend/tests/test_analytics_store.py` with regression coverage for row reconstruction, dashboard parity, additive vs. max writes, transaction use, pool configuration, tenant scoping, idempotent history copy, buffer restoration/capping, Mongo fallback, tenant-scoped purge, and daily retention.
- Added Guide 12 environment variables to `backend/.env.example` and updated the combined ops/security guide with rollout, rollback, migration, and test status.

## Checks run in this environment

| Check | Result | Detail |
|---|---|---|
| Python syntax compilation | PASS | `python -m compileall -q .` completed with exit code 0. |
| Isolated storage smoke checks | PASS | Checked counter flatten/rebuild and `build_summary` parity, transactional additive and concurrency-max writes, tenant-scoped reads, nested histogram reconstruction, one-time heat-history import, pooled connection settings, and five-second pool timeouts using a fake Postgres connection. |
| Flush-failure smoke check | PASS | Simulated a failed Postgres write; verified the counter snapshot was restored, pending keys were cleared, and the configured buffer key cap held. |
| Targeted pytest module | BLOCKED BEFORE COLLECTION | `python -m pytest tests/test_analytics_store.py -q` exits 4 because `tests/conftest.py` imports `mongomock`, which is missing in this runtime. |
| Full backend pytest suite | NOT VERIFIED | Project dependencies including `motor`, `pymongo`, `mongomock`, `mongomock_motor`, and `asyncpg` are absent. An attempt to install dependencies was blocked by unavailable package-index DNS/network access. |
| Real Neon / Atlas migration | NOT RUN | No live database credentials or provisioned Neon schema were supplied to this execution. |

The failed pytest collection is an environment/dependency blocker, not evidence that the test module passed. No full-suite pass count is claimed.

## Before cutover

1. Install `backend/requirements-dev.txt` in an environment with package-index access and run `python -m pytest tests -q` from `backend/`. Resolve any failures before switching storage.
2. Provision `backend/sql/analytics_postgres_schema.sql` in Neon using an owner/admin account, then grant the dedicated runtime role only the documented table/schema privileges.
3. Outside voting hours, configure `ANALYTICS_STORE=postgres`, `ANALYTICS_POSTGRES_URL` with Neon's pooled TLS URL, `ANALYTICS_POSTGRES_POOLED=true`, and `ANALYTICS_FLUSH_S=600` or `900` in Render. Changing environment variables restarts the service; do not do this during voting or around closing/certification.
4. Run the one-off importer with a UTC cutoff that matches the switch day. Verify migration totals and compare dashboard summaries for representative organisations/date ranges. Keep the Mongo collections for at least a week.
5. Roll back by setting `ANALYTICS_STORE=mongo` if needed. The actual live cutover is still pending.
