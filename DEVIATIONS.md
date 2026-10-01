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
| 3.3 | ApplicantPortal polling changes, single `/public/bootstrap` | not started |
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

