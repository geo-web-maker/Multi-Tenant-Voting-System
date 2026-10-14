# BallotBox backups: setup and restore runbook

Atlas M0 has no snapshots. These backups are the only protection. They are made by
`backend/backup.py`, triggered from outside by `.github/workflows/backup.yml`.

## 1. One-time setup (Backblaze B2)

1. **Create a NEW bucket** (not the audit-checkpoint bucket). Private, **Object Lock enabled**
   (must be set at creation), no default retention. Server-side encryption on.
2. **Keys** (App Keys, both restricted to this bucket):
   - *Writer key* (goes on Render): `listBuckets, listFiles, readFiles, writeFiles, writeFileRetentions`.
     **No** `deleteFiles`, **no** `bypassGovernance`. A compromised server cannot delete or shorten anything.
   - *Admin key* (keep OFFLINE, never on Render): all bucket capabilities incl. `bypassGovernance`,
     `deleteFiles`. Only for undoing a mistake within a routine lock.
3. **Lifecycle rules** (Bucket Settings -> Lifecycle Settings -> custom), one per prefix:
   - `routine/`: days from uploading to hiding **15**, days from hiding to deleting **1**
   - `safety/`: hiding **91**, deleting **1**
   - `_reports/`, `_selftest/`: hiding **15**, deleting **1**
   - **No rule on `milestone/`** (those are compliance-locked >= 1 year and are kept).
4. **Spending cap**: Account -> Caps & Alerts -> set storage and transaction caps to $0 (or $1-2).
   When a cap is hit uploads fail and the backend emails the superadmin ("SPENDING CAP HIT").
5. **Render env vars**:
   `B2_BACKUP_ENDPOINT`, `B2_BACKUP_KEY_ID`, `B2_BACKUP_APPLICATION_KEY` (writer key),
   `B2_BACKUP_BUCKET_NAME`, `BACKUP_TRIGGER_TOKEN` (24+ random chars),
   `RESEND_API_KEY` (+ optional `ALERT_FROM_EMAIL`, `BACKUP_ALERT_EMAIL`; default recipient is `SUPER_ADMIN_ID`).
   Email uses Resend's HTTPS API because Render's free tier blocks SMTP.
6. **GitHub repo secrets**: `BACKUP_URL`, `BACKUP_TOKEN`. (cron-job.org works too: POST
   `<url>/internal/backup/run?mode=incr` every 15 min, `mode=full` daily, `mode=weekly` weekly, header
   `X-Backup-Token`, enable its failure notification.)

## 1b. Running on Render's free web service

Render free is ~0.1 CPU, 512 MB RAM, sleeps after 15 minutes without inbound traffic and restarts from scratch when
woken. The backup stack is tuned for that:

- **`POST /internal/backup/run` returns 202 immediately** and runs as a background job (cold start + a long request
  would hit cron-job.org's 30 s limit). Poll `GET /internal/backup/run/{run_id}` or `GET /internal/backup/status`.
  Failures are still logged and e-mailed by the backend. For a scheduler that can wait (GitHub Actions) use
  `?wait=true` (or set `BACKUP_RUN_WAIT=true`) to get the old behaviour: 200 on success, 500 on failure.
- While a job runs the service pings its own `RENDER_EXTERNAL_URL/health` every 4 minutes so Render does not sleep it
  mid-upload. Jobs orphaned by a restart are marked failed at boot instead of blocking for 2 hours.
- Exports/uploads/restores stream through temp files (about 2 MB of Python memory for 100k documents measured); the
  restore test and "Verify backups" no longer load a whole backup into RAM.
- Compression is gzip level 1 and work is sliced so voters are still served during a backup.
- The mirror and monitoring probes run at most every ~30 minutes on the 15-minute incremental schedule (full/weekly
  runs always do both). The Backups tab polls every 60 s, fetching only `/summary` and the job list.
- Alert e-mail cooldowns are stored in MongoDB so a restart does not re-send the same alert.

Tunables (all optional): `BACKUP_CPU_SLICE` (100), `BACKUP_BATCH_PAUSE_S` (0.05), `BACKUP_GZIP_LEVEL` (1),
`BACKUP_SPOOL_MEM_BYTES` (1 MiB), `BACKUP_MIRROR_TIMEOUT_S` (300), `BACKUP_MIRROR_INCR_MIN_GAP_MIN` (30),
`BACKUP_PROBE_INCR_MIN_GAP_MIN` (30), `BACKUP_KEEPALIVE_INTERVAL_S` (240), `PROBE_CACHE_S` (60),
`PROBE_CONCURRENCY` (3), `B2_SUMMARY_CACHE_S` (1800), `BACKUP_READ_CACHE_S` (30). Raise the speed settings on a paid
instance. Free instances also have a 750 hour/month limit: one always-on service fits, two do not.

## 2. First run

Call `POST /internal/backup/selftest` (header `X-Backup-Token`) once: it reads every collection with the
`org_id` filter, checks `dbStats`, and writes+reads a locked test object. Fix anything it reports.
The first `run` then measures database and Cloudinary sizes and emails a report with a monthly estimate
(also at `GET /internal/backup/report`). If the estimate exceeds 10 GB, asset copying is held and options
are listed in the email; approve with `POST /internal/backup/approve-assets` or choose another option.

## 3. Schedule (what the calls do)

| Call | Does |
|------|------|
| `mode=incr` every 15 min | open elections: new `vote_events` / `audit_log` records only; also detects open / close / certified and takes the milestone snapshot |
| `mode=full` daily | open elections: full tenant backup (+ assets, new or changed only) |
| `mode=weekly` | idle tenants: full backup only if something changed (or the last copy is 10+ days old) |

Pre-reset snapshots are automatic (`/admin/reset-election`, `wipe_election_data.py --org-slug <slug>`), one tenant at a time; failure aborts the reset/wipe.

## 4. Restore ONE tenant

Tenant id = the org `_id` string. `default` only appears if stray documents with no `org_id` still exist (the app no longer creates or reads them); the scheduled backup keeps dumping them as a safety net until you delete them.

```
cd backend   # needs the B2_BACKUP_* env vars and MONGO_URL
python restore_tenant.py list --tenant <id> [--cls routine|safety|milestone]
python restore_tenant.py restore --tenant <id> --backup routine/<id>/full-<ts> --dry-run
python restore_tenant.py restore --tenant <id> --backup routine/<id>/full-<ts> --target-db restore_copy --replace
```
1. Pick a `full-*` (or a milestone / safety snapshot). Routine restores also apply every later `incr-*`
   (`--until <ts>` stops earlier).
2. `--dry-run` downloads everything and verifies each file's SHA-256 (compressed and uncompressed) and record
   count against `manifest.json`. Any mismatch stops the restore.
3. Restore into a copy (`--target-db`) first and check it. Only the given `org_id` is read or written; a
   document with another `org_id` aborts the restore.
4. The script prints expected vs actual counts per collection (OK / MISMATCH, exit code 1 on mismatch).
5. Live restore: `--live` (asks you to type `RESTORE <id>`). Add `--include-org` to restore the organization document.
Assets: files are under `<class>/<tenant>/assets/` (or the snapshot's own `assets/`); the manifest maps each to its
original Cloudinary URL and SHA-256.

## 5. Risks to know

- **Render sleeps when idle.** During an open election the instance must stay awake or voters hit a cold start.
  The 15-minute backup call happens to keep it warm, but do not rely on that: use a real keep-alive/uptime ping.
- GitHub may delay scheduled runs and disables schedules after 60 days without repo activity.
- Backups contain voter personal data. The bucket must stay private; keep the writer key only on Render.
