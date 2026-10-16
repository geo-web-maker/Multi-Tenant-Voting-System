# BE-1 — Round-aware ballot data and counts

- **Date:** 16 October 2026
- **Status:** Source changes prepared; automated runtime verification is blocked by the current environment.

## Implemented
Added tenant-scoped rounds/ties, per-round voter markers, candidate snapshots, round-filtered tallies/voter roll, OTP limiter separation, round-bound sessions/codes, and V2 round-bound hash events with V1 verification compatibility.

## Checks
Round isolation, hash-chain and snapshot regressions were authored. Backend syntax compilation passed; pytest could not collect without `mongomock`.

## HUMAN checks still required
Run full dummy vote cycle and compare Round 1 counts before/after; verify round-specific eligibility, exactly-once voting, and hash chain separately for both rounds.
