# BallotBox: Post-Election Review, Improvement Plan and By-Election Specification

**Prepared:** 16 October 2026 (election day, voting closed, results provisional)
**Scope:** Accounting Society of Kyambogo election (558 voters) and the next client (about 4,000 students)
**Status of this document:** a plan. No code was changed while writing it.

**How to read the evidence labels.** Each claim is tagged:
- **[Report]**: taken from the SMS CSV, the browser-error panel or the dashboard figures you pasted.
- **[Code]**: seen in the uploaded zip (`Multi-Tenant-Voting-System.zip`). Line numbers drift, so re-check them (playbook rule A1.3).
- **[Inferred]**: a reasoned guess. Verify before acting on it.
- **[Open]**: not yet known.

---

## 1. Summary

1. The election ran well. **414 of 558 voters (74.2%) had voted** at the last dashboard reading, every voter had a phone on file, and browser errors were few and device-specific. [Report]
2. The SMS send ratio was **1.42 OTPs per voter** (638 OTPs to 449 voters) in the EgoSMS-style report to 18:29. [Report] The morning baseline was 1.37.
3. The planned cheaper route (first OTP on EgoSMS at UGX 35, resends on MamboSMS at UGX 20) was **not live**: all 638 OTPs were billed at UGX 35. [Report] This matches the patch not having been applied yet. [Inferred]
4. **Bug found:** at the end of the voting window the Results page keeps saying "Live Tallying" instead of "Provisional Standings", because it reads only the manual `is_open` switch and ignores the voting window. [Code]
5. **Tie:** two candidates tied. The committee wants a **by-election**. The system has no tie detection and no round-aware voting, so a by-election needs a small, carefully scoped build (section 7).
6. The next client has about 4,000 students, so SMS cost, provider throughput and the front-end fixes in this plan matter more there.

---

## 2. What the data shows

### 2.1 SMS (EgoSMS-style report, 16 October to 18:29) [Report]

| Measure | Value |
|---|---|
| Messages in the file | 752 (638 OTP, 114 other) |
| OTP recipients (unique) | 449 |
| Send ratio | 1.42 OTPs per voter |
| Voters with 1 OTP | 335 (75%) |
| Voters with 2 or more | 114 (25%) |
| Repeat sends | 189 (30% of OTPs) |
| OTP spend | UGX 22,330 (all at UGX 35) |
| Total spend in this file | UGX 27,265 |

Sends per voter: 1 (335), 2 (71), 3 (25), 4 (9), 5 (6), 6 (1), 7 (2).

**Delivery status**
- Airtel: 323 Delivered, 19 Sent, 14 Pending, 6 Expired, 6 Failed.
- MTN: 375 Sent and 9 Pending. MTN never shows "Delivered", so MTN delivery **cannot be verified** from this report.

**Volume by hour (OTPs):** 07h 129, 08h 123, 09h 86, 10h 56, 11h 42, 12h 38, 13h 42, 14h 31, 15h 23, 16h 12, 17h 34, 18h 22. Peak in the first two hours, with a small evening bump.

**Voters to follow up (limit is 8 per day):** numbers ending 3477 and 8186 (7 sends each), 1896 (6), and 7803, 4981 and 1392 (5 each).

### 2.2 The 1,201 figure [Report, Inferred]
The dashboard shows 1,201 SMS sent. This file has 752. You confirmed the difference is a **MamboSMS bulk send**. By subtraction that is about 449 messages (inferred; confirm in the MamboSMS report). It is not an OTP count, so it must not be mixed into the OTP ratio.

Approximate election SMS spend: UGX 27,265 (this file) + about UGX 8,980 (449 bulk at UGX 20, if that rate applied) = **about UGX 36,000**. Confirm with the final reports.

### 2.3 Browser problem reports [Report]
28 reports against 558 voters: 16 blank screens, 11 JavaScript errors, 1 failed request.
- **Blank screens** fire at boot (`root_empty_20s`), before the bot check loads, so the bot check is not the cause. Likely causes: slow mobile data, ad blockers or private DNS, in-app browsers (WhatsApp, Facebook), and Chrome 53 (too old to run the app).
- **`xbrowser is not defined` / `swbrowser is not defined`** (Chrome 131): these names are not in your front-end code, so they come from an extension or in-app browser. Harmless, but they pollute alerts.
- **`localStorage ... Access is denied`** (Chrome 155): private mode or blocked storage. Check for unguarded `localStorage` use.
- **Opera 99 `reading 'default'`** on results: usually a lazy-loaded page chunk that failed, often a cached older build after a redeploy.
- **Alert threshold** for blank screens is 1 in 10 minutes, so one stuck voter sends an email. Treat those emails as a prompt to look, not an outage.

**Decision taken:** no change to the bot-check setting. Nothing pointed to it, and switching to Adaptive or Off would weaken protection in the last hours of voting.

### 2.4 Turnout [Report]
414 of 558 voted (144 not yet voted) at the time of the pasted figures. 449 voters requested at least one code, so up to about 35 may have been sent a code and not finished. [Inferred] Get the final numbers and check this group after close.

---

## 3. Issues register

| ID | Issue | Evidence | Severity | Fix in section |
|---|---|---|---|---|
| I-1 | Results page stays on "Live Tallying" after the window closes | [Code] | High | 5 |
| I-2 | Public results release in "closed" mode depends on `is_open`, not the window | [Code] | High | 5 |
| I-3 | No tie detection | [Code] (no tie logic for ballots) | High | 6 |
| I-4 | No by-election mechanism: `has_voted` is a single flag, `vote_events` have no round | [Code] | High | 7 |
| I-5 | Resend routing patch not live; all OTPs at UGX 35 | [Report] | Medium | 8 |
| I-6 | MTN delivery cannot be confirmed | [Report] | Medium | 8 |
| I-7 | Send ratio 1.42, 30% repeats | [Report] | Medium | 8 |
| I-8 | Announcement said "closes Fri 7PM"; real close time unverified | [Report] | Medium | 10 |
| I-9 | SMS budget shows "not set" | [Report] | Medium | 8 |
| I-10 | Front-end hardening (`localStorage`, extension errors, chunk retry) | [Report] | Low to Medium | 9 |
| I-11 | Blank-screen alert threshold too sensitive | [Report] | Low | 9 |
| I-12 | MamboSMS resends may fall back to EgoSMS silently | [Inferred] | Medium | 8 |

---

## 4. Immediate actions (today and the next 48 hours)

Voting is closed, so changes are now allowed, but follow the order below.

1. **Back up first.** Export results, the voter list with voted flags, the audit log and both SMS reports. Do not edit first-round data.
2. **Record the tie.** Note the position, the two candidates, the vote counts and who decided on a by-election. Mark the position "provisional, by-election ordered".
3. **Verify the real closing time** against the schedule screen. If the "Fri 7PM" SMS was wrong, send a correction.
4. **Pull the final reports** (EgoSMS and MamboSMS) so the final ratio and spend can be computed.
5. **Check the unfinished group** (voters who requested a code but did not vote) and the stuck numbers listed in 2.1.
6. **Open one blank-screen report** and read its detail field for missing browser features.
7. **Write the decision notes** (backup, limiter, analytics, SMS routing) in your own words for your supervisor. Understanding them is the point, so use the assistant to challenge your notes, not to write them.

---

## 5. Fix: results do not switch to provisional (I-1, I-2)

### 5.1 Cause [Code]
- Voting is correctly blocked by the clock: `assert_phase_open` and `_phase_is_open` compare now against the voting window.
- `Results.jsx` sets its open state from `statusRes.data.is_open` only. `is_open` is a manual master switch that stays true after the window ends until someone toggles it.
- `/election-results` in "closed" mode releases tallies when `is_open` is false, so the same gap applies.
- `/election-status` already returns `voting_phase` (`open`, `not_started` or `ended`).

### 5.2 Change
1. **Front end (`Results.jsx`):** treat the election as open only when `is_open` is true **and** `voting_phase !== 'ended'`. Keep the existing banner wording ("Live Tallying", "Provisional Standings", "Official Certified Results").
2. **Back end (`/election-results`):** when deciding `results_released`, also release when the voting phase has ended (use `voting_window_state(...)["ended"]` or `_phase_is_open` on the voting window).
3. **Optional safety net:** a small function that sets `is_open=false` once the window has ended, called on read. It must be idempotent and write one audit entry per transition (counts and mode only, no voter data).
4. **Do not change** API shapes, storage keys, `data-track`, ids or `data-phase`.

### 5.3 Tests (write first)
- Window ended, `is_open` true: Results shows "Provisional Standings"; tallies released in "closed" mode.
- Window open: still "Live Tallying".
- Certified: "Official Certified Results".
- Unenforced window: behaviour unchanged.
- Cross-tenant: org A's ended window does not affect org B.

### 5.4 Staging check
Set the end time two minutes ahead, wait, and confirm the banner, the results gating and the voting block all change on their own.

---

## 6. Tie detection (I-3)

### 6.1 Rule
After the voting window ends, for each position take the vote counts from `vote_events` (already aggregated by `get_vote_counts`). A position is **tied** when two or more candidates share the highest count and that count is above zero. For multi-seat positions, also check ties at the cut-off place.

### 6.2 Behaviour
- Admins see a clear banner: "Tie: candidate A and candidate B on N votes". No winner is shown for that position.
- The public page shows "Tie, pending decision" for that position (counts still follow the existing release rules).
- The tie record stores the position, the tied candidate ids, the count and the time detected. It contains **no voter data**.
- Detection is computed from the data, never typed in by hand.

### 6.3 Tie-break policy (decide before the next election)
A setting, locked before voting opens: run-off between the tied candidates, re-vote of the full position, committee decision (manual), or another rule your constitution allows.

---

## 7. By-election specification

### 7.1 What exists already [Code]
- `round_id` is stored on the phase schedule (`election_phases`, default `round-1`) and on candidate tokens.
- `has_voted` is one flag per voter, set when a ballot is recorded. A full reset (`has_voted=False`) is an existing action, but it is global.
- `vote_events` hold `candidate_id` and a coarse time bucket, **no voter id** (ballot secrecy), and are hash-chained.
- `/vote-bulk` and `/vote` set `has_voted` and insert `vote_events`.

### 7.2 Gap
A voter who voted in round 1 is blocked from voting again, and results count every candidate together. A by-election therefore needs round-aware voted state and round-aware counts, without touching round-1 data. **Before building, trace the full `/vote` and `/vote-bulk` path** to confirm no other code assumes a single round. [Open]

### 7.3 Data model (proposed)
- **Rounds:** a `rounds` collection per org: `round_id`, `kind` (`general` or `by_election`), `parent_round_id`, `reason`, `position`, `candidate_ids`, `eligibility_rule`, `created_by`, `created_at`, `status`.
- **Parent link:** `parent_election_id` (or `parent_round_id`) plus `reason` such as "tie for position X". Filled in automatically from the detected tie record.
- **Voted state per round:** add a `voted_rounds` list on the voter, or a separate `round_votes` marker keyed by `(org_id, round_id, voter_id)`. Keep `has_voted` working for round 1 so existing screens do not break.
- **Votes:** add `round_id` to new `vote_events`. Existing events are treated as `round-1`. The hash chain must continue to verify for each round (check `chain_verify.py`).
- **Candidates:** the by-election copies only the tied candidates into the new round. Round 1 candidates are not edited.
- **Indexes:** add `round_id` to the relevant compound indexes.

### 7.4 Who can create it
**Superadmin only**, enforced on the server with `require_role("superadmin")` (the UI is a convenience, never the control; playbook rule A1.5).

The endpoint takes the **tie record id**, not free-form candidate lists, so a superadmin cannot create a by-election for positions that were not tied. It then:
1. Validates the tie record belongs to the org and has no existing by-election.
2. Requires a logged **reason** (minimum length, like the early-stop rule) and an **eligibility rule** (all registered voters, or only round-1 voters).
3. Creates the round with `parent_round_id` and `reason`, and copies only the tied candidates.
4. Writes its own phase schedule (separate from round 1).
5. Writes an audit entry: actor role, round id, position, counts only. **No names, phone numbers or registration numbers** (rule A1.10).

### 7.5 Voting flow in a by-election
- `/verify-identity` and `/verify-otp` use the **current round** (`current_round_id`) and check eligibility for that round.
- The "already voted" test filters by round.
- **OTP limiter state is per round**, so round-1 send counts do not carry over. Use the existing per-round reset logic where `round_id` changes (`otp_derived`).
- SMS routing uses the first-send and resend rules from section 8.

### 7.6 Results and audit
- Each round has its own results, phase and status.
- Round-1 results stay visible and unchanged, labelled "Round 1 (tie)". The by-election appears as a linked entry.
- A second tie in a by-election goes to the locked tie-break policy.
- The final report and certificate show both rounds and the parent link.

### 7.7 Security and secrecy checklist
- Server-side role check on creation and on every by-election admin action.
- Every query scoped by `org_query` or `_oq`; every cache keyed by org and round.
- No voter identity added to `vote_events`.
- Round creation cannot delete or alter round-1 data.
- All new audit actions added to the audit vocabulary, with counts and booleans only.

### 7.8 Tests
- Tie detected for two-way, three-way, second-place and zero-vote cases.
- Non-superadmin gets 403 on creation (admin, commissioner, IT admin, overseer).
- A tied round-1 voter can vote in the by-election, exactly once.
- A voter cannot vote twice in the same round.
- Round-1 counts are identical before and after the by-election.
- Cross-tenant: org B cannot see or create from org A's tie.
- Hash chain verifies for round 1 and for the by-election.

---

## 8. SMS plan

### 8.1 Routing and cost [Report]
- First OTP through EgoSMS (UGX 35), resends through MamboSMS (UGX 20), each with the other as fallback.
- Patch: `otp_first_ego_resend_mambo.patch` (changes `backend/main.py` only). It can be turned off with `OTP_RESEND_VIA_MAMBO=0`. Apply on staging, load-test, then apply for the by-election.
- **Why it matters:** per voter, planning for 3 SMS, the split costs UGX 75 against UGX 105 (29% less). At 8 sends it is UGX 175 against UGX 280.
- **Confirm** that MamboSMS bills UGX 20 for OTP traffic (your UGX 20 is from a bulk send), needs no sender-ID approval for transactional messages, and delivers on both MTN and Airtel.
- **Watch for silent fallback:** if MamboSMS fails, resends fall back to EgoSMS at UGX 35. Check backend logs for "falling back to EgoSMS" warnings and the MamboSMS dashboard.

### 8.2 Controls (environment variables on Render) [Code]
| Variable | Default | Effect |
|---|---|---|
| `OTP_SEND_LADDER_SECONDS` | 0,30,60,120,300,600 | waits between resends |
| `OTP_CODE_TTL_MINUTES` | 10 | code lifetime; longer means fewer new codes but easier guessing (15 is a sensible ceiling) |
| `OTP_DAILY_SEND_CEILING` | 8 | daily cap per voter |
| `OTP_RESEND_VIA_MAMBO` | on (patch) | cheaper resend route |

Do not change these while voters are live. Plan an admin UI for them (guide 13) so they can be changed without redeploying.

### 8.3 Lowering the ratio (target 1.15 to 1.2)
1. Voters confirm phone numbers before the election.
2. One clear line on the OTP screen and in the announcement SMS: "The code can take up to 2 minutes. Please wait before requesting another."
3. Check Pending and Failed sends one to two hours after opening. A ratio above about 1.4 or many Pending sends means a gateway problem that can still be fixed live.
4. Do not push the ratio down by blocking voters. Keep the admin reset path ready.

### 8.4 Budget model (set the SMS budget field before opening, I-9)
Plan per voter: 1 × 35 + 2 × 20 = **UGX 75** worst case for three sends, plus a 30% balance buffer on both providers.

| Scenario | Voters | OTP cost estimate | Ceiling |
|---|---|---|---|
| By-election (about 450 voting, ratio 1.4) | 450 | about UGX 20,000 | UGX 34,000 |
| By-election announcement (bulk, MamboSMS) | 558 | about UGX 11,000 | n/a |
| Next client (ratio 1.37, split) | 4,000 | about UGX 168,000 | UGX 300,000 |
| Next client (all EgoSMS, ratio 1.37) | 4,000 | about UGX 192,000 | UGX 420,000 |

Add the announcement and reminder bulk SMS as a separate line at UGX 20 each.

### 8.5 Scale for 4,000 voters [Inferred]
Expect about 1,400 or more OTPs in the first hour. Ask both providers about rate limits and queueing. Expect around 900 voters with repeats and a few dozen with bad numbers. Staff a helpdesk and the admin reset process.

---

## 9. Front-end hardening

| Item | Change |
|---|---|
| `localStorage` / `sessionStorage` | Wrap every read and write in `try/catch`, and render correctly when storage is empty or blocked |
| Extension errors | Ignore `xbrowser` and `swbrowser` errors in the problem-report sender so they do not count toward alerts |
| Failed page chunks | Add a one-time reload or retry when a lazy-loaded chunk fails (fixes the Opera "reading 'default'" case) |
| Boot size | Keep the first download small for slow mobile data |
| Blank-screen alert | Raise the threshold to about 3 in 10 minutes |
| Voter help text | "Open in Chrome or Safari, not inside WhatsApp. Switch between Wi-Fi and mobile data. Try a private window." |
| Old browsers | Show a short "please update your browser" notice instead of a blank screen where feasible |

---

## 10. Operations runbook for the by-election

### 10.1 Before opening
1. Committee confirms in writing: position, the two candidates, eligibility rule, open and close times, and when results become final.
2. Backup taken and verified (restore test if time allows).
3. By-election round created by a superadmin from the detected tie, with a logged reason.
4. Staging dry run completed (section 11, step 5).
5. **Check the schedule screen** against the announcement text. Times are stored in UTC and shown in the election timezone (`Africa/Kampala`), so confirm both agree.
6. Both SMS balances topped up with a 30% buffer.
7. Announcement SMS sent through MamboSMS bulk with the correct times and the wait-before-resend line.

### 10.2 While open
- Do not change code or settings.
- Check the SMS report one to two hours in: ratio, Pending, Failed.
- Reset stuck voters from the admin side (numbers near the 8-send ceiling).
- Treat blank-screen emails as prompts to look, not as outages.

### 10.3 After closing
- Confirm the banner switches to provisional on its own (section 5).
- Confirm the tally and any new tie.
- Collect final SMS reports and compute the final ratio and spend.
- Certify results only when the committee confirms.

---

## 11. Delivery plan (follows `BALLOTBOX_PHASE_RUNBOOK.md`)

Use the runbook's method: **one card per session, one branch per card, tests first, progress file per card**. Branch name `improvements/<ID>`. Commit format `<ID>: <what> [be N / fe N / lint 0]`. Never read or commit `*.env` files. A partial, committed card is a success.

| Card | Goal | Files (only these) | Lane |
|---|---|---|---|
| **PH-1** | Provisional fix (section 5) | `backend/main.py` (`/election-results`), `frontend/src/components/Results.jsx`, new tests | C (Results) |
| **TIE-1** | Tie detection record and admin banner (section 6) | `backend/main.py`, new `backend/tests/test_ties.py`, results admin component | B (backend) then C |
| **BE-1** | Round model, per-round voted state, per-round counts (7.3) | `backend/main.py`, `backend/database.py` / indexes, `chain_verify.py` if needed, new tests | B |
| **BE-2** | Superadmin by-election endpoint and audit entries (7.4) | `backend/main.py`, new tests | B (after BE-1) |
| **BE-3** | Superadmin panel UI: tie list and "Create by-election" (7.4, section 12) | `SuperAdminDashboard.jsx` tab array, one new panel file, tests | D (UI) |
| **SMS-1** | Apply the resend routing patch and logging | `backend/main.py` | B (after BE-2) |
| **FE-1** | Front-end hardening (section 9) | `analytics.js`, error reporter, storage helpers | A |
| **OPS-1** | Budget sheet and checklist | docs only | none |

**Lanes.** `backend/main.py` is a collision hotspot, so backend cards run **one at a time in this order**: PH-1 (backend part), TIE-1, BE-1, BE-2, SMS-1. The front-end cards (FE-1, BE-3, the `Results.jsx` part of PH-1) can run in parallel with them because they touch different files.

**Each card starts with a PRE-CHECK.** If the code does not match this document, stop, write `deviations/<ID>.md` and report. Do not guess.

**Acceptance for every card:** no new failures against the numbers at the moment its branch was cut, plus its own new tests green. Run backend `pytest -q`, frontend `npx vitest run`, lint, and `npx vite build`. Never weaken or skip an existing test without a `DEVIATIONS.md` entry.

**Order of work**
1. Backup and decisions (section 4).
2. PH-1 on staging, then live.
3. TIE-1 (read-only, low risk).
4. BE-1 and BE-2 on staging with dummy voters through a full cycle: upcoming, voting, provisional, final.
5. SMS-1 applied and load-tested.
6. BE-3 UI.
7. Full dummy by-election on staging, then a smoke test a day before going live.

---

## 12. UI design (follows `UI_TEMPLATE_MANUAL.md`)

**Golden rule:** new panels are written once, with the shared panel kit, and contain **no template branches**. The same classes look right in the Default and Blueprint templates.

### 12.1 Tie list and by-election panel (Superadmin)
Add it as a tab through the `tabGroups` array in `SuperAdminDashboard.jsx` (the Blueprint sidebar reads those arrays; do not hard-code navigation). Build it from the kit:

| Need | Use |
|---|---|
| Panel | `<section className="perf-card card-pad">` (never nest `bp-card`) |
| Title | `<h3 style={{ margin: '0 0 6px', fontSize: 15 }}>` |
| Description | `perf-lead`, with small hints in `perf-note` |
| One tie row | `perf-row` with `perf-row-title` (position), `perf-row-text` (candidates and vote count), trailing `perf-btn` |
| Create action | `perf-btn perf-btn-primary` ("Create by-election") |
| Cancel / back | `perf-btn` |
| Reason and rule fields | `perf-field` (48 px, 16 px text); eligibility choice as `perf-check` rows inside `perf-checks` |
| Button row | `perf-btnbar`, with `perf-btnbar-stack` so buttons stack on phones |
| Success / error | `perf-msg` with `data-kind="ok"` or `"error"`; the text must say what happened |
| Status | `BackupPill` or `<bp.Pill>` showing words such as "Tie, pending decision" and "By-election open" |
| Loading / polling | `usePolling` and `LoadingBlock` |

Use the shared confirm dialog (`useConfirm`) before creating a by-election: "Create a by-election for [position]? This cannot be undone. Round 1 results are kept."

### 12.2 Results page
- Keep the existing banner and pill pattern.
- Tied position: show "Tie, pending decision" in place of a winner. Use the existing `warn` tone, not a new colour.
- Linked by-election: a short row under the position, "By-election: [status]".
- Status is always **words**, never colour alone.

### 12.3 Rules for every new or changed screen
1. Kit classes only. **No hex colours**, no new fonts, no new dependencies. Colours only from `var(--...)` tokens (`--text-muted`, `--border-color`, `--card-bg`, `--success`, `--danger`). Add a token if one is missing.
2. Every control at least 44 px tall (48 px in Blueprint). Fields use `perf-field`.
3. Keep formal wording and proper capitals.
4. Do not change API calls, storage keys, `data-track`, ids or `data-phase` as part of a visual change.
5. Check for class-name collisions before adding a class (`perf-bar` is the progress bar, not a button row; `bp.cls.alt` is the red error block).
6. Prefer classes over inline styles, because inline `background` and `border` ignore Blueprint.
7. A template wrapper must not early-return inside a component that uses hooks.
8. Edit only `src/templates/blueprint/blueprint.css` for Blueprint styles, with no `!important` outside the fenced `NEUTRALISERS` section. Change `index.css` and the matching Blueprint block in the same commit.
9. **Phone check at 390 px:** no sideways scroll, buttons stack, nothing squeezed to one side.

### 12.4 Verification (from the manual)
```bash
cd frontend
npx vitest run                              # default template
VITE_UI_TEMPLATE=blueprint npx vitest run   # whole suite again, Blueprint on
npx vite build --outDir /tmp/dist-default
VITE_UI_TEMPLATE=blueprint npx vite build --outDir /tmp/dist-bp
ls /tmp/dist-default/assets | grep -i blueprint   # must print nothing
```
Then look at the page by eye in both templates, light and dark, at about 1100 px and 390 px. Tests do not catch an ugly layout. `uiTemplateRules.test.js` must pass.

### 12.5 Recording the work
- One `progress/<card>.md` per card: what changed, what ran, what did not run, and the **HUMAN** checks (real browser or phone) that the assistant cannot claim.
- Any departure from the manual or the playbook goes in `deviations/<card>.md`, merged into `docs/DEVIATIONS.md` at the end.

---

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Round-aware voting breaks the single-round path | Keep `has_voted` for round 1; trace `/vote` and `/vote-bulk` first; test round 1 unchanged |
| Hash chain breaks when `round_id` is added | Check `chain_verify.py`; verify each round separately in tests |
| Results timing mismatch (UTC vs local) | Store UTC, show in `Africa/Kampala`, test with a two-minute staging window |
| Resend route falls back silently and costs more | Log fallback counts; check the MamboSMS dashboard during the vote |
| MTN delivery not visible | Test on real MTN numbers before the election; track "Sent" counts and voter reports |
| Voters locked out by limits | Keep the admin reset path and helpdesk ready |
| Rushed live changes | Staging first, backup first, no changes while voting is open |
| Dispute over the by-election | Written committee decision, logged reason, round 1 kept intact, parent link visible |

---

## 14. Open questions

1. Which position is tied, and by how many votes?
2. Who may vote in the by-election: all 558 voters, or only the round-1 voters?
3. What does your constitution say about ties (run-off, re-vote, or committee decision)?
4. Is `/vote` and `/vote-bulk` the only path that records ballots?
5. Does MamboSMS bill UGX 20 for OTP traffic, and does it deliver on MTN and Airtel?
6. What was the real voting end time, and was the "Fri 7PM" SMS wrong?
7. What are the final turnout and the final SMS totals?
8. Where does the extra "extension" error code (`xbrowser`) come from, and can it be filtered at the source?

---

## 15. Checklists

### 15.1 Before the by-election
- [ ] Backup taken and verified
- [ ] Committee decision in writing (rule, voters, times)
- [ ] PH-1 live and checked on staging
- [ ] Tie detected in the system and matches the manual count
- [ ] By-election created by a superadmin, reason logged
- [ ] Dummy run completed, round 1 results unchanged
- [ ] SMS patch applied, MamboSMS rate and delivery confirmed
- [ ] Both SMS balances topped up (30% buffer); SMS budget field set
- [ ] Schedule screen times match the announcement
- [ ] Front-end hardening live
- [ ] Helpdesk and admin reset process ready

### 15.2 Before the 4,000-student election
- [ ] Phone numbers verified in advance
- [ ] Provider rate limits confirmed; first-hour volume tested
- [ ] Limiter settings decided; admin UI for them built
- [ ] Budget set at about UGX 170,000 with a UGX 300,000 ceiling, plus bulk SMS lines
- [ ] Tie policy locked per position before opening
- [ ] Voter instructions prepared (browser, data, wait before resend)

---

## 16. Implementation outcome and verification

**Updated:** 16 October 2026  
**Implementation report:** `docs/POST_ELECTION_IMPLEMENTATION_REPORT.md`  
**Status:** Source changes prepared; not production-tested.

### Implemented in the source archive

- PH-1: Results uses the scheduled voting phase to move to provisional state, and `closed` results release when the selected round ends even if the global `is_open` switch remains true.
- TIE-1: Top-place and multi-seat cut-off ties are computed from anonymous vote events and persisted without voter identifiers. The superadmin tie list triggers detection after close.
- BE-1 / BE-2: Added round-aware vote counts, voter markers, OTP limits, session/code validation, hash-chain V2 round binding with V1 compatibility, superadmin-only by-election creation from a persisted tie, and round-specific candidate/phase/result snapshots.
- BE-3: Added the Superadmin By-elections panel, Results round navigation, tie labels/links, position seat-count configuration and reset protection after a by-election exists.
- SMS-1: Managed first OTP via EgoSMS and resend preference via MamboSMS with fallback/logging, controlled by `OTP_RESEND_VIA_MAMBO`.
- FE-1: Added safe storage fallback, extension-error filtering, adjusted blank-screen threshold and updated browser guidance.
- OPS-1: Added `rounds` and `ties` to backup collection sets and created per-card progress notes.

### Verification outcome

- **PASS:** Python syntax compilation for the backend source.
- **PASS:** TypeScript parser processed 268 frontend JS/JSX/TS source files with zero syntax diagnostics.
- **PASS:** `node --check frontend/src/storage.js`.
- **BLOCKED:** `pytest -q backend/tests/test_post_election_plan.py` could not collect tests because `mongomock` is missing.
- **BLOCKED:** Frontend tests, lint and build could not run because `vitest`, `eslint` and `vite` are not installed. Dependency installation could not reach the package registry because DNS/network access was unavailable.
- **NOT RUN:** Staging, production, real provider sends, real-phone/browser acceptance and manual UI checks. No full test pass is claimed.

### Decisions and rollout gates still required

1. The committee must specify the constitutional tie-break rule. The code prevents automatic creation of another by-election from a by-election tie rather than inventing a rule.
2. The committee must select by-election eligibility (`all_registered` or `round1_voters`).
3. Verify MamboSMS OTP rates, sender-ID requirements, MTN/Airtel delivery and throughput with the provider; code cannot prove provider behavior or billing.
4. Install dependencies in a connected environment; run pytest, Vitest, ESLint and Vite build; resolve failures before deployment.
5. Complete two-template human checks and a full dummy by-election staging cycle, verify Round 1 counts remain unchanged, and verify hash chains separately for each round.
6. Take and verify a backup before live changes. Do not deploy or change election settings while voting is active.

See `docs/POST_ELECTION_IMPLEMENTATION_REPORT.md` and `deviations/POST-ELECTION-IMPLEMENTATION.md` for the detailed record.
