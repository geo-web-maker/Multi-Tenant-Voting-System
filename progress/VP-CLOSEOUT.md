# Vetting close-out

When the enforced vetting window has ended, pending finance-cleared applications are closed out once.
Nothing is approved or denied just because people did not turn up.

- **Clear majority of the votes that were cast** (3 approve and 1 deny, with someone not voting): the application is decided. The audit entry is the normal approval or denial plus `closeout: true` and the counts. `decided_by_closeout` is stored. The live approval policy is not re-applied: a strict policy that was still waiting for every vote does not leave the application pending forever.
- **Tie, or no votes:** not guessed. The application is marked `vetting_closed_undecided` ("Vetting closed without a decision") with the counts. The Chairperson, still able to open the panel and not the applicant, decides from the Vetting Panel (`POST /admin/applications/{id}/closeout-decision`). If no such Chairperson can, the superadmin decides (`POST /superadmin/applications/{id}/closeout-decision`) and the panel is told to wait. The decision is logged (`application_closeout_decided`, superadmin audit only, same as a tie-break) and the outcome entry records that it was a close-out.
- Votes of panelists whose access ended with the phase still count. Dropping them at the moment the window ends would quietly change the result.
- A later resweep does not reopen a close-out. Finance reversing a clearance clears the close-out flags so the application can be cleared again. A payment cleared after the window has already ended is closed out immediately, including a rejection that Finance reinstates straight to cleared.
- The Chairperson's own dashboard says when one or more applications are waiting. IT admin and the overseer see the stage, not the votes.

## Background sweep and unenforced windows
- A background loop (`_vetting_closeout_loop`, started in `lifespan`) runs the close-out for every organisation every 60 seconds, so nothing waits for someone to open a screen. `VETTING_CLOSEOUT_SWEEP_SECONDS` changes the interval; `0` turns it off (the on-demand call still works). It is safe on several instances: every write is guarded by an atomic status/flag check.
- One failing application or organisation is logged and retried on the next pass; it does not stop the others.
- The window counts as ended when the vetting phase has an end date in the past, **enforced or not**. This matches panelist access, which already ends at the phase end date either way. A phase with no end date never closes out.

## Template fit (Blueprint)
- Vetting action buttons were 30 px tall. Blueprint now lifts them to the 44 px floor (R10) with `.vp-actions button` and `button.vp-switch` in `blueprint.css`; phones stack them full width. The default template is untouched (R1). Classes are plain (no `bp-`) so default JS stays clean. Guarded by `frontend/src/vettingTapTargets.test.js`.
- Register: E15 (action targets) and E16 (new chrome strings) added to `docs/DEVIATIONS.md` and `docs/BLUEPRINT_TEMPLATE_GUIDE.md` section 7.
- Not run: frontend tests, lint, `check_template_build.sh`, or a browser check (no network in the sandbox).
