# SMS-1 — First-send/resend routing

- **Date:** 16 October 2026
- **Status:** Source changes prepared; automated runtime verification is blocked by the current environment.

## Implemented
First OTP prefers EgoSMS; subsequent per-round sends prefer MamboSMS with EgoSMS fallback. `OTP_RESEND_VIA_MAMBO=0` restores configured resend routing. Fallback is logged.

## Checks
Routing regression tests were added, but they could not be executed because backend test collection is blocked by missing `mongomock`.

## HUMAN checks still required
On provider test accounts, verify actual billing, MTN/Airtel delivery, sender ID, fallback behavior, throughput, and provider dashboard counters before live use.
