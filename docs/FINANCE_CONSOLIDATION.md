# Candidate payments moved to the Financial Controller

**Rule:** clearing payments is done in the Financial Controller portal; application votes are cast by the Vetting Panel. One person may hold the Financial Controller and commissioner roles together, and each role acts through its own login (and, for voting, the panel hat — see `VETTING_PANEL_CHANGE_GUIDE.md`).

## What changed
- `POST /admin/applications/{id}/finance-clear` and `/finance-reject` now accept the **Financial Controller only**
  (body: `financial_controller_id`, `reason`; reject needs a reason). Commissioners, IT admins, overseers and the
  superadmin get 403. The superadmin keeps `/superadmin/applications/{id}/force-finance-clear` (still logged).
- One person may hold both roles. Each role has its own login and portal, so the session says which system is
  acting: payments need the Financial Controller session, votes need the panel hat. When a dual-role
  person clears or rejects a payment, the audit entry is marked `decider_also_commissioner`.
- Audit entries for clear/reject now carry the receipt URL, fee and payment method.
- Financial Controller portal: **Voter payments** and **Candidate payments** tabs, each with Pending/Approved/Denied views.
  Denying a voter request now needs a reason, same as rejecting a candidate payment.
- The Financial Controller sees receipts but not which panelist voted how.
- `set-finance-commissioner` returns 410; "Set/Clear Finance" buttons and the "Finance" badge are gone.
- Unchanged: the upload bypass (the one path that skips the controller).

## Rollout
1. Deploy backend + frontend.
2. `python migrate_retire_finance_commissioner.py` (dry run: lists holders, waiting applications, and orgs with no
   Financial Controller), then rerun with `--apply`.
3. Applications that were waiting on a commissioner need no data change: they appear in the controller's
   **Candidate payments → Awaiting** list.
