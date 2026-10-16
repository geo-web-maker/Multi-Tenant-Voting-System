# Post-Election Plan — Deviations and Verification Limits

**Date:** 16 October 2026

## Specification decisions left open

- The source specification calls for the committee to lock a tie-break policy before the next election but does not provide the institution's constitutional rule. The implementation does not invent one. A second tie in a by-election is rejected for automatic by-election creation and must be handled under the committee's recorded rule.
- By-election eligibility is required at creation time and is selectable as `all_registered` or `round1_voters`. The committee must decide which applies; no default is asserted to be constitutionally correct.
- The SMS plan depends on external facts (MamboSMS actual OTP pricing, sender-ID requirements and MTN/Airtel delivery/throughput). No provider account was accessed and those facts remain unverified.

## Optional behavior not adopted

- The spec's optional read-triggered `is_open=false` safety-net write was not added. Scheduled-window logic is used for Results state/release rather than mutating election configuration as a side effect of a read.

## Environment / acceptance blockers

- Backend test collection is blocked by missing `mongomock` (`ModuleNotFoundError` in `backend/tests/conftest.py`).
- Frontend test, lint and build commands are blocked because `vitest`, `eslint` and `vite` are absent. Package registry DNS/network failure prevented installation.
- No real browser/phone, staging, provider or production checks were run.
- Static checks passed (backend Python syntax compilation; parser of 268 frontend JS/JSX/TS source files with no syntax diagnostics; Node syntax check on `frontend/src/storage.js`). These are not substitutes for tests or a build.
