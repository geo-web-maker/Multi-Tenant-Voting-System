# WP-6b — Stop the typing placeholder re-rendering App (card A4)
status: done
branch: improvements/WP-6b
commits: see git log on this branch
tests added: frontend/src/App.placeholder.test.jsx (2)
results: backend not re-run (frontend-only; baseline 275 passed) · frontend 68 passed, 0 failed · lint 0/0 · build ok (entry chunk 93.3 KB)
baseline at branch cut: backend 275 · frontend 66
deviations: none (playbook default option: effect and 4 states deleted, static placeholders from examples[0])
HUMAN checks pending: React DevTools Profiler shows no App re-renders while idle on the login screen
