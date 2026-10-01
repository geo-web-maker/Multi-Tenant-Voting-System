# D1a — §5.3 usable_ms (card D1a)
status: done
branch: improvements/D1a
commits: see git log on this branch
tests added: backend/tests/test_analytics_usable.py (6) · frontend/src/analytics.usable.test.js (4)
results: backend 287 passed · frontend 72 passed, 0 failed · lint 0/0 · build ok (entry chunk 94.5 KB)
baseline at branch cut: backend 281 · frontend 68 (all existing analytics tests still pass)
deviations: card FILES excludes App.jsx / VoterLoginInputs.jsx, so "login form interactive" is detected inside analytics.js: markUsable() fires when input[name="voter-reg-no"] is in the DOM (checked at init, then a MutationObserver that disconnects on match or after 20 s). Entry pages other than voter login never match and send no usable_ms (backend treats missing/0 as "no sample").
notes: usable_ms = performance.mark('usable').startTime (ms since navigation start), sent inside the existing once-per-session perf event; backend clamps 0..60000, stores histogram `us.<bucket>` (USABLE_EDGES = 500,1000,2000,3000,5000,8000) and returns usable_p50/usable_p95 on summary `perf` and `network_perf` rows. Not yet shown in the dashboard (lane D2). If perf is sent before the form renders, usable_ms is 0 and ignored for that session.
HUMAN checks pending: on a real phone, load the voter login and confirm a `usable` entry in DevTools Performance (performance.getEntriesByName('usable')).
