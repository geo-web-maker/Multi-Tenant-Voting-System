# D2c — WP-9.1 + 9.2 Insights card + tagged-link builder
status: done
branch: improvements/D2c
tests added: src/insights.test.js (9), src/linkBuilder.test.js (19), src/components/D2c.components.test.jsx (6)
results: backend 293 passed · frontend 159 passed (125 + 34) · lint 0 · vite build OK
change: pure `insights.js` (`buildInsights`) and `linkBuilder.js` (`buildTaggedLink`, five channels, tag rule ^[a-z0-9_-]{2,40}$); `InsightsCard.jsx` and `LinkBuilder.jsx` mounted in AnalyticsPanel (insights under the alert panel, link builder under Traffic channels).
choices to review (not specified by the card):
 - Vote→Apply sentence = application-form sessions as a share of voter-login sessions (funnel step values). It is a ratio of two separate counts, not a same-session conversion, and the wording says so.
 - "3G/unknown" share uses network labels `3g` and `unknown`; the load figure is the highest p95 of those two (merged p95 cannot be recomputed from the summary).
 - Reason codes are shown with underscores turned into spaces (e.g. "not on roll"), because the friendly label map lives in FunnelPanels.jsx, outside this card's FILES.
 - The builder's host defaults to the host of the page the admin is on; pass `host` if the voter site differs from the admin site.
HUMAN checks pending: read the five sentences against a real summary once; confirm the host in the generated link is the voter-facing one.
