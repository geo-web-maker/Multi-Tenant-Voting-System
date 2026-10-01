# D1b — WP-9.3 backend: tracking_since (card D1b)
status: done
branch: improvements/D1b
commits: see git log on this branch
tests added: backend/tests/test_analytics_tracking_since.py (6)
results: backend 281 passed (baseline at cut 275 + 6 new) · frontend not touched (68 passed at cut) · lint n/a · build n/a
baseline at branch cut: backend 275 · frontend 68
deviations: none. Lookup is best-effort (any DB error -> null) so a failed lookup can never 500 the summary; this also keeps the existing FakeColl in test_analytics.py (no sort()) working unchanged.
notes: query is {org_id} only (not limited to the summary window/seg/device), sorted by day asc, limit 1; served by the existing unique (org_id, day, ...) index prefix. Field is top-level `tracking_since` ("YYYY-MM-DD" or null) on GET /superadmin/analytics/summary. `compare` is unchanged.
HUMAN checks pending: none for this card. Dashboard line is D2e (depends on this merge).
