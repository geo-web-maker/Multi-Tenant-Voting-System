"""In-process performance collector.

The command listener runs on driver threads: one lock, integer updates, no I/O.
Every hook swallows its own errors (P1). Writes to perf_minutes are not counted (P4).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import resource
import threading
import time
from collections import deque

from pymongo import monitoring

from analytics import API_EDGES, _hist_index, hist_percentile, route_template
from perf_tiers import (
    ALERT_COOLDOWN_S,
    AUDIT_OPS_PER_VOTER,
    CMD_LAT_EDGES,
    COLD_START_SECONDS,
    HTTP_SLOW_MIN_REQUESTS,
    HTTP_SLOW_P95_MS,
    LOOP_LAG_P95_MS,
    THROTTLE_CAP_PCT,
    THROTTLE_P95_MS,
    VOTER_SEQUENCES_MIN,
    current_config,
    on_change,
    percent_of,
    perf_enabled,
)

log = logging.getLogger(__name__)

IGNORED = frozenset({
    "hello", "isMaster", "ismaster", "ping", "saslStart", "saslContinue",
    "endSessions", "buildInfo", "killCursors", "logout",
})
SELF_COLLECTION = "perf_minutes"
_BATCH_KEYS = {"insert": "documents", "update": "updates", "delete": "deletes"}
VOTER_ROUTES = ("/verify-identity", "/verify-otp", "/vote-bulk")
POOL_MAX_SIZE = 20
_KEY_LIMIT = 64
_SLOW_LIMIT = 50
_INFLIGHT_CAP = 4096
_SUMMARY_TTL = 2.0

_CURRENT = contextvars.ContextVar("perf_request", default=None)
_LOCK = threading.Lock()
_clock = None
_paused = False
_slow_ms = 250
_swallowed: dict[str, float] = {}
_started_at = time.time()
_collecting_since = None
_election_open = False
_summary_cache = {"at": 0.0, "body": None}
_summary_computes = 0
_task = None
_manager = None
_last_flushed_minute = None
_recent_alerts: deque = deque(maxlen=20)
_last_fired: dict = {}
_start_id = str(int(_started_at))

# Cumulative voter-path figures. They outlive the 15-minute detail window.
_voter = {route: {"n": 0, "ops": 0} for route in VOTER_ROUTES}
_sequences = 0
_election = {"vote": 0, "otp_send": 0, "otp_verify": 0, "otp_fail": 0}
_sms = {"sends": 0, "failures": 0, "latency_sum": 0.0, "n": 0}
_cache = {}
_inflight = 0
_inflight_peak = 0
_inflight_peak_at = 0
_cpu_pct = 0.0
_cpu_proc = None
_cpu_wall = None
_lag_samples: deque = deque(maxlen=240)
_pool_waiting_since = None
_timeouts: deque = deque(maxlen=200)


def set_clock(fn) -> None:
    """Tests inject a wall clock. Production leaves this unset."""
    global _clock
    _clock = fn


def _now() -> float:
    if _clock is not None:
        return float(_clock())
    return time.time()


def _swallow_once(where: str) -> None:
    now = time.monotonic()
    if now - _swallowed.get(where, 0.0) < 60:
        return
    _swallowed[where] = now
    log.warning("perf hook %s failed", where, exc_info=True)


def refresh_flags() -> None:
    global _paused, _slow_ms, _summary_cache
    try:
        cfg = current_config()
        _paused = bool(cfg.get("paused"))
        _slow_ms = int(cfg.get("slow_ms") or 250)
    except Exception:
        _swallow_once("refresh")
    _summary_cache = {"at": 0.0, "body": None}


def collecting() -> bool:
    return perf_enabled() and not _paused


def _stamp_collecting(now: float | None = None) -> None:
    global _collecting_since
    if _collecting_since is None:
        _collecting_since = now if now is not None else _now()


def _weight(name: str, cmd: dict) -> int:
    key = _BATCH_KEYS.get(name)
    if key and isinstance(cmd, dict):
        try:
            return max(1, len(cmd.get(key) or ()))
        except Exception:
            return 1
    return 1


def _collection(name: str, cmd: dict) -> str:
    try:
        if name == "getMore":
            return str((cmd or {}).get("collection") or "(other)")
        value = (cmd or {}).get(name)
        return value if isinstance(value, str) else "(other)"
    except Exception:
        return "(other)"


def _empty_hist(edges) -> list[int]:
    return [0] * (len(edges) + 1)


def _add_hist(hist: list[int], edges, ms: float) -> None:
    hist[_hist_index(ms, edges)] += 1


def _pct(hist, edges, q):
    value = hist_percentile(hist, edges, q)
    if value is None:
        return None
    return round(value, 1)


class _SecondRing:
    N = 900  # 15 minutes

    def __init__(self):
        n = self.N
        self.stamp = [0] * n
        self.ops = [0] * n
        self.cmds = [0] * n
        self.reqs = [0] * n
        self.errs = [0] * n
        self.attributed = [0] * n
        self.lag_max = [0.0] * n

    def slot(self, sec: int) -> int:
        i = sec % self.N
        if self.stamp[i] != sec:
            self.stamp[i] = sec
            self.ops[i] = 0
            self.cmds[i] = 0
            self.reqs[i] = 0
            self.errs[i] = 0
            self.attributed[i] = 0
            self.lag_max[i] = 0.0
        return i

    def value(self, sec: int, field: str):
        i = sec % self.N
        if self.stamp[i] != sec:
            return None
        return getattr(self, field)[i]


class _MinuteRing:
    N = 1440  # 24 hours

    def __init__(self):
        self.stamp = [0] * self.N
        self.slots = [None] * self.N

    def slot(self, minute: int) -> dict:
        i = minute % self.N
        if self.stamp[i] != minute or self.slots[i] is None:
            self.stamp[i] = minute
            self.slots[i] = {
                "ops": 0, "cmds": 0, "reqs": 0, "s2": 0, "s4": 0, "s5": 0, "s429": 0,
                "http_hist": _empty_hist(API_EDGES),
                "cmd_hist": _empty_hist(CMD_LAT_EDGES),
                "routes": {}, "colls": {}, "orgs": {}, "org_stats": {}, "ops_types": {},
                "failures": {},
            }
        return self.slots[i]

    def value(self, minute: int):
        i = minute % self.N
        if self.stamp[i] != minute:
            return None
        return self.slots[i]


class _Detail:
    """Latency histograms for the last 15 minutes. Older minutes keep counts only."""
    N = 15

    def __init__(self):
        self.stamp = [0] * self.N
        self.routes = [{} for _ in range(self.N)]
        self.colls = [{} for _ in range(self.N)]

    def _fresh(self, minute: int) -> int:
        i = minute % self.N
        if self.stamp[i] != minute:
            self.stamp[i] = minute
            self.routes[i] = {}
            self.colls[i] = {}
        return i

    def route(self, minute: int, name: str) -> dict:
        i = self._fresh(minute)
        table = self.routes[i]
        key = _cap_key(table, name)
        row = table.get(key)
        if row is None:
            row = {"n": 0, "ops": 0, "lat": _empty_hist(API_EDGES), "per": _empty_hist([1, 2, 4, 8, 16, 32, 64, 128])}
            table[key] = row
        return row

    def coll(self, minute: int, name: str) -> dict:
        i = self._fresh(minute)
        table = self.colls[i]
        key = _cap_key(table, name)
        row = table.get(key)
        if row is None:
            row = {"ops": 0, "lat": _empty_hist(CMD_LAT_EDGES)}
            table[key] = row
        return row

    def merged_routes(self, now_min: int, minutes: int = 15) -> dict:
        acc: dict = {}
        for age in range(minutes):
            minute = now_min - age
            i = minute % self.N
            if self.stamp[i] != minute:
                continue
            for key, row in self.routes[i].items():
                dest = acc.get(key)
                if dest is None:
                    dest = {"n": 0, "ops": 0, "lat": _empty_hist(API_EDGES), "per": _empty_hist(row["per"])}
                    acc[key] = dest
                dest["n"] += row["n"]
                dest["ops"] += row["ops"]
                for j, n in enumerate(row["lat"]):
                    dest["lat"][j] += n
                for j, n in enumerate(row["per"]):
                    if j < len(dest["per"]):
                        dest["per"][j] += n
        return acc


def _cap_key(table: dict, key: str) -> str:
    if key in table:
        return key
    if len(table) >= _KEY_LIMIT:
        return "(other)"
    return key


def _bump(table: dict, key: str, n: int = 1) -> None:
    key = _cap_key(table, key)
    table[key] = table.get(key, 0) + n


SECONDS = _SecondRing()
MINUTES = _MinuteRing()
DETAIL = _Detail()
_slow = deque(maxlen=_SLOW_LIMIT)
_inflight_cmds: dict = {}


def _sec(now: float | None = None) -> int:
    return int(now if now is not None else _now())


def _minute(now: float | None = None) -> int:
    return _sec(now) // 60 * 60


class CommandListener(monitoring.CommandListener):
    def started(self, event):
        if not collecting():
            return
        try:
            name = event.command_name
            if name in IGNORED:
                return
            cmd = getattr(event, "command", None) or {}
            coll = _collection(name, cmd)
            if coll == SELF_COLLECTION:
                return
            weight = _weight(name, cmd)
            now = _now()
            _stamp_collecting(now)
            with _LOCK:
                if len(_inflight_cmds) < _INFLIGHT_CAP:
                    _inflight_cmds[event.request_id] = (coll, name)
                sec = SECONDS.slot(_sec(now))
                SECONDS.ops[sec] += weight
                SECONDS.cmds[sec] += 1
                minute = MINUTES.slot(_minute(now))
                minute["ops"] += weight
                minute["cmds"] += 1
                _bump(minute["colls"], coll, weight)
                op = "getMore" if name == "getMore" else name
                _bump(minute["ops_types"], op if op in (
                    "find", "count", "aggregate", "insert", "update", "delete", "getMore", "distinct"
                ) else "other", weight)
        except Exception:
            _swallow_once("started")

    def succeeded(self, event):
        self._done(event, True)

    def failed(self, event):
        self._done(event, False)

    def _done(self, event, ok: bool):
        if not collecting():
            return
        try:
            with _LOCK:
                meta = _inflight_cmds.pop(getattr(event, "request_id", None), None)
            if not meta:
                return
            coll, name = meta
            ms = float(getattr(event, "duration_micros", 0) or 0) / 1000.0
            now = _now()
            err = None
            if not ok:
                err = _error_name(getattr(event, "failure", None))
            with _LOCK:
                minute = MINUTES.slot(_minute(now))
                _add_hist(minute["cmd_hist"], CMD_LAT_EDGES, ms)
                row = DETAIL.coll(_minute(now), coll)
                row["ops"] += 1
                _add_hist(row["lat"], CMD_LAT_EDGES, ms)
                if ms >= _slow_ms:
                    _slow.append({
                        "t": datetime_iso(now),
                        "command": name,
                        "collection": coll,
                        "duration_ms": round(ms, 1),
                        "route": None,
                    })
                if err:
                    key = f"{name}:{err}"
                    _bump(minute["failures"], key, 1)
        except Exception:
            _swallow_once("done")


def _error_name(failure) -> str:
    if failure is None:
        return "error"
    if isinstance(failure, BaseException):
        return type(failure).__name__
    if isinstance(failure, dict):
        return str(failure.get("codeName") or "error")[:40]
    return type(failure).__name__


def datetime_iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class PoolListener(monitoring.ConnectionPoolListener):
    def __init__(self):
        self._local = threading.local()
        self.in_use = 0
        self.waiting = 0
        self.created = 0
        self.closed = 0
        self.max_size = POOL_MAX_SIZE
        self.wait_hist = _empty_hist(CMD_LAT_EDGES)
        self.timeouts = 0

    def pool_created(self, event):
        try:
            options = getattr(event, "options", None) or {}
            if options.get("maxPoolSize"):
                self.max_size = int(options["maxPoolSize"])
        except Exception:
            _swallow_once("pool_created")

    def pool_ready(self, event):
        return None

    def pool_cleared(self, event):
        return None

    def pool_closed(self, event):
        return None

    def connection_created(self, event):
        try:
            with _LOCK:
                self.created += 1
        except Exception:
            _swallow_once("pool")

    def connection_ready(self, event):
        return None

    def connection_closed(self, event):
        try:
            with _LOCK:
                self.closed += 1
        except Exception:
            _swallow_once("pool")

    def connection_check_out_started(self, event):
        if not collecting():
            return
        try:
            self._local.t = time.perf_counter()
            with _LOCK:
                self.waiting += 1
                global _pool_waiting_since
                if _pool_waiting_since is None:
                    _pool_waiting_since = _now()
        except Exception:
            _swallow_once("pool")

    def connection_checked_out(self, event):
        if not collecting():
            return
        try:
            started = getattr(self._local, "t", None)
            wait = max(0.0, (time.perf_counter() - started) * 1000.0) if started else 0.0
            with _LOCK:
                self.waiting = max(0, self.waiting - 1)
                self.in_use += 1
                _add_hist(self.wait_hist, CMD_LAT_EDGES, wait)
                if self.waiting <= 0:
                    global _pool_waiting_since
                    _pool_waiting_since = None
        except Exception:
            _swallow_once("pool")

    def connection_checked_in(self, event):
        if not collecting():
            return
        try:
            with _LOCK:
                self.in_use = max(0, self.in_use - 1)
        except Exception:
            _swallow_once("pool")

    def connection_check_out_failed(self, event):
        if not collecting():
            return
        try:
            reason = str(getattr(event, "reason", "") or "")
            with _LOCK:
                self.waiting = max(0, self.waiting - 1)
                if self.waiting <= 0:
                    global _pool_waiting_since
                    _pool_waiting_since = None
                if reason == "timeout" or "timeout" in reason.lower():
                    self.timeouts += 1
                    _timeouts.append(_now())
        except Exception:
            _swallow_once("pool")

    def snapshot(self) -> dict:
        with _LOCK:
            idle = max(0, (self.created - self.closed) - self.in_use)
            recent = [t for t in _timeouts if t >= _now() - 3600]
            return {
                "in_use": self.in_use,
                "idle": idle,
                "max": self.max_size,
                "waiting": self.waiting,
                "wait_p95_ms": _pct(list(self.wait_hist), CMD_LAT_EDGES, 0.95) or 0,
                "timeouts_1h": len(recent),
            }


COMMAND_LISTENER = CommandListener()
POOL_LISTENER = PoolListener()


def motor_kwargs() -> dict:
    """Client options. With monitoring off, these are exactly the historical pool settings."""
    kw = {"maxPoolSize": POOL_MAX_SIZE, "minPoolSize": 1, "waitQueueTimeoutMS": 2500}
    if perf_enabled():
        kw["event_listeners"] = [COMMAND_LISTENER, POOL_LISTENER]
    return kw


class RequestMetrics:
    __slots__ = ("ops", "calls", "by_coll")

    def __init__(self):
        self.ops = 0
        self.calls = 0
        self.by_coll = {}


def begin_request():
    if not collecting():
        return None
    try:
        holder = RequestMetrics()
        _CURRENT.set(holder)
        global _inflight, _inflight_peak, _inflight_peak_at
        with _LOCK:
            _inflight += 1
            now = _sec()
            if _inflight_peak_at and now - _inflight_peak_at > 900:
                _inflight_peak = _inflight
                _inflight_peak_at = now
            elif _inflight > _inflight_peak:
                _inflight_peak = _inflight
                _inflight_peak_at = now
        _stamp_collecting()
        return holder
    except Exception:
        _swallow_once("begin_request")
        return None


def note_op(collection: str, method: str, n: int = 1) -> None:
    """Called from TenantCollection on the event-loop side. Must never raise."""
    try:
        if not collecting():
            return
        holder = _CURRENT.get()
        if holder is None:
            return
        weight = n if isinstance(n, int) and n > 0 else 1
        holder.ops += weight
        holder.calls += 1
        holder.by_coll[collection] = holder.by_coll.get(collection, 0) + weight
    except Exception:
        return None


def note_cache(name: str, hit: bool) -> None:
    try:
        if not collecting():
            return
        with _LOCK:
            row = _cache.setdefault(name, {"hit": 0, "miss": 0})
            row["hit" if hit else "miss"] += 1
    except Exception:
        return None


def note_election(kind: str) -> None:
    try:
        if not collecting() or kind not in _election:
            return
        with _LOCK:
            _election[kind] += 1
    except Exception:
        return None


def note_sms(kind: str, result: str, ms: float) -> None:
    try:
        if not collecting():
            return
        with _LOCK:
            _sms["n"] += 1
            _sms["latency_sum"] += float(ms or 0)
            if result == "ok":
                _sms["sends"] += 1
            elif result == "failed":
                _sms["failures"] += 1
            if kind == "otp" and result in ("ok", "ambiguous"):
                _election["otp_send"] += 1
    except Exception:
        return None


def note_phase_open(is_open: bool) -> None:
    global _election_open
    try:
        _election_open = bool(is_open)
    except Exception:
        return None


def end_request(holder, *, route, status, ms, org) -> None:
    global _inflight, _sequences
    try:
        with _LOCK:
            if holder is not None:
                _inflight = max(0, _inflight - 1)
            if not collecting():
                return
            now = _now()
            _stamp_collecting(now)
            sec_i = SECONDS.slot(_sec(now))
            SECONDS.reqs[sec_i] += 1
            if holder is not None:
                SECONDS.attributed[sec_i] += holder.ops
            if status >= 500:
                SECONDS.errs[sec_i] += 1
            minute = MINUTES.slot(_minute(now))
            minute["reqs"] += 1
            if 200 <= status < 300:
                minute["s2"] += 1
            elif status == 429:
                minute["s429"] += 1
                minute["s4"] += 1
            elif 400 <= status < 500:
                minute["s4"] += 1
            elif status >= 500:
                minute["s5"] += 1
            _add_hist(minute["http_hist"], API_EDGES, ms)
            route_name = route or "(unmatched)"
            _bump_route_counts(minute["routes"], route_name, 0 if holder is None else holder.ops)
            if org:
                _bump(minute["orgs"], str(org), 0 if holder is None else holder.ops)
                # Per-org request, 5xx and 429 counts so the Performance tab can show which organisation is busy or failing.
                okey = _cap_key(minute["org_stats"], str(org))
                ost = minute["org_stats"].setdefault(okey, [0, 0, 0])
                ost[0] += 1
                if status >= 500:
                    ost[1] += 1
                elif status == 429:
                    ost[2] += 1
            if holder is not None:
                detail = DETAIL.route(_minute(now), route_name)
                detail["n"] += 1
                detail["ops"] += holder.ops
                _add_hist(detail["lat"], API_EDGES, ms)
                _add_hist(detail["per"], [1, 2, 4, 8, 16, 32, 64, 128], holder.ops)
                if route_name in _voter:
                    _voter[route_name]["n"] += 1
                    _voter[route_name]["ops"] += holder.ops
                    if route_name == "/vote-bulk" and status < 400:
                        _sequences += 1
    except Exception:
        _swallow_once("end_request")


def _bump_route_counts(table: dict, route: str, ops: int) -> None:
    key = _cap_key(table, route)
    row = table.get(key)
    if row is None:
        row = [0, 0]
        table[key] = row
    row[0] += 1
    row[1] += ops


async def perf_middleware(request, call_next):
    if not collecting():
        return await call_next(request)
    holder = begin_request()
    t0 = time.perf_counter()
    status = 500
    try:
        try:
            response = await call_next(request)
            status = getattr(response, "status_code", 500) or 500
            return response
        except Exception:
            status = 500
            raise
    finally:
        try:
            route = route_template(request, status)
        except Exception:
            route = "(unmatched)"
        org = getattr(getattr(request, "state", None), "org_slug", None)
        end_request(holder, route=route, status=status, ms=(time.perf_counter() - t0) * 1000.0, org=org)


def record_lag_ms(ms: float) -> None:
    try:
        if not collecting():
            return
        now = _now()
        with _LOCK:
            _lag_samples.append((now, float(ms)))
            sec = SECONDS.slot(_sec(now))
            if ms > SECONDS.lag_max[sec]:
                SECONDS.lag_max[sec] = float(ms)
    except Exception:
        _swallow_once("lag")


def heartbeat(now: float | None = None) -> None:
    """Mark this second and minute as observed so an idle process stores 0, not a gap."""
    if not collecting():
        return
    now = _now() if now is None else now
    try:
        with _LOCK:
            SECONDS.slot(_sec(now))
            MINUTES.slot(_minute(now))
            _stamp_collecting(now)
    except Exception:
        _swallow_once("heartbeat")


async def measure_lag_once(interval: float = 0.25, sleep=None) -> float:
    sleep = sleep or asyncio.sleep
    heartbeat()
    t = time.perf_counter()
    await sleep(interval)
    lag = max(0.0, (time.perf_counter() - t - interval) * 1000.0)
    record_lag_ms(lag)
    _sample_cpu()
    return lag


async def lag_probe(interval: float = 0.25):
    while True:
        try:
            await measure_lag_once(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            _swallow_once("lag_probe")
            await asyncio.sleep(interval)


def _sample_cpu() -> None:
    global _cpu_pct, _cpu_proc, _cpu_wall
    try:
        proc = time.process_time()
        wall = time.perf_counter()
        if _cpu_proc is not None and wall > _cpu_wall:
            _cpu_pct = max(0.0, (proc - _cpu_proc) / (wall - _cpu_wall) * 100.0)
        _cpu_proc, _cpu_wall = proc, wall
    except Exception:
        return None


def _rss_mb():
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
    except Exception:
        return None


def _peak_mb():
    try:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def _window_sum(field: str, seconds: int, now: float | None = None) -> tuple[int, int]:
    """Sum of a per-second field over the last `seconds` full seconds, and how many existed."""
    end = _sec(now) - 1
    total, present = 0, 0
    for age in range(seconds):
        value = SECONDS.value(end - age, field)
        if value is None:
            continue
        present += 1
        total += value
    return total, present


def _ops_over(seconds: int, now: float | None = None) -> float:
    total, present = _window_sum("ops", seconds, now)
    if seconds <= 1:
        return float(total)
    return round(total / seconds, 1)


def _last_full_ops(now: float | None = None) -> int:
    value = SECONDS.value(_sec(now) - 1, "ops")
    return 0 if value is None else int(value)


def _peak(now: float | None = None, seconds: int = 900) -> int:
    end = _sec(now) - 1
    best = 0
    for age in range(seconds):
        value = SECONDS.value(end - age, "ops")
        if value is not None and value > best:
            best = value
    return int(best)


def _consecutive(field: str, predicate, now: float | None = None, limit: int = 120) -> int:
    end = _sec(now) - 1
    n = 0
    for age in range(limit):
        value = SECONDS.value(end - age, field)
        if value is None or not predicate(value):
            break
        n += 1
    return n


def _cmd_hist_recent(now: float | None = None) -> list[int]:
    minute = MINUTES.value(_minute(now))
    if not minute:
        return _empty_hist(CMD_LAT_EDGES)
    return list(minute["cmd_hist"])


def _http_hist_recent(now: float | None = None) -> list[int]:
    hist = _empty_hist(API_EDGES)
    base = _minute(now)
    for age in range(2):
        minute = MINUTES.value(base - age * 60)
        if not minute:
            continue
        for i, n in enumerate(minute["http_hist"]):
            hist[i] += n
    return hist


def _requests_in(seconds: int, now: float | None = None) -> int:
    total, _present = _window_sum("reqs", seconds, now)
    return total


def gauge_status(db: dict, cfg: dict) -> str:
    cap = cfg.get("ops_cap")
    if not cap:
        p95 = (db.get("latency_ms") or {}).get("p95") or 0
        waiting = (db.get("pool") or {}).get("waiting") or 0
        lag = ((db.get("loop_for_status") or 0))
        if waiting > 0 or p95 > THROTTLE_P95_MS:
            return "critical"
        if p95 >= 250 or lag > LOOP_LAG_P95_MS:
            return "busy"
        return "ok"
    if db.get("throttle_suspect"):
        return "throttling"
    pct = db.get("cap_pct") or 0
    if pct >= cfg.get("crit_pct", 90):
        return "critical"
    if pct >= cfg.get("warn_pct", 70):
        return "busy"
    return "ok"


def _voter_math(ops_60: float, cap):
    means = []
    voter_ops_s = 0.0
    for route in VOTER_ROUTES:
        row = _voter[route]
        mean = (row["ops"] / row["n"]) if row["n"] else 0
        means.append(mean)
        # requests in the last minute for this route, from the minute slots, is approximate;
        # use the cumulative mean times the recent request share when we have it.
    req_60 = 0
    voter_req = {route: 0 for route in VOTER_ROUTES}
    now_min = _minute()
    for age in range(1):
        minute = MINUTES.value(now_min - age * 60)
        if not minute:
            continue
        req_60 += minute["reqs"]
        for route in VOTER_ROUTES:
            stats = minute["routes"].get(route)
            if stats:
                voter_req[route] += stats[0]
    for route, mean in zip(VOTER_ROUTES, means):
        voter_ops_s += (voter_req[route] / 60.0) * mean
    if _sequences >= VOTER_SEQUENCES_MIN and all(_voter[r]["n"] for r in VOTER_ROUTES):
        ops_per = round(sum(means), 1)
        source = "measured"
    else:
        ops_per = AUDIT_OPS_PER_VOTER
        source = "audit"
    headroom = None
    if cap and ops_per:
        non_voter = max(0.0, float(ops_60) - voter_ops_s)
        headroom = int(round(max(0.0, (cap - non_voter)) / ops_per * 60))
    return headroom, ops_per, source


def _loop_stats(now: float | None = None) -> dict:
    now = now if now is not None else _now()
    recent = [ms for (t, ms) in _lag_samples if t >= now - 60]
    window = [ms for (t, ms) in list(_lag_samples) if t >= now - 900]
    # 15-minute max also considers the second ring, which outlives the 240-sample deque.
    peak = max(window) if window else 0
    end = _sec(now)
    for age in range(900):
        value = SECONDS.value(end - age, "lag_max")
        if value is not None and value > peak:
            peak = value
    if not recent:
        return {"now": round(_lag_samples[-1][1], 1) if _lag_samples else 0, "p95": 0, "max": round(peak, 1)}
    ordered = sorted(recent)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"now": round(recent[-1], 1), "p95": round(p95, 1), "max": round(peak, 1)}


def _ready(now: float | None = None) -> bool:
    if _collecting_since is None:
        return False
    return (_sec(now) - _sec(_collecting_since)) >= 1 or _last_full_ops(now) > 0 or _requests_in(5, now) > 0


def compute_summary() -> dict:
    global _summary_computes
    _summary_computes += 1
    cfg = current_config()
    now = _now()
    cap = cfg.get("ops_cap")
    ops_s = _last_full_ops(now)
    ops_10 = _ops_over(10, now)
    ops_60 = _ops_over(60, now)
    cap_pct = percent_of(ops_s, cap)
    cmd_hist = _cmd_hist_recent(now)
    http_hist = _http_hist_recent(now)
    cmd_p95 = _pct(cmd_hist, CMD_LAT_EDGES, 0.95)
    throttle = bool(
        cap and cap_pct is not None and cap_pct >= THROTTLE_CAP_PCT and (cmd_p95 or 0) > THROTTLE_P95_MS
    )
    attributed, _a = _window_sum("attributed", 60, now)
    listened, _b = _window_sum("ops", 60, now)
    unattributed = None
    if listened:
        unattributed = round(max(0, listened - attributed) / listened * 100, 1)
    pool = POOL_LISTENER.snapshot()
    loop = _loop_stats(now)
    headroom, ops_per, source = _voter_math(ops_60 if isinstance(ops_60, (int, float)) else 0, cap)
    s5 = 0
    s429 = 0
    minute = MINUTES.value(_minute(now))
    if minute:
        s5 = minute["s5"]
        s429 = minute["s429"]
    cache = {}
    for name, row in _cache.items():
        total = row["hit"] + row["miss"]
        cache[name] = {**row, "rate": round(row["hit"] / total, 3) if total else None}
    db = {
        "ops_s": ops_s,
        "ops_s_10s": ops_10,
        "ops_s_60s": ops_60,
        "peak_15m": _peak(now),
        "cap": cap,
        "cap_pct": cap_pct,
        "headroom": (cap - ops_s) if cap is not None else None,
        "commands_s": SECONDS.value(_sec(now) - 1, "cmds") or 0,
        "throttle_suspect": throttle,
        "latency_ms": {
            "p50": _pct(cmd_hist, CMD_LAT_EDGES, 0.5),
            "p95": cmd_p95,
            "p99": _pct(cmd_hist, CMD_LAT_EDGES, 0.99),
        },
        "pool": pool,
        "unattributed_pct": unattributed,
        "warn_pct": cfg["warn_pct"],
        "crit_pct": cfg["crit_pct"],
        "by_op": dict((minute or {}).get("ops_types") or {}),
        "failures": dict((minute or {}).get("failures") or {}),
        "loop_for_status": loop["p95"],
    }
    status = gauge_status(db, cfg)
    db.pop("loop_for_status", None)
    alerts = evaluate_perf_alerts(_alert_sample(cfg, db, loop, now))
    body = {
        "enabled": perf_enabled(),
        "paused": bool(cfg.get("paused")),
        "ready": _ready(now) and not cfg.get("paused"),
        "status": status,
        "tier": cfg["tier"],
        "note": cfg["note"],
        "uptime_s": int(max(0, now - _started_at)),
        "collecting_since": datetime_iso(_collecting_since) if _collecting_since else None,
        "presets_verified_on": cfg["presets_verified_on"],
        "conn_cap": cfg["conn_cap"],
        "sources": cfg["sources"],
        "db": db,
        "http": {
            "rps": _requests_in(1, now),
            "in_flight": _inflight,
            "in_flight_peak_15m": _inflight_peak,
            "p95_ms": _pct(http_hist, API_EDGES, 0.95),
            "p50_ms": _pct(http_hist, API_EDGES, 0.5),
            "p99_ms": _pct(http_hist, API_EDGES, 0.99),
            "s5xx_1m": s5,
            "s429_1m": s429,
            "s2xx_1m": (minute or {}).get("s2", 0) if minute else 0,
            "s4xx_1m": (minute or {}).get("s4", 0) if minute else 0,
        },
        "runtime": {
            "loop_lag_ms": loop,
            "rss_mb": _rss_mb(),
            "peak_mb": _peak_mb(),
            "cpu_pct": round(_cpu_pct, 1),
            "tasks": _task_count(),
            "threads": threading.active_count(),
        },
        "election": {
            "voters_per_min_headroom": headroom,
            "ops_per_voter": ops_per,
            "ops_per_voter_source": source,
            "votes_1m": _election["vote"],
            "otp_sends": _election["otp_send"],
            "otp_verifies": _election["otp_verify"],
            "otp_failures": _election["otp_fail"],
            "sms_sends": _sms["sends"],
            "sms_failures": _sms["failures"],
            "sms_latency_ms": round(_sms["latency_sum"] / _sms["n"], 1) if _sms["n"] else None,
        },
        "cache": cache,
        "alerts": alerts,
        "recent_alerts": list(_recent_alerts),
    }
    # votes_1m in the catalogue is "per minute". The counters above are since start, which is what
    # a single process can say without a second store. The names stay stable for the tab.
    return body


def _task_count():
    try:
        return len(asyncio.all_tasks())
    except Exception:
        return None


def _alert_sample(cfg: dict, db: dict, loop: dict, now: float) -> dict:
    cap = cfg.get("ops_cap")
    warn_at = (cap * cfg["warn_pct"] / 100.0) if cap else None
    crit_at = (cap * cfg["crit_pct"] / 100.0) if cap else None
    timeouts_recent = len([t for t in _timeouts if t >= now - 60])
    waiting_for = 0
    if _pool_waiting_since is not None and POOL_LISTENER.waiting > 0:
        waiting_for = int(now - _pool_waiting_since)
    http_p95 = compute_http_p95()
    return {
        "capped": bool(cap),
        "cap": cap,
        "warn_pct": cfg["warn_pct"],
        "crit_pct": cfg["crit_pct"],
        "ops_s": db["ops_s"],
        "secs_above_warn": _consecutive("ops", lambda v: warn_at is not None and v >= warn_at, now) if warn_at else 0,
        "secs_above_crit": _consecutive("ops", lambda v: crit_at is not None and v >= crit_at, now) if crit_at else 0,
        "throttle_suspect": db["throttle_suspect"],
        "pool_waiting_secs": waiting_for,
        "pool_timeouts": timeouts_recent,
        "loop_lag_p95": loop["p95"],
        "http_p95": http_p95,
        "http_requests_1m": _requests_in(60, now),
        "uptime_s": int(max(0, now - _started_at)),
        "election_open": _election_open,
    }


def compute_http_p95():
    return _pct(_http_hist_recent(), API_EDGES, 0.95)


def summary() -> dict:
    now = time.monotonic()
    cached = _summary_cache.get("body")
    if cached is not None and now - _summary_cache["at"] < _SUMMARY_TTL:
        return cached
    body = compute_summary()
    _summary_cache["at"] = now
    _summary_cache["body"] = body
    return body


def invalidate_summary() -> None:
    _summary_cache["at"] = 0.0
    _summary_cache["body"] = None


def timeseries(window: str = "15m") -> dict:
    now = _now()
    if window == "24h":
        end = _minute(now)
        points = []
        for age in range(1440):
            minute = end - age * 60
            slot = MINUTES.value(minute)
            if slot is None:
                points.append({"t": minute, "ops": None, "reqs": None})
            else:
                points.append({
                    "t": minute,
                    "ops": round(slot["ops"] / 60.0, 2),
                    "reqs": slot["reqs"],
                    "http_p95": _pct(slot["http_hist"], API_EDGES, 0.95),
                })
        points.reverse()
        return {"window": "24h", "step_s": 60, "points": points}
    end = _sec(now)
    points = []
    for age in range(900):
        sec = end - age
        ops = SECONDS.value(sec, "ops")
        points.append({
            "t": sec,
            "ops": ops,
            "reqs": SECONDS.value(sec, "reqs"),
            "lag_ms": SECONDS.value(sec, "lag_max"),
        })
    points.reverse()
    cfg = current_config()
    return {"window": "15m", "step_s": 1, "cap": cfg.get("ops_cap"), "points": points}


def breakdown(by: str = "collection") -> dict:
    now_min = _minute()
    if by == "route":
        merged = DETAIL.merged_routes(now_min)
        rows = []
        total_ops = sum(r["ops"] for r in merged.values()) or 1
        for name, row in merged.items():
            if row["n"] < 1:
                continue
            rows.append({
                "name": name,
                "requests": row["n"],
                "ops": row["ops"],
                "ops_per_request": round(row["ops"] / row["n"], 2) if row["n"] else None,
                "p95_ms": _pct(row["lat"], API_EDGES, 0.95),
                "share": round(row["ops"] / total_ops, 3),
            })
        rows.sort(key=lambda r: (-(r["ops"] or 0), r["name"]))
        slow = [r for r in rows if (r["requests"] or 0) >= 20]
        slow.sort(key=lambda r: (-(r["p95_ms"] or 0), r["name"]))
        return {"by": "route", "rows": rows, "slowest": slow[:10], "unattributed_pct": summary()["db"]["unattributed_pct"]}
    minute_tables = []
    for age in range(15):
        slot = MINUTES.value(now_min - age * 60)
        if slot:
            minute_tables.append(slot)
    if by == "org":
        ops_acc: dict[str, int] = {}
        stat_acc: dict[str, list] = {}
        covered = 0
        for slot in minute_tables:
            covered += 1
            for name, n in slot["orgs"].items():
                ops_acc[name] = ops_acc.get(name, 0) + n
            for name, st in slot.get("org_stats", {}).items():
                tot = stat_acc.setdefault(name, [0, 0, 0])
                for i in range(3):
                    tot[i] += st[i]
        total = sum(ops_acc.values()) or 1
        seconds = max(60, covered * 60)
        names = set(ops_acc) | set(stat_acc)
        rows = [{
            "name": name, "ops": ops_acc.get(name, 0), "share": round(ops_acc.get(name, 0) / total, 3),
            "ops_s": round(ops_acc.get(name, 0) / seconds, 2),
            "requests": stat_acc.get(name, [0, 0, 0])[0], "errors_5xx": stat_acc.get(name, [0, 0, 0])[1],
            "throttled_429": stat_acc.get(name, [0, 0, 0])[2],
        } for name in names]
        rows.sort(key=lambda r: (-r["ops"], -r["requests"], r["name"]))
        return {"by": "org", "rows": rows, "window_s": seconds, "unattributed_pct": summary()["db"]["unattributed_pct"]}
    key = {"collection": "colls", "org": "orgs", "op": "ops_types"}.get(by, "colls")
    acc: dict[str, int] = {}
    for slot in minute_tables:
        for name, n in slot[key].items():
            acc[name] = acc.get(name, 0) + n
    total = sum(acc.values()) or 1
    rows = [{"name": name, "ops": n, "share": round(n / total, 3)} for name, n in acc.items()]
    rows.sort(key=lambda r: (-r["ops"], r["name"]))
    if by == "collection":
        detail = _merged_colls(now_min)
        for row in rows:
            extra = detail.get(row["name"])
            if extra:
                row["p95_ms"] = _pct(extra["lat"], CMD_LAT_EDGES, 0.95)
    return {"by": by if by in ("collection", "org", "op", "route") else "collection", "rows": rows,
            "unattributed_pct": summary()["db"]["unattributed_pct"]}


def _merged_colls(now_min: int) -> dict:
    acc = {}
    for age in range(15):
        minute = now_min - age * 60
        i = minute % DETAIL.N
        if DETAIL.stamp[i] != minute:
            continue
        for name, row in DETAIL.colls[i].items():
            dest = acc.get(name)
            if dest is None:
                dest = {"ops": 0, "lat": _empty_hist(CMD_LAT_EDGES)}
                acc[name] = dest
            dest["ops"] += row["ops"]
            for j, n in enumerate(row["lat"]):
                dest["lat"][j] += n
    return acc


def slow_commands() -> list:
    with _LOCK:
        return list(_slow)


def route_stats(route: str) -> dict:
    with _LOCK:
        return dict(_voter.get(route) or {})


def attributed_routes() -> dict:
    return DETAIL.merged_routes(_minute())


def evaluate_perf_alerts(sample: dict) -> list[dict]:
    """Pure. Percentage rules apply only when the tier has a hard cap."""
    out = []
    capped = bool(sample.get("capped"))
    cap = sample.get("cap")

    def add(kind, level, message):
        out.append({"kind": kind, "level": level, "message": message})

    if capped:
        if sample.get("secs_above_warn", 0) >= 10:
            add("ops_warn", "warning",
                f"Database operations at or above {sample.get('warn_pct')}% of the {cap} ops/s cap "
                f"for {sample.get('secs_above_warn')}s (now {sample.get('ops_s')} ops/s).")
        if sample.get("secs_above_crit", 0) >= 5:
            add("ops_critical", "critical",
                f"Database operations at or above {sample.get('crit_pct')}% of the {cap} ops/s cap "
                f"for {sample.get('secs_above_crit')}s (now {sample.get('ops_s')} ops/s).")
        if sample.get("throttle_suspect"):
            add("throttle_suspect", "critical",
                f"Operations are near the {cap} ops/s cap and command latency is high. "
                "The cluster may be throttling.")
    if sample.get("pool_waiting_secs", 0) >= 10 or sample.get("pool_timeouts", 0) > 0:
        add("pool_pressure", "critical",
            f"Connection pool is under pressure (waiting {sample.get('pool_waiting_secs', 0)}s, "
            f"{sample.get('pool_timeouts', 0)} timeouts in the last minute).")
    if (sample.get("loop_lag_p95") or 0) > LOOP_LAG_P95_MS:
        add("loop_lag", "warning",
            f"Event-loop lag p95 is {sample.get('loop_lag_p95')} ms over the last minute.")
    if (sample.get("http_p95") or 0) > HTTP_SLOW_P95_MS and sample.get("http_requests_1m", 0) >= HTTP_SLOW_MIN_REQUESTS:
        add("latency", "warning",
            f"HTTP p95 is {sample.get('http_p95')} ms over the last minute "
            f"({sample.get('http_requests_1m')} requests).")
    if sample.get("election_open") and 0 <= sample.get("uptime_s", 99999) <= COLD_START_SECONDS:
        add("cold_start", "warning",
            f"This process started {sample.get('uptime_s')}s ago while an election phase is open.")
    return out


def apply_cooldown(alerts, last_fired: dict, now: float, start_id: str):
    """Return (alerts that should be sent, updated last-fired map). Pure."""
    fired = []
    updated = dict(last_fired or {})
    for alert in alerts:
        kind = alert["kind"]
        if kind == "cold_start":
            key = f"cold_start:{start_id}"
            if key in updated:
                continue
            updated[key] = now
            fired.append(alert)
            continue
        cooldown = ALERT_COOLDOWN_S.get(kind, 300)
        previous = updated.get(kind)
        if previous is not None and cooldown is not None and (now - previous) < cooldown:
            continue
        updated[kind] = now
        fired.append(alert)
    return fired, updated


async def dispatch_alerts(alerts) -> None:
    """Email newly fired alerts. Never raises into the caller."""
    try:
        from alerts import alert_critical, alert_warning
        fired, updated = apply_cooldown(alerts, _last_fired, _now(), _start_id)
        _last_fired.clear()
        _last_fired.update(updated)
        for alert in fired:
            _recent_alerts.append({"t": datetime_iso(_now()), **alert})
            send = alert_critical if alert["level"] == "critical" else alert_warning
            cooldown = ALERT_COOLDOWN_S.get(alert["kind"]) or 300
            await send(f"Performance {alert['kind']}", alert["message"], cooldown_s=cooldown)
    except Exception:
        _swallow_once("dispatch")


def _org_minute(slot: dict) -> dict:
    """One minute's per-organisation counters as {org: [ops, requests, 5xx, 429]}."""
    stats = slot.get("org_stats", {})
    out = {}
    for name in set(slot["orgs"]) | set(stats):
        st = stats.get(name, [0, 0, 0])
        out[name] = [slot["orgs"].get(name, 0), st[0], st[1], st[2]]
    return out


_ORG_RANGES = {"15m": (15, 60), "24h": (1440, 900), "7d": (10080, 7200)}   # minutes, bucket seconds
_ORG_SERIES_TOP = 6


async def org_series(window: str = "15m") -> dict:
    """Per-organisation load over 15 minutes, 24 hours (memory) or 7 days (memory plus the history sink)."""
    n_min, step = _ORG_RANGES.get(window, _ORG_RANGES["15m"])
    now_min = _minute()
    start = now_min - (n_min - 1) * 60
    per_min: dict[int, dict] = {}
    for age in range(min(n_min, 1440)):
        t = now_min - age * 60
        slot = MINUTES.value(t)
        if slot is not None:
            per_min[t] = _org_minute(slot)
    note = None
    if n_min > 1440:
        try:
            if _manager is None:
                ensure_sink()
            for batch in await _manager.sink.read(start, now_min - 1440 * 60):
                for row in (batch.get("rows") if isinstance(batch, dict) else None) or []:
                    t = row.get("t") if isinstance(row, dict) else None
                    if t is None or t < start or t in per_min or not row.get("orgs"):
                        continue
                    per_min[int(t)] = {k: list(v) for k, v in row["orgs"].items()}
        except Exception:
            _swallow_once("org_series_history")
            note = "Older history could not be read from the sink."
    buckets = max(1, n_min * 60 // step)
    totals: dict[str, list] = {}
    series: dict[str, list] = {}
    for t, per_org in per_min.items():
        if t < start:
            continue
        bi = min(buckets - 1, (t - start) // step)
        for name, v in per_org.items():
            tot = totals.setdefault(name, [0, 0, 0, 0])
            for i in range(4):
                tot[i] += v[i]
            series.setdefault(name, [0] * buckets)[bi] += v[0]
    all_ops = sum(t[0] for t in totals.values()) or 1
    seconds = max(60, len(per_min) * 60)
    rows = [{
        "name": name, "ops": t[0], "share": round(t[0] / all_ops, 3), "ops_s": round(t[0] / seconds, 3),
        "requests": t[1], "errors_5xx": t[2], "throttled_429": t[3],
    } for name, t in totals.items()]
    rows.sort(key=lambda r: (-r["ops"], -r["requests"], r["name"]))
    for row in rows[:_ORG_SERIES_TOP]:
        row["points"] = [round(v / step, 3) for v in series[row["name"]]]
    return {"window": window if window in _ORG_RANGES else "15m", "step_s": step, "buckets": buckets, "start": start,
            "covered_minutes": len(per_min), "rows": rows, "note": note}


def build_batch(now: float | None = None) -> dict | None:
    """Finished minutes since the previous flush. The current minute stays in memory."""
    global _last_flushed_minute
    now = _now() if now is None else now
    end = _minute(now) - 60  # last finished minute
    if end < 0:
        return None
    start = _last_flushed_minute + 60 if _last_flushed_minute is not None else end
    if start > end:
        return None
    rows = []
    t = start
    while t <= end:
        slot = MINUTES.value(t)
        if slot is None:
            rows.append({"t": t, "ops": None})
        else:
            row = {
                "t": t,
                "ops": slot["ops"],
                "cmds": slot["cmds"],
                "reqs": slot["reqs"],
                "http_p95": _pct(slot["http_hist"], API_EDGES, 0.95),
            }
            orgs = _org_minute(slot)
            if orgs:
                row["orgs"] = orgs   # per-organisation [ops, requests, 5xx, 429]; lets the Performance tab chart 7 days
            rows.append(row)
        t += 60
    _last_flushed_minute = end
    return {"_id": rows[0]["t"], "minute_dt": datetime_iso(rows[0]["t"]), "rows": rows}


def _hot() -> bool:
    cfg = current_config()
    cap = cfg.get("ops_cap")
    if not cap:
        return False
    return _last_full_ops() >= (cap * cfg["warn_pct"] / 100.0)


async def flush_once() -> None:
    if _manager is None or not collecting():
        return
    cfg = current_config()
    if not cfg.get("persist_s"):
        return
    batch = build_batch()
    hot = _manager.sink.name == "mongo" and _hot()
    if batch is None:
        if not hot:
            try:
                await _manager.drain()
            except Exception as exc:
                _manager.mark_err(exc)
        try:
            await dispatch_alerts(summary().get("alerts") or [])
        except Exception:
            _swallow_once("flush_alerts")
        return
    try:
        if hot:
            _manager.enqueue(batch)
        else:
            await asyncio.wait_for(_manager.sink.write(batch), timeout=5)
            _manager.mark_ok()
            await _manager.drain()
    except Exception as exc:
        _manager.mark_err(exc)
        _manager.enqueue(batch)
    try:
        await dispatch_alerts(evaluate_perf_alerts(_alert_sample(cfg, summary()["db"], _loop_stats(), _now())))
    except Exception:
        _swallow_once("flush_alerts")


async def _persist_loop():
    while True:
        try:
            cfg = current_config()
            wait = cfg.get("persist_s") or 60
            await asyncio.sleep(max(1, int(wait)))
            if collecting() and cfg.get("persist_s"):
                await flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            _swallow_once("persist_loop")
            await asyncio.sleep(5)


def install_sink(sink) -> None:
    global _manager
    from perf_sinks import SinkManager
    _manager = SinkManager(sink)
    url = os.getenv("PERF_POSTGRES_URL") or os.getenv("PERF_MONGO_URL")
    _manager.add_secret(url)


_db_getter = None


def ensure_sink(get_db=None) -> None:
    """Install the configured sink with a real database handle if start() has not run (for example in tests).

    The getter is remembered, so a sink rebuilt later never ends up without a database handle."""
    global _db_getter
    if get_db is not None:
        _db_getter = get_db
    if _manager is None:
        from perf_sinks import build_sink
        install_sink(build_sink(lambda: _db_getter() if _db_getter else None))


def sink_status() -> dict:
    if _manager is None:
        ensure_sink()
    return _manager.status()


async def read_history(start_epoch: int, end_epoch: int) -> dict:
    if _manager is None:
        ensure_sink()
    from perf_sinks import gap_fill
    sink = _manager.sink
    window = 7 * 86400
    if sink.name == "b2":
        window = 86400
    if end_epoch - start_epoch > window:
        start_epoch = end_epoch - window
    batches = await sink.read(start_epoch, end_epoch)
    return {
        "sink": sink.name,
        "from": start_epoch,
        "to": end_epoch,
        "minutes": gap_fill(batches, start_epoch, end_epoch),
        "uses_main_cluster": sink.name == "mongo",
    }


_tasks: list = []


async def start(db, b2_client=None) -> None:
    global _tasks
    if not perf_enabled():
        return
    from perf_sinks import build_sink
    from perf_tiers import load_config
    try:
        await load_config(db)
    except Exception:
        _swallow_once("load_config")
    refresh_flags()
    install_sink(build_sink(lambda: db, b2_client=b2_client))
    sink = _manager.sink
    if sink.name == "mongo":
        try:
            await sink.ensure_index(current_config()["retention_days"])
        except Exception:
            _swallow_once("ttl_index")
    if not _tasks:
        _tasks = [asyncio.create_task(lag_probe()), asyncio.create_task(_persist_loop())]


async def stop() -> None:
    global _tasks
    tasks, _tasks = _tasks, []
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _swallow_once("stop")


def reset_for_tests() -> None:
    """Drop in-memory counters. Does not rebuild the listener objects."""
    global _paused, _slow_ms, _collecting_since, _election_open, _summary_computes
    global _sequences, _inflight, _inflight_peak, _inflight_peak_at, _cpu_pct
    global _last_flushed_minute, _manager, _pool_waiting_since, _started_at, _start_id
    with _LOCK:
        SECONDS.__init__()
        MINUTES.__init__()
        DETAIL.__init__()
        _slow.clear()
        _inflight_cmds.clear()
        _lag_samples.clear()
        _timeouts.clear()
        for route in _voter.values():
            route["n"] = 0
            route["ops"] = 0
        _sequences = 0
        for key in _election:
            _election[key] = 0
        _sms.update({"sends": 0, "failures": 0, "latency_sum": 0.0, "n": 0})
        _cache.clear()
        _inflight = 0
        _inflight_peak = 0
        _inflight_peak_at = 0
        POOL_LISTENER.in_use = 0
        POOL_LISTENER.waiting = 0
        POOL_LISTENER.created = 0
        POOL_LISTENER.closed = 0
        POOL_LISTENER.timeouts = 0
        POOL_LISTENER.wait_hist = _empty_hist(CMD_LAT_EDGES)
    _collecting_since = None
    _election_open = False
    _summary_computes = 0
    _last_flushed_minute = None
    _pool_waiting_since = None
    _recent_alerts.clear()
    _last_fired.clear()
    _started_at = _now()
    _start_id = str(int(_started_at))
    invalidate_summary()
    from perf_tiers import swap_saved
    swap_saved({})
    refresh_flags()


on_change(refresh_flags)
refresh_flags()
