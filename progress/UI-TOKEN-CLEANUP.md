# Token fallbacks and hex ratchet

- **Date:** 12 October 2026
- **Status:** Source changes applied; automated/browser verification incomplete where noted.

## Changed

Converted raw colours in App.jsx, ClosedNotice.jsx, ViewAsBanner.jsx, BallotBox.jsx and icons.jsx to `var(--token, #hex)` fallbacks. CandidateStatusPortal retains its separate palette (guide D9), PhaseBanner has a theme map, HelpPanel keeps WhatsApp brand green, and print outputs remain fixed for parity. Hex count under hexRatchet test rules is now 294; ceiling lowered to 294.

## Verification

Static count checked with Python; frontend tests/builds unavailable.
