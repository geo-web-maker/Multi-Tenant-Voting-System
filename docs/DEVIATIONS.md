# Implementation of IMPROVEMENT_GUIDE.md (second pass)

This section is the second pass, done with the guide in hand. The WP-12 review further down is the first pass and is unchanged.

## Final results
| Check | Result |
|---|---|
| Backend `pytest -q` | 275 passed, 0 failed (was 250; +6 ported dormant tests, +19 new) |
| Frontend `npm test` (Vitest) | 63 passed, 0 failed (was 18) |
| `npm run lint` | 0 errors, 0 warnings |
| `npx vite build` | succeeds. App entry chunk 94 KB (32 KB gzip). First-load JS in total is about 320 KB raw / 107 KB gzip: React 192 KB, axios 37 KB, app 94 KB. |
| Manual browser checklist, real phone, 3G, Turnstile | NOT done |

## Done, by guide section
| Guide | What changed | Tests |
|---|---|---|
| 2.1 | `.gitignore` now covers `*.env`, `.env.*` and keeps `!*.env.example`. Added `backend/.env.example` and `frontend/.env.example` (names only). | verified with a throwaway git repo |
| 3.1 | Lazy-loaded every dashboard, Results, ApplicantPortal, CandidateStatusPortal, VerifyCertificate, HeatmapOverlay and BallotBox. BallotBox chunk is prefetched when the voter reaches the OTP step. HeatmapOverlay only mounts for superadmins. Removed the unused `AdminDashboard` import from `App.jsx`. Vendor chunks for react and axios. | build |
| 3.2 | Splash is held back 500 ms. If `/health` answers first the app opens with no splash. Cold-start copy is unchanged. | 2 (mutation-checked) |
| 3.3 | `usePolling` got a minimum gap (burst guard) and failure backoff with jitter. `/election-status` now polls every 60 s. `/candidates` is fetched only when the sample-ballot guide opens. Results polls every 10 s while open, 60 s otherwise, and stops when certified. The raw `setInterval` polling in TurnoutBreakdown, SharedAdminPanels (3), SecurityPanel, ContactChangesQueue and ContactChangePanel now goes through the same code. | 5 |
| 3.4 | Short-TTL cache of the raw `election_config`, `election_phases` and `security_settings` documents, invalidated at every write site. Indexes for `settings`, `positions`, `candidates`, `voters(org_id, student_id)`, created inside try/except so an index problem cannot stop boot. `/positions` sends `Cache-Control` with `Vary: X-Org-Slug` (admin requests get `no-store`). GZip is registered before CORS. | 8 + 5 |
| 3.5 | CORS `max_age` 600 to 7200. | 1 |
| 3.6 | axios timeout and GET retry (details below). | 11 |
| 4.3 | Login errors map to guidance with a next step. | 10 |
| 4.4 | Picker is restricted to JPEG/PNG/WEBP/GIF (the PDF mismatch). Size and type are checked on selection. A `useRef` lock stops double submit. | 5 |
| 4.8 | #1 inline OTP feedback with lockout countdown (field no longer cleared on a wrong code). #2 "already cast" counts as success, and a lost response triggers a status check. New `GET /vote-status`. #3 "Still sending" after 6 s. #4 double-tap lock on the vote. #5 resend keeps the chosen phone. #6 pasted "123 456" works. #7 `autocomplete="one-time-code"`. #8 unconfirmed-delivery note. #9 SMS failure wording. | 9 + 4 + 3 |
| 5.1, 5.2 | First-API timing ignores `/health` and failures. `an:netfail` skips `/health` and is limited to one per route per 30 s. | 4 |
| 5.4 | API counters are stored with seg `public` or `staff`. Readers already matched `{seg, "all"}`, so old data still shows. | 3 |
| 5.6 | Dashboard button text is `#fff` (dark-mode contrast). | none (visual) |
| 5.7 | The staff login is tagged `admin_login`. | 2 |
| 7 | Deleted `frontend/usePolling.js` (identical copy) and `backend/test_flows.py` (see below). | |

## Deviations from the guide (and why)
- **axios timeout is 30 s, not 20 s.** The guide itself notes a 30-50 s cold start; the retry covers a first attempt that times out. Votes get 60 s and uploads 120 s. Votes and all other writes are never retried. `/health` opts out of retry.
- **Splash grace is 500 ms, not the guide's 1.5 s.** 1.5 s would delay the cold-start copy. A warm server never sees the splash either way.
- **GZip `minimum_size` is 1024, not 500, and is not honoured for small bodies.** The existing `@app.middleware("http")` layers pass the body down as a stream, and Starlette always compresses streamed bodies. Harmless (about 20 bytes of overhead on tiny responses). A test documents it.
- **The settings cache does not cover vote casting.** `assert_voting_open` still reads `election_config` straight from the database, so closing or certifying takes effect immediately for ballots.
- **Entry-chunk target of 250 KB** is met by the app chunk (94 KB) but not by total first-load JS (about 320 KB). React alone is 192 KB.
- **`/positions` admin requests get `no-store`** so an admin sees an edit at once. Public requests get `max-age=15`.
- **`/vote-status` does not compare the one-time jti.** A successful vote clears `vote_jti`, so the same token must still be able to ask. It checks signature, expiry, tenant and student, and reveals only that voter's own `has_voted`.

## Finding: tests that never ran
`backend/test_flows.py` was not a stale duplicate. It held 6 tests missing from `tests/test_flows.py` (application window, fee snapshot at submit time, SMS on approval). Pytest only collects `tests/`, so they never ran. They are now merged and pass, and the root copy is removed.

## Not done
| Guide | Item | Why |
|---|---|---|
| 4.1 | Phase banner and Apply now button | UI design work; needs a look on a 360 px screen |
| 4.1a | Help button on Apply | same; needs a real-phone check of the keyboard and bottom-right overlap |
| 4.1b | Confirm before "Vote Now" signs an admin out | not started |
| 4.2 | Results page "not started" state | not started |
| 4.3 | Register link and support button on the error modal | messages are in; the modal has no action buttons |
| 4.4 | Step labels, upload percent, validate-all-fields, reuse uploaded files, error mapping table | only gaps 1-3 done |
| 4.5, 4.6 | Dead-click fix and `data-track` names | not started |
| 4.8 | Auto-verify on the 6th digit (optional) | skipped on purpose |
| 3.3 | ApplicantPortal polling changes, single `/public/bootstrap` | polling done (B5); `/public/bootstrap` done (E1, `progress/E1.md`) |
| 3.6 | Typing placeholder re-render, image resize on the phone | not started |
| 5.3 | `usable_ms` | needs backend histogram changes |
| 5.6 | Chart time zone, default range, load-test formula | not started |
| 6.x | Insights card, tagged-link builder, tracking-since, alert panel | not started |
| 7 | `pnpm` lockfiles, Procfile/Dockerfile/railpack, `demo_results_mode*.py` | your call, not mine |

## HUMAN steps
1. Check git history for `backend.env`, `frontend.env`, `backend/loadtest.env` and rotate anything that was ever committed or shared (guide 2.1).
2. Version-skew check before touching analytics code (guide 1.2).
3. Confirm the new indexes in Atlas (hand-made ones with the same keys are simply reused).
4. Schedule a `GET /health` keep-warm ping during the election window (guide 3.2).
5. Test on a low-end Android on Slow 3G: splash, OTP paste/autofill, vote with the network dropped, apply uploads, Turnstile set to "on".
6. Deploy note: `SETTINGS_CACHE_TTL_S` (default 5, 0 disables) is a new optional env var.

---

# Review of the WP-12 implementation (IT admin voter-register export)

## Final results
| Check | Result |
|---|---|
| Backend `pytest -q` | 250 passed, 0 failed (35 are the new `tests/test_voter_export.py`) |
| Frontend `npm test` (Vitest) | 18 passed, 0 failed |
| `npx vite build` | succeeds (entry chunk 711 KB raw / 206 KB gzip; WP-2 lazy loading is NOT done) |
| `npm run lint` | 0 errors, 0 warnings (was 27; see below) |

## What was wrong and is now fixed
| Area | Problem found | Fix |
|---|---|---|
| `main.py` list_commissioners | Stray `it_admin_export_mode` line injected into the commissioner roster | Removed; normalisation moved to `list_it_admins` where it belongs |
| `main.py` export endpoint | Was a stripped-down version: no `_csv_safe` / `_export_row`, no formula-injection protection, no enabled voter fields, no sort, no rate limit, `None` names exported as "None", text typing not forced in xlsx, no `too_many_rows` audit row, generic filename, no nosniff/Pragma | Replaced with the playbook 12.4.1 / 12.4.5 implementation |
| `main.py` set mode | Setting `none` used `$unset`, losing who/when; | Always `$set` with set_by / set_at |
| `main.py` turnstile | `_turnstile_verify` was called but not defined (NameError the moment captcha is on) | Added (True / False / None contract the tests expect) |
| `ITAdminDashboard.jsx` | `<VoterRegisterExport />` and `<VoterList />` were adjacent JSX with no wrapper (syntax error) | Wrapped in a fragment |
| `registerExport.js`, `ExportModeControl.jsx`, `VoterRegisterExport.jsx` | Thin stubs: no confirm for Full, no error display, no double-click lock, blob errors unreadable, filename ignored, object URL revoked immediately, no aria-pressed, no white active text | Rewritten per playbook 12.5 |
| `SuperAdminDashboard.jsx` | No confirm for Full, no toast / error handling, no saving state | Added per 12.5.3 |
| Tests | No WP-12 tests existed; no frontend runner | Added `test_voter_export.py` (T1-T19) and Vitest (WP-0) with 3 test files |

## Stale existing tests (updated, reason stated)
- `test_flows.py`: two tests posted `phone` but the model requires `phones` (list).
- `test_flows.py::test_schedule_timezone...`: indexed `phases[2]`; the list now has 5 phases, so look up "voting" by name.
- `test_flows.py::test_add_path_regression...`: add now returns 409 for an existing registration number (both endpoint and approval path). Test now asserts the 409 and still asserts vote + roles are untouched.

## Environment note
`pymongo` newer than 4.10 breaks `mongomock` (`add_update() got an unexpected keyword argument 'sort'`), which made 4 voter_fields tests fail. Tests pass with `pymongo==4.10.1`. requirements.txt was not changed.

## Not done / not verified
- Only WP-12 is present in this zip. WP-1 to WP-9 and WP-H are not implemented (no GZip, no lazy loading, no retry.js, etc.).
- Manual checklist H1-H13 (real browser): not verified.
- The zip has no .git, so the playbook's git-based checks (env files untouched, history) could not run. I never opened any `.env` file.
- HUMAN: `backend.env`, `frontend.env`, `backend/.env`, etc. were inside the zip you shared; rotate anything sensitive if that zip went anywhere beyond you.

## Lint cleanup (27 -> 0)
Correction: my earlier note said the 27 were all unused variables. That was wrong: 17 were unused variables, 2 were fast-refresh errors, 1 was a set-state-in-effect error, and 6 were hook-dependency warnings.
| Kind | Where | What I did |
|---|---|---|
| Unused variables / dead code | `SuperAdminDashboard.jsx`, `AdminDashboard.jsx` | Removed never-referenced code (old import handlers, `filteredVoters`, `turnout`, `stage1-3`, `duplicateIds`, `th`/`td`, `importFile`/`importing`/`voterSearch2` state). Where a setter is still called, kept it and dropped only the unused value |
| Real hook fix | `UIFeedback.jsx` | Moved `dismissToast` above `toast` and listed it as a dependency (no suppression) |
| Mount-only effects | Commission, FinancialController, ITAdminStudentEdit, Overseer, SecurityPanel | Targeted `eslint-disable-next-line` with a reason. Adding the fetchers as deps would refetch on every render |
| Hook exported next to component | `AdminHeader.jsx`, `RevealGroup.jsx` | Same file-level disable `UIFeedback.jsx` already used |
| set-state-in-effect | `RevealGroup.jsx` | Targeted disable: the effect reads a ref, which is not reactive |
Not browser-tested: the deleted code was confirmed unreferenced by lint, and build + 18 Vitest tests pass, but no UI click-through was done.

---

# Custom tasks (owner-requested, outside the runbook lanes)

## CUSTOM-1 · Voter statistics restored in the superadmin Voters section
| Item | Detail |
|---|---|
| Why | The Voters tab became a table only; total voters, voters per section and SMS amount were no longer visible. |
| Backend | New `GET /admin/voters/stats` (superadmin only): totals, voted, phone coverage, per-enabled-field registered/voted, SMS headline numbers taken from the existing `get_sms_usage`. Counts only. |
| Frontend | `VoterStats.jsx` (new); `SuperAdminDashboard.jsx` Voters tab split into Register / Statistics / SMS sub-tabs. SMS shows live EgoSMS/MamboSMS balances (existing `/admin/sms-balance`, existing `SmsProviderCard`, previously fetched but never rendered) plus `SmsUsageTile`. |
| Tests | +2 backend, +2 frontend. Totals now backend 295 / frontend 256. |
| Caveat | Rebuilt from current data; git has no earlier copy of the removed statistics. Details in `progress/CUSTOM-1.md`. |

## E1 · Single `/public/bootstrap`
| Item | Detail |
|---|---|
| Spec | The improvement guide (§3.3 item 5) is not in the zip, and the playbook says only "out of scope unless the human asks". Built from the runbook card: one request, org-scoped, cache keyed by org, no secrets or voter data. |
| Backend | `GET /public/bootstrap` composes the existing branding, status and positions handlers. The auth guard (`PUBLIC` GET list in `_is_public`) blocked it until it was added there; a test now covers it. |
| Frontend | `bootstrap.js` with a 10 s shared request and a fallback to the old endpoints. Used by `App.jsx` (mount) and `ApplicantPortal.jsx` (mount). |
| Existing test changed | `ApplicantPortal.apply.test.jsx`: the shared API mock now also answers `/public/bootstrap` with the same data, and the bootstrap cache is reset in `beforeEach`. Reason: startup no longer calls the two old endpoints. No assertion was changed or removed. |
| Not changed | Polling still calls `/election-status` and `/positions` directly. |


---

# Per-phase records (merged by F3)
Generated from `progress/*.md` and `deviations/*.md`. The originals stay in those folders.

## progress/A1.md
A1 — WP-7a Phase banner + Apply now
status: done
branch: improvements/A1
tests added: src/phase.test.js (16), src/components/PhaseBanner.test.jsx (11)
results: backend 293 passed · frontend 213 passed (186 + 27) · lint 0 · vite build OK
change: new pure `phase.js` (`derivePhase(status)`, `formatCountdown(ms)`); new `PhaseBanner.jsx` replaces the yellow ClosedNotice strip on the voter login card (not on the admin login path). Login form and the admin link are untouched. `App.jsx`: import swapped and one mount line (`onApply` -> `setView("apply")`).
rules used: voting ended or master switch off -> voting_closed; voting open -> voting_open; voting not started -> apply_open if applications open, else voting_soon. Unknown status shape -> no banner. Countdown (1 s clock) only for voting opening, shown in apply_open and voting_soon. Dates in the election zone (Africa/Kampala fallback) via fmtZoned.
decisions to confirm: (1) apply_open also states when applications close and when voting opens; (2) master switch off shows "Voting is closed" even if the schedule says open; (3) while voting is open, an open applications window does not change the banner (card: applications take priority only while voting has not opened).
note: ClosedNotice.jsx is unchanged and still used by other screens; `votingNoticeText` is no longer imported in App.jsx.
HUMAN: at 360x640 the banner is under 25 % of screen height and the login form is above the fold (apply_open is the tallest state: title, 2 lines, countdown, 44 px button).

## progress/A2.md
A2 — WP-7b Help button on Apply
status: done
branch: improvements/A2
tests added: src/helpItems.test.js (8), src/components/HelpPanel.apply.test.jsx (7), src/App.helpFab.test.jsx (1)
results: backend 293 passed · frontend 186 passed (159 + 16 + 11 for the follow-up below) · lint 0 · vite build OK
change: new pure `helpItems.js` (`helpItemsFor(page)`, `showHelpFab(view, step)`); `HelpPanel` takes `page` and filters its entries; `FabTrigger` takes `compact` and also goes icon-only under 400 px; `App.jsx` passes `page={view}` and uses `showHelpFab` (FAB now also on Apply, still not on voter step 3).
files touched beyond the card's literal list: components/HelpTriggers.jsx (FabTrigger lives there; lane A owns HelpPanel/FabTrigger).
assumptions to confirm against the §4.1a table (I only had the two rules in the card):
 - Sample Ballot: voter only. Nomination Fees: apply only (this REMOVES Fees from the voter menu, as the card says).
 - Check Voter Register, Election Timeline and the support entries stay on both pages.
 - The "Code not arriving?" note is voter only (it talks about SMS codes).
 To change any of these edit the two lists in helpItems.js and its test.
follow-up (branch improvements/A2-extras, added at the owner's request): the rest of the WP-7b playbook text.
 - Fade on focus: FabTrigger fades (opacity 0, taps ignored, hidden from assistive tech) while an input, textarea or select has focus; it stays visible while the Help menu is open so it can be closed. Applies to every FAB instance (voter login too), not only Apply. Checkboxes, radios, files and buttons do not trigger it.
 - data-track ids: `help-fab` (the button), `help-timeline`, `help-fees`, and `help-support` on every support entry (generic, per-reason and configured contacts). Ids live in `HELP_TRACK` in helpItems.js and fit the tracker's ^[a-z0-9_-]{2,40}$ rule.
 - Support reasons: on Apply, the generic "Contact Support" entry is replaced by two `buildSupportLink` links, "Application problem" and "Payment" (message ends "(never send your code)"). Voter keeps the single generic link. Configured per-reason contacts (Branding) still show on both pages. With no support number configured, neither page shows the generated links.
 - Existing test changed for a stated reason: HelpPanel.apply.test.jsx no longer expects "Contact Support" on Apply (it now expects the two reasons).
 - Tests added: 11 (helpers, tracking ids, reason links, fade behaviour).
still not done: the ~96 px bottom padding on the apply container (ApplicantPortal.jsx is lane B; do it in the B1 branch).
HUMAN checks pending: on a 360×640 phone, the `?` does not cover the submit button or the open keyboard on the Apply page (the fade should hide it while a field is focused; check it comes back after); check the table assumptions above; confirm the two WhatsApp messages read well to an applicant.

## progress/A5.md
A5 — WP-7e remainder: action buttons on the login error modal (card A5)
status: done
branch: improvements/A5
commits: see git log on this branch
tests added: frontend/src/components/LoginErrorActions.test.jsx (8)
results: backend not touched (baseline 287 passed) · frontend 117 passed, 0 failed · lint 0/0 · build ok (entry chunk 95.8 KB)
baseline at branch cut: backend 287 · frontend 109
deviations:
 - The card says the function is `loginErrorGuidance`; in this code it is `loginGuidance` (src/loginErrors.js). Same job, so it was used as is.
 - src/loginErrors.js (not in the card's FILES) got one additive field, `support: true`, on the rows whose message points to support (ID not found, already voted, SMS failed). Existing results are unchanged (all 10 loginErrors tests still pass; unknown text still returns exactly {title, message}).
 - The playbook's "contact-change link" has no voter-facing page in the front end (ContactChangePanel is admin-only), so "Request a contact change" opens the support chat with a prefilled message ("no phone number on file ... please add one"). Replace the href if a real form is added later.
 - The "check the voter register" link is a button that closes the error and opens the same register search as the Help menu.
notes: new src/components/LoginErrorActions.jsx renders under the modal text: ID not found -> register button + Contact support; name mismatch -> register button; already voted -> Contact support; no phone -> Request a contact change; SMS failed -> Contact support; unknown or object detail -> no buttons. Support and contact-change links appear only when the organisation has a support contact configured (same source the OTP screen uses). Prefilled messages never ask for the code. App.jsx: the error modal stores `action`/`support` and renders the component for non-success modals; admin-path errors and every other modal pass neither, so they are unchanged. Buttons are at least 44 px tall.
HUMAN checks pending: on a phone, try an unknown registration number: the register search opens from the button and the WhatsApp link opens with the prefilled text; check the modal fits 360x640 with both buttons plus "Try Again".

## progress/B-all.md
Lane B — B1 + B2 + B3 + B4 (done in one pass, one file)
status: done
branch: improvements/B-all (cut from improvements/A1)
tests added: src/applyErrors.test.js (19), src/imageResize.test.js (7), src/components/ApplicantPortal.apply.test.jsx (15)
results: backend 293 passed · frontend 254 passed (213 + 41) · lint 0 · vite build OK (ApplicantPortal chunk 22.4 KB)
B1: `applyErrors.js` (`mapApplyError`, `missingFields`, block reasons); one validation pass listing every missing field, `aria-invalid` + red border, focus/scroll to the first; registration number trimmed + uppercased before sending. Tests A1, A2, A3, A5.
B2: step labels (n/4, or n/3 with no photo), upload percent via `onUploadProgress`, `beforeunload` while busy, slow-connection note, Cancel via `AbortController`, fields inert (`fieldset disabled`), button `aria-busy`. Tests A4, A7 + percent, beforeunload, slow, cancel.
B3: `uploadedRef` keyed by name+size+lastModified, so a retry skips files already uploaded; "Re-attach your receipt" when a draft is restored. Tests A6, A8.
B4: `imageResize.js` (`fitWithin`, `resizeImage`), one call site in the upload helper; any failure returns the original.
mutation-checked: removing the upload cache, the busy guard, the fieldset, the uppercase, the abort signal, or the click guard each makes tests fail.
deviations: see deviations/B-all.md (message table missing from zip; submit_blocked reasons not recorded yet; api:slow not emitted).
HUMAN: real Android Chrome incl. HEIC/AVIF phones (B4); check the Help `?` does not cover the submit button (96 px bottom padding now added to the apply container, as A2 asked); wording of the error messages vs the guide's §4.4 table; Cancel and the percent on a throttled 3G connection.

## progress/B5.md
B5 — WP-4 remainder: ApplicantPortal polling (card B5)
status: done (already on usePolling; guard test added, no source change)
branch: improvements/B5
commits: see git log on this branch
tests added: frontend/src/components/ApplicantPortal.polling.test.js (3)
results: backend not touched (baseline 287 passed) · frontend 109 passed, 0 failed (see end of this file for the final run) · lint 0/0
baseline at branch cut: backend 287 · frontend 106
deviations: none to the code. Pre-check `grep -n "setInterval" ApplicantPortal.jsx` finds nothing: the portal already polls `/election-status` and `/positions` every 20 s through the shared `usePolling`, and pauses once `submitted`. The new test locks that in (no raw setInterval, uses usePolling, stops when submitted).
notes: one thing for the owner to decide, not changed here: the polling callback wraps each request in `.catch(() => null)`, so it never throws and `usePolling`'s failure backoff (delay doubles up to 4x) never triggers when the server is struggling. The page keeps its last values, which is safe, but it keeps asking every ~20 s. Making the callback throw when BOTH requests fail would enable the backoff; this is a behaviour change, so it was left alone.
HUMAN checks pending: none required.

## progress/CUSTOM-1.md
CUSTOM-1 — Restore voter statistics in the superadmin Voters section (custom task, not a runbook card)
status: done
branch: improvements/custom-voter-stats
commits: see git log on this branch
tests added: backend/tests/test_voter_stats.py (2) · frontend/src/components/VoterStats.test.jsx (2)
results: backend 295 passed, 0 failed · frontend 256 passed, 0 failed · lint 0/0 · build not re-run
baseline at branch cut: backend 293 · frontend 254
deviations: see "Custom tasks" in DEVIATIONS.md. This task is outside the A–F lane plan; it was requested by the owner directly.
what: the Voters tab (superadmin) now has three sub-tabs. Register = the existing paginated VoterList (unchanged). Statistics = total voters, voted / not voted, turnout %, phone on file / no phone, SMS sent, SMS budget left, and registered + voted per enabled voter field (e.g. hostel, faculty). SMS = live provider balances (EgoSMS, MamboSMS, from the existing GET /admin/sms-balance and the SmsProviderCard that was left unused in SuperAdminDashboard) above the existing SmsUsageTile (budget, delivery, routing), reused not copied.
files: backend/main.py (new GET /admin/voters/stats, superadmin only, counts only), frontend/src/components/VoterStats.jsx (new), SuperAdminDashboard.jsx (sub-tab switcher in the Voters tab).
note: git history holds no earlier version of these statistics (the oldest commit already has the table-only tab), so they were rebuilt from the current data, not restored from a diff. Wording and layout may differ from what you remember.
HUMAN checks pending: open Voters as superadmin on a real org and confirm the numbers match what you expect (especially which voter field you consider the "section"); org with no voter fields shows the "no per-section breakdown" line.

## progress/D1a.md
D1a — §5.3 usable_ms (card D1a)
status: done
branch: improvements/D1a
commits: see git log on this branch
tests added: backend/tests/test_analytics_usable.py (6) · frontend/src/analytics.usable.test.js (4)
results: backend 287 passed · frontend 72 passed, 0 failed · lint 0/0 · build ok (entry chunk 94.5 KB)
baseline at branch cut: backend 281 · frontend 68 (all existing analytics tests still pass)
deviations: card FILES excludes App.jsx / VoterLoginInputs.jsx, so "login form interactive" is detected inside analytics.js: markUsable() fires when input[name="voter-reg-no"] is in the DOM (checked at init, then a MutationObserver that disconnects on match or after 20 s). Entry pages other than voter login never match and send no usable_ms (backend treats missing/0 as "no sample").
notes: usable_ms = performance.mark('usable').startTime (ms since navigation start), sent inside the existing once-per-session perf event; backend clamps 0..60000, stores histogram `us.<bucket>` (USABLE_EDGES = 500,1000,2000,3000,5000,8000) and returns usable_p50/usable_p95 on summary `perf` and `network_perf` rows. Not yet shown in the dashboard (lane D2). If perf is sent before the form renders, usable_ms is 0 and ignored for that session.
HUMAN checks pending: on a real phone, load the voter login and confirm a `usable` entry in DevTools Performance (performance.getEntriesByName('usable')).

## progress/D1b.md
D1b — WP-9.3 backend: tracking_since (card D1b)
status: done
branch: improvements/D1b
commits: see git log on this branch
tests added: backend/tests/test_analytics_tracking_since.py (6)
results: backend 281 passed (baseline at cut 275 + 6 new) · frontend not touched (68 passed at cut) · lint n/a · build n/a
baseline at branch cut: backend 275 · frontend 68
deviations: none. Lookup is best-effort (any DB error -> null) so a failed lookup can never 500 the summary; this also keeps the existing FakeColl in test_analytics.py (no sort()) working unchanged.
notes: query is {org_id} only (not limited to the summary window/seg/device), sorted by day asc, limit 1; served by the existing unique (org_id, day, ...) index prefix. Field is top-level `tracking_since` ("YYYY-MM-DD" or null) on GET /superadmin/analytics/summary. `compare` is unchanged.
HUMAN checks pending: none for this card. Dashboard line is D2e (depends on this merge).

## progress/D2a.md
D2a — §5.6b, 5.6c Chart time zone + default range (card D2a)
status: done
branch: improvements/D2a
commits: see git log on this branch
tests added: frontend/src/chartTime.test.js (8) · frontend/src/components/AnalyticsPanel.range.test.jsx (3)
results: backend not touched (baseline 287 passed) · frontend 106 passed, 0 failed · lint 0/0 · build ok
baseline at branch cut: backend 287 · frontend 95
deviations: card FILES names UsageCharts.jsx, AnalyticsPanel.jsx and pure helper files; all three used (new helper: src/chartTime.js). Daily buckets keep their plain UTC date on purpose: they are whole-UTC-day totals, so shifting them into another zone would label them with a day they do not cover. Only hourly buckets (real instants) are converted. The note under the chart now says so.
notes: bucketLabel(t, bucket, tz): "2026-09-14T21:00:00Z" renders 15/9 00h in Africa/Kampala (23:30 UTC on day X shows as day X+1 in EAT). TimelineChart takes a `tz` prop (default Africa/Kampala); AnalyticsPanel passes the election zone. defaultRangeDays(tracking_since, now): 1 ("Last 24 hours") when the earliest recorded day is today (UTC), else 7; applied once on the first summary load and never over a range the user picked. The default is judged from `tracking_since` (D1b), not from the timeline points.
HUMAN checks pending: on a day-one election, open Site Usage and confirm it opens on "Last 24 hours" with hour labels matching Kampala time; on an older org it opens on 7 days.

## progress/D2b.md
D2b — §5.6d Load-test advice formula (card D2b)
status: done
branch: improvements/D2b
commits: see git log on this branch
tests added: frontend/src/loadTestAdvice.test.js (6) · frontend/src/components/AnalyticsPanel.loadAdvice.test.jsx (1)
results: backend not touched (baseline 287 passed) · frontend 95 passed, 0 failed · lint 0/0 · build ok (entry chunk 94.5 KB)
baseline at branch cut: backend 287 · frontend 88
deviations: the card names only a helper and its call site. The panel has no eligible-voter count, so a small "Eligible voters" number box was added in the Reliability section (local state, nothing saved). The existing "observed peak concurrency x 1.5" sentence is unchanged.
notes: src/loadTestAdvice.js: expected_peak = voters x share_in_busiest_hour x (avg_session_seconds / 3600); (1500, 0.40, 180) -> 30, range 1.5x to 2x -> 45 to 60. Busiest-hour share comes from summary `hour_of_day` (max / total, unaffected by the time-zone shift); average session from `totals.average_session_seconds`. Missing, zero, negative or non-numeric input returns 0 and no line is shown (never NaN). Share is capped at 1.
HUMAN checks pending: type the real eligible-voter count on the Site Usage page and sanity-check the suggested user range before setting it in backend/loadtest/locustfile.py.

## progress/D2c.md
D2c — WP-9.1 + 9.2 Insights card + tagged-link builder
status: done
branch: improvements/D2c
tests added: src/insights.test.js (9), src/linkBuilder.test.js (19), src/components/D2c.components.test.jsx (6)
results: backend 293 passed · frontend 159 passed (125 + 34) · lint 0 · vite build OK
change: pure `insights.js` (`buildInsights`) and `linkBuilder.js` (`buildTaggedLink`, five channels, tag rule ^[a-z0-9_-]{2,40}$); `InsightsCard.jsx` and `LinkBuilder.jsx` mounted in AnalyticsPanel (insights under the alert panel, link builder under Traffic channels).
choices to review (not specified by the card):
 - Vote→Apply sentence = application-form sessions as a share of voter-login sessions (funnel step values). It is a ratio of two separate counts, not a same-session conversion, and the wording says so.
 - "3G/unknown" share uses network labels `3g` and `unknown`; the load figure is the highest p95 of those two (merged p95 cannot be recomputed from the summary).
 - Reason codes are shown with underscores turned into spaces (e.g. "not on roll"), because the friendly label map lives in FunnelPanels.jsx, outside this card's FILES.
 - The builder's host defaults to the host of the page the admin is on; pass `host` if the voter site differs from the admin site.
HUMAN checks pending: read the five sentences against a real summary once; confirm the host in the generated link is the voter-facing one.

## progress/D2d-be.md
D2d-be — alerts field on the analytics summary (backend half of D2d)
status: done
branch: improvements/D2d-be
tests added: backend/tests/test_analytics_alerts_summary.py (6)
results: backend 293 passed (baseline 287 + 6) · frontend untouched
change: `current_alerts(org)` in backend/analytics.py reuses `build_window_stats` + `evaluate_alerts` + `_alert_config`; `GET /superadmin/analytics/summary` now returns `alerts: [{kind, level, metric, value, threshold}]` (empty list = healthy). Org-scoped, read-only, `routes` deliberately not exposed.
deviations: edits backend/analytics.py, outside the original D2d FILES list, with the owner's go-ahead (see deviations/D2d.md).
HUMAN checks pending: none
next step: D2d (frontend panel) reads `summary.alerts`.

## progress/D2d.md
D2d — WP-9.4 Alert panel (card D2d)
status: done
branch: improvements/D2d-panel (the original improvements/D2d branch only holds the earlier blocked note)
commits: see git log; backend half merged first as D2d-be
tests added: frontend/src/alertState.test.js (3), frontend/src/components/AlertPanel.test.jsx (5)
results: backend 293 passed · frontend 125 passed (117 + 8) · lint 0 · vite build OK
change: new `alertState.js` (pure state/label mapping), new `AlertPanel.jsx` (read-only), mounted in AnalyticsPanel.jsx above the funnels. Labels: Healthy / Warning / Critical; hidden when the backend sends no `alerts` field.
HUMAN checks pending: look at the panel once in the real analytics tab, and confirm the Warning colour (`--warning` falls back to #d98e04) suits your theme.

## progress/D2e.md
D2e — "Tracking of funnel steps started on <date>" line (card D2e, §1.2)
status: done
branch: improvements/D2e
commits: see git log on this branch
tests added: frontend/src/components/AnalyticsPanel.trackingSince.test.jsx (3)
results: backend not touched (baseline 287 passed) · frontend 88 passed, 0 failed · lint 0/0 · build not re-run (one JSX line)
baseline at branch cut: backend 287 · frontend 85
deviations: none
notes: reads `tracking_since` ("YYYY-MM-DD" or null) from GET /superadmin/analytics/summary (added in D1b). The line sits just above the Apply funnel panel and is shown only when the value is non-null; date is formatted in the election time zone via fmtZoned with the time part stripped.
HUMAN checks pending: open Site Usage as superadmin on an org with data and confirm the line reads correctly; an org with no analytics rows shows no line.

## progress/D2f.md
D2f — §5.5 Failure-reason labels (card D2f, verify-first)
status: done (already complete, no code change)
branch: improvements/D2f
commits: see git log on this branch
tests added: none
results: not re-run (no code change) · baseline backend 287 · frontend 88
baseline at branch cut: backend 287 · frontend 88
deviations: none
notes: pre-check compared every literal reason code passed to `set_reason(request, "<code>")` (41 call sites) and every `ApiError(..., reason=...)` in backend/*.py against `REASONS` in frontend/src/components/FunnelPanels.jsx. 25 distinct codes found, 0 without a label. Unknown codes already fall back safely: `reasonLabel()` shows `HTTP <n>` for `http_<n>` and the raw code otherwise. Labels with no literal call site (`budget`, `captcha_required`, `guess_lock`) are kept; they are most likely set from helper modules and are harmless.
HUMAN checks pending: none

## progress/E1.md
E1 — Single /public/bootstrap (card E1, §3.3 item 5)
status: done
branch: improvements/E1 (cut from integration after Merge B-all and Merge CUSTOM-1)
commits: see git log on this branch
tests added: backend/tests/test_public_bootstrap.py (5) · frontend/src/bootstrap.test.js (4)
results: backend 300 passed, 0 failed · frontend 260 passed, 0 failed · lint 0/0 · vite build OK
baseline at branch cut: backend 295 · frontend 256
deviations: see "E1" in DEVIATIONS.md
change: new GET /public/bootstrap returns {branding, status, positions}, each built by the SAME handler as /superadmin/branding, /election-status and /positions (shapes cannot drift, org_query scoping and the settings cache are reused). Added to the public GET allowlist in `_is_public`. New frontend/src/bootstrap.js `fetchBootstrap()` shares one request between App (branding + election status on mount) and the Apply form (positions + status on mount); if the endpoint fails it falls back to the three original endpoints. The old endpoints are untouched. Polling (60 s status, 20 s Apply refresh) still uses the original endpoints on purpose.
HUMAN checks pending: on a real deploy, open the voter page and the Apply page in DevTools > Network and confirm one /public/bootstrap request at startup instead of /superadmin/branding + /election-status (+ /positions); confirm branding and the closed/open notice still render for a second organisation (X-Org-Slug).

## progress/F1.md
F1 — data-track names (WP-7f, §4.5/4.6)
status: partial (code done; tests NOT run, sandbox has no network so `npm ci` could not install)
branch: improvements/F1
tests added: frontend/src/components/MobileMoneyNumber.copy.test.jsx (3) · frontend/scripts/check_data_track.py (static check)
results: check_data_track.py -> "17 static, 3 dynamic labels / data-track labels OK". vitest, eslint, vite build NOT RUN.
change: added data-track to login-submit, login-switch-admin, otp-resend (App.jsx); otp-submit (OtpInput.jsx); apply-position-<n>, apply-payment-method, apply-proof-upload, apply-fee-link (x2), apply-submit (ApplicantPortal.jsx); ballot-submit (BallotBox.jsx). Payment number is now one tap-to-copy button (apply-copy-number, min-height 44px, "Tap to copy") with a document.execCommand('copy') fallback.
deviations: results-tab-* not added (Results has no tabs; nav-results already exists). export-* labels already existed.
HUMAN checks pending: run `cd frontend && npm ci && npm test && npm run lint && npx vite build`; check payment number tap-to-copy on a real phone.

## progress/F2.md
F2 — Housekeeping (WP-H, §7)
status: done (no deletions, by owner decision)
branch: improvements/F2
decisions (owner): pnpm vs npm lockfiles = not sure, keep both · live host (Procfile / Dockerfile / railpack) = not sure, keep all · demo_results_mode*.py = not sure, keep both
change: none. Nothing removed because the owner could not yet confirm which files are live.
open items for the owner: confirm the package manager and the live host, then run a "diff before delete" removal with tests before and after.

## progress/WP-6b.md
WP-6b — Stop the typing placeholder re-rendering App (card A4)
status: done (revised: animation kept, extracted)
branch: improvements/WP-6b (revision committed on integration)
commits: see git log
tests added: frontend/src/App.placeholder.test.jsx (2)
results: backend not re-run (frontend-only; baseline 275 passed) · frontend 68 passed, 0 failed · lint 0/0
baseline at branch cut: backend 275 · frontend 66
deviations: human chose the playbook's alternative option: typing animation kept, effect + 4 states moved into frontend/src/components/VoterLoginInputs.jsx (renders the two voter inputs); App owns no animation state
HUMAN checks pending: React DevTools Profiler shows no App re-renders while idle on the login screen

## progress/WP-7c.md
WP-7c — Confirm before "Vote Now" signs an admin out (card A3)
status: done
branch: improvements/WP-7c
commits: see git log on this branch
tests added: frontend/src/App.voteNow.test.jsx (3)
results: backend not re-run (frontend-only change; baseline 275 passed) · frontend 66 passed, 0 failed · lint 0/0 · build ok (entry chunk 93.9 KB)
baseline at branch cut: backend 275 · frontend 63
deviations: none (playbook 1455-1457 read; wording and tests match)
HUMAN checks pending: on a phone, signed in as admin, tap "Vote Now" from Results/Apply -> native confirm appears; Cancel keeps you signed in

## progress/WP-7d.md
WP-7d — Results page states (card C1)
status: done
branch: improvements/WP-7d
commits: see git log on this branch
tests added: frontend/src/resultsState.test.js (9) · frontend/src/components/Results.state.test.jsx (4)
results: backend not touched (baseline 287 passed) · frontend 85 passed, 0 failed · lint 0/0 · build ok (entry chunk 94.5 KB)
baseline at branch cut: backend 287 · frontend 72
deviations: none. Card FILES = resultsState.js (new), Results.jsx, new tests. Uses existing /election-status fields (voting_phase, voting_opens_at); no backend change.
notes: states by priority: not_started (voting_phase 'not_started' and not open) > embargoed (results_released === false) > no_votes (turnout and candidate votes both 0) > live (open) > closed. not_started shows "Voting opens <date in Africa/Kampala>. Results will appear here live." and hides the banner (so no "Live Tallying"), turnout, candidate list, voter roll, turnout breakdown and the print button. no_votes shows "No votes yet." and hides the roll and breakdown. embargoed and live/closed render as before.
HUMAN checks pending: view /results on a phone before the voting window opens (message and date) and with voting open but zero ballots.

## deviations/B-all.md
# Lane B (B1+B2+B3+B4) — deviations and open points
1. **§4.4 message table was not in the zip** (IMPROVEMENT_GUIDE.md is absent; the playbook only says "the §4.4 table"). `mapApplyError` wording is therefore mine, built from the real backend strings: server text is kept where it already tells the person what to do (404 not on register, 400 name mismatch, 403 window closed). Compare with §4.4 and edit `applyErrors.js` + its table test if the wording differs.
2. **`submit_blocked` reasons are computed but not recorded.** `trackStep(flow, step)` takes no reason and `backend/analytics.py` `CLIENT_STEPS` is a fixed vocabulary. The portal calls `trackStep('apply','submit_blocked', reason)` with `missing_field` / `bad_file_type` / `too_large` (fixed labels, never values); the third argument is ignored today. Recording it needs `analytics.js` and `analytics.py` (outside lane B), as a separate card.
3. **`api:slow` is never emitted** (nothing in `api.js` dispatches it, and `api.js` is outside the lane). The portal listens for it and also shows the "Slow connection" note after 10 s of busy as a fallback.
4. **Registration number is sent trimmed and in capitals** as the card says. This is safe: `/apply/check-eligibility` and `/apply` match with `get_forgiving_filter` and `/apply` stores the voter's canonical `student_id`. It does not contradict `regNo.js`, which is about keys the client sends back for its own lookups.
5. **Step count is 3 (not 4) without a photo**: labels read (1/3)..(3/3) so the denominator is honest.
6. **Resize skips GIF** (a canvas redraw would drop the animation) as well as non-images and files under 1 MB. It also keeps the original when the JPEG is not smaller.
7. Removed the `uploadingProof` state: the step label replaces "Uploading receipt…".
8. Fields are made inert with `<fieldset disabled>`; the position and payment-method rows are divs, so their click handlers also check `uploading`. Cancel and the status note sit outside the fieldset so they stay usable.

## deviations/D2d.md
# D2d — WP-9.4 Alert panel: stopped at pre-check
status: blocked (no code change)
branch: improvements/D2d
reason: the card lists only frontend files (new panel, mount in the analytics tab, new test) and says to "surface the existing alert thresholds' current state". No endpoint exposes that state:
 - backend/analytics.py `evaluate_alerts()` / `build_window_stats()` run only inside `_send_alerts()` (background flush) and the result is emailed, never returned.
 - GET /superadmin/analytics/summary has no `alerts` field; AnalyticsPanel.jsx has nothing to read.
 Building the panel against an invented response shape would be guessing, and adding the field means editing backend/analytics.py (and its tests), which is outside this card's FILES list (runbook rule: STOP and report).
proposed follow-up (needs the owner's go-ahead): card D2d-be, backend/analytics.py + new backend test only: add `alerts` to the summary = `[{kind, level, metric, value, threshold}]` from `evaluate_alerts(build_window_stats(...), _alert_config())`, org-scoped and read-only, empty list when healthy. Then D2d as written: map each state to Healthy / Warning / Critical labels, read-only (no POST).
HUMAN checks pending: decide whether to approve D2d-be.

# Final acceptance (F1-F3)
- F1 (data-track names): code merged; `check_data_track.py` passes. Vitest, eslint and vite build were NOT run in the sandbox (no network for `npm ci`). Run them locally.
- F2 (housekeeping): nothing removed. Owner was unsure which of pnpm/npm lockfiles, Procfile/Dockerfile/railpack and `demo_results_mode*.py` are live, so all were kept.
- Last verified totals (E1): backend 300 passed, frontend 260 passed, lint 0/0, build OK. F1 adds 3 frontend tests that are unverified.
- HUMAN: rotate secrets from the earlier zip's env files; run the card HUMAN checks (phone layouts, Slow 3G, Atlas indexes, `/health` keep-warm ping).

# Blueprint Console (BP-T0 … BP-T10) — final table
Source: BLUEPRINT_TEMPLATE_GUIDE.md §7 and §13; per-card notes in progress/BP-*.md.

| Item | Status |
|---|---|
| Switch | `VITE_UI_TEMPLATE=blueprint`, build time, per deployment; default UI unchanged (G1) |
| Frontend tests | 584 pass default and 584 pass with the template on (G3); lint 0/0 (574 at T10 + 10 dialog tests) |
| Bundle | default entry 34,996 B gz; blueprint entry 35,628 B gz; blueprint chunk 11,191 B gz (budget 30 KB) |
| Hex ratchet | 394 literals ceiling (`src/hexRatchet.test.js`) |
| E1–E13 (guide §7) | as written in the guide; no further deviations recorded in T0–T10 |
| E14 dialogs (post-T10 audit) | No browser dialogs remain: Vote Now sign-out confirm (`App.jsx`) and Finance "Reverse clearance" use the in-app dialog. **Default template: dialog looks exactly as before**; only invisible behaviour was added (`role=dialog`/`alertdialog` + accessible name, Escape, focus start/restore, Tab wrap). **Blueprint**: visible title, card look, 48 px pill buttons, stacked on phones, via N10-N14 and the dialog rules in `blueprint.css`; `.modal-content` modals get the accent top edge. `UIFeedback.dialog.test.jsx` fails if a native `window.confirm/alert/prompt` is reintroduced |
| E15 Vetting actions (post-T10) | The Vetting Panel's Approve/Deny rows (vote, tie-break, close-out decision, Retry) and every \"Switch to Vetting Panel\" / \"Switch back to …\" button are inline-styled 30 px controls. **Default template: unchanged pixels.** **Blueprint**: lifted to the 44 px floor (R10) by `.vp-actions button` / `button.vp-switch` in `blueprint.css`, stacked full-width on phones. Plain class names (no `bp-`) so default JS stays clean. `vettingTapTargets.test.js` guards it |
| E16 New chrome strings (R4 exception, post-T10) | New copy for the any-admin panel link and the vetting close-out: \"Switch to Vetting Panel\", \"Switch back to <role>\", \"Overseer access paused\", \"Vetting closed without a decision\", \"Vetting closed. Votes cast: N approve, N deny.\", \"Waiting for the Chairperson to decide.\", \"Waiting for the superadmin to decide.\", \"Decided by the Chairperson / the superadmin after vetting closed.\", \"Decided when the vetting window closed.\", and the Chairperson's \"Vetting closed on N application(s) without a decision.\" banner. Same text in both templates; the existing strings are untouched |
| E17 Performance tab (PERF-M6, superadmin only) | New tab in the Platform group after Site Usage, plus new copy (R4 exception): \"Performance monitoring is off.\", \"Collecting data, give it a minute.\", \"No data yet\", \"Database load\", \"Voter headroom\", \"About N voters per minute before the cap\", \"Where the load comes from\", \"Slow commands\", \"Unattributed: N% of operations come from collections that are not tied to a route.\", \"Pause collection\", \"Reset to defaults\", \"Check these against your Atlas plan\" and the sink line \"History: <sink> · last write … · N queued\". Same text in both templates. **Default template: no existing screen changes**; only the new tab and the two lines in `SuperAdminDashboard.jsx`. **Blueprint**: buttons and tap targets reach 44 px, form fields 48 px, via plain classes `.perf-btn`, `.perf-actions button`, `.perf-field`, `.perf-check` in `blueprint.css` (screen block, no priority overrides, no `bp-` strings in default JS). Colours are tokens only; charts are one inline SVG helper, no new library. `perfTapTargets.test.js` guards the rule; `PerformancePanel.test.jsx` covers the states and that polling stops while the page is hidden |
| T10 additions | focus ring extended to summary/role=button/tabindex; reduced motion for meter bars; README section |
| Known behaviour change | IT Admin `force_denied` badge shows as negative (shared status map) instead of warn (BP-T8c) |
| Left bare on purpose | AdminDashboard.jsx (legacy, unrendered), FinalReport and `.print-only` blocks, CandidateStatusPortal print sheet, `icons.jsx` dotGreen, PhaseBanner THEME (replaced in blueprint) |
| HUMAN, pending | keyboard/screen-reader walk, 200 % zoom, print PDF comparison, device checks, Tier B "ok" columns, 18×4 mockup comparison, D1–D9 owner sign-off |

# Legacy (no-org) tenant removed
- `org_query()`, `org_stamp()` and `_oq()` no longer fall back to an unscoped filter / `org_id=None`; they raise 400 via `require_org()`. The same applies to `get_commissioner_count`, `_resolve_position_title`, `_position_fee`, `_create_candidate_from_application` and the contact-change apply/remove paths.
- `REQUIRE_ORG_CONTEXT` is removed: a missing `X-Org-Slug` is always a 400, except the token/id-scoped and superadmin-bootstrap prefixes in `ORG_EXEMPT_PREFIXES`.
- `/verify-admin`: only the superadmin may sign in without `X-Org-Slug`; IT admin, financial controller, overseer, commissioner and the rest are refused before any lookup.
- `/admin/reset-election` and `backup.snapshot_before_destructive()` are single-tenant only (`all_tenants` removed). `wipe_election_data.py` now requires `--org-slug` and only deletes that org's documents (`ip_send_stats`, a tenant-less per-IP throttle, is no longer wiped by it).
- Seed and load-test scripts no longer create or hit a "legacy/no-org" dataset.
- Before deploying: open Superadmin > Security > **Legacy data check** (it also runs on demand with "Check again"). It lists documents that belong to no organization, including the old `default` SMS counter and OTP-limit keys, and lets the superadmin **assign** each group to an organization or **remove** it. `migrate_assign_org.py <org_id>` still works for a bulk backfill.
- Legacy data check: `GET /superadmin/legacy-data`, `POST /superadmin/legacy-data/assign`, `POST /superadmin/legacy-data/delete` (superadmin only; exempt from the X-Org-Slug requirement because it spans tenants). Removal needs the typed phrase `DELETE LEGACY DATA` and a successful B2 safety snapshot (`backup.snapshot_legacy_data`) when backed-up collections are involved; otherwise nothing is deleted. `vote_events`, `audit_checkpoints` and `roster_ledger` are remove-only (their hash chain / anchors include the org). Tenant-less system events (organization created, unauthenticated 401s) are now stamped `scope: "system"` in `audit_log` so they are not reported as legacy. Not run in the sandbox: pytest and vitest. New tests: `backend/tests/test_legacy_data_check.py`, `frontend/src/components/LegacyDataPanel.test.jsx`.
- NOT run in the sandbox (no network for pip): the backend test suite. `py_compile` passes on every changed file; run `pytest` locally. New tests: `backend/tests/test_no_legacy_tenant.py`.

# Security / SMS save fixes
- `PUT /superadmin/security-settings` re-swept every open application on EVERY save (the form posts all fields, so `approval_policy` was always in `updates`). It now only runs when the policy actually changed, and a failure there no longer turns an already-saved change into an error: the response is 200 with a `warning` string.
- Security panel: each form (security, SMS routing, SMS budget) now has its own reason box; they used to share one value, and the budget form had no box of its own. After any failed or timed-out save the panel re-reads the server, so it never shows stale values for a change that was applied.
- New tests: `backend/tests/test_security_save.py`. Not run in the sandbox (no network for pip).

# Nomination form, phase N1 (settings, public read, template upload)
- New settings doc `nomination_form` (per org): `enabled, required, title, instructions, template_file{url,filename}, accepted_types, max_mb`. Defaults: disabled, required, PDF only, 5 MB.
- `GET /nomination-form` is public (added to the `_is_public` GET set). Disabled returns only `{"enabled": false}`.
- `PUT /superadmin/nomination-form` is a **partial update** (fields left out are unchanged), needs a `reason` (>=3 chars), returns 400 "Nothing to change.", audits `nomination_form_changed` with old/new, and calls `invalidate_settings`. Template URL must be `https://`; clear it with `clear_template_file: true`.
- `POST /superadmin/nomination-form/template` (multipart: `file`, `reason`) uploads the blank PDF/DOCX as a public Cloudinary raw file (up to 10 MB), stores `{url, filename}`, audits `nomination_form_template_uploaded` (no URL in the log).
- Helpers reused by N2: `_sniff_document(content, accepted)` (magic bytes; DOCX must contain `[Content_Types].xml` and `word/document.xml`, no `vbaProject.bin`) and `_safe_filename`.
- No new collection yet (`nomination_uploads` is N2). `tdb`/lint unchanged. Tests: `backend/tests/test_nomination_form.py` (21). Full backend suite: 497 passed (476 + 21).
- NOT verified: the `cloudinary.uploader.upload(..., resource_type="raw", public_id="<id>.<ext>")` call against the real service (tests monkeypatch it). Try one real template upload after deploying.

# Nomination form, phase N2 (signed forms to a private B2 bucket)
- Completed forms are stored in a **private Backblaze B2 bucket**, not Cloudinary (they carry signatures and IDs). New module `backend/nomination_storage.py` is the only code that knows about B2 (`put_object`, `presigned_get_url`, `delete_object`, `is_configured`), so switching store later is a one-file change.
- **Separate credentials**: `NOMINATION_B2_ENDPOINT / _KEY_ID / _APPLICATION_KEY / _BUCKET_NAME` (documented in `backend.env`). The backup `B2_*` values are never used or borrowed. The client is built on first use, so missing values cannot stop the app booting; uploads then return 503 and send a critical alert.
- `POST /apply/upload-document` (public, added to `PUBLIC_PATHS`; same IP upload rate limit and `applications` phase gate as the photo upload). Needs the form enabled (else 404). Size limit is the org's `max_mb`; type is decided from the real bytes with `_sniff_document` against the org's `accepted_types`. Key: `nomination-forms/<org_id>/<random 128-bit id>.<ext>`. Returns only `{upload_id, filename, kind, bytes}`: no key, no link.
- New tenant collection `nomination_uploads` (`tenant_db.TENANT_COLLECTIONS`, legacy check list): `upload_id, key, filename, kind, bytes, sha256, status (pending|attached), uploaded_at, student_id, position_id, attached_at, application_id`.
- `POST /apply` takes optional `nomination_upload_id`. Form enabled + required + no id -> 400 before anything is stored. An id is claimed atomically (pending -> attached, same org, uploaded within 24 h), so one upload serves one application; unknown, stale, foreign and reused ids all get the same 400. If the application insert fails the claim is released. The application stores `nomination_form: {upload_id, filename, kind, bytes}` (or `null`); the storage key stays in `nomination_uploads`. Audit `application_submitted` gains `nomination_form` (filename). Form disabled: an id is ignored and not consumed.
- `presigned_get_url` is ready (5-minute cap, forces download with a sanitised filename) but **no route uses it yet**; the staff read-back route is N3.
- Not done in N2: front-end upload step (later card), cleanup of uploads never attached to an application (they sit in `nomination_uploads` as `pending`; the bucket lifecycle rule is the backstop), per-election lifecycle/retention, and org-deletion cleanup of the bucket.
- Tests: `backend/tests/test_nomination_upload.py` (15). Full backend suite: 512 passed (497 + 15).
- NOT verified: real calls to B2 (`put_object`, presigned GET) are faked in tests; the presigned URL is only checked offline for expiry and forced download. Do one real upload and download after setting the env values.
- **Bucket setup (human)**: create a NEW private bucket (do not enable Object Lock if forms must ever be deleted early); create an application key limited to that bucket with read/write/delete files; add a lifecycle rule to hide/delete files under `nomination-forms/` after the retention you choose.

# Nomination form, phase N3 (staff read-back and role shaping)
- `GET /admin/applications/{id}/nomination-form` returns a presigned link (5 min, forced download, `Cache-Control: no-store`) plus `filename / kind / bytes / expires_in`. It never returns a storage key. Roles: `vetting`, `superadmin`, `overseer`; `commission` only once the application is resolved (same rule as `list_applications`); IT admin, financial controller and anyone else get 403. The route sits under the existing `/admin/applications` panel prefix, so the panel's confidentiality gate and access-expiry checks still apply first.
- Every issued link writes `nomination_form_viewed` (`application_id`, `role`; plus `viewed_by_superadmin` for a view-as session). Failed lookups (404/403/502/503) write no row, because no link was issued. Storage not configured -> 503 + critical alert; presign failure -> 502 + critical alert.
- `shape_application_for_role` now replaces `nomination_form` with `has_nomination_form`, `nomination_form_filename`, `nomination_form_required` for **every** role, superadmin included, so the upload id never reaches a browser. The nomination form is deliberately NOT in `_FINANCE_ONLY_APPLICATION_FIELDS` (the panel needs it).
- **Small change to N2 code:** `/apply` now also stores `nomination_form_required` (snapshot of `enabled and required` at submit time; the A2 design asked for it and N2 had skipped it). Older applications have no such field and read as `false` ("Not required at submission" in the UI).
- Not done: front-end (card N4: hook, superadmin panel, applicant section, vetting-row View button, snapshots). Corrections after submit and late attachment stay out of scope for v1.
- Tests: `backend/tests/test_nomination_readback.py` (13). Full backend suite: 525 passed (512 + 13).
- NOT verified: a real B2 presigned download (faked in tests, as in N2). The N2 human checks still apply.
