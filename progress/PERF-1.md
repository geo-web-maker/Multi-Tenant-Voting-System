# PERF-1: Performance audit fixes (items 1 to 5)

Source: `PERFORMANCE_AUDIT.md`, section 5. Item 6 (load test on a real cluster) is not code and is not done.

## Done
1. **Indexes** (`PERF_INDEXES`, `_ensure_perf_indexes`, called from `lifespan`): otps, admin_otps, revoked_tokens, panel_members, applications, candidate_tokens, certificates, organizations, voters (org_id, has_voted). Created one by one; a failure is logged and skipped.
2. **Public results cache** (`_RESULTS_TTL`, env `RESULTS_CACHE_TTL_S`, default 5 s): per organisation, keyed by `results_released`. Dropped by `invalidate_settings`, so opening, closing or certifying shows at once.
3. **Cached settings on the voter path**: election_config in `/verify-identity` and in `assert_voting_allowed`, branding in the SMS text. Branding save now calls `invalidate_settings(org, "branding")`.
4. **Shared SMS HTTP client** (`_sms_http`): keep-alive, connect timeout 5 s, read timeout unchanged at 15 s, closed on shutdown, rebuilt if the event loop changes.
5. **bcrypt off the event loop**: `verify_password_async` at all 10 handler call sites, and the dummy comparison in the commissioner login.

## Deviations from the audit
- Index key order is `(student_id, org_id)` / `(panel_member_id)` rather than org-first, so lookups without an `org_id` use the same index.
- The audit's "`sms_usage` read 3 times" finding was wrong (mock internals); nothing was changed for it. Counts in the audit are corrected in its section 0.

## Not done (out of the five items)
- `/vote` double candidate count, `/election-status` (already cached), admin-guard caching (deliberately left uncached for instant logout), worker count.

## Behaviour to know
- Public results can lag live votes by up to 5 s. A single worker is assumed: `invalidate_settings` is per process, so with several workers another worker could lag by up to 5 s after an election is closed.

## Tests
`backend/tests/test_performance_budget.py` (14 tests). `backend/tests/opcount.py` counts application-level DB calls. `conftest.py` switches the results cache off for the other tests, as it already does for the settings cache.
