# PERF-M1 — Collector, listener, rings
- Date / session: 10 Oct 2026
- Files changed: backend/perf_metrics.py, main.py (motor_kwargs)
- Tests added (names): tests/test_perf_metrics.py
- Gates: see PERF-M7.md (full results)
- Overhead check (same DB calls with metrics on/off): pass (test_disabled_means_client_options_are_the_historical_ones)
- Deviations recorded (DEVIATIONS.md ids): none
- Not done / HUMAN items outstanding: H3 (real-driver events confirmed only by the load test)
