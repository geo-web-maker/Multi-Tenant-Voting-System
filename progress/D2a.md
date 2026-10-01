# D2a — §5.6b, 5.6c Chart time zone + default range (card D2a)
status: done
branch: improvements/D2a
commits: see git log on this branch
tests added: frontend/src/chartTime.test.js (8) · frontend/src/components/AnalyticsPanel.range.test.jsx (3)
results: backend not touched (baseline 287 passed) · frontend 106 passed, 0 failed · lint 0/0 · build ok
baseline at branch cut: backend 287 · frontend 95
deviations: card FILES names UsageCharts.jsx, AnalyticsPanel.jsx and pure helper files; all three used (new helper: src/chartTime.js). Daily buckets keep their plain UTC date on purpose: they are whole-UTC-day totals, so shifting them into another zone would label them with a day they do not cover. Only hourly buckets (real instants) are converted. The note under the chart now says so.
notes: bucketLabel(t, bucket, tz): "2026-09-14T21:00:00Z" renders 15/9 00h in Africa/Kampala (23:30 UTC on day X shows as day X+1 in EAT). TimelineChart takes a `tz` prop (default Africa/Kampala); AnalyticsPanel passes the election zone. defaultRangeDays(tracking_since, now): 1 ("Last 24 hours") when the earliest recorded day is today (UTC), else 7; applied once on the first summary load and never over a range the user picked. The default is judged from `tracking_since` (D1b), not from the timeline points.
HUMAN checks pending: on a day-one election, open Site Usage and confirm it opens on "Last 24 hours" with hour labels matching Kampala time; on an older org it opens on 7 days.
