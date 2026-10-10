# PERF-M5 — Persistence and sinks
- Date / session: 10 Oct 2026
- Files changed: backend/perf_sinks.py, requirements.txt (asyncpg==0.30.0), .env.example
- Tests added (names): tests/test_perf_sinks.py (14)
- Gates: see PERF-M7.md (full results)
- Overhead check (same DB calls with metrics on/off): pass
- Deviations recorded (DEVIATIONS.md ids): none
- Not done / HUMAN items outstanding: H8 to H12; the optional PERF_TEST_POSTGRES_URL integration test needs a real database
