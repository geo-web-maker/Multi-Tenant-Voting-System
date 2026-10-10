# BallotBox — Phase Runbook (run remaining work in small, parallel, mergeable pieces)

**Why this exists.** Giving an AI "all the remainder" in one go burns the whole token budget on reading and planning, and nothing gets committed. This runbook cuts the remainder into **phase cards**. One card = one AI session = one git branch = its own tests = one commit trail. Cards in different **lanes** touch different files, so several can run at the same time and merge back into one `integration` branch.

**Source of truth for "what's remaining":** `DEVIATIONS.md` → "Not done" table (second pass). **Source of detail:** `BALLOTBOX_AI_IMPLEMENTATION_PLAYBOOK` (line ranges are given per card so the AI reads ~30–120 lines, not 1,674).

**Baseline to beat (from DEVIATIONS.md, second pass):** backend `pytest -q` 275 passed · frontend `npm test` 63 passed · `npm run lint` 0/0 · `npx vite build` OK. Final acceptance for any phase = **no new failures vs. the numbers at the moment its branch was cut + its own new tests green.**

---

## 0. One-time setup (you or the AI, once)

The uploaded zip has **no `.git`**, so create the history first. Do this before any phase.

```bash
cd "Multi-Tenant Voting System"
git init -b main

# SAFETY: confirm env files are ignored BEFORE the first add. Never open them.
git check-ignore -v backend.env frontend.env backend/.env backend/loadtest.env frontend/.env 2>&1 | head
#   every existing env file must print a matching .gitignore rule. If one does not, STOP and fix .gitignore.

git add -A && git status --short | grep -i "\.env" | grep -v "\.env\.example"   # must print NOTHING
git commit -m "baseline: state after second pass (275 be / 63 fe tests)"
git tag baseline-2nd-pass
git checkout -b integration
mkdir -p progress deviations && touch progress/.gitkeep deviations/.gitkeep
git add progress deviations && git commit -m "chore: per-phase progress and deviation folders"
```

Test environment note (from DEVIATIONS.md): backend tests need `pymongo==4.10.1` (newer breaks `mongomock`). Env vars the tests use: `SUPER_ADMIN_ID=root SUPER_ADMIN_PASSWORD=x JWT_SECRET_KEY=test-secret DEBUG_MODE=true`.

**Why `progress/` and `deviations/` are folders of one file per phase:** if every phase appended to one shared `DEVIATIONS.md`, every merge would conflict on it. One file per phase never conflicts. Merge them into `DEVIATIONS.md` once, at the end (card **F3**).

---

## 1. Starting a phase (parallel-safe)

Each phase gets its own **worktree** (a separate folder on its own branch), so two AIs never share a working directory.

```bash
# from the main repo folder, on integration:
PHASE=WP-7d                                   # the card ID
git worktree add ../bb-$PHASE -b improvements/$PHASE integration
cd ../bb-$PHASE
# (frontend) npm ci      (backend) python3 -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements.txt pytest pytest-asyncio mongomock-motor && pip install "pymongo==4.10.1"
```

Open the AI **inside that folder** and paste the prompt from §2. Repeat in another terminal for another card in a *different lane*.

---

## 2. The prompt to paste (fill in the two blanks)

```
You are doing exactly ONE phase of the BallotBox improvement work: PHASE = <ID, e.g. WP-7d>.
Working folder: this git worktree, branch improvements/<ID>. Do not touch any other branch.

READ ONLY THESE (do not read anything else "for context"):
 1. The card for <ID> in BALLOTBOX_PHASE_RUNBOOK.md (§4).
 2. The playbook line ranges that card lists, via `sed -n A,Bp`. Also playbook lines 11-22 (rules A1).
 3. Only the source files the card names.

DO:
 - Run the card's PRE-CHECK first. If the code does not match the card, STOP, write
   deviations/<ID>.md, commit it, and report. Do not guess.
 - Write the tests FIRST (or alongside), then the change. Tests go in NEW files named after the phase.
 - While working, run only the targeted tests. Run the full suites once, at the end.
 - Commit after each sub-step that is green:  `<ID>: <what> [be N / fe N / lint 0]`
 - Never read, print, or commit *.env files. Never run against production. Never widen scope.
 - Do not add dependencies. Do not edit files outside the card's FILES list. If you must, STOP and say why.
 - Keep command output short (`| tail -15`). Do not re-read files you already read.

FINISH WITH:
 - Full backend + frontend tests, lint, and (if frontend changed) `npx vite build`.
 - Write progress/<ID>.md using the template in §6 (paste the real result lines), commit it.
 - Reply with at most 10 lines: status, commit SHAs, test counts, anything for a human to check.

IF YOU RUN LOW ON BUDGET: stop at the last green commit, fill progress/<ID>.md with
"status: partial", the exact next step, and commit that. A partial, committed phase is a success.
```

---

## 3. Lanes, and what can run at the same time

A **lane** is a set of cards that touch the same files. **Inside a lane: one card at a time, in order.** **Across lanes: run in parallel.**

| Lane | Files it owns | Cards (in order) | Parallel with |
|---|---|---|---|
| **A — App shell** | `App.jsx`, `ClosedNotice.jsx`, `HelpPanel`/`FabTrigger`, `phase.js`, `PhaseBanner.jsx`, error modal | A1 → A2 → A3 → A4 → A5 | B, C, D1, D2 |
| **B — Apply form** | `ApplicantPortal.jsx`, `applyErrors.js`, `imageResize.js` | B1 → B2 → B3 → B4 → B5 | A, C, D1, D2 |
| **C — Results page** | `Results.jsx` (+ new `resultsState.js`) | C1 | everything |
| **D1 — Analytics backend** | `backend/analytics.py`, `frontend/src/analytics.js` | D1a → D1b | A, B, C, D2 |
| **D2 — Admin dashboard UI** | `UsageCharts.jsx`, `AnalyticsPanel.jsx`, new insight files | D2a → D2b → D2c → D2d → D2e | A, B, C, D1 |
| **E — Bootstrap endpoint** | `backend/main.py`, plus the fetch code in `App.jsx` and `ApplicantPortal.jsx` | E1 | **only after A and B are merged** |
| **F — Closers** | many files | F1 (data-track), F2 (housekeeping), F3 (acceptance) | **only after everything else is merged; one at a time** |

**Collision hotspots** (why the lanes look like this): `App.jsx` (A + E + F1), `ApplicantPortal.jsx` (B + E + F1), `backend/main.py` (E + D1b), `analytics.py` (D1a + D1b).

**Suggested waves** (pick fewer at a time if tokens are tight; one at a time also works):

| Wave | Run together | Then merge |
|---|---|---|
| 1 | A1, B1, C1, D1a, D2a | merge each as it finishes (§5) |
| 2 | A2, B2, D1b, D2b | merge |
| 3 | A3, A4, B3, D2c | merge |
| 4 | A5, B4, B5, D2d, D2e | merge |
| 5 | E1 (optional) | merge |
| 6 | F1 → F2 → F3 | merge |

---

## 4. Phase cards

Format: **Goal** · **FILES** (only these may change) · **Playbook** (line ranges) · **Pre-check** · **Tests** · **Done when**. "HUMAN" = needs a real browser or phone; the AI must list it in `progress/<ID>.md`, not claim it.

### Lane A — App shell

#### A1 · WP-7a · Phase banner + Apply now (guide §4.1) — size M
- **Goal:** one prominent phase notice on the voter card with an **Apply now** button while applications are open. Login form and the "Are you an admin?" link stay exactly as they are (your recorded decisions: landing page stays Voter Login; admin link stays visible).
- **FILES:** `src/phase.js` (new), `src/components/PhaseBanner.jsx` (new), `App.jsx` (mount only), test files `src/phase.test.js`, `src/components/PhaseBanner.test.jsx`.
- **Playbook:** 1434–1450 (WP-7 header and 7a).
- **Pre-check:** `sed -n 2776,2800p backend/main.py` (phase keys); `grep -n "voting_phase\|applications_phase" frontend/src/components/ClosedNotice.jsx`.
- **Tests:** `derivePhase` table, 9 combinations of `applications_phase` × `voting_phase`; banner shows exactly one state; Apply button only for `apply_open`; click switches view to `apply`; countdown with fake timers; date in `Africa/Kampala` near midnight.
- **Done when:** tests green, lint 0, build OK. **HUMAN:** at 360×640 the banner is under 25 % of screen height and the form is above the fold.

#### A2 · WP-7b · Help button on Apply (§4.1a) — size S–M
- **Goal:** floating Help on both Voter Login and Apply (icon-only `?` on Apply and under 400 px); content filtered per page.
- **FILES:** `App.jsx` (FabTrigger condition), `HelpPanel` file, `src/helpItems.js` (new, pure `helpItemsFor(page)`), new test.
- **Playbook:** 1451–1454. **Pre-check:** `sed -n 706,724p frontend/src/App.jsx`; `grep -rn InlineHelpButton frontend/src`.
- **Tests:** `helpItemsFor('voter')` vs `('apply')` match the table exactly; FAB renders on `apply`, not on voter step 3.
- **Done when:** green. **HUMAN:** `?` does not cover the submit button or the open keyboard on 360×640. *(The ~96 px bottom padding on the apply container lives in `ApplicantPortal.jsx`: that is lane B, so put it in the B1 branch, or leave it to HUMAN review and note it in `progress/A2.md`.)*

#### A3 · WP-7c · Confirm before "Vote Now" signs an admin out (§4.1b) — size S
- **FILES:** `App.jsx`, new test. **Playbook:** 1455–1457.
- **Tests:** token + confirm=false → token still present; confirm=true → cleared; no token → no dialog.

#### A4 · WP-6b · Stop the typing placeholder re-rendering `App` (§3.6) — size S
- **FILES:** `App.jsx` only. **Playbook:** 1331–1336. Default option: delete the effect and its four states, use static placeholders.
- **Tests:** `grep -n "setPlaceholderText\|setTypingSpeed\|setIsDeleting\|setLoopNum" frontend/src/App.jsx` returns nothing; lint clean. **HUMAN:** React Profiler shows no `App` re-renders while idle.

#### A5 · WP-7e (remainder) · Action buttons on the login error modal (§4.3) — size S–M
- **Goal:** messages are already mapped; add the **Register link** and **support button** to the modal. 
- **FILES:** the error modal component (find with `grep -rn "loginErrorGuidance" frontend/src`), `App.jsx` if it owns the modal, new test. **Playbook:** 1461–1474.
- **Tests:** each guidance row from the playbook table renders its link/button; unknown/object `detail` still falls back without crashing.

### Lane B — Apply form (§4.4 remainder, only gaps 1–3 are done)

*Split on purpose: the playbook's WP-6e is one big card; four small sessions use far fewer tokens than one large one.*

#### B1 · WP-6e-i · Error mapping + validate-all-fields — size M
- **Goal:** `mapApplyError` table; one validation pass listing every missing field with `aria-invalid`, red border, scroll to first; fixed-label `submit_blocked` reasons (`missing_field`, `bad_file_type`, `too_large`; never values); trim + uppercase registration number via `regNo.js`.
- **FILES:** `src/applyErrors.js` (new), `ApplicantPortal.jsx`, new tests. **Playbook:** 1359–1392 (items 5, 7, 8 and the tests table A1, A5).
- **Tests:** playbook A1 (table-driven over every case in §4.4 of the guide) and A5.

#### B2 · WP-6e-ii · Progress feedback — size M
- **Goal:** step labels `(1/4)…(4/4)` (skip the photo step when none), upload percent via `onUploadProgress`, `beforeunload` warning while uploading, "Slow connection…" on `api:slow`, **Cancel** with `AbortController`, inputs inert and button `aria-busy` while busy.
- **FILES:** `ApplicantPortal.jsx`, new tests. **Playbook:** 1359–1392 (items 4/1; tests A4, A7).
- **Tests:** playbook A4 (double Enter → one call) and A7 (inert while busy); cancel aborts the request.

#### B3 · WP-6e-iii · Reuse uploads + draft restore — size S–M
- **Goal:** keep uploaded URLs in a `useRef` keyed by `name+size+lastModified` so retry skips files already uploaded; show "Re-attach your receipt" when a draft is restored.
- **FILES:** `ApplicantPortal.jsx`, new tests. **Playbook:** items 6 and 9, tests A6, A8.
- **Tests:** playbook A6 (photo uploaded once in total, receipt twice) and A8.

#### B4 · WP-6d · Resize photos on the phone (§3.6) — size S ⚠️ needs devices
- **FILES:** `src/imageResize.js` (new), `ApplicantPortal.jsx` (one call site), new test. **Playbook:** 1355–1358.
- **Tests:** `fitWithin(w,h,max)` geometry; any failure returns the **original** file (mock `createImageBitmap` to throw); skip non-images and files under 1 MB. **HUMAN:** real Android Chrome, including HEIC/AVIF phones.

#### B5 · WP-4 (remainder) · ApplicantPortal polling (§3.3) — size S
- **Goal:** move the portal's polling onto the shared `usePolling` (burst guard + backoff already exist). Do **not** build `/public/bootstrap` here (that is E1).
- **FILES:** `ApplicantPortal.jsx`, new test. **Playbook:** 1171–1246 (read only the ApplicantPortal bullets: `grep -n "ApplicantPortal" ` inside that range first).
- **Pre-check:** `grep -n "setInterval" frontend/src/components/ApplicantPortal.jsx`. **Tests:** no raw `setInterval` left; polling pauses when the tab is hidden if `usePolling` already does so; failure backoff applies.

### Lane C — Results page

#### C1 · WP-7d · Results "not started" and other states (§4.2) — size S–M
- **Goal:** `resultsState(status, results)` → `not_started | live | no_votes | closed | embargoed`; not-started shows "Voting opens <date>. Results will appear here live." (no "Live Tallying"); hide turnout/voter-roll until data exists.
- **FILES:** `src/resultsState.js` (new), the Results component, new tests. **Playbook:** 1458–1460.
- **Tests:** one case per state, including `results_released === false`.

### Lane D1 — Analytics backend (sequential)

#### D1a · §5.3 · `usable_ms` — size M
- **Goal:** `performance.mark('usable')` when the login form becomes interactive; send `usable_ms`; backend histogram support.
- **FILES:** `src/analytics.js`, `backend/analytics.py`, `backend/tests/test_analytics_usable.py` (new), `src/analytics.usable.test.js` (new). **Playbook:** 1499–1530 (row 5.3 only).
- **Pre-check:** `cd backend && pytest tests/test_analytics.py -q` must already pass 100 % (record the count).
- **Tests:** mark exists after boot; value ≥ 0; backend stores and aggregates it; **all existing analytics tests still pass**.

#### D1b · WP-9.3 backend · `tracking_since` (§6.3) — size S
- **Goal:** earliest `day` in `analytics_counters` for the org, added to the summary response (per-org; empty org → `null`).
- **FILES:** `backend/analytics.py`, new test file. **Playbook:** 1531–1539 (item 3).
- **Tests:** two orgs with different first days; empty org returns `null`. *(The dashboard line itself is in D2e.)*

### Lane D2 — Admin dashboard UI (sequential)

#### D2a · §5.6b, 5.6c · Chart time zone + default range — size S
- **FILES:** `UsageCharts.jsx`, `AnalyticsPanel.jsx`, pure helper files, new tests. **Playbook:** 1499–1530 (rows 5.6b, 5.6c).
- **Tests:** UTC 23:30 on day X renders day X+1 00:30 in `Africa/Kampala`; default "Last 24 hours" when all data is within 24 h.

#### D2b · §5.6d · Load-test advice formula — size S
- **Tests:** `expected_peak = voters × share_in_busiest_hour × (avg_session_seconds / 3600)`; `(1500, 0.40, 180) → 30`; 1.5–2× gives 45–60.
- **FILES:** the load-test advice helper + `AnalyticsPanel.jsx` call site, new test. **Playbook:** row 5.6d.

#### D2c · WP-9.1 + 9.2 · Insights card + tagged-link builder (§6.1, 6.2) — size M
- **FILES:** `src/insights.js` (new, `buildInsights(summary)`), `src/linkBuilder.js` (new), their components, new tests. **Playbook:** 1531–1539 (items 1, 2).
- **Tests:** one fixture per sentence; zero/empty data gives **no** `NaN%` and no divide-by-zero; no IDs or names in output; each channel (`whatsapp, facebook, class-group, poster-qr, sms`) builds `https://<host>/?src=<tag>`; invalid custom tag rejected (`^[a-z0-9_-]{2,40}$`).

#### D2d · WP-9.4 · Alert panel (§6.4) — size S
- **Tests:** each threshold state maps to the right label; **read-only** (no POST). **FILES:** new panel + mount in the analytics tab, new test. **Playbook:** item 4.

#### D2e · §1.2 line · "Tracking of funnel steps started on <date>" — size XS
- **Depends on:** D1b merged. **FILES:** `AnalyticsPanel.jsx`, new test. **Tests:** line shown only when `tracking_since` is non-null.

#### D2f · §5.5 · Failure-reason labels — *verify first*
- `DEVIATIONS.md` lists 5.1, 5.2, 5.4, 5.6a and 5.7 as done and does **not** mention 5.5 in either table. **Pre-check:** `grep -n "set_reason(" backend/main.py` and compare with `REASONS` in `FunnelPanels.jsx`. If every code already has a label, write `progress/D2f.md` saying "already complete" and stop. If not, add the labels (test: every code has a label; an unknown code renders raw without crashing). Put it in lane D2 order after D2e.

### Lane E — Bootstrap endpoint (optional, after A and B merged)

#### E1 · §3.3 · Single `/public/bootstrap` — size M — **done** (`progress/E1.md`)
- **Goal:** one request replaces several startup calls. **Tenant-scoped with `org_query`, cache keyed by org, no secrets or voter data in the response.**
- **FILES:** `backend/main.py`, the startup fetch in `App.jsx` and `ApplicantPortal.jsx`, new backend and frontend tests. **Playbook:** 1171–1246, rules A1.6 (lines 11–22), A4 (87–101).
- **Tests:** cross-tenant case (org A response never contains org B data); the old endpoints still work; response contains only public fields.

### Custom tasks (added by the owner, not part of the lane plan)

#### CUSTOM-1 · Voter statistics back in the superadmin Voters section — size S — **done**
- **FILES:** `backend/main.py` (new `GET /admin/voters/stats`), `frontend/src/components/VoterStats.jsx` (new), `SuperAdminDashboard.jsx` (Voters sub-tabs), two new test files.
- **Result:** Voters tab = Register / Statistics / SMS. Totals backend 295, frontend 256. Record: `progress/CUSTOM-1.md`, `DEVIATIONS.md` ("Custom tasks"), branch `improvements/custom-voter-stats`.
- **Merge:** like any card (§5). Touches `SuperAdminDashboard.jsx`, so merge it before any later card that edits the Voters tab.

### Lane F — Closers (after everything else, one at a time)

#### F1 · WP-7f · `data-track` names (§4.5, 4.6) — size M (touches many files, so it goes last)
- **FILES:** many `.jsx` files (attributes only, no logic), `frontend/scripts/check_data_track.py` (new). **Playbook:** 1475–1498 (script is included there).
- **Rules:** names match `^[a-z0-9_-]{2,40}$`; never IDs or names. Payment number tap-to-copy with `document.execCommand('copy')` fallback, Copy target ≥ 44 px.
- **Tests:** `python frontend/scripts/check_data_track.py` passes (all required labels exist, all valid); existing UI tests still pass.

#### F2 · WP-H · Housekeeping (§7) — **decisions are yours, not the AI's**
- Already done: `usePolling.js` copy removed, `backend/test_flows.py` merged and removed. Still open and **needing your answer first:** pnpm lockfiles; which of Procfile / Dockerfile / railpack is the live host; which `demo_results_mode*.py` to keep. Tell the AI the decision, then it does a "diff before delete" removal with tests before and after. **Playbook:** 1540–1554.

#### F3 · Final acceptance (Part E)
- Merge `progress/*.md` and `deviations/*.md` into one `DEVIATIONS.md`; run the global checks. **Playbook:** 1555–1674 (read E2 and E3 only, about 40 lines).

---

## 5. Merging a finished phase back into `integration`

Do this one phase at a time, in the order phases finish.

```bash
# 1. In the phase worktree: pull in anything merged since you branched, and re-test.
cd ../bb-<ID>
git merge integration                      # conflicts? see "Conflict rule" below
(cd backend && pytest -q | tail -5)        # frontend: npm test --silent | tail -8 ; npm run lint | tail -3 ; npx vite build | tail -4

# 2. In the main repo folder: merge with a visible merge commit, then re-run the full suites.
cd ../"Multi-Tenant Voting System"
git checkout integration
git merge --no-ff improvements/<ID> -m "Merge <ID>"
(cd backend && pytest -q | tail -5); (cd frontend && npm test --silent | tail -8 && npm run lint | tail -3)

# 3. Mark it, and clean up.
git tag done/<ID>
git worktree remove ../bb-<ID>             # branch stays in history; delete only if you want
```

**Rollback of a bad merge:** `git revert -m 1 <merge-commit>` (keeps history, undoes the phase). Because every phase is a separate `--no-ff` merge, any phase can be undone alone.

**Conflict rule (give this to the AI if a merge conflicts):**

```
Resolve the conflict by KEEPING BOTH sides' intent. Never delete the other phase's lines to make yours fit.
Only touch conflicted hunks. Then re-run the tests of BOTH phases (their test files are named after the phase)
plus the full suites. Commit as "merge <ID>: resolve conflict in <file>". If you cannot keep both, stop and report.
```

**Re-sync long-running phases:** if a phase takes a while, run `git merge integration` into it once mid-way, not at the very end.

---

## 6. `progress/<ID>.md` template (one per phase; this is what "recorded in git" means)

```markdown
# <ID> — <title>
status: done | partial | blocked
branch: improvements/<ID>
commits: <sha> <message> (one per line)
tests added: <file names and count>
results: backend <N passed, M failed> · frontend <N passed, M failed> · lint <e/w> · build <ok/fail + entry chunk KB>
baseline at branch cut: backend <N> · frontend <N>
deviations: <none | list, or see deviations/<ID>.md>
HUMAN checks pending: <list or none>
next step (only if partial): <exact file and action>
```

---

## 7. Token-saving rules (the part that stops "all tokens, no output")

1. **One card per session.** If a card still feels big, split it again by sub-step (see how WP-6e became B1–B3) and commit between sub-steps.
2. **Never paste the whole playbook.** Cards give line ranges; the AI uses `sed -n A,Bp`.
3. **Tests first, targeted while working, full once at the end.** Full suites are the most expensive repeated command.
4. **Trim output.** Always `| tail -15` (or `-5` for green runs). Never print diffs of whole files; use `git diff --stat`.
5. **No exploration.** The card names the files. If the AI wants to open others, that is a signal to stop and report, not to browse.
6. **Commit early, commit green.** Every green sub-step is a safe resume point; a session that runs out of budget still leaves usable work.
7. **Resume prompt for a partial phase:**
   ```
   Resume phase <ID>. Read only progress/<ID>.md and the card in BALLOTBOX_PHASE_RUNBOOK.md.
   Continue from "next step". Same rules as before. Do not redo finished sub-steps.
   ```
8. **Ask for a short report.** "≤ 10 lines" is in the prompt on purpose.

---

## 8. What stays with you (no AI can do these)

From `DEVIATIONS.md` → HUMAN steps: check git history for `backend.env`, `frontend.env`, `backend/loadtest.env` and rotate anything ever committed or shared (the zip you shared contained them); the §1.2 version-skew check **before** anyone touches analytics for "zero" numbers (relevant to lane D1/D2); confirm new indexes in Atlas; schedule a `GET /health` keep-warm ping during the election window; test on a low-end Android on Slow 3G (splash, OTP paste/autofill, vote with network dropped, apply uploads, Turnstile on); set the optional `SETTINGS_CACHE_TTL_S` env var if you want something other than 5 s. Plus every **HUMAN** line in the cards above.

---

## 9. Quick reference

| I want to… | Do |
|---|---|
| Start a phase | §1 worktree command → paste §2 prompt |
| Run two at once | pick two cards from **different lanes** (§3) |
| Merge a finished phase | §5 |
| See what is done | `git tag -l "done/*"` and `ls progress/` |
| Undo one phase | `git revert -m 1 <its merge commit>` |
| Recover from a stalled session | commit what is green, then use the resume prompt (§7.7) |

*Caveat: this runbook was built from `DEVIATIONS.md` and the playbook text. The code inside the zip and `CHANGES_SINCE_UPLOAD.diff` were not re-inspected, which is why every card starts with a Pre-check that must pass before any edit.*

## Performance tab: during voting (H6 to fill in)

Open Superadmin, Platform, Performance. Decide beforehand who watches it and what they do at each alert. Suggested starting point, to be confirmed by the team: **Busy** (warn) keep watching; **Critical** pause results polling and SMS bursts; **Throttling** ask voters to retry in a minute. Keep the host warm during the election window so the in-memory window is not lost on a cold start (H7). Settings (tier, caps, thresholds) are edited in the tab and need no redeploy.
