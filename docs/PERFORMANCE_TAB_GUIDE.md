# BallotBox — Superadmin Performance tab: what to measure, how, and how to build it

Status: implemented in code (PERF-M0 to PERF-M7, see progress/PERF-M*.md); human checks H1 to H12 and the optional PERF-M3b are outstanding. Originally a design guide. Reference code in the appendices was **not executed** when this guide was written, with one exception: Appendix A (`resolve` and `validate`) was run against the precedence and validation cases in PERF-M0 and behaved as described. The gates in §11 verify the rest.

**Revision, 10 Oct 2026:** the recommended history sink is now **PostgreSQL** (`PERF_SINK=postgres`: §5.7, PERF-M5, H10 to H12, Appendix F), chosen over B2 so history is queryable and no bucket lifecycle rules are needed. This adds one named dependency exception (`asyncpg`, rule P5). The Postgres sink code in Appendix F was **not executed**; PERF-M5 tests and H10 to H12 verify it. B2 and the separate Mongo cluster remain available as options.

Written against the `ballotbox.zip` project as of 10 Oct 2026. Facts about the code were read from the source; facts about Atlas were checked against MongoDB's public documentation and **must be re-checked before election day** because plan limits change (HUMAN item H1).

---

## 0. Summary

| Item | Decision |
|---|---|
| Goal | A superadmin-only **Performance** tab that shows database operations per second against the cluster's cap, plus the other numbers that explain why the system is slow or about to be. |
| Why it matters here | On the Free tier Atlas allows **100 read and write operations per second**. Past that, Atlas throttles, adds a one-second cooldown per connection, and queued operations can wait more than a second. `PERFORMANCE_AUDIT.md` measured about 26–29 DB calls per voter, so the cap, not the code, is the election-day risk. |
| Tier is adjustable in the tab | The superadmin picks the tier and can set the ops cap, connection cap and thresholds from a **Settings card in the Performance tab**. Saved values live in the database and apply immediately, with no redeploy. Environment variables are only the defaults, and a Reset button returns to them. Every threshold is a percentage of the cap (§2). |
| How it is measured | The MongoDB driver's own command-monitoring hook gives **exact** counts of what this app sends. A request middleware gives latency, rate and errors. A small timer gives event-loop lag. Per-route and per-organisation attribution comes from the existing tenant-scoped collection wrapper (§5). |
| Cost to the database | The tab reads memory, not Mongo, so **watching it costs zero DB operations**. History is written as **one document every 5 minutes** (1 operation, about 0.003 ops/s, 288 a day), tagged so it is excluded from its own count. A **sink** setting sends that write to a separate service instead (recommended: a separate PostgreSQL database), so it uses none of the main cluster's operations at all (§5.7). |
| New dependencies | None by default (rule P5). The one exception is `asyncpg`, needed only when `PERF_SINK=postgres`, imported lazily. Memory and CPU come from `/proc` and the standard library. |
| Build size | Eight cards, PERF-M0 to PERF-M7 (§9). Roughly 700 lines of backend, 400 of frontend, 60 tests. |
| Known limits | Figures cover **this process only**, reset on restart or sleep, and do not include other clients of the cluster. Atlas's own console stays the source of truth for the cap (§12). |

---

## 1. Rules (apply to every card)

| # | Rule |
|---|---|
| P1 | **Metrics must never break a request.** Every hook is wrapped so an exception in metrics code is swallowed and logged once per minute at most. The app behaves identically with `PERF_ENABLED=false`. |
| P2 | **No personal data.** Record route templates (`/vote-bulk`), never raw paths. Record collection and command names, never filters, values, student ids, phone numbers or tokens. Reuse `analytics.route_template`. |
| P3 | **Zero DB cost to view.** The summary and timeseries endpoints read in-memory structures only. Only a request for history older than the in-memory window reads Mongo. |
| P4 | **Measurement must not distort what it measures.** Metric writes go to `perf_minutes`, are tagged, and are excluded from ops/s, per-route and per-collection counts. |
| P5 | **No new dependencies, with one named exception.** Standard library plus what `requirements.txt` already has. The exception is `asyncpg`, pinned in `requirements.txt` and imported **inside `PostgresSink` only**, so a deployment that does not choose `PERF_SINK=postgres` never loads it. No other package may be added. |
| P6 | **Superadmin only.** Every route uses `require_role("superadmin")`. The tab is absent for every other role. |
| P7 | **Bounded memory.** All structures are fixed-size rings or capped dictionaries. A route or collection that is not in the known list collapses into `(other)`. |
| P8 | **Default template is sacred.** Same rule as the Blueprint guide R1: new files and additive class names only on the default path. The tab must also look right in the Blueprint template (§7.4). |
| P9 | **Tier values are data, not code.** No limit number appears outside `perf_tiers.py`, the environment defaults and the saved settings document (§2). **Secrets are never editable in the UI or stored in the database**: sink connection strings stay in the environment. |
| P10 | **Runbook hygiene.** One card per session, tests first, commit green, `progress/PERF-<ID>.md`, never open or print any `*.env` file, never run against production. |

---

## 2. The tier variable

### 2.1 Environment variables (defaults)

These are the starting values. Anything marked **UI** can be overridden from the tab (§2.5); the rest are infrastructure and stay in the environment.

| Variable | Default | Meaning |
|---|---|---|
| `PERF_ENABLED` | `true` | Hard master switch (environment only). The tab also has a soft **Pause collection** control (§2.5). `false` removes every hook (listener, middleware, probe) and the tab shows "Performance monitoring is off". |
| `MONGO_TIER` | `free` | **UI.** Preset name from §2.2. Unknown values fall back to `free` and log a warning. |
| `DB_OPS_CAP` | *(from preset)* | **UI.** Operations per second the cluster allows. A positive number overrides the preset. `0` or `none` means **no hard cap**: threshold alerts are disabled and the gauge shows raw ops/s with no percentage. |
| `DB_CONN_CAP` | *(from preset)* | **UI.** Maximum connections the cluster allows. Same override rules. |
| `PERF_WARN_PCT` | `70` | **UI.** Percentage of the ops cap that is a warning. |
| `PERF_CRIT_PCT` | `90` | **UI.** Percentage of the ops cap that is critical. |
| `PERF_SLOW_COMMAND_MS` | `250` | **UI.** A DB command slower than this goes into the slow-command list. |
| `PERF_PERSIST_SECONDS` | `300` | **UI.** How often history is written (60 to 3600). `0` turns persistence off (memory only). |
| `PERF_SINK` | `mongo` | Where history is written: `mongo` (main cluster), `postgres` (**recommended**), `mongo_separate`, `b2`, or `none` (§5.7). Environment only. The default stays `mongo` so nothing breaks before a URL is set; set `postgres` for election day. |
| `PERF_POSTGRES_URL` | *(unset)* | Connection string for the metrics database. Required when `PERF_SINK=postgres`. Use a **separate database** from any application data. Must require TLS (for example `?sslmode=require`). Environment only, never shown in the UI. |
| `PERF_POSTGRES_POOLED` | `false` | Set `true` when the URL points at a pooler endpoint (PgBouncer, Neon's or Supabase's pooler). It turns off prepared-statement caching (`statement_cache_size=0`), which poolers do not support. |
| `PERF_MONGO_URL` | *(unset)* | Connection string for the separate metrics cluster. Required when `PERF_SINK=mongo_separate`. Environment only, never shown in the UI. |
| `PERF_MONGO_DB` | `ballotbox_perf` | Database name on the separate cluster. |
| `PERF_RETENTION_DAYS` | `14` | How long persisted history is kept. Mongo sinks: TTL index created at start. `postgres`: one `DELETE` after each successful flush. `b2`: not enforced by the app; set a lifecycle rule on the `perf/` prefix in the B2 console. Environment only. |

### 2.2 Presets (`backend/perf_tiers.py`)

```python
TIERS = {
    # name:   (ops_per_s_cap, connection_cap, note)
    "free":  (100, 500, "Atlas Free (M0): 100 ops/s; operations queue and are throttled above it."),
    # Add paid tiers here when you move. None = no hard ops cap; use CPU/latency instead.
    # "flex": (500, 500, "Verify against current Atlas Flex limits before use."),
    # "m10":  (None, 1500, "Dedicated: no ops cap; watch latency and connections."),
}
```

Only `free` ships filled in, because it is the one value this project has confirmed (MongoDB documents Free clusters at 100 operations per second, and older documentation listed the connection limit differently from newer pages, so the connection figure is the less certain of the two). When you change plan, pick the tier in the tab. If the plan is not in this table, choose **Custom** in the tab and type the caps; nothing here needs editing. Adding a line here only makes a plan appear in the dropdown by name.

### 2.3 Resolution order

For each setting, the first one that exists wins:

1. The value **saved from the tab** (document `perf_config` in the global `platform_settings` collection).
2. The environment variable.
3. The preset for the chosen tier.
4. The `free` preset.

`GET /superadmin/performance/config` returns the resolved values **and where each came from** (`ui`, `env`, `preset`), and the tab shows it ("Cap 100 ops/s · from Free preset"). A mismatch with what Atlas says is fixed in the tab, not in code (H1).

### 2.4 What changes with the tier

| Behaviour | Capped tier (Free) | Uncapped tier |
|---|---|---|
| Headline gauge | ops/s as a percentage of the cap | raw ops/s, no percentage |
| Voters-per-minute headroom | shown | hidden |
| Warn, critical, throttle-suspect alerts | on | off |
| Latency, pool, loop lag, errors, slow commands | on | on, and become the main signals |

### 2.5 Editing from the tab

**Who and what.** Superadmin only. The Settings card in the Performance tab edits:

| Field | Control | Validation |
|---|---|---|
| Tier | Dropdown: each preset, plus **Custom** | Must be a known preset or `custom` |
| Ops cap | Number, or the switch "No hard cap" | Whole number 1 to 100,000, or none |
| Connection cap | Number, or "No hard cap" | Whole number 1 to 100,000, or none |
| Warn at (%) | Number | 1 to 99, and below Critical |
| Critical at (%) | Number | 2 to 100, and above Warn |
| Slow command (ms) | Number | 10 to 10,000 |
| History write interval | Dropdown: Off, 1, 5, 15, 60 min | One of those values |
| **Pause collection** | Switch | Soft pause (below) |

Choosing a preset fills the caps from it. Editing a cap by hand switches the tier to **Custom** so the header never claims "Free" while showing a different number.

**Storage.** One document, `{name: "perf_config", values: {...}, version, updated_at, updated_by}`, in a **global** collection `platform_settings` (not tenant-scoped, because the cluster cap is a platform fact, not an organisation's). It is read once at start, cached in memory, and re-read only after a save (and once a minute if more than one worker ever runs, using `version`). A save costs 2 operations; reading costs none during normal running.

**Effect.** Applied immediately in memory with an atomic swap, no restart, no redeploy. Every threshold, status pill, alert rule and the headroom figure follow the new values on the next poll.

**Audit.** Each save writes one `perf_config_changed` entry through the existing `log_action`, with the old and new values and the actor. No reason field is required (display and alert thresholds only; nothing about security or election outcomes changes).

**Reset.** "Reset to defaults" deletes the saved document, so environment variables and presets apply again.

**Pause collection (soft).** The listener and middleware are installed at start, so a true off needs `PERF_ENABLED=false` and a restart. The soft pause makes every hook return immediately (one boolean check), stops history writes, and the tab shows "Paused". Use it if you ever suspect the monitor itself during a live election.

**Not editable here, on purpose:** `PERF_ENABLED`, `PERF_SINK`, `PERF_MONGO_URL`, `PERF_POSTGRES_URL` and retention. They are infrastructure or secrets, changed in the environment. The tab shows their current state read-only (sink type, last successful write, queue depth).

**Where to look at Atlas.** The card links the text "Check these against your Atlas plan" and states the date the preset values were last verified, so a stale number is visible.

---

## 3. What the code looks like today (facts that drive the design)

| Fact | Where | Consequence |
|---|---|---|
| One uvicorn process, no workers | `Procfile`, `Dockerfile` | In-process metrics are complete for the app. They would **not** be if workers are added (see §12). |
| Motor client with `maxPoolSize=20`, `minPoolSize=1`, `waitQueueTimeoutMS=2500` | `main.py` ~L359 | Pool exhaustion shows up as 2.5 s waits and then errors. Pool metrics are first-class. |
| Every tenant collection is reached through `TenantCollection` / `ScopedDB` | `tenant_db.py` | One choke point on the event-loop side where each operation can be attributed to a request and an organisation. |
| Global collections (`revoked_tokens`, `login_attempts`, `ip_rate_limits`, `otp_attempts`, `organizations`, …) use the raw `db` handle | `main.py` | The driver listener sees these; the wrapper does not. They appear as **unattributed** until the optional PERF-M3b proxy is built. |
| `analytics.py` already keeps per-minute, per-route counters for 5xx and 429, a latency histogram helper (`hist_percentile`, `_hist_index`), `route_template`, a background flusher and an alert evaluator | `analytics.py` | Reuse the helpers. Do not build a second route-naming scheme. |
| `alerts.py` provides `alert_warning` / `alert_critical` with cooldowns | `alerts.py` | Reuse it for performance alerts. |
| `tests/opcount.py` counts DB calls at application level for the performance budget tests | `tests/` | Its method list (`OPS`) is the reference for which methods are operations. The new code must agree with it. |
| `tests/test_tenant_scoping_lint.py` fails on new raw access to a tenant collection | `tests/` | The new module touches only `perf_minutes`, which is not a tenant collection. No allow-list entry is needed. |
| Superadmin tabs live in `tabGroups` in `SuperAdminDashboard.jsx`; the **Platform** group already holds Site Usage | `SuperAdminDashboard.jsx` ~L876–930 | The new tab goes in Platform, right after `usage_analytics`. |
| `main.py` is about 640 KB | repo | Keep new logic in new files (`perf_metrics.py`, `perf_tiers.py`, `perf_routes.py`); `main.py` only gets small wiring edits. |

---

## 4. Metric catalogue

"Source" says where the number comes from. "Accuracy" says how far to trust it.

### 4.1 Group A — Database

| ID | Metric | Definition | Source | Accuracy |
|---|---|---|---|---|
| A1 | **Ops per second (headline)** | Weighted operations in the last full second, plus 1 s / 10 s / 60 s averages and the peak in the last 15 min | Driver command listener (§5.1) | Exact for this app. Counts documents in a batch, not just commands (see note below) |
| A2 | **Ops cap utilisation** | A1 divided by the resolved cap, as a percentage | A1 and §2 | Same as A1 |
| A3 | **Commands per second** | Raw commands sent, unweighted | Listener | Exact |
| A4 | **By collection** | Weighted ops per collection over the window | Listener (collection from the command document) | Exact |
| A5 | **By operation type** | find, count, aggregate, insert, update, delete, other | Listener | Exact |
| A6 | **By organisation** | Weighted ops per organisation (slug) | `TenantCollection` hook (§5.2) | Covers tenant collections only |
| A7 | **By route, and ops per request** | Mean and p95 DB ops per request for each route | `TenantCollection` hook + middleware | Covers tenant collections only; the rest is shown as unattributed |
| A8 | **Unattributed share** | Listener total minus attributed total, as a percentage | A1 − A6 | Exact; this is the honesty check on A6 and A7 |
| A9 | **Command latency** | p50 / p95 / p99 of command duration, overall and by collection | Listener (`duration_micros`) | Exact; includes Atlas queueing when throttled |
| A10 | **Slow commands** | Last 50 commands slower than `PERF_SLOW_COMMAND_MS`: time, command name, collection, duration, route if known | Listener | Exact; no filter values stored (P2) |
| A11 | **Throttle suspect** | True when ops are at or above the cap **and** p95 command latency is high in the same minute | A2 and A9 | A strong hint, not proof |
| A12 | **Pool** | Connections in use, idle, pool maximum, requests waiting, wait-time p95, pool-timeout errors | Pool listener (§5.1) | Exact |
| A13 | **Command failures** | Failed commands per minute by command and error name | Listener | Exact |

**Weighting note.** A single `insert_many`, `bulk_write` or multi-update command carries many operations. Atlas's counters are documented as read and write *operations*, so the headline weights a command by the documents it carries: `insert` counts `len(documents)`, `update` counts `len(updates)`, `delete` counts `len(deletes)`, everything else counts 1. Raw commands are kept as A3. Whether Atlas weights exactly this way is verified in the load test (H4); if it does not, change one function (`_weight`) and nothing else.

### 4.2 Group B — HTTP

| ID | Metric | Definition | Source |
|---|---|---|---|
| B1 | Requests per second | Overall and by route template | Middleware |
| B2 | Latency | p50 / p95 / p99 per route and overall, in milliseconds | Middleware, histogram |
| B3 | In-flight requests | Current and peak in 15 min | Middleware counter |
| B4 | Status mix | 2xx / 4xx / 5xx per minute; 429 counted separately | Middleware (agree with the existing analytics counters) |
| B5 | Slowest routes | Top 10 by p95, minimum 20 requests in the window | B2 |

### 4.3 Group C — Runtime

| ID | Metric | Definition | Source |
|---|---|---|---|
| C1 | **Event-loop lag** | How late a 250 ms timer fires: current, p95 and max in 15 min. Catches blocking work such as bcrypt, which no per-route timing shows | Probe task |
| C2 | Process memory | Resident memory now and peak | `/proc/self/statm`, `resource.getrusage` |
| C3 | Process CPU | CPU time divided by wall time over the last minute | `time.process_time` |
| C4 | Uptime and cold starts | Seconds since start, start time, count of starts seen in persisted history | Process start time + rollups |
| C5 | Open tasks / threads | Counts, as a leak early warning | `asyncio`, `threading` |

### 4.4 Group D — Election-specific

| ID | Metric | Definition | Source |
|---|---|---|---|
| D1 | **Voters per minute headroom** | `(cap − current ops/s excluding the voter routes) ÷ measured ops per voter × 60`. Seeded with 26 (the audit figure) until the live per-voter figure exists | A1, A7 |
| D2 | Votes, OTP sends, OTP verifies and failures per minute | Counted at the existing handlers, as a single increment each | Counter calls added in PERF-M2 |
| D3 | SMS sends, failures and provider latency | Existing SMS functions, wrapped | Counter + timer |
| D4 | Cache hit rate | Settings, organisation and results caches | Hit/miss counters in the existing cache helpers |

### 4.5 Group E — Alerts (see §8)

Derived, not measured: warn, critical, throttle suspect, pool pressure, loop lag, 5xx burst, cold start.

### 4.6 What is deliberately not measured

- Per-user or per-student activity (privacy, P2).
- Query filter values and result bodies.
- Atlas-side metrics the app cannot see (other clients, disk, replication). Use the Atlas console for those.

---

## 5. How each measurement is taken

### 5.1 Database: the driver's command and pool listeners (A1–A5, A9–A13)

PyMongo, which Motor sits on, lets a client register listeners at construction. They are called for **every** command and every connection-pool event, with the command name, duration and request id. This is exact, needs no wrapping of call sites, and also sees the raw `db.<collection>` calls the tenant wrapper cannot.

Wiring (one edit at `main.py` ~L359):

```python
from perf_metrics import COMMAND_LISTENER, POOL_LISTENER, perf_enabled
client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URL, maxPoolSize=20, minPoolSize=1, waitQueueTimeoutMS=2500,
    **({"event_listeners": [COMMAND_LISTENER, POOL_LISTENER]} if perf_enabled() else {}),
)
```

Rules for the listener:

1. **It runs on driver threads, not the event loop.** Keep it O(1): one short lock, integer increments, no I/O, no awaits, no logging in the hot path.
2. **Ignore housekeeping commands**: `hello`, `isMaster`, `ping`, `saslStart`, `saslContinue`, `endSessions`, `buildInfo`, `killCursors`, `logout`. They are not application operations and Atlas does not count them as such. Keep this list in one constant.
3. **Collection name** is the value of the command's first key for `find`, `insert`, `update`, `delete`, `aggregate`, `count`, `distinct`, `findAndModify`; for `getMore` it is `command["collection"]`. Unknown shapes become `(other)`.
4. **Weight** (see §4.1 note): `insert` → `len(documents)`, `update` → `len(updates)`, `delete` → `len(deletes)`, else 1. `getMore` is counted but shown separately (A5) because it is a continuation, not a new query.
5. **Self-exclusion (P4).** A command on `perf_minutes` is dropped. The listener checks the collection name; no other tagging is needed.
6. **Duration** comes from `succeeded` / `failed` events (`duration_micros`). Match start to finish by `request_id` in a small dict that is popped on completion and capped at 4096 entries so a missed event cannot leak memory.

Pool metrics (A12) come from the pool listener: count `connection_checked_out` minus `connection_checked_in` for in-use; `connection_check_out_started` minus (`connection_checked_out` + `connection_check_out_failed`) for waiting; time between started and checked-out on the same thread (a `threading.local`) for wait time; and `connection_check_out_failed` with reason timeout for pool-timeout errors.

### 5.2 Attribution: which route and which organisation (A6–A8)

The listener cannot tell which request caused a command, because it runs on a driver thread without the request's context. Attribution therefore happens on the **event-loop side**, in `tenant_db.TenantCollection`, where each operation is issued:

1. The metrics middleware (§5.3) creates a small `RequestMetrics` holder per request and stores it in a `contextvars.ContextVar`.
2. `TenantCollection`'s method dispatch calls `perf_metrics.note_op(collection, method, weight_hint)` once per operation. The call reads the context variable, increments the holder, and returns. The holder is shared by reference, so it works across the task the framework creates for the downstream app.
3. When the request finishes, the middleware reads the route template, and adds the holder's count to that route's "ops per request" statistics and to the organisation's counters.
4. Work started outside a request (background tasks, the analytics flusher, backups) has no holder and is counted only by the listener. That is the correct result: it is real load with no route.

**Unattributed share (A8)** is `listener total − attributed total`. Today that gap is the global collections (`revoked_tokens` is read on **every authenticated admin request**, plus login, OTP and rate-limit collections). Showing the gap, not hiding it, is the point.

*Optional PERF-M3b:* wrap only the dozen hottest global collections in the same note-op proxy, so the gap shrinks. Do this only if A8 stays above about 15% on a load test. A global proxy over `main.db` is deliberately **not** recommended: transactions and sessions go through the client, and the risk outweighs the benefit.

### 5.3 HTTP: one outermost middleware (B1–B5)

Starlette runs the **last registered** middleware outermost. Register `perf_middleware` after `security_headers_middleware` in `main.py` so it also times requests the auth guard rejects, and so the context holder exists before any other middleware touches the database.

```python
@app.middleware("http")
async def perf_middleware(request, call_next):
    if not perf_enabled():
        return await call_next(request)
    holder = perf_metrics.begin_request()          # sets the ContextVar, bumps in-flight
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        perf_metrics.end_request(                   # never raises (P1)
            holder, route=route_template(request, status), status=status,
            ms=(time.perf_counter() - t0) * 1000, org=getattr(request.state, "org_id", None))
```

Latency uses the histogram edges already used by analytics (`hist_percentile`, `_hist_index`) so percentiles are comparable with the Site Usage tab. Streaming responses are timed to first byte, which is the right figure for this app (it has no long streams).

### 5.4 Event-loop lag (C1)

```python
async def _lag_probe(interval=0.25):
    while True:
        t = time.perf_counter()
        await asyncio.sleep(interval)
        record_lag_ms(max(0.0, (time.perf_counter() - t - interval) * 1000))
```

Started and cancelled in `lifespan` next to the analytics flusher. A healthy loop reports a few milliseconds. Sustained values above 100 ms mean something is blocking the loop (the audit's P3-1 bcrypt finding is the known candidate). This is the one metric that explains "everything felt slow but no route was slow".

### 5.5 Process (C2–C5), without a new dependency

- Resident memory: `int(open("/proc/self/statm").read().split()[1]) * os.sysconf("SC_PAGE_SIZE")`. On a platform without `/proc`, report `null` and the tab shows "n/a".
- Peak memory: `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` (kilobytes on Linux).
- CPU: `time.process_time()` delta divided by wall-clock delta, sampled once a second.
- Tasks and threads: `len(asyncio.all_tasks())`, `threading.active_count()`.

### 5.6 Storage in memory (P7)

| Structure | Resolution | Window | Size |
|---|---|---|---|
| Per-second ring: weighted ops, commands, requests, errors, loop-lag max | 1 s | 15 min (900 slots) | fixed arrays |
| Per-minute ring: everything above plus per-route, per-collection and per-org tables and latency histograms | 1 min | 24 h (1,440 slots) | a few hundred KB; route/collection/org tables capped at 64 keys each, overflow into `(other)` |
| Slow-command list | event | last 50 | fixed |
| Pool and process gauges | 1 s | latest + 15 min | fixed |

Each slot stores its epoch second or minute, so a slot from a previous lap is never mistaken for current data. The ring is cleared on restart; the tab shows "collecting since HH:MM".

### 5.7 Persistence and where history is written (sinks)

The live view never depends on any of this: it reads memory. Persistence only provides history across restarts and for the 7-day view.

**What is written.** One document per flush (default every 5 minutes) holding the finished minutes since the last flush as an array of compact rows. `_id` is the first minute's epoch, written with `replace_one(..., upsert=True)`, so a retry is idempotent. A TTL index on `minute_dt` expires old batches after `PERF_RETENTION_DAYS`. On the `postgres` sink the same epoch is the primary key, the write is `INSERT ... ON CONFLICT DO UPDATE` (also idempotent), and expiry is a `DELETE` after each successful flush.

**What it costs on the main cluster.** One operation per flush: 288 a day, about **0.003 ops/s, 0.003% of a 100 ops/s cap**. It is tagged and excluded from the ops/s figure (P4). A restart is stored as a gap (`null`), not zero.

**Sinks.** `PERF_SINK` chooses where the batch goes. All sinks implement the same three methods (`write`, `read`, `status`, Appendix F), so switching is an environment change.

| Sink | Operations used on the main cluster | Survives main-cluster throttling or outage | New secret or dependency | Notes |
|---|---|---|---|---|
| `mongo` (default) | 1 per flush | No: the write competes with voting traffic | None | Skipped automatically while ops are at or above the warn threshold; kept in the retry queue and written when load drops |
| `postgres` (**recommended for election day**) | **0** | **Yes** | One connection string (`PERF_POSTGRES_URL`) and the `asyncpg` library (the P5 exception) | A separate Postgres database (Neon, Supabase, or Render). Real history queries: 7 days or more with one `SELECT`. Retention is a `DELETE` after each flush. See "Postgres sink details" below |
| `mongo_separate` | **0** | **Yes** | One connection string (`PERF_MONGO_URL`); no new library | A second free Atlas project and cluster. Has its own 100 ops/s budget, so metrics can never starve voters and keep recording while the main cluster is throttled |
| `b2` | 0 | Yes | None: reuses the existing B2 client and bucket | Objects under `perf/YYYY/MM/DD/HHMM.json`. Cheapest to run, slowest to read (list then fetch), so the history view is limited to 24 h per request. Needs a lifecycle rule on the `perf/` prefix (including old file versions) because the app cannot expire objects, and the existing B2 client must be called from a thread executor if it is synchronous |
| `none` | 0 | n/a | None | Memory only. History is lost on restart |

**Write behaviour for every sink.**
- Fire-and-forget background task with a 5 s timeout. A request never waits for it.
- A bounded retry queue of 12 batches (one hour at the default interval). When full, the oldest batch is dropped and a counter increases. Backoff doubles from 5 s to 5 min.
- Status (`ok`, last success time, queue depth, dropped batches, last error text with no secrets) is shown read-only in the tab and available at `GET /superadmin/performance/sink`.
- **The separate-cluster client has its own small pool (`maxPoolSize=2`, `serverSelectionTimeoutMS=3000`) and no command listener**, otherwise its own traffic would be counted as main-cluster operations.

**Postgres sink details (`PERF_SINK=postgres`).**
- **Client:** `asyncpg` pool with `min_size=1`, `max_size=2`, `command_timeout=5`, connect `timeout=5`. Created lazily on the first flush and re-created after a failure. **No Mongo listener is attached** and the pool is separate from Motor, so its traffic is never counted as main-cluster operations.
- **Table** (created with `CREATE TABLE IF NOT EXISTS` on first write, so there is no migration step):

```sql
CREATE TABLE IF NOT EXISTS perf_batches (
    minute_epoch bigint      PRIMARY KEY,   -- first minute in the batch
    minute_dt    timestamptz NOT NULL,
    rows         jsonb       NOT NULL       -- the compact per-minute rows
);
CREATE INDEX IF NOT EXISTS perf_batches_dt ON perf_batches (minute_dt);
```

- **Write:** `INSERT ... ON CONFLICT (minute_epoch) DO UPDATE`, then `DELETE FROM perf_batches WHERE minute_dt < now() - make_interval(days => PERF_RETENTION_DAYS)`. A failing `DELETE` is logged once and does not fail the flush.
- **Read:** a single `SELECT` by `minute_epoch` range, which serves `/history` for up to 7 days per call.
- **Pooler URLs:** set `PERF_POSTGRES_POOLED=true` so `statement_cache_size=0` is used.
- **Providers (free tiers change; check H11):** Neon scales to zero, so the first write after idle can be slow, which the 5 s timeout and retry queue absorb. Supabase pauses inactive free projects. Render's free Postgres has a limited lifetime. Pick one that will stay up through the election window.
- **Separation:** use a database that holds only metrics. Do not share it with BallotBox application data, now or after any future Postgres migration.
- **Missing or bad URL:** `PERF_SINK=postgres` without `PERF_POSTGRES_URL` falls back to `none` and says so in sink status.

**Why not send live data to an external service every second?** The live view needs no service, and an extra network dependency in the middle of an election adds a failure point for no benefit. Batched history to a separate sink gives the isolation you want at a fraction of the complexity.

**Data sensitivity.** Batches hold aggregate counts, route templates, collection names and timings only (P2). Treat the connection string as a secret anyway.

### 5.8 Cross-checking against Atlas

On the Free tier Atlas's metrics view is limited, so this tab's number is the primary one. Two checks keep it honest (H4): run the load test while watching Atlas's real-time view, and compare. If Atlas reads higher, the gap is other clients or a different weighting; the listener weighting function is the single place to adjust.

---

## 6. API

All routes use `require_role("superadmin")` and are `GET` unless stated. Settings live in the global `platform_settings` collection and history in the configured sink; use `cross_tenant(db)` for those reads so the lint stays green and the door is greppable. Responses are JSON, never contain filter values, identifiers or connection strings, and set `Cache-Control: no-store`.

| Route | Reads | Returns |
|---|---|---|
| `/superadmin/performance/config` | memory | Resolved values **with their source** (`ui`, `env`, `preset`), `enabled`, `paused`, sink type, start time, `collecting_since`, preset list for the dropdown, and the date the presets were last verified |
| `PUT /superadmin/performance/config` | Mongo (2 ops) | Validates (§2.5), saves, swaps the in-memory config, writes the audit entry. Returns the new resolved config. `400` with a field-level message on invalid input |
| `POST /superadmin/performance/config/reset` | Mongo (1 op) | Deletes the saved document so environment and presets apply again |
| `/superadmin/performance/sink` | memory | Sink type, `ok`, last success, queue depth, dropped batches, last error |
| `/superadmin/performance/summary` | memory | The headline block (A1–A3, A11, A12, B1–B3, C1–C3, D1, active alerts). Cached for 2 s so many open tabs cost one computation |
| `/superadmin/performance/timeseries?window=15m` | memory | Per-second series for the last 15 min; `window=24h` returns per-minute series |
| `/superadmin/performance/breakdown?by=collection` (or `route`, `org`, `op`) | memory | Ranked tables (A4–A7, B2, B5), with `unattributed` |
| `/superadmin/performance/slow` | memory | Slow-command list (A10) |
| `/superadmin/performance/history?from=&to=` | the sink | Persisted minutes, limited to 7 days per call (24 h on the `b2` sink) and one page of 1,440 rows. Costs main-cluster operations **only** when the sink is `mongo`; the `postgres` sink answers from the metrics database |

Summary shape (abridged):

```json
{
  "enabled": true, "tier": "free", "uptime_s": 5321, "collecting_since": "2026-10-10T07:12:00Z",
  "db": {"ops_s": 37, "ops_s_10s": 31.4, "ops_s_60s": 22.8, "peak_15m": 88,
         "cap": 100, "cap_pct": 37, "headroom": 63, "commands_s": 29, "throttle_suspect": false,
         "latency_ms": {"p50": 3, "p95": 14, "p99": 41},
         "pool": {"in_use": 3, "idle": 2, "max": 20, "waiting": 0, "wait_p95_ms": 0, "timeouts_1h": 0},
         "unattributed_pct": 12},
  "http": {"rps": 11, "in_flight": 2, "p95_ms": 120, "s5xx_1m": 0, "s429_1m": 0},
  "runtime": {"loop_lag_ms": {"now": 3, "p95": 9, "max": 41}, "rss_mb": 142, "cpu_pct": 18},
  "election": {"voters_per_min_headroom": 140, "ops_per_voter": 26, "ops_per_voter_source": "audit"},
  "alerts": []
}
```

`ops_per_voter_source` is `"audit"` until at least 30 complete voter sequences have been observed, then `"measured"`.

---

## 7. The tab (frontend)

### 7.1 Placement and wiring

- `SuperAdminDashboard.jsx`: add `{ id: 'performance', label: <>Performance</>, icon: 'chart' }` to the **Platform** group after `usage_analytics`, and `{activeTab === 'performance' && <PerformancePanel />}` beside the other panels.
- New file `frontend/src/components/PerformancePanel.jsx`, plus a pure helper `frontend/src/perfFormat.js` (formatting and status colouring, unit-tested).
- Polling: every 5 s while the tab is visible **and** `document.visibilityState === 'visible'`; stop when either is false. One request (`summary`) per poll; `timeseries` and `breakdown` load once on open and then every 15 s.

### 7.2 Layout (phone first; one column, then a two-column grid above 768 px)

1. **Header line:** "Free tier · cap 100 ops/s · 500 connections", uptime, "collecting since …".
2. **DB load card:** large "37 / 100 ops/s", a bar to the cap, status pill (OK, Busy, Critical, Throttling), 10 s and 60 s averages, 15-minute peak. For an uncapped tier: the number only.
3. **Voter headroom card** (capped tiers only): "About 140 voters per minute before the cap" and the ops-per-voter figure with its source.
4. **15-minute chart:** ops/s line with the cap as a dashed line; a second small chart for request latency p95.
5. **Pool and latency:** connections in use against maximum, waiting, command p95.
6. **Runtime:** loop lag, memory, CPU.
7. **Where the load comes from:** tabs for **Collections**, **Routes**, **Organisations**, each a ranked table with ops/s, share, and p95. Always shows the **Unattributed** row.
8. **Slow commands** list and **active alerts**.
9. **History** control (24 h from memory; 7 days from the sink on demand, with a note that it uses main-cluster operations only when the sink is `mongo`).
10. **Settings card** (collapsed by default, §2.5): tier dropdown, ops cap, connection cap, warn and critical percentages, slow-command threshold, history interval, **Pause collection**, **Save** and **Reset to defaults**. Each field shows its source (UI, environment, preset). Invalid input is explained under the field; Save stays disabled until the form is valid and changed. A saved change shows a confirmation and the header updates at once.
11. **Sink line:** "History: separate cluster · last write 2 min ago · 0 queued" with a warning style if the queue is growing or batches were dropped.

Empty and error states: "Performance monitoring is off" (`enabled:false`), "Collecting data, give it a minute" (fresh start), "Could not load, retry" with the existing retry pattern. A cold start never shows a green "OK" with zero; it shows "No data yet".

### 7.3 Status rules (all derived from the cap, §2)

| Status | Rule (capped tier) |
|---|---|
| OK | below `PERF_WARN_PCT` |
| Busy | `PERF_WARN_PCT` to below `PERF_CRIT_PCT` |
| Critical | at or above `PERF_CRIT_PCT` |
| Throttling | A11 true: at or above 95% of the cap **and** command p95 above 800 ms in the same minute |

Uncapped tier: status comes from command p95, pool waiting and loop lag only.

### 7.4 Template compliance (Blueprint guide rules)

- No hex literals. Colours are `var(--…)` tokens, with `var(--bp-ok, <literal>)`-style fallbacks only where the existing screens already use them. The hex ratchet in `hexRatchet.test.js` must not rise.
- Form fields in the Settings card are 48 px tall in Blueprint with real `<label>`s; buttons and tap targets are at least 44 px in Blueprint. Follow the E15 pattern: a plain class (no `bp-` prefix, because the build check rejects `bp-` strings in default JS), with the 44 px rule in `blueprint.css` inside `@media screen`, no `!important`.
- Wide tables use the existing mobile card-row pattern (`data-l` labels) so they do not scroll sideways on phones.
- Copy is new chrome: add it to `DEVIATIONS.md` as the next free E-number, the way E16 records the vetting strings.
- Respect `prefers-reduced-motion`; no animated gauges.
- Charts reuse the helpers `AnalyticsPanel` already uses (`chartTime.js`). No new chart library (P5).

---

## 8. Alerts

Reuse `alerts.alert_warning` / `alert_critical` with a cooldown, evaluated by the persistence tick and by the summary computation. All percentage rules apply only to capped tiers.

| Kind | Rule | Level | Cooldown |
|---|---|---|---|
| `ops_warn` | ops/s at or above `PERF_WARN_PCT` of cap for 10 s | warning | 10 min |
| `ops_critical` | at or above `PERF_CRIT_PCT` for 5 s | critical | 5 min |
| `throttle_suspect` | A11 true | critical | 5 min |
| `pool_pressure` | waiting requests above 0 for 10 s, or any pool-timeout error | critical | 5 min |
| `loop_lag` | loop-lag p95 above 100 ms over 1 min | warning | 15 min |
| `latency` | overall HTTP p95 above 1,500 ms over 1 min with at least 50 requests | warning | 15 min |
| `cold_start` | process started within the last 5 min while an election phase is open | warning | once per start |

The alert body states the numbers and the cap in use, never identifiers. The tab shows active alerts and the last 20 fired.

---

## 9. Phase cards

One card per session. Tests first. Each card ends with the gates in §11 and a `progress/PERF-<ID>.md`.

#### PERF-M0 · Config and tier resolution — size S
- **Files:** new `backend/perf_tiers.py`, new `backend/tests/test_perf_tiers.py`, `backend/.env.example` (document the variables, no values that are secrets).
- **Do:** `TIERS` table; `resolve(saved)` returning each value with its source per §2.3; `validate(payload)` per §2.5; `perf_enabled()`; the global `platform_settings` load/save helpers with an in-memory atomic swap.
- **Tests:** default is `free` and 100/500; `MONGO_TIER=unknown` falls back and warns; `DB_OPS_CAP=250` overrides the preset; a saved value beats the environment; `0` and `none` give "no cap"; garbage falls back; validation rejects warn at or above critical, caps below 1, unknown tier, bad interval; editing a cap makes the tier `custom`; reset removes the saved document.
- **Done when:** no limit number exists outside `perf_tiers.py` and the environment (grep check in the test).

#### PERF-M1 · Collector, listener, rings — size M
- **Files:** new `backend/perf_metrics.py` (rings, histograms, `COMMAND_LISTENER`, `POOL_LISTENER`, `_weight`, `note_op`, `begin_request`, `end_request`), `main.py` (listener wiring at the client, §5.1), new `backend/tests/test_perf_metrics.py`.
- **Do:** Appendix A–C. Reuse `analytics.hist_percentile` and `_hist_index`.
- **Tests:** feed fake command events and assert ops/s, weighting (`insert` of 5 documents counts 5), ignored commands, `getMore` handling, `perf_minutes` self-exclusion, ring wrap-around and stale-slot rejection, request-id dict cap, listener exception safety (P1), thread-safety with 8 threads hammering the listener.
- **Done when:** with `PERF_ENABLED=false` the client is constructed exactly as before.

#### PERF-M2 · HTTP middleware, loop lag, process, counters — size S–M
- **Files:** `perf_metrics.py`, `main.py` (middleware registered last; probe started in `lifespan`; one-line counter calls in the vote, OTP and SMS handlers and the three caches).
- **Tests:** middleware records status and route template (never a raw path); it still records when the app raises; in-flight returns to zero; probe records a deliberate 200 ms `time.sleep` as lag; **a request with metrics on makes exactly the same number of DB calls as with metrics off** (extend the style of `test_performance_budget.py`).

#### PERF-M3 · Attribution through the tenant wrapper — size M
- **Files:** `backend/tenant_db.py` (one `note_op` call in the method dispatch), `perf_metrics.py`, tests.
- **Tests:** an operation inside a request is attributed to that route and organisation; an operation outside a request is not; ops per request for `verify-identity`, `verify-otp`, `vote-bulk` match `tests/opcount.py` (the budget tests are the oracle); `test_tenant_scoping_lint.py` and `test_tenant_db.py` still pass unchanged.
- **PERF-M3b (optional, only if A8 stays above about 15% under load):** note-op proxy for the hottest global collections.

#### PERF-M4 · API routes — size M
- **Files:** new `backend/perf_routes.py` (an `APIRouter` included from `main.py`), tests.
- **Tests:** every route (including `PUT` config and reset) returns 401/403 for non-superadmin and for an unauthenticated caller; `PUT` writes exactly one `perf_config_changed` audit entry with old and new values; a saved config takes effect on the next `summary` without a restart; an invalid `PUT` changes nothing; `summary` and `timeseries` make zero DB calls (assert with the counting DB); `history` is the only route that does; response contains no identifier-shaped values (regex check on a seeded run); cache behaviour of `summary` (two calls inside 2 s compute once).

#### PERF-M5 · Persistence and sinks — size M
- **Files:** new `backend/perf_sinks.py` (`Sink` interface, `MongoSink`, `PostgresSink`, `SeparateMongoSink`, `B2Sink`, `NullSink`, retry queue), `perf_metrics.py`, `main.py` (index creation beside the other startup indexes; sink chosen at start from `PERF_SINK`), `requirements.txt` (pin `asyncpg`), `backend/.env.example` (document `PERF_POSTGRES_URL` and `PERF_POSTGRES_POOLED`, no real values), tests.
- **Tests:** one document per flush and `replace_one` idempotent; TTL index exists; restart gap stored as `null`, not 0; with the `mongo` sink the write is skipped above the warn threshold and caught up later; with `mongo_separate` it is **not** skipped and uses **zero** main-cluster operations (assert with the counting DB); the separate client has no listener; queue is bounded at 12 and drops the oldest with a counter; a sink that raises or times out never raises into a request; `PERF_SINK=mongo_separate` without `PERF_MONGO_URL` falls back to `none` and says so in sink status; the write is excluded from ops/s.
- **Postgres tests:** `asyncpg` is **not imported** unless the sink is `postgres` (assert `"asyncpg" not in sys.modules` after starting with another sink); write is an upsert and a repeat of the same batch changes nothing; the retention `DELETE` runs after a successful flush and a failing `DELETE` does not fail the flush; with `PERF_POSTGRES_POOLED=true` the pool is created with `statement_cache_size=0`; the pool has no Mongo listener and a flush makes **zero** main-cluster operations (counting DB); a pool that cannot connect or times out raises into the retry queue only, never into a request; `PERF_SINK=postgres` without `PERF_POSTGRES_URL` falls back to `none` and says so in sink status; status never contains the URL or password. Use a fake pool object for CI; add one integration test that runs only when `PERF_TEST_POSTGRES_URL` is set.
- **B2 notes (only if `b2` is chosen):** the upload runs in a thread executor if the client is synchronous; document the lifecycle rule in H12.

#### PERF-M6 · Tab, formatting helper, template fit — size M
- **Files:** `frontend/src/components/PerformancePanel.jsx`, `frontend/src/components/PerformanceSettings.jsx` (the Settings card, §2.5), `frontend/src/perfFormat.js` and test, `SuperAdminDashboard.jsx` (two lines), `blueprint.css` (44 px rule), `docs/DEVIATIONS.md` entry, a static test in the style of `vettingTapTargets.test.js`.
- **Tests:** renders every state in §7.2 (off, paused, collecting, healthy, busy, critical, throttling, uncapped tier); the Settings card validates as the server does, disables Save until valid and changed, shows each field's source, switches the tier to Custom when a cap is edited, and Reset restores defaults;  polling stops when the tab or page is hidden; no raw hex added (ratchet); Blueprint rule exists and is scoped; default build has no `bp-` strings; the panel does nothing for a non-superadmin because the tab is not rendered.

#### PERF-M7 · Alerts, docs, load-test validation — size S–M
- **Files:** `perf_metrics.py` or `perf_routes.py` (alert evaluator, pure function like `analytics.evaluate_alerts`), `docs/PERFORMANCE_AUDIT.md` (add "measured in production" section), runbook note, `backend/loadtest/` note.
- **Tests:** the evaluator is a pure function: table-driven tests for every row of §8, including "no alerts on an uncapped tier" and cooldown behaviour.
- **HUMAN:** H3 and H4 below. The card is not done until the load test has been compared with Atlas.

---

## 10. Test plan summary

| Layer | What it proves |
|---|---|
| Unit, pure | Tier resolution, weighting, rings, percentiles, alert rules, status rules, formatters |
| Unit, concurrency | The listener is safe under threads and never raises |
| Integration (mongomock, as the existing tests) | Attribution, zero extra DB calls with metrics on, zero DB calls for `summary`/`timeseries`, auth on every route, no identifiers in responses |
| Static | New code touches no tenant collection raw; no limit numbers outside `perf_tiers.py`; no new hex; no `bp-` in default JS |
| Template | The tab renders under `VITE_UI_TEMPLATE=blueprint` and the full existing suite still passes (R9 of the Blueprint guide) |

Note: mongomock does not fire PyMongo command events, so listener tests feed event objects directly. The real-driver behaviour is confirmed in H3.

---

## 11. Gates (copy-paste)

```bash
# backend/
python -m pytest -q
python -m pytest -q tests/test_perf_tiers.py tests/test_perf_metrics.py tests/test_perf_routes.py \
                    tests/test_tenant_scoping_lint.py tests/test_performance_budget.py

# frontend/
npm test
npm run lint
VITE_UI_TEMPLATE=blueprint npm test
BASELINE_ENTRY_GZ=<bytes> bash scripts/check_template_build.sh
```

Pre-existing failures in your zip (9 backend, 3 frontend, as recorded in the earlier session) are not caused by this work; the gate is "no **new** failures".

---

## 12. Known limits (say these out loud on the tab's help text)

1. **This process only.** Other clients of the same cluster, and Atlas's own housekeeping, are invisible here. Atlas's console is the source of truth for the cap.
2. **Single worker.** If workers are ever added, each holds its own counters. The tab would show one worker's share. Merging is a later project (persisted rollups keyed by worker id would be the route).
3. **Resets on restart or sleep.** A sleeping Render instance loses its memory window. Persisted rollups bridge restarts; the 15-minute detail does not survive them.
4. **Weighting is an assumption** until H4 confirms how Atlas counts batched operations.
5. **Attribution is partial** until PERF-M3b: tenant collections are attributed, global collections are shown as unattributed.
6. **Latency includes Atlas queueing.** When the cluster throttles, command latency rises. That is useful (it is how throttling is detected) but it means a slow command is not always a slow query.
7. **Settings are only as right as you make them.** The tab judges against the values you save. A wrong cap gives wrong percentages and alerts. The header always shows the cap in use and where it came from.
8. **The sink can lag.** A failing sink queues one hour of history, then drops the oldest. The live view is unaffected.
9. **Measuring has a cost.** The listener adds a lock and a few integer updates per command; the middleware adds one timer. Both are tiny, but the "same DB calls with metrics on" test and the load test (H3) confirm it.

---

## 13. Rollout and rollback

1. Deploy with `PERF_ENABLED=false`. Nothing changes.
2. Enable on a non-production deployment, run the load test (H3), read the tab.
3. Enable in production **outside** an election window first; watch for a day.
4. Rollback is an environment change: `PERF_ENABLED=false` removes the listener, middleware and probe on the next start. No data migration; `perf_minutes` can simply expire.
5. Moving plan: open the Settings card, pick the new tier (or Custom and type the caps), Save. No redeploy, no restart.
6. Changing where history goes (`PERF_SINK`) is an environment change and a restart.

---

## 14. HUMAN checklist (no AI can do these)

| # | Item |
|---|---|
| H1 | Before election day, re-read Atlas's current limits for your plan and set the tier and caps in the tab's Settings card to match. The tab's header shows what it is judging against and where the value came from; make sure it is right. |
| H2 | Confirm the superadmin account is the only one that can open the tab (log in as each other role and check the Platform group). |
| H3 | Run the load test (`backend/loadtest/locustfile.py`) against a **non-production** cluster with `PERF_ENABLED=true`. Record: peak ops/s shown, p95 latency, pool in use and waiting, loop lag, unattributed share. Then run it with `PERF_ENABLED=false` and compare request latency to confirm the overhead is negligible. |
| H4 | During the same run, watch Atlas's real-time operations view. Compare its figure with the tab's headline. If they differ by more than about 10%, adjust `_weight` (batching) or explain the gap (other clients). |
| H5 | Open the tab on a real phone and on the Blueprint build. Check the 44 px targets, card rows, and that polling stops when the browser tab is in the background. |
| H6 | Decide who looks at this during voting and what they do at each alert (for example: at "critical", pause results polling or SMS bursts; at "throttling", ask voters to retry in a minute). Write it in the runbook. |
| H7 | Keep the Render instance warm during the election window (`/health` ping), as the audit already advises, so cold starts do not blank the in-memory window. |
| H8 | Alternative to H10 (use one or the other): create a second free Atlas project and cluster for metrics, put its connection string in `PERF_MONGO_URL`, set `PERF_SINK=mongo_separate`, restart, and confirm the tab's sink line shows "separate cluster" with writes succeeding. Restrict that cluster's network access and database user to the metrics database only. |
| H9 | Test the failure path once: set a wrong `PERF_MONGO_URL` or `PERF_POSTGRES_URL` on a non-production deployment and confirm the sink line shows the error and queue growth while the live view and voting are unaffected. |
| H10 | **Recommended:** create a Postgres database for metrics only (Neon, Supabase, or Render), with TLS required and a user limited to that database. Put its connection string in `PERF_POSTGRES_URL` (the pooler URL plus `PERF_POSTGRES_POOLED=true` if it is a pooler), set `PERF_SINK=postgres`, restart, and confirm the tab's sink line shows "postgres" with writes succeeding and `perf_batches` filling (one row per flush). |
| H11 | Re-check the chosen provider's current free-tier limits (inactivity pause, scale-to-zero, storage, database lifetime) shortly before election day, and decide whether a paid tier is worth it for the election window. |
| H12 | Only if `b2` is chosen instead: in the B2 console add a lifecycle rule on the `perf/` prefix that deletes files after `PERF_RETENTION_DAYS` days **and** removes old file versions, and consider an application key limited to that prefix. |

---

## 15. Progress file template (`progress/PERF-<ID>.md`)

```
# PERF-<ID> — <title>
- Date / session:
- Files changed:
- Tests added (names):
- Gates: backend __ passed __ failed (pre-existing __); frontend __ passed __ failed (pre-existing __); lint __; template build __
- Overhead check (same DB calls with metrics on/off): pass / fail
- Deviations recorded (DEVIATIONS.md ids):
- Not done / HUMAN items outstanding:
```

---

# Appendices (reference code — not executed when this guide was written)

## Appendix A — `perf_tiers.py`

```python
import os
import logging

log = logging.getLogger(__name__)

# name: (ops_per_s_cap, connection_cap, note). Add a line only to make a plan appear by name in the dropdown.
TIERS = {
    "free": (100, 500, "Atlas Free: 100 ops/s; operations queue and are throttled above it."),
}
PRESETS_VERIFIED_ON = "2026-10-10"       # shown in the tab so a stale preset is visible (H1)
DEFAULT_TIER = "free"
NO_CAP = ("0", "none", "off", "unlimited")


def perf_enabled() -> bool:
    return os.getenv("PERF_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def _env_cap(name):
    """(found, value): value None means an explicit 'no hard cap'."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return False, None
    if raw.strip().lower() in NO_CAP:
        return True, None
    try:
        v = int(float(raw))
        return (True, v) if v > 0 else (False, None)
    except ValueError:
        log.warning("%s=%r is not a number; ignoring it", name, raw)
        return False, None


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


def _pick(key, saved, env_value, preset_value):
    """Precedence: saved (UI) > environment > preset. A saved None means 'no cap' and is honoured."""
    if key in saved:
        return saved[key], "ui"
    found, v = env_value
    if found:
        return v, "env"
    return preset_value, "preset"


def resolve(saved: dict | None = None) -> dict:
    """saved = the `values` of platform_settings/perf_config, or None."""
    saved = saved or {}
    requested = str(saved.get("tier") or os.getenv("MONGO_TIER", DEFAULT_TIER)).strip().lower()
    custom = requested == "custom"
    base = DEFAULT_TIER if custom or requested not in TIERS else requested
    if not custom and requested not in TIERS:
        log.warning("Unknown tier %r; using %r", requested, DEFAULT_TIER)
    ops, conns, note = TIERS[base]
    ops_cap, ops_src = _pick("ops_cap", saved, _env_cap("DB_OPS_CAP"), ops)
    conn_cap, conn_src = _pick("conn_cap", saved, _env_cap("DB_CONN_CAP"), conns)
    return {
        "tier": "custom" if custom else base, "note": "Custom caps" if custom else note,
        "ops_cap": ops_cap, "ops_cap_source": ops_src,
        "conn_cap": conn_cap, "conn_cap_source": conn_src,
        "warn_pct": saved.get("warn_pct", _env_int("PERF_WARN_PCT", "70")),
        "crit_pct": saved.get("crit_pct", _env_int("PERF_CRIT_PCT", "90")),
        "slow_ms": saved.get("slow_ms", _env_int("PERF_SLOW_COMMAND_MS", "250")),
        "persist_s": saved.get("persist_s", _env_int("PERF_PERSIST_SECONDS", "300")),
        "paused": bool(saved.get("paused", False)),
        "retention_days": _env_int("PERF_RETENTION_DAYS", "14"),     # env only
        "presets_verified_on": PRESETS_VERIFIED_ON,
    }


def validate(payload: dict) -> dict:
    """Return the cleaned values to save, or raise ValueError({field: message}). Mirrors the UI (§2.5)."""
    errs, out = {}, {}

    def cap(field):
        if field not in payload:
            return
        v = payload[field]
        if v is None:
            out[field] = None
        elif isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 100_000):
            errs[field] = "Enter a whole number from 1 to 100,000, or choose no hard cap."
        else:
            out[field] = v

    tier = payload.get("tier")
    if tier is not None:
        if str(tier).lower() not in (*TIERS, "custom"):
            errs["tier"] = "Unknown tier."
        else:
            out["tier"] = str(tier).lower()
    cap("ops_cap"); cap("conn_cap")
    if "ops_cap" in out or "conn_cap" in out:
        chosen = out.get("tier")
        preset = TIERS.get(chosen)
        matches = (preset is not None and out.get("ops_cap", preset[0]) == preset[0]
                   and out.get("conn_cap", preset[1]) == preset[1])
        out["tier"] = chosen if matches else "custom"
    warn, crit = payload.get("warn_pct"), payload.get("crit_pct")
    for k, v, lo, hi in (("warn_pct", warn, 1, 99), ("crit_pct", crit, 2, 100)):
        if k in payload:
            if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
                errs[k] = f"Enter a whole number from {lo} to {hi}."
            else:
                out[k] = v
    if "warn_pct" in out and "crit_pct" in out and out["warn_pct"] >= out["crit_pct"]:
        errs["warn_pct"] = "Warning must be below critical."
    if "slow_ms" in payload:
        v = payload["slow_ms"]
        if isinstance(v, bool) or not isinstance(v, int) or not (10 <= v <= 10_000):
            errs["slow_ms"] = "Enter a whole number from 10 to 10,000."
        else:
            out["slow_ms"] = v
    if "persist_s" in payload:
        v = payload["persist_s"]
        if v not in (0, 60, 300, 900, 3600):
            errs["persist_s"] = "Choose Off, 1, 5, 15 or 60 minutes."
        else:
            out["persist_s"] = v
    if "paused" in payload:
        out["paused"] = bool(payload["paused"])
    if errs:
        raise ValueError(errs)
    return out
```

`validate` checks only the fields in the payload. The route must merge the payload over the saved values and re-check warn below critical on the merged result, so saving only one of the two cannot create an invalid pair.

The tier/custom rule in `validate` is deliberately simple to state: **editing a cap by hand makes the tier `custom`** unless the typed number equals the chosen preset's. The test in PERF-M0 pins this down.

## Appendix B — command and pool listeners (sketch)

```python
import threading
from pymongo import monitoring

IGNORED = frozenset({"hello", "isMaster", "ismaster", "ping", "saslStart", "saslContinue",
                     "endSessions", "buildInfo", "killCursors", "logout"})
SELF_COLLECTION = "perf_minutes"
_BATCH_KEYS = {"insert": "documents", "update": "updates", "delete": "deletes"}


def _weight(name: str, cmd: dict) -> int:
    key = _BATCH_KEYS.get(name)
    if key:
        try:
            return max(1, len(cmd.get(key) or ()))
        except Exception:
            return 1
    return 1


def _collection(name: str, cmd: dict) -> str:
    try:
        if name == "getMore":
            return str(cmd.get("collection") or "(other)")
        v = cmd.get(name)
        return v if isinstance(v, str) else "(other)"
    except Exception:
        return "(other)"


class CommandListener(monitoring.CommandListener):
    def __init__(self):
        self._lock = threading.Lock()
        self._inflight = {}                      # request_id -> (collection, name)

    def started(self, event):
        try:
            name = event.command_name
            if name in IGNORED:
                return
            coll = _collection(name, event.command)
            if coll == SELF_COLLECTION:
                return
            w = _weight(name, event.command)
            with self._lock:
                if len(self._inflight) < 4096:
                    self._inflight[event.request_id] = (coll, name)
                RING.add_ops(coll, name, w)      # O(1): integer increments
        except Exception:
            _swallow_once("started")

    def _done(self, event, ok):
        try:
            with self._lock:
                meta = self._inflight.pop(event.request_id, None)
            if meta:
                RING.add_latency(meta[0], meta[1], event.duration_micros / 1000.0, ok, event)
        except Exception:
            _swallow_once("done")

    def succeeded(self, event): self._done(event, True)
    def failed(self, event):    self._done(event, False)


COMMAND_LISTENER = CommandListener()
```

Pool listener: subclass `monitoring.ConnectionPoolListener`; implement `connection_check_out_started`, `connection_checked_out`, `connection_checked_in`, `connection_check_out_failed` (read `event.reason` for timeout), and ignore the rest. Use a `threading.local` to carry the check-out start time to the matching `connection_checked_out` on the same thread.

## Appendix C — request holder and note-op (sketch)

```python
import contextvars

_CURRENT = contextvars.ContextVar("perf_request", default=None)


class RequestMetrics:
    __slots__ = ("ops", "by_coll")
    def __init__(self):
        self.ops = 0
        self.by_coll = {}


def begin_request():
    h = RequestMetrics()
    _CURRENT.set(h)
    RING.inflight_inc()
    return h


def note_op(collection: str, method: str, n: int = 1):
    """Called from TenantCollection on the event-loop side. Must never raise."""
    try:
        h = _CURRENT.get()
        if h is not None:
            h.ops += n
            h.by_coll[collection] = h.by_coll.get(collection, 0) + n
    except Exception:
        pass


def end_request(h, *, route, status, ms, org):
    try:
        RING.inflight_dec()
        RING.add_request(route, status, ms, h.ops, org)
    except Exception:
        _swallow_once("end_request")
```

## Appendix D — ring slot discipline (sketch)

```python
class SecondRing:
    N = 900                                      # 15 minutes
    def __init__(self):
        self.stamp = [0] * self.N                # epoch second stored in each slot
        self.ops = [0] * self.N
        self.cmds = [0] * self.N
    def _slot(self, now):
        i = now % self.N
        if self.stamp[i] != now:                 # slot is from a previous lap: reset it
            self.stamp[i] = now
            self.ops[i] = self.cmds[i] = 0
        return i
```

Read side: when building a series, include a slot only if its `stamp` falls inside the requested window; otherwise emit `null`.

## Appendix E — headroom formula (D1)

```
voter_ops_s      = sum over the three voter routes of (requests per second × mean ops per request)
non_voter_ops_s  = ops_s_60s − voter_ops_s                 # voter routes: verify-identity, verify-otp, vote-bulk
ops_per_voter    = sum of mean ops per request across those three routes    # measured; 26 until ≥30 sequences are seen
voters_per_min   = max(0, (cap − non_voter_ops_s)) / ops_per_voter × 60
```

Show the result as a rounded figure with the words "about", and hide it entirely on an uncapped tier.

## Appendix F — sink interface and config store (sketch)

```python
class Sink:
    name = "base"
    async def write(self, batch: dict) -> None: ...          # raise on failure; the caller queues and retries
    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]: ...
    def status(self) -> dict: ...                             # {"type", "ok", "last_success", "queued", "dropped", "last_error"}


class SeparateMongoSink(Sink):
    name = "mongo_separate"
    def __init__(self, url: str, dbname: str):
        # Own client, tiny pool, NO event_listeners (its traffic must not count as main-cluster ops).
        self._client = motor.motor_asyncio.AsyncIOMotorClient(url, maxPoolSize=2, serverSelectionTimeoutMS=3000)
        self._coll = self._client[dbname]["perf_batches"]
    async def write(self, batch):
        await asyncio.wait_for(
            self._coll.replace_one({"_id": batch["_id"]}, batch, upsert=True), timeout=5)


class PostgresSink(Sink):
    """Recommended sink. NOT executed; PERF-M5 tests and H10 verify it."""
    name = "postgres"
    DDL = """
    CREATE TABLE IF NOT EXISTS perf_batches (
        minute_epoch bigint PRIMARY KEY,
        minute_dt    timestamptz NOT NULL,
        rows         jsonb NOT NULL
    );
    CREATE INDEX IF NOT EXISTS perf_batches_dt ON perf_batches (minute_dt);
    """
    UPSERT = """
    INSERT INTO perf_batches (minute_epoch, minute_dt, rows) VALUES ($1, $2, $3::jsonb)
    ON CONFLICT (minute_epoch) DO UPDATE SET minute_dt = EXCLUDED.minute_dt, rows = EXCLUDED.rows
    """

    def __init__(self, url: str, pooled: bool = False, retention_days: int = 14):
        self._url, self._pooled, self._days = url, pooled, retention_days
        self._pool = None
        self._ready = False

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg                       # lazy: only this sink needs it (rule P5)
            kw = {"min_size": 1, "max_size": 2, "command_timeout": 5, "timeout": 5}
            if self._pooled:
                kw["statement_cache_size"] = 0   # poolers (PgBouncer) cannot keep prepared statements
            self._pool = await asyncpg.create_pool(self._url, **kw)
        return self._pool

    async def write(self, batch):
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            if not self._ready:
                await con.execute(self.DDL)
                self._ready = True
            when = datetime.fromtimestamp(batch["_id"], tz=timezone.utc)
            # asyncpg returns/accepts jsonb as text unless a codec is set, so send JSON text.
            await con.execute(self.UPSERT, batch["_id"], when, json.dumps(batch["rows"]))
            try:
                await con.execute(
                    "DELETE FROM perf_batches WHERE minute_dt < now() - make_interval(days => $1)",
                    self._days)
            except Exception:
                _swallow_once("pg_retention")    # retention failure must not fail the flush

    async def read(self, start_epoch, end_epoch):
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            # widen the start by one flush interval so a batch that began just before the window is included
            recs = await con.fetch(
                "SELECT minute_epoch, rows FROM perf_batches "
                "WHERE minute_epoch BETWEEN $1 AND $2 ORDER BY minute_epoch",
                start_epoch - 3600, end_epoch)
        return [{"_id": r["minute_epoch"], "rows": json.loads(r["rows"])} for r in recs]

    # status() returns the shared dict (type, ok, last_success, queued, dropped, last_error);
    # last_error must be scrubbed so it never contains the URL or password.


# Config store (global collection, not tenant-scoped; read at start, cached, swapped atomically on save)
async def load_config(db):
    doc = await cross_tenant(db).platform_settings.find_one({"name": "perf_config"})
    return (doc or {}).get("values") or {}

async def save_config(db, values: dict, actor: str):
    await cross_tenant(db).platform_settings.update_one(
        {"name": "perf_config"},
        {"$set": {"values": values, "updated_at": datetime.utcnow(), "updated_by": actor},
         "$inc": {"version": 1}},
        upsert=True)
```
