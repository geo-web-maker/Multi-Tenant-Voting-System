# VP-P4: Commission slimming, outcomes feed, overseer copy
source: VETTING_PANEL_CHANGE_GUIDE section 9, row P4
status: built, not deployed; frontend not compiled and backend tests not run (no network in the sandbox)

changes:
- backend main.py: GET /admin/vetting-outcomes (commission only): resolved applications with final_reason, decided_at, position title. No votes, tallies or split.
- CommissionDashboard.jsx: voting removed (castVote, deny box, tally, policy copy, approval-policy fetch). Pending/Approved/Denied/Removed become one Outcomes tab fed by the outcomes endpoint. Live Results, Student Changes, Contact Changes, Reset OTP (Chair/Deputy), Platform and Official Document unchanged. Legacy tab ids map to Outcomes.
- OverseerDashboard.jsx: pending shows "x of y voted"; the approve/deny split appears only after resolution.
- SuperAdminDashboard.jsx: FinalReasonEditor on denied and removed applications (POST /superadmin/applications/{id}/final-reason, max 500 chars).

not done here:
- Commission-side tests for the outcomes feed (guide section 10) still to be written.
- Overseer "Commissioners" summary card unchanged (guide keeps it as a commissioner figure).
- The superadmin Commission tab copy still says "commissioners vote" in places (P6 sweep).

HUMAN: npm run build, frontend tests, backend pytest.
