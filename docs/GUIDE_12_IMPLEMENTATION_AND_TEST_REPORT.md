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

## Restored after a rebase (11 Oct 2026)

A rebase had dropped the storage layer from `backend/analytics.py`, so `GET /superadmin/performance/storage` failed and the Performance tab showed "Could not load storage settings". Restored in `analytics.py`:

- `storage_mode()`, `storage_status()`, `switch_storage()`, `load_storage_choice()`, `_analytics_store()`. The choice made in the tab is saved in `platform_settings` (`name: analytics_storage`) and wins over `ANALYTICS_STORE` after a restart.
- `_flush_once(include_heat, force)` writes through the active store. Counters reach the store every `ANALYTICS_FLUSH_S` (default 30); alerts and the per-minute trim still tick every 30 s. `force` is used at shutdown and just before a storage switch.
- A failed write puts back only what was not written. New buffer keys are refused once `ANALYTICS_MAX_BUFFER_KEYS` is reached (the snapshot being written counts toward the cap), so an outage cannot grow memory without bound.
- Mongo writes have no timeout (a cancelled bulk can half-apply); Postgres writes get 5 s (one transaction).
- Reads (summary, heatmap, compare) go through the store. A Postgres read failure returns 503 "temporarily unavailable" instead of an empty dashboard.
- Purging an organisation clears Postgres and, when Postgres is active, MongoDB too, so a later migration cannot bring the data back.
- Switching to Postgres checks the tables and creates them if they are missing (`CREATE ... IF NOT EXISTS`, same definitions as `backend/sql/analytics_postgres_schema.sql`). Creating needs a login that may create tables; with a CRUD-only login the switch fails with a message saying so, and nothing changes. The Mongo production default stays chunked (25 writes, 0.5 s pause), set through `MongoAnalyticsStore(chunk_default, pace_default)`.
