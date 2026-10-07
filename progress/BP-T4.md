# BP-T4 — Ballot flow
status: done
branch: improvements/BP-T4 (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: components/BallotBox.template.test.jsx (11) + contrast row ['ai','no'] in templates/blueprint/contrast.test.js (+2) = 13 new; 431 total
results (default):   frontend 431 passed, 0 failed · lint 0/0 · build ok, entry gz 34,929 B
results (blueprint): frontend 431 passed, 0 failed · build ok, entry gz 35,536 B, blueprint chunk gz 7,591 B
baseline at branch cut: frontend 418 · entry gz 34,777 B (BP-T0 baseline; G1 allows +1,536 B)
gates: G1 pass · G2 pass · G3 pass (431 = 431) · G4 `data-track labels OK` · G5 lint 0/0
files:
- BallotBox.jsx (seams only): `bp = getTemplate()` after all hooks; StepBar, PositionHeading, CandidateRow, BottomDock branches; modal buttons take class hooks (`k?.btn|ghost|danger|row2`) and drop inline style only when `k`; S2 swaps for the loading colour, preview banner, h1, modal titles, summary position label. Default branches are the original JSX, untouched.
- templates/blueprint/: BottomDock.jsx (publishes/clears --bottom-bar-height, ResizeObserver-guarded), BallotParts.jsx (PositionHeading keeps `position-header`; CandidateRow), primitives.jsx (+StepBar, +Avatar), labels.js (cls: danger, row2, block), index.js exports, blueprint.css (+dock last-child 2x, .bp-block, avatar img, tick icon, .bp-btn.bp-danger).
decisions applied: E7 (StepBar 2/3, decorative), D3 (h1 uses --bp-tx on the page background, not accent; accent text only on card surfaces), D2.
deviations from the card/guide:
- G1 grep: the guide's `grep -l "bp-"` also matches S2 fallback tokens such as `var(--bp-no, #e11d48)`, which the guide itself prescribes for default JS. scripts/check_template_build.sh now forbids only bp- CLASS names (`(?<![-\w])bp-`). Still proves no blueprint classes/chunk in the default build.
- New file BallotParts.jsx (not in the card's FILES list) to keep PositionHeading/CandidateRow out of primitives.jsx; labels.js, index.js, contrast.test.js and scripts/check_template_build.sh also touched (exports / test row / gate).
- Candidate rows are `role="button"` + `aria-pressed` + Enter/Space + tabIndex 0 in blueprint only (default rows are bare divs with onClick). Needed for the R10 keyboard floor; no handler or state change. Say if you want it dropped.
- Solid-fill colours in the modals use classes (.bp-btn / .bp-danger on `--bp-ai` ink), not S2 `--bp-*-solid`; T9's solid-fill audit therefore has nothing left in BallotBox.
- Success/done view is NOT in BallotBox (it is App step 3/4 after `onVoteSuccess`), so it is not restyled here. T3 also deferred step 4 to this card. Needs an App.jsx seam: assign it to T2's follow-up or T9.
- Review modal stays a modal (E5); no change to countdown, castingRef lock, status check or statusModal logic.
findings (not fixed, per card):
- InlineHelpButton is referenced only in App.jsx comments; BallotBox renders no Help button. The Help FAB reads --bottom-bar-height (HelpTriggers.jsx:74, HelpPanel.jsx:134), which the default ballot never publishes (footerBarStyle has no useReportedHeight). In blueprint the dock now publishes it, so the FAB clears the dock; in default the FAB can overlap the fixed footer as before.
- Default markup renders `<img src="">` for candidates with no photo (React warns in tests). Blueprint avoids it by showing initials.
not covered by jsdom (HUMAN): 40+ candidates scroll smoothly; dock never covers the last candidate or the Help button (bottom padding 120 px kept); notched iPhone safe area; selected row readable without colour (tick + outline); real-phone tap targets (row min 72 px, dock buttons 48 px); light/dark; 360x640 keyboard-open behaviour of the review modal.
HUMAN checks pending: the list above, with `VITE_UI_TEMPLATE=blueprint npm run dev`, mockup deep links `#p=ballot` and `#p=review`.
next step: BP-T5 (results) and BP-T6 (apply) are independent and can run next; the done view needs an App.jsx seam (see deviations).
