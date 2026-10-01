# WP-7c — Confirm before "Vote Now" signs an admin out (card A3)
status: done
branch: improvements/WP-7c
commits: see git log on this branch
tests added: frontend/src/App.voteNow.test.jsx (3)
results: backend not re-run (frontend-only change; baseline 275 passed) · frontend 66 passed, 0 failed · lint 0/0 · build ok (entry chunk 93.9 KB)
baseline at branch cut: backend 275 · frontend 63
deviations: none (playbook 1455-1457 read; wording and tests match)
HUMAN checks pending: on a phone, signed in as admin, tap "Vote Now" from Results/Apply -> native confirm appears; Cancel keeps you signed in
