# WP-7d — Results page states (card C1)
status: done
branch: improvements/WP-7d
commits: see git log on this branch
tests added: frontend/src/resultsState.test.js (9) · frontend/src/components/Results.state.test.jsx (4)
results: backend not touched (baseline 287 passed) · frontend 85 passed, 0 failed · lint 0/0 · build ok (entry chunk 94.5 KB)
baseline at branch cut: backend 287 · frontend 72
deviations: none. Card FILES = resultsState.js (new), Results.jsx, new tests. Uses existing /election-status fields (voting_phase, voting_opens_at); no backend change.
notes: states by priority: not_started (voting_phase 'not_started' and not open) > embargoed (results_released === false) > no_votes (turnout and candidate votes both 0) > live (open) > closed. not_started shows "Voting opens <date in Africa/Kampala>. Results will appear here live." and hides the banner (so no "Live Tallying"), turnout, candidate list, voter roll, turnout breakdown and the print button. no_votes shows "No votes yet." and hides the roll and breakdown. embargoed and live/closed render as before.
HUMAN checks pending: view /results on a phone before the voting window opens (message and date) and with voting open but zero ballots.
