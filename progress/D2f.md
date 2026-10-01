# D2f — §5.5 Failure-reason labels (card D2f, verify-first)
status: done (already complete, no code change)
branch: improvements/D2f
commits: see git log on this branch
tests added: none
results: not re-run (no code change) · baseline backend 287 · frontend 88
baseline at branch cut: backend 287 · frontend 88
deviations: none
notes: pre-check compared every literal reason code passed to `set_reason(request, "<code>")` (41 call sites) and every `ApiError(..., reason=...)` in backend/*.py against `REASONS` in frontend/src/components/FunnelPanels.jsx. 25 distinct codes found, 0 without a label. Unknown codes already fall back safely: `reasonLabel()` shows `HTTP <n>` for `http_<n>` and the raw code otherwise. Labels with no literal call site (`budget`, `captcha_required`, `guess_lock`) are kept; they are most likely set from helper modules and are harmless.
HUMAN checks pending: none
