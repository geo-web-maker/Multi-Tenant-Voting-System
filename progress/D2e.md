# D2e — "Tracking of funnel steps started on <date>" line (card D2e, §1.2)
status: done
branch: improvements/D2e
commits: see git log on this branch
tests added: frontend/src/components/AnalyticsPanel.trackingSince.test.jsx (3)
results: backend not touched (baseline 287 passed) · frontend 88 passed, 0 failed · lint 0/0 · build not re-run (one JSX line)
baseline at branch cut: backend 287 · frontend 85
deviations: none
notes: reads `tracking_since` ("YYYY-MM-DD" or null) from GET /superadmin/analytics/summary (added in D1b). The line sits just above the Apply funnel panel and is shown only when the value is non-null; date is formatted in the election time zone via fmtZoned with the time part stripped.
HUMAN checks pending: open Site Usage as superadmin on an org with data and confirm the line reads correctly; an org with no analytics rows shows no line.
