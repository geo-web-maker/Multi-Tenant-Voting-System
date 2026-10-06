# Vetting Panel: frontend audit fixes

Round 1: C1, H1, H2, H3, M1, M2, M3, M5, M7 (copy), M9, M10, L1, L4.
Round 2 (this round):
- Naming: "Chairperson" and "Deputy Chairperson" everywhere users see a role (dashboards, audit titles, tie-break copy, superadmin buttons, backend tie-break errors).
- M4: VettingDashboard uses outer-wrap + dashboard-shell + shared TabBar (counts), usePolling, usePersistedTab.
- M6: "View as" on active panelist rows. Backend: /superadmin/view-as accepts role "vetting" (student_id carries the PM- id); the read-only token skips the external confidentiality gate.
- M8: PATCH /superadmin/vetting-panel/{id} (affiliation, phone, access end; while vetting is open only a later date is allowed); Chairperson badge, minimum-3 and frozen hints; schedule dialog warns when the panel is below 3 or a tie only the superadmin could resolve.
- L2: overseer shows panel size, "Panel split ... decided by tie-break". L3: panel votes show names. L5: Chairperson sees "N applications are tied" (GET /admin/panel-link -> tie_waiting). L6: final-reason editor has counter, unsaved marker, follows reloads. L7: resolved tab has search, registration number, decision date.

Still open (needs your decision): H4 consent wording and what an external panelist receives; M11 (guide row 7 says commissioners decide student changes, UI says Financial Controller decides).
Verified: eslint clean, vitest 280/280, vite build, backend 347 pass. 8 backend tests fail identically on the untouched Phase 5+6 baseline (test_vetting_panel_p1 deactivated-token, three in test_vetting_panel_p2, four in test_voter_fields).
