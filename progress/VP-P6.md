# VP-P6: copy sweep, docs, seeds, final regression
source: VETTING_PANEL_CHANGE_GUIDE section 9, row P6
status: copy/docs/seed fixes made; final regression not run (no network in the sandbox)

changes:
- Copy sweep (decision 1, risk "stale wording"): fixed every UI string that still said
  "commissioner(s)" for the application vote, in SecurityPanel.jsx (approval-policy note
  and option labels), ApplicantPortal.jsx (all three policy descriptions), SuperAdminDashboard.jsx
  ("Commission votes:" → "Panel votes:"), SharedAdminPanels.jsx (audit label "Commission vote
  cast" → "Panel vote cast"), FinancialControllerDashboard.jsx and ClosedNotice.jsx. Left
  `is_commissioner`-flag copy alone (toggling commissioner status, roster/contact-change text) —
  that role still exists for everything outside vetting.
- docs/VOTING_CONSENSUS_SETUP.md: rewritten. It predated the `approval_policy` setting
  entirely (said "no policy toggle exists"); now documents the real toggle, the panel/
  commissioner split across the two vote types, and updated the seed-data walkthrough to
  say panel hat instead of commissioner login for application votes.
- docs/FINANCE_CONSOLIDATION.md: "Commission portal only votes" → Vetting Panel; "votes need
  the Commission session" → panel hat; "which commissioner voted how" → "which panelist".
- backend/seed_advanced_scenarios.py: real bug, not just copy — `cast_commissioner_vote`
  was posting to `/admin/applications/{id}/vote` with a plain commissioner token, which P2
  now rejects (that route requires the `vetting` role). Added a switch-hat step before any
  `endpoint="vote"` call; `endpoint="vote-remove"` is untouched since removal voting stayed
  commissioner-only (decision 3). Updated the surrounding comments/docstring to match.
- Left alone (deliberately, not stale): `is_commissioner` DB field/flag, `CommissionerVote`
  pydantic model, `commissioner_id` body field, route names (`commissioner_vote`,
  `/admin/applications/{id}/vote`), and backend code comments that use "commission vote" as
  shorthand for the approval event rather than claiming commissioners cast it — renaming
  those is an API/internals change the guide scopes as a copy sweep, not a contract change.

not done:
- Final regression (frontend build, frontend/backend test suites) — no network in this
  sandbox.

HUMAN: npm run build, frontend tests, backend pytest (including test_vetting_panel_p1.py
and test_vetting_panel_p2.py); run seed_test_data.py + seed_advanced_scenarios.py end to
end and confirm the nomtest panel votes resolve through the switch-hat step; grep the repo
yourself for "commissioner vote" / "Full consensus" to confirm nothing was missed.

## Follow-up: any admin on the panel
See progress/VP-LINK-COMMISSIONER.md. Tests: backend/tests/test_vetting_panel_any_admin.py, frontend PanelHatButton.test.jsx
and VettingScreens.render.test.jsx. Two existing tests updated (panel-link now answers for all admin roles).
