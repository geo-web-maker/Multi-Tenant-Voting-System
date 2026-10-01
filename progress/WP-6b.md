# WP-6b — Stop the typing placeholder re-rendering App (card A4)
status: done (revised: animation kept, extracted)
branch: improvements/WP-6b (revision committed on integration)
commits: see git log
tests added: frontend/src/App.placeholder.test.jsx (2)
results: backend not re-run (frontend-only; baseline 275 passed) · frontend 68 passed, 0 failed · lint 0/0
baseline at branch cut: backend 275 · frontend 66
deviations: human chose the playbook's alternative option: typing animation kept, effect + 4 states moved into frontend/src/components/VoterLoginInputs.jsx (renders the two voter inputs); App owns no animation state
HUMAN checks pending: React DevTools Profiler shows no App re-renders while idle on the login screen
