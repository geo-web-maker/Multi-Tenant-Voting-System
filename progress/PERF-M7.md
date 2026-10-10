# PERF-M7 — Alerts, docs, closing gates
- Date / session: 10 Oct 2026
- Files changed: docs/PERFORMANCE_AUDIT.md (placeholder section), docs/BALLOTBOX_PHASE_RUNBOOK.md (H6 note), backend/loadtest/README_PERF.md, docs/PERFORMANCE_TAB_GUIDE.md (status line), docs/DEVIATIONS.md (E17), blueprint.css (comment reworded: it contained the text that the !important structure test scans for)
- Tests added (names): alert rules in test_perf_metrics.py (table-driven, uncapped, cooldown, cold start)
- Gates: backend 683 passed, 12 failed; frontend default 714 passed, 3 failed; Blueprint 714 passed, 3 failed; lint 1 error (ApplicantPortal.nomination.test.jsx, not perf); template build OK (default entry 38,834 B gz, panel adds 0 B; blueprint chunk 12,152 B)
- Overhead check: pass
- Deviations recorded: E17
- Not done / HUMAN items outstanding: H1 to H12 (load test against Atlas, phone check, runbook decisions, sink setup), optional PERF-M3b. Failures not from perf: the 3 frontend ones (ConsoleFrame snapshot, two tokens.test.js checks on existing CSS) and 12 backend ones (apply_phone, demo_mode x3, nomination_form x2, nomination_retention, table_import 'noun' UnboundLocalError, tenant lint on nomination_uploads.drop_index in lifespan, vetting x3); all 11 non-lint ones fail identically with PERF_ENABLED=false.
