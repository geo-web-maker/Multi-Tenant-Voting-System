# Post-election implementation: verification fixes (16 October 2026)

An independent run of the full suites (backend pytest, frontend Vitest, ESLint, Vite build) found failures in the
first implementation. This file records each one, its cause, and the fix. Nothing here changes a spec decision.

| # | Finding | Cause | Fix |
|---|---|---|---|
| 1 | 3 call-budget tests failed (`test_performance_budget` x2, `test_vote_path_budget`) | Every vote, OTP and results request added 1-2 `rounds.find_one` reads, even for Round 1, which has no eligibility rule. A cached results hit also touched `settings` and `rounds`. | Round 1 skips the `rounds` read on `/verify-identity`, `/vote`, `/vote-bulk`, the candidate list and `_round_candidate_allowed`. `/election-results` now checks its cache before tie detection and the Round 1 read; `_round_is_ended` and the certified check use `cached_setting` (already invalidated on write). A cache hit touches no collection again. Tie detection still runs on every cache miss after close. |
| 2 | `/vote-status` returned an extra `round_id` | Spec section 5.2: do not change API shapes. | Response is `{has_voted}` again; the value is still round-aware. |
| 3 | `test_threshold_sends_one_alert` failed | Blank-screen threshold was raised to 3 in 10 minutes (spec 9) but the test still expected an alert on the first report. | Test updated to expect no alert at 2 reports and one alert at 3. |
| 4 | `test_otp_limiter_state_is_scoped_by_round...` failed | The test expected an upper-case key; student ids are lower-cased before keying (unchanged behaviour). | Test expectation corrected. Round 1 key format is unchanged. |
| 5 | **Bug:** a clear winner was labelled "Tie, pending decision" | `getPositionTieDetails` put a lone leader into `tiedIds`. | Only two or more candidates sharing first place count as tied. Caught by `Results.template.test.jsx`. |
| 6 | `Results.template` test expected the old `TIE (RE-RUN)` text | The label was changed to "Tie, pending decision" (spec 12.2). | Test updated to the new label. |
| 7 | `uiTemplateRules`: `perf-btn-card` undefined in `index.css` | Class used by `SharedAdminPanels.jsx` / `BackupJobList.jsx` and styled only in Blueprint. | Added `.perf-btn-card` to `index.css` (mirrors the existing Blueprint rule). |
| 8 | `tokens.test` fence count (20 rules, 18 numbered) | The heatmap button rules sat inside the NEUTRALISERS fence but use no `!important`. | Moved them just after the fence, unchanged. |
| 9 | `ApplicantPortal` A4 test failed | The handler awaits `wakeServer()` before posting; the test counted calls synchronously. Not touched by this work. | Test waits for the call, then confirms it stays at one. |
| 10 | 4 ESLint errors in `SmsSettings.jsx` | setState-in-effect (project convention: `eslint-disable-next-line` with reason) and a non-component export. | Disable comments added; `ROUTE_LABELS` is no longer exported (it had no other users). |

Remaining ESLint output: one pre-existing `exhaustive-deps` warning in `Results.jsx` (not changed: adding the dependency risks a refetch loop).

## Still not done (needs people, providers or real devices)
Staging election cycle, dummy by-election, real SMS and MamboSMS price/delivery checks, and the two-template visual checks at 1100 px and 390 px.
