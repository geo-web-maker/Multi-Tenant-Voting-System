# D2d-be — alerts field on the analytics summary (backend half of D2d)
status: done
branch: improvements/D2d-be
tests added: backend/tests/test_analytics_alerts_summary.py (6)
results: backend 293 passed (baseline 287 + 6) · frontend untouched
change: `current_alerts(org)` in backend/analytics.py reuses `build_window_stats` + `evaluate_alerts` + `_alert_config`; `GET /superadmin/analytics/summary` now returns `alerts: [{kind, level, metric, value, threshold}]` (empty list = healthy). Org-scoped, read-only, `routes` deliberately not exposed.
deviations: edits backend/analytics.py, outside the original D2d FILES list, with the owner's go-ahead (see deviations/D2d.md).
HUMAN checks pending: none
next step: D2d (frontend panel) reads `summary.alerts`.
