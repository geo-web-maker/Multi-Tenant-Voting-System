# Backup control room runbook

## Environment setup

Configure these values in the backend deployment environment, never in source control or chat:

- `MONGO_URL`, `MONGO_DB_NAME`: current live database.
- `SECOND_MONGO_URL`: distinct second Atlas cluster. Before cutover, this is the temporary Frankfurt cluster; after cutover, the Cape Town cluster.
- `MIGRATION_TARGET_URL`: optional override; defaults to `SECOND_MONGO_URL`.
- `MIRROR_DB_NAME=mirror`, `RESTORE_TEST_DB_NAME=restore_test` (the restore guard refuses any other scratch name).
- `MIRROR_ENABLED=true` after the second-cluster connection and safety guards pass.
- `RESTORE_TEST_KEEP_DATA=false` by default; only set true temporarily when a superadmin needs to inspect the scratch copy.
- `BACKUP_TRIGGER_TOKEN` must be at least 24 characters and configured as a Render secret and a repository secret.
- Existing B2 backup values (`B2_BACKUP_*`) must continue to point to the locked routine/safety/milestone bucket. The nomination bucket is separate and should have versioning enabled.

The repository adds two scheduler examples: `.github/workflows/backup-probe.yml` calls the token-protected probe every 15 minutes, and `.github/workflows/restore-test.yml` starts the weekly test Sunday at 03:00 UTC and polls until it finishes. Add repository Actions secrets named `BACKEND_URL` and `BACKUP_TRIGGER_TOKEN`. Existing `/internal/backup/run` schedules must be preserved for `incr`, `full` and `weekly`. After cutover update `BACKEND_URL` for every scheduler workflow.

## Before the first live check

1. In Atlas create/confirm the second cluster in a different project/cluster, add a separate database user, and temporarily allow your administrator IP plus Render's outbound IPs. Remove broad temporary access afterwards.
2. Set `SECOND_MONGO_URL` without changing `MONGO_URL` yet. Keep `MIGRATION_TARGET_URL` unset unless there is an explicit reason to override the default.
3. Open **Superadmin → Platform → Backups → Connections**, run **Test connections now**, and resolve all failed safety guards. A not-configured connection is not a healthy connection.
4. Resolve any nonzero counts in **Backup ownership preflight**. Assign the records to a real `org_id` or delete them through the approved legacy-data workflow before considering cutover.
5. Run one full backup. Verify newest backups, run B2 self-test, perform a full mirror sync and Chain Verify the mirror. Run the restore test and read every step.

## Weekly restore test / before an election

The weekly scheduler skips the test while an election is open. Before manually opening each election, use **Staging (restore test) → Run restore test now**, inspect all steps and confirm the status is **Passed** (or resolve and document any warning). The restore-test database is flushed at the start and normally at the end of every run. Do not use the `mirror` database as scratch.

A checksum/count/ownership/Chain Verify failure or a backup vote ID missing from live is a hard failure. Preserve the job ID and investigate. Missing non-vote records from live and missing asset objects are warnings; uncovered tenant-data collections are also warnings until backup coverage is fixed. Do not treat a successful upload as proof that a restore is usable.

## Cutover checklist (do this last)

1. Work off-hours with no election open. In Migration run **Plan**, **Copy** (rehearsal), then **Verify migration**. Rehearse all of these while the old live database is still authoritative.
2. Confirm B2 verify passed within 24 hours, recent full backups are within their 36-hour active / 8-day idle thresholds, mirror counts match, restore-test passed within 7 days, the coverage audit is clean and all connections/guards are healthy.
3. Start the write freeze for 20 minutes (maximum 30 minutes). It is refused while any election is open and auto-expires/restarts clear it.
4. Run **Final pass** while frozen, then **Verify migration**. Wait for every cutover-readiness check to pass. If time expires, stop and repeat the steps; do not switch with a partial final pass.
5. Manually create a new Render service in Frankfurt and configure its `MONGO_URL` to the new cluster. Test login, demo voting, results and Performance on the temporary URL before switching frontend/backend URLs and scheduler destination.
6. Keep the original service and Cape Town database untouched as rollback until the new service is stable. After cutover point `SECOND_MONGO_URL` at Cape Town and check that mirror mode becomes `full` on the first sync. The temporary `mirror` and `restore_test` databases formerly on Frankfurt must be dropped manually in Atlas—never drop `electiondbaccounting`.
7. Run **Run all checks** with restore test included; verify Chain Verify on live and mirror, counts, scheduler jobs, and role-swap checklist.

## Incident runbooks

### Live cluster lost: manual switch to mirror

1. Check `Mirror last sync` and understand the data lag.
2. Chain Verify the mirror for each organisation before trusting it.
3. In Render switch `MONGO_URL` to the second cluster and `MONGO_DB_NAME=mirror`; set `MIRROR_ENABLED=false`, then redeploy.
4. Admins and voters need to sign in again; security/OTP collections are deliberately not mirrored.
5. After stabilizing, create a fresh live cluster, migrate from the mirror, verify, and switch back.

### Restore one tenant from B2

Use `python restore_tenant.py list --tenant <org_id>` to choose a prefix. Restore to a disposable copy first, use `--dry-run`, verify counts and Chain Verify, and only use the CLI's explicit `--live --replace` confirmation when necessary. Never target the `mirror` or `restore_test` database with the migration tool.

### Restore test failed

Open the job detail in the Backups tab. Checksum/count mismatch means the B2 object/manifest or restore reader is inconsistent; keep the failed run ID, create a forced full backup for the affected tenant, and rerun verification. If restored Chain Verify fails while live verifies, investigate the backup/restore path. If live Chain Verify also fails, stop and treat it as a data-integrity incident.
