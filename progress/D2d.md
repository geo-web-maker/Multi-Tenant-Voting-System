# D2d — WP-9.4 Alert panel (card D2d)
status: done
branch: improvements/D2d-panel (the original improvements/D2d branch only holds the earlier blocked note)
commits: see git log; backend half merged first as D2d-be
tests added: frontend/src/alertState.test.js (3), frontend/src/components/AlertPanel.test.jsx (5)
results: backend 293 passed · frontend 125 passed (117 + 8) · lint 0 · vite build OK
change: new `alertState.js` (pure state/label mapping), new `AlertPanel.jsx` (read-only), mounted in AnalyticsPanel.jsx above the funnels. Labels: Healthy / Warning / Critical; hidden when the backend sends no `alerts` field.
HUMAN checks pending: look at the panel once in the real analytics tab, and confirm the Warning colour (`--warning` falls back to #d98e04) suits your theme.
