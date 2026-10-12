# Remaining button-style exceptions

- **Date:** 12 October 2026
- **Status:** Source changes applied; automated/browser verification incomplete where noted.

## Changed

`LEGACY_BUTTON_FILES` contains 20 entries. Tier A `App.jsx`, `ApplicantPortal`, `BallotBox`, `LoginErrorActions` and `OtpInput` preserve the existing voter/applicant forms, OTP and voting interaction surfaces. `CandidateStatusPortal`, `Results`, `ColumnMapper`, `VoterRegisterSearch`, `VoterList` and `TabBar` are standalone/public status, mapping, export, search/list or navigation controls. `DemoInbox`, `FloatingHelpMenu`, `HelpPanel`, `HelpTriggers`, `MobileMoneyNumber`, `PanelHatButton` and `UIFeedback` use demo-specific, icon, floating/help, input or compact utility affordances. `ResetOtpLimitsPanel` and `SharedAdminPanels` keep their small inline `linkBtn` actions intentionally.

## Verification

All exceptions were checked against the current inline declaration guard; full visual review is still open.
