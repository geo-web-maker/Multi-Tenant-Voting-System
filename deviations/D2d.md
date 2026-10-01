# D2d — WP-9.4 Alert panel: stopped at pre-check
status: blocked (no code change)
branch: improvements/D2d
reason: the card lists only frontend files (new panel, mount in the analytics tab, new test) and says to "surface the existing alert thresholds' current state". No endpoint exposes that state:
 - backend/analytics.py `evaluate_alerts()` / `build_window_stats()` run only inside `_send_alerts()` (background flush) and the result is emailed, never returned.
 - GET /superadmin/analytics/summary has no `alerts` field; AnalyticsPanel.jsx has nothing to read.
 Building the panel against an invented response shape would be guessing, and adding the field means editing backend/analytics.py (and its tests), which is outside this card's FILES list (runbook rule: STOP and report).
proposed follow-up (needs the owner's go-ahead): card D2d-be, backend/analytics.py + new backend test only: add `alerts` to the summary = `[{kind, level, metric, value, threshold}]` from `evaluate_alerts(build_window_stats(...), _alert_config())`, org-scoped and read-only, empty list when healthy. Then D2d as written: map each state to Healthy / Warning / Critical labels, read-only (no POST).
HUMAN checks pending: decide whether to approve D2d-be.
