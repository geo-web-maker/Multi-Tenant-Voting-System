# D2b — §5.6d Load-test advice formula (card D2b)
status: done
branch: improvements/D2b
commits: see git log on this branch
tests added: frontend/src/loadTestAdvice.test.js (6) · frontend/src/components/AnalyticsPanel.loadAdvice.test.jsx (1)
results: backend not touched (baseline 287 passed) · frontend 95 passed, 0 failed · lint 0/0 · build ok (entry chunk 94.5 KB)
baseline at branch cut: backend 287 · frontend 88
deviations: the card names only a helper and its call site. The panel has no eligible-voter count, so a small "Eligible voters" number box was added in the Reliability section (local state, nothing saved). The existing "observed peak concurrency x 1.5" sentence is unchanged.
notes: src/loadTestAdvice.js: expected_peak = voters x share_in_busiest_hour x (avg_session_seconds / 3600); (1500, 0.40, 180) -> 30, range 1.5x to 2x -> 45 to 60. Busiest-hour share comes from summary `hour_of_day` (max / total, unaffected by the time-zone shift); average session from `totals.average_session_seconds`. Missing, zero, negative or non-numeric input returns 0 and no line is shown (never NaN). Share is capped at 1.
HUMAN checks pending: type the real eligible-voter count on the Site Usage page and sanity-check the suggested user range before setting it in backend/loadtest/locustfile.py.
