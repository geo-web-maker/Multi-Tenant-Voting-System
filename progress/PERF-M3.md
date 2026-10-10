# PERF-M3 — Attribution through the tenant wrapper
- Date / session: 10 Oct 2026
- Files changed: backend/tenant_db.py, perf_metrics.py
- Tests added (names): test_perf_metrics.py::test_attribution_inside_a_request_not_outside; tests/test_perf_attribution.py (verify-identity, verify-otp, vote-bulk attributed ops equal the opcount oracle on tenant collections)
- Gates: see PERF-M7.md (full results)
- Overhead check (same DB calls with metrics on/off): pass
- Deviations recorded (DEVIATIONS.md ids): none
- Not done / HUMAN items outstanding: PERF-M3b (optional) not built: unattributed share is only measurable under load (H3)
