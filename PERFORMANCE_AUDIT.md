# BallotBox Performance Audit

Scope: backend request paths (voting, OTP, results, admin guard), database access and indexes, and front-end polling and bundling.

## 0. Update: fixes applied, and corrections to the first version

Items 1 to 5 of section 5 are now implemented (see `progress/PERF-1.md`) and covered by `backend/tests/test_performance_budget.py`. Full backend suite: 397 passed.

Two corrections to the first version of this audit, found while implementing:

- **The "`sms_usage` is read 3 times" finding was wrong.** Only one of the three reads is real. The other two were internals of the mock database that my first counter picked up. No change was made for it.
- **Per-voter cost is 29 calls, not about 34.** The first counts included those mock internals. Re-measured at the application level (what `main.py` itself asks Mongo for): `/verify-identity` 13, `/verify-otp` 10, `/vote-bulk` 6.

| Per request (warm cache) | Before | After |
|---|---|---|
| `/verify-identity` | 13 | 11 |
| `/verify-otp` | 10 | 10 |
| `/vote-bulk` | 6 | 5 |
| **Per voter** | **29** | **26** |
| One results-page poll | 3 | 0 on a cache hit (at most one recompute per 5 s per organisation) |

At 100 ops/s the per-voter ceiling moves from about 3.4 to about 3.8 voters/s, so the larger win is the results cache and the indexes, not this trim. The load test (item 6) is still yours to run.

## 1. Bottom line

The code is generally well built for speed (see section 6). The real risk is not slow code. It is **the number of database operations each voter costs, set against the ceiling of a free Atlas M0 cluster**.

Atlas documents Free (M0) clusters as limited to **100 read and write operations per second**. Beyond that, operations queue and wait more than a second.

| Item | Value | Basis |
|---|---|---|
| `POST /verify-identity` | 13 DB calls | measured at application level, warm cache (first version said 15) |
| `POST /verify-otp` | 10 DB calls | measured (first version said 12) |
| `POST /vote-bulk` | 6 DB calls | measured with the transaction stubbed out (first version estimated 7) |
| **Total per voter** | **29** | first version said about 34 |
| Theoretical ceiling at 100 ops/s | about 3.4 voters/s, roughly 200 voters/min | **before** any other traffic |

Every wrong code, resend, results-page view and admin screen then competes for the same 100 ops/s. If all students vote at once (you have said they may), the queueing will be visible to voters.

## 2. How this was measured

- **Measured:** round trips per request, counted by wrapping every database call while running the real endpoints against the test database, with the production settings cache switched on and caches warm.
- **Estimated:** `/vote-bulk` (the mock database cannot run transactions) and anything marked "about".
- **Not measured:** real latency, query plans (`explain()`), Atlas metrics, SMS provider speed. These need a real cluster. See section 7.

## 3. Findings

### P1-1: Per-voter operation count versus the 100 ops/s cap
Detail is in section 1. Fixes are in P1-2, P2-1 and P2-2. Reducing operations per voter raises the ceiling directly.

### P1-2: `/election-results` is uncached and scales with viewers
Each public results view costs about 4 operations: a voter count, an aggregation over **all** `vote_events` for the org, a candidates read and a settings read. The front end polls every **10 s** while voting is open, plus `/election-status`.

- 100 open results pages is about 50 ops/s, half the whole cluster.
- The aggregation also grows with turnout, since there is one event per position per voter.

Fix: cache the public payload in memory per org for 5 to 10 s, and send `Cache-Control: public, max-age=10`. This makes cost per org constant instead of per viewer. The admin and gated branches must bypass the cache. This is a product decision: results would lag by up to 10 s.

### P1-3: Hot lookups with no index created by the app
`lifespan` creates indexes for only some collections. Nothing is created for these. If you made some by hand in Atlas, they are reused, so please check Atlas before applying.

| Collection | Queried by | Suggested index |
|---|---|---|
| `otps` | `/verify-identity`, `/verify-otp`, per voter | `(student_id, org_id)` |
| `admin_otps` | `/verify-otp` fallback | `(student_id, org_id)` |
| `revoked_tokens` | **every authenticated admin request** | `jti` |
| `panel_members` | admin guard, `log_action` and 27 call sites | `(panel_member_id)`, `(student_id, org_id)` |
| `applications` | 44 call sites, filtered by status, sorted by `submitted_at` | `(org_id, status)`, `(org_id, submitted_at)` |
| `candidate_tokens` | applicant status page | `token`, `(org_id, round_id, student_id)` |
| `certificates` | public certificate verify | `certificate_id` |
| `organizations` | slug lookup (cached 60 s) | `slug` |
| `voters` | results turnout count | `(org_id, has_voted)`; the existing `has_voted` index is not org-prefixed |

`otps` matters most. Codes live 10 minutes, so on election day it can hold thousands of documents, and each voter request scans it. Implemented with `student_id` and `panel_member_id` first, so one index also serves lookups that carry no `org_id` (for example `log_action`). Each index is created on its own, so a conflict with one made by hand in Atlas cannot stop the app starting.

### P2-1: Redundant reads on the voter path
- ~~`/verify-identity` reads `sms_usage` 3 times.~~ **Retracted**: only one read is real (see section 0).
- Only 4 places use the 5 s settings cache, while **32** call `db.settings.find_one` directly. Election config and branding are read directly in `/verify-identity`, and election config and phases are read directly again at vote time.
- `/verify-otp` does a second lookup in `admin_otps` whenever `otps` has no match.

Fix applied: the direct election-config and branding reads now use `cached_setting`. Measured saving: 3 calls per voter (29 down to 26). Caveat: `invalidate_settings` is process-local. With one worker, closing an election takes effect immediately. With several workers, other workers lag by up to 5 s.

### P2-2: Per-request cost of the admin guard
Every authenticated admin request makes 2 extra round trips: a revocation lookup and an account lookup (voters or panel_members). The revocation lookup is unindexed (P1-3). I recommend **not** caching these, because instant logout and deactivation are security properties. Just add the index.

### P2-3: SMS sending
A new `httpx.AsyncClient` is created per SMS, which means a fresh TLS handshake every time. A slow provider holds the voter for up to 15 s, and a fallback can double that. Fix: one shared client with keep-alive, and an explicit short connect timeout. Keep the 15 s read timeout, because the "ambiguous" logic depends on a read timeout.

### P3-1: bcrypt blocks the event loop
`verify_password` and the dummy comparison call `bcrypt.checkpw` directly inside `async` handlers (about 5 login paths). Each login stalls every other request on the process for roughly 100 to 250 ms. Wrap them in `run_in_threadpool`, which the file already uses elsewhere.

### P3-2: Deployment shape
One uvicorn process, and a Render instance that sleeps when idle. Startup also runs about 35 `create_index` calls. Keep the instance warm before election day (an uptime ping on `/health`). Do not add workers until the in-process caches (settings, org, analytics buffer) are reviewed, because each worker would hold its own copy.

### P3-3: Minor
`/vote` runs `count_documents` on the candidate twice (once outside and once inside the transaction). `/vote-bulk` is the path the ballot uses, so this is low priority.

## 4. Front end

- Results polling: 10 s when open and 60 s otherwise. It stops once certified, pauses in background tabs and never overlaps requests. Good.
- The voter roll is fetched only every few ticks, not on every poll. Good.
- Vendor chunking is in place (React and axios split out), with 12 lazy-loaded modules.
- The roster-status hook polls every 60 s on admin screens. Fine.
- Not measured: actual bundle sizes. Run `vite build` and review the output if load time on slow mobile data is a concern.

## 5. Recommended order

| # | Change | Effort | Effect |
|---|---|---|---|
| 1 | Add the missing indexes (P1-3) | small | removes scans on the voter path and every admin request |
| 2 | Cache public results (P1-2) | small | removes viewer-driven load |
| 3 | Trim redundant reads (P2-1) | small to medium | about 34 down to about 26 ops per voter |
| 4 | Shared SMS client (P2-3) | small | faster code delivery |
| 5 | bcrypt in threadpool (P3-1) | small | no login stalls |
| 6 | Load test against a real cluster (section 7) | medium | replaces estimates with numbers |

Only after 1 to 3, if the load test still shows queueing, consider a paid Atlas tier for the election window. Check current tiers, pricing and whether you can move back down, given your irregular income.

## 6. What is already good

- Votes are append-only inserts in one transaction, with no shared tally document to contend on.
- Analytics counters are buffered in memory and flushed in batches.
- Settings cache (5 s) and org-slug cache (60 s) exist.
- Per-IP and OTP limiters are database-backed with TTL cleanup.
- Connection pool is sized (20) with a queue timeout, well under the 500-connection cap.
- GZip is on, and public bootstrap and candidates responses carry cache headers.

## 7. Not verified, and how to close the gap

1. Run `backend/loadtest/locustfile.py` against a staging copy with `DEBUG_MODE` on, and watch Atlas **Operations per second** and **Connections** while ramping to the real expected concurrency.
2. Run `explain()` on the voter lookups, `otps` lookups and the vote-event aggregation before and after the indexes.
3. Confirm in Atlas which indexes already exist.
4. Measure SMS provider latency from the Render region.
