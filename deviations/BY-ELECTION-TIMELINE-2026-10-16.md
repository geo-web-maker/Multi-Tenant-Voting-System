# By-election timeline inside the By-elections tab (2026-10-16)

Request: the by-election timeline (voting start and end) is set and shown inside the By-elections tab, not only in the general Timeline tab.

## Added
- `GET /superadmin/by-elections/{round_id}/schedule`: the round's voting window, state (unscheduled / upcoming / active / closed) and seconds until start or end.
- `POST /superadmin/by-elections/{round_id}/schedule`: sets only the voting window (start, end, optional timezone and reason). Other phases are carried over unchanged, then the existing `set_phase_schedule` does the validation, early-end reason rule, audit entry and side effects.
  - 404 for Round 1 or an unknown round, 403 for non-superadmin, 409 if certified or not the current round, 400 if end is not after start or the end is already past.
- `ByElectionSchedule` card in `ByElectionsPanel.jsx` under each ordered by-election: status text, opening/closing countdown, date-time inputs in the election timezone, confirm dialog, early-end reason prompt.
- Audit labels: `by_election_created`, and `phases_scheduled` now reads as "By-election schedule set" for non-Round-1 rounds.
- Tests: 2 backend (`test_post_election_plan.py`), 4 frontend (`ByElectionsPanel.schedule.test.jsx`).

## Not changed
- Voting-open rules, vote path, `/vote-status` and `/election-status` shapes are untouched. No extra database reads on voter paths.

## Still open
- The voter-page banner still does not say "By-election" (separate suggested change, awaiting approval).
- Visual check of the new card in both templates at 1100 px and 390 px.
- Full backend run shows `test_backup_jobs.py::test_ttl_index_is_180_days` failing only when run with the whole suite (passes alone, also fails with the new tests deselected). Not caused by this change.

## Follow-up: tie gating and shared phone numbers
- By-election scheduling now requires the round to link to a recorded tie (`parent_tie_id`); otherwise 409.
- New `GET /superadmin/shared-contacts` (409 `no_tie` until a tie exists): groups numbers held by 2+ voters, flags possible duplicate records, and recommends per voter: delete duplicate, remove contact (when another number exists), change contact, or keep. Delete is offered only while the roster is unfrozen, and never for voters who voted or hold an admin role.
- New `POST /superadmin/shared-contacts/acknowledge` records a shared number as legitimate (household, guardian) with a reason of 10+ characters; audit label `shared_contact_acknowledged`.
- The By-elections tab shows the card only when ties exist. Change/remove contact reuse `/admin/students/edit`; delete voter reuses `/superadmin/students/remove`, so freeze and approval rules still apply.
- Tests: 5 backend, 2 frontend added.

## Follow-up 2: shared numbers in Student Changes, and voter-code split in the SMS tab
- Shared phone numbers moved to `GET /admin/shared-contacts` and `POST /admin/shared-contacts/acknowledge` (superadmin and IT admin; the `/superadmin/` prefix is superadmin-only). No longer tied to a tie: it is now a general roster check, also shown in the By-elections tab when ties exist.
- Statistics block: shared numbers, unresolved, accepted, voters sharing (and % of roster), possible duplicates, largest group, sharing voters who already voted, admin-role holders sharing.
- New `SharedContactsPanel`, shown under the Student Changes screen (superadmin) and the Edit tab (IT admin). IT admin's delete is a removal request through `/it-admin/students/request-remove`.
- SMS tab: new card "Voter codes: first message and resend". Settings `otp_split_enabled`, `otp_first_ego_pct`, `otp_resend_ego_pct` (saved through `PUT /superadmin/sms-budget`, with a reason, audited). When on, each first code and each resend picks EgoSMS first with that percentage chance (random per message, so the ratio holds over many messages, not exactly in any small batch); the other provider remains the fallback. When off, the fixed policy is unchanged (first EgoSMS, resend MamboSMS). Presets include "First 30:70, resend 100:0".
- Cost estimate (`otpSplitCost.js`): voters, resends per voter and the saved per-part prices give messages and UGX per provider; a provider that carries messages but has no price makes the total "not set".
- Budget counting and the vote path are unchanged.

## Follow-up 3: shared numbers removed from the By-elections tab
- The shared-phone-numbers panel now lives only under Student Changes (superadmin) and the Edit tab (IT admin). It was removed from the By-elections tab, which keeps the tie list and the by-election timeline only.
- The panel's list is wrapped in the shared `ScrollList` (60% of the viewport height), so a long list scrolls inside the panel instead of lengthening the page.
