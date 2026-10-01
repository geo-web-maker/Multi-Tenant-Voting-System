# CUSTOM-1 — Restore voter statistics in the superadmin Voters section (custom task, not a runbook card)
status: done
branch: improvements/custom-voter-stats
commits: see git log on this branch
tests added: backend/tests/test_voter_stats.py (2) · frontend/src/components/VoterStats.test.jsx (2)
results: backend 295 passed, 0 failed · frontend 256 passed, 0 failed · lint 0/0 · build not re-run
baseline at branch cut: backend 293 · frontend 254
deviations: see "Custom tasks" in DEVIATIONS.md. This task is outside the A–F lane plan; it was requested by the owner directly.
what: the Voters tab (superadmin) now has three sub-tabs. Register = the existing paginated VoterList (unchanged). Statistics = total voters, voted / not voted, turnout %, phone on file / no phone, SMS sent, SMS budget left, and registered + voted per enabled voter field (e.g. hostel, faculty). SMS = live provider balances (EgoSMS, MamboSMS, from the existing GET /admin/sms-balance and the SmsProviderCard that was left unused in SuperAdminDashboard) above the existing SmsUsageTile (budget, delivery, routing), reused not copied.
files: backend/main.py (new GET /admin/voters/stats, superadmin only, counts only), frontend/src/components/VoterStats.jsx (new), SuperAdminDashboard.jsx (sub-tab switcher in the Voters tab).
note: git history holds no earlier version of these statistics (the oldest commit already has the table-only tab), so they were rebuilt from the current data, not restored from a diff. Wording and layout may differ from what you remember.
HUMAN checks pending: open Voters as superadmin on a real org and confirm the numbers match what you expect (especially which voter field you consider the "section"); org with no voter fields shows the "no per-section breakdown" line.
