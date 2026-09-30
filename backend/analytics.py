"""Privacy-safe, aggregate-only site usage analytics.

No raw events, IP addresses, URLs or identifiers are stored. Collection only mutates
memory; MongoDB is written by the periodic flusher (one bulk_write per collection).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pymongo import UpdateOne
from starlette.routing import Match

from alerts import alert_critical, alert_warning

log = logging.getLogger("analytics")

PAGE_PREFIXES = {
    "voter_identity", "voter_otp", "voter_ballot", "results", "apply",
    "candidate_status", "verify_certificate", "admin_login", "superadmin",
    "commission", "it_admin", "financial_controller", "overseer",
}
PAGE_RE = re.compile(r"^[a-z_]{3,24}(:[a-z0-9_]{2,40})?$")
LABEL_RE = re.compile(r"^[a-z0-9_-]{2,40}$")
ERR_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]{0,39}$")
NET_VALUES = {"slow-2g", "2g", "3g", "4g", "unknown"}
NET_ERRORS = {"net:network", "net:timeout"}
BROWSERS = (("Edge", re.compile(r"Edg/")), ("Opera", re.compile(r"OPR/")),
            ("Chrome", re.compile(r"Chrome/|CriOS/")), ("Firefox", re.compile(r"Firefox/|FxiOS/")),
            ("Safari", re.compile(r"Safari/")))
API_EDGES = [100, 250, 500, 1000, 2000, 5000]
LOAD_EDGES = [500, 1000, 2000, 3000, 5000, 8000]
FIRST_API_EDGES = [300, 700, 1500, 3000, 5000, 10000]
COLD_MS = 5000
CAPS = {"pages": 150, "labels": 60, "errors": 40, "routes": 400}
MAX_SIDS = 50_000
SKIP_PATHS = {"/analytics/collect", "/health", "/"}

# ---- in-memory state (single event loop; no awaits inside mutations, so no lock) ----
_deltas: dict[tuple, dict[str, int]] = {}
_heat: dict[tuple, int] = defaultdict(int)
_seen_pages: dict[str, set] = defaultdict(set)
_seen_labels: dict[tuple, set] = defaultdict(set)
_seen_errors: dict[str, set] = defaultdict(set)
_seen_routes: set[str] = set()
_sid_windows: dict[str, deque] = {}
_global_window: deque = deque()
_live: dict[tuple[str, str], float] = {}
_minutes: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
_last_flush_at: str | None = None
_dropped_over_capacity = 0
_task: asyncio.Task | None = None
_db = None
_org_slug_resolver: Callable[[str], str | None] = lambda org_id: None
_org_id_resolver: Callable[[str], Any] | None = None


def _enabled() -> bool:
    return os.getenv("ANALYTICS_ENABLED", "true").strip().lower() == "true"


# ============================== pure helpers ==============================
def page_ok(page: Any) -> bool:
    if not isinstance(page, str) or not PAGE_RE.fullmatch(page):
        return False
    return page.split(":", 1)[0] in PAGE_PREFIXES


def device_bucket(width: Any) -> str:
    try:
        w = int(width)
    except (TypeError, ValueError):
        return "desktop"
    return "mobile" if w < 768 else "tablet" if w < 1100 else "desktop"


def parse_ua(ua: str | None) -> tuple[str, str, str]:
    """Return (browser, os, source). Source is 'browser' or 'in_app:<name>'."""
    s = ua or ""
    low = s.lower()
    source, browser = "browser", None
    if "fban" in low or "fbav" in low or "facebook" in low:
        source, browser = "in_app:facebook", "Facebook"
    elif "instagram" in low:
        source, browser = "in_app:instagram", "Instagram"
    elif "whatsapp" in low:
        source, browser = "in_app:whatsapp", "WhatsApp"
    elif "tiktok" in low or "musical_ly" in low or "bytedance" in low:
        source, browser = "in_app:tiktok", "TikTok"
    elif re.search(r"\bwv\b|; wv\)|line/|snapchat|twitter|linkedinapp", low):
        source, browser = "in_app:other", "In-app"
    if browser is None:
        browser = "Other"
        for name, rx in BROWSERS:
            if rx.search(s):
                browser = name
                break
    if "android" in low:
        os_name = "Android"
    elif "iphone" in low or "ipad" in low or "ipod" in low:
        os_name = "iOS"
    elif "windows" in low:
        os_name = "Windows"
    elif "mac os" in low or "macintosh" in low:
        os_name = "macOS"
    elif "linux" in low or "cros" in low:
        os_name = "Linux"
    else:
        os_name = "Other"
    return browser, os_name, source


def _clamp(v, lo, hi, default=0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return max(lo, min(hi, f))


ALLOWED_FIELDS = {"t", "page", "from", "from_dur", "first", "ns", "second", "entry", "label", "gx", "gy",
                  "dead", "rage", "pct", "dur", "name", "load_ms", "first_api_ms", "net"}


def validate_events(payload: Any) -> tuple[str, int, str, list[dict[str, Any]]]:
    """Validate and normalise a collect body. Raises ValueError for unusable bodies."""
    if not isinstance(payload, dict):
        raise ValueError("invalid body")
    try:
        sid = str(uuid.UUID(str(payload.get("sid"))))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("bad sid")
    w = int(_clamp(payload.get("w", 0), 1, 10000, 1))
    seg = payload.get("seg", "public")
    seg = seg if seg in {"public", "staff"} else "public"
    events = payload.get("events", [])
    if not isinstance(events, list) or len(events) > 25:
        raise ValueError("too many events")
    out = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        e = {k: v for k, v in raw.items() if k in ALLOWED_FIELDS}
        t, page = e.get("t"), e.get("page")
        if t not in {"pv", "click", "scroll", "leave", "err", "perf"} or not page_ok(page):
            continue
        if t == "click":
            label = e.get("label")
            e["label"] = label if isinstance(label, str) and LABEL_RE.fullmatch(label) else "unknown"
            e["gx"] = int(_clamp(e.get("gx"), 0, 49))
            e["gy"] = int(_clamp(e.get("gy"), 0, 400))
            e["dead"], e["rage"] = bool(e.get("dead")), bool(e.get("rage"))
        elif t == "pv":
            frm = e.get("from")
            e["from"] = frm if frm == "(entry)" or page_ok(frm) else "(entry)"
            e["from_dur"] = int(_clamp(e.get("from_dur"), 0, 1_800_000))
            e["entry"] = e["entry"] if page_ok(e.get("entry")) else page
            for k in ("first", "ns", "second"):
                e[k] = bool(e.get(k))
        elif t == "leave":
            e["dur"] = int(_clamp(e.get("dur"), 0, 1_800_000))
        elif t == "scroll":
            e["pct"] = int(_clamp(e.get("pct"), 0, 100))
        elif t == "err":
            name = str(e.get("name", "Error"))
            e["name"] = name if name in NET_ERRORS or ERR_RE.fullmatch(name) else "Error"
        elif t == "perf":
            e["load_ms"] = int(_clamp(e.get("load_ms"), 0, 60000))
            e["first_api_ms"] = int(_clamp(e.get("first_api_ms"), 0, 60000))
            e["net"] = e.get("net") if e.get("net") in NET_VALUES else "unknown"
        out.append(e)
    return sid, w, seg, out


def hist_percentile(counts: list[int], edges: list[int], q: float) -> float | None:
    """Linear-interpolated percentile from a histogram. counts has len(edges)+1 buckets;
    the open last bucket reports the last finite edge."""
    total = sum(counts)
    if not total:
        return None
    target = total * q
    cum = 0
    for i, c in enumerate(counts):
        if c and target <= cum + c:
            if i >= len(edges):
                return float(edges[-1])
            lo = 0 if i == 0 else edges[i - 1]
            return lo + (edges[i] - lo) * ((target - cum) / c)
        cum += c
    return float(edges[-1])


def _hist_index(ms: float, edges: list[int]) -> int:
    for i, edge in enumerate(edges):
        if ms <= edge:
            return i
    return len(edges)


def route_template(request: Any, status: int | None = None) -> str:
    """Route template for a finished request; never the raw path (which can hold IDs)."""
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    # No route in scope: a guard answered before routing, or nothing matches.
    try:
        for candidate in request.app.router.routes:
            match, _ = candidate.matches(request.scope)
            if match in (Match.FULL, Match.PARTIAL):
                return "(guard)"
    except Exception:
        pass
    return "(unmatched)"


DEFAULT_ALERT_CONFIG = {"5xx": 10, "429": 30, "fe": 20, "spike_factor": 5, "spike_min": 150,
                        "cold_pct": 0.30, "cold_min_sessions": 20}


def evaluate_alerts(window_stats: dict[str, Any], config: dict[str, float]) -> list[dict[str, Any]]:
    """Pure: in-memory window stats in, alerts out. Never touches a database."""
    g = window_stats.get
    out: list[dict[str, Any]] = []

    def add(kind, level, metric, value, threshold, routes=()):
        out.append({"kind": kind, "level": level, "metric": metric, "value": value,
                    "threshold": threshold, "routes": list(routes)[:3]})

    if g("server_5xx", 0) >= config["5xx"]:
        add("5xx", "critical", "Server 5xx responses per minute", g("server_5xx"), config["5xx"], g("routes_5xx", []))
    if g("responses_429", 0) >= config["429"]:
        add("429", "warning", "HTTP 429 responses per minute", g("responses_429"), config["429"], g("routes_429", []))
    if g("front_end_errors", 0) >= config["fe"]:
        add("front_end", "warning", "Front-end errors per minute", g("front_end_errors"), config["fe"])
    views, avg = g("views", 0), g("trailing_15_avg", 0)
    if views >= config["spike_min"] and views >= config["spike_factor"] * avg:
        add("spike", "warning", "Page views per minute", views,
            max(config["spike_min"], config["spike_factor"] * avg))
    sessions = g("sessions", 0)
    if sessions >= config.get("cold_min_sessions", 20) and g("cold", 0) / sessions >= config["cold_pct"]:
        add("cold", "warning", "Suspected cold-start share of sessions (15 min)",
            round(g("cold", 0) / sessions, 3), config["cold_pct"])
    return out


def build_window_stats(minutes: dict[int, dict[str, Any]], now_min: int) -> dict[str, Any]:
    """Per-minute rolling counters -> the stats evaluate_alerts expects."""
    cur, prev = minutes.get(now_min, {}), minutes.get(now_min - 1, {})
    pick = lambda f: max(cur.get(f, 0), prev.get(f, 0))  # noqa: E731 (a flush can land mid-minute)
    older = [minutes.get(now_min - 1 - i, {}).get("views", 0) for i in range(1, 16)]
    last15 = [minutes.get(now_min - i, {}) for i in range(0, 15)]

    def top_routes(field):
        merged: dict[str, int] = defaultdict(int)
        for m in (cur, prev):
            for r, n in m.get(field, {}).items():
                merged[r] += n
        return [r for r, _ in sorted(merged.items(), key=lambda x: -x[1])[:3]]

    return {"server_5xx": pick("s5"), "responses_429": pick("s429"), "front_end_errors": pick("fe"),
            "views": pick("views"), "trailing_15_avg": sum(older) / 15,
            "sessions": sum(m.get("perf_n", 0) for m in last15), "cold": sum(m.get("cold", 0) for m in last15),
            "routes_5xx": top_routes("r5"), "routes_429": top_routes("r429")}


def _alert_config() -> dict[str, float]:
    f = lambda k, d: float(os.getenv(k, d))  # noqa: E731
    return {"5xx": f("ANALYTICS_ALERT_5XX_PER_MIN", "10"), "429": f("ANALYTICS_ALERT_429_PER_MIN", "30"),
            "fe": f("ANALYTICS_ALERT_FE_ERR_PER_MIN", "20"), "spike_factor": f("ANALYTICS_ALERT_SPIKE_FACTOR", "5"),
            "spike_min": 150, "cold_pct": f("ANALYTICS_ALERT_COLD_PCT", "0.30"), "cold_min_sessions": 20}


# ============================== in-memory aggregation ==============================
def _inc(key: tuple, fields: dict[str, int]) -> None:
    d = _deltas.setdefault(key, {})
    for k, v in fields.items():
        d[k] = d.get(k, 0) + v


def _bump(org: str, field: str, n: int = 1, route: str | None = None) -> None:
    m = _minutes[org].setdefault(int(time.time() // 60), {})
    m[field] = m.get(field, 0) + n
    if route is not None:
        rf = "r5" if field == "s5" else "r429"
        rd = m.setdefault(rf, {})
        rd[route] = rd.get(route, 0) + 1


def _trim_minutes(now_min: int) -> None:
    for org in list(_minutes):
        for k in [k for k in _minutes[org] if k < now_min - 16]:
            del _minutes[org][k]
        if not _minutes[org]:
            del _minutes[org]


def _day_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _accept_event(org, device, seg, browser, os_name, source, e, now) -> None:
    day, t, page = _day_key(now), e["t"], e["page"]
    if page not in _seen_pages[org]:
        if len(_seen_pages[org]) >= CAPS["pages"]:
            return
        _seen_pages[org].add(page)
    ua_key = f"{browser}|{os_name}"
    if t == "pv":
        h = {f"h.{now.hour}": 1}
        _inc((org, day, "pv", page, ua_key, device, seg),
             {"n": 1, "uv": 1 if e["first"] else 0, "dur_sum": 0, "dur_n": 0, **h})
        _bump(org, "views")
        frm = e["from"]
        _inc((org, day, "trans", frm, page, device, seg), {"n": 1})
        if frm != "(entry)" and e["from_dur"] > 0:  # time spent on the PREVIOUS page
            _inc((org, day, "pv", frm, ua_key, device, seg), {"dur_sum": e["from_dur"], "dur_n": 1})
        if e["ns"]:
            _inc((org, day, "sess", e["entry"], source, device, seg), {"n": 1, **h})
        if e["second"]:
            _inc((org, day, "sess2", e["entry"], source, device, seg), {"n": 1})
    elif t == "leave":
        if e["dur"] > 0:
            _inc((org, day, "pv", page, ua_key, device, seg), {"dur_sum": e["dur"], "dur_n": 1})
    elif t == "click":
        label = e["label"]
        _heat[(org, page, device, seg, "click", e["gx"], e["gy"])] += 1
        lk = (org, page)
        if label not in _seen_labels[lk]:
            if len(_seen_labels[lk]) >= CAPS["labels"]:
                return
            _seen_labels[lk].add(label)
        _inc((org, day, "click", page, label, device, seg), {"n": 1})
        if e["dead"]:
            _inc((org, day, "dead", page, label, device, seg), {"n": 1})
        if e["rage"]:
            _inc((org, day, "rage", page, label, device, seg), {"n": 1})
    elif t == "scroll":
        _heat[(org, page, device, seg, "scroll", 0, min(10, e["pct"] // 10))] += 1
    elif t == "err":
        name = e["name"]
        if name not in _seen_errors[org]:
            if len(_seen_errors[org]) >= CAPS["errors"]:
                return
            _seen_errors[org].add(name)
        _inc((org, day, "err", page, name, device, seg), {"n": 1})
        if name not in NET_ERRORS:
            _bump(org, "fe")
    elif t == "perf":
        load, api = e["load_ms"], e["first_api_ms"]
        fields = {"n": 1, "cold": 1 if api >= COLD_MS else 0}
        if load > 0:
            fields[f"l.{_hist_index(load, LOAD_EDGES)}"] = 1
        if api > 0:
            fields[f"c.{_hist_index(api, FIRST_API_EDGES)}"] = 1
        _inc((org, day, "perf", page, "", device, seg), fields)
        _inc((org, day, "net", e["net"], "", "all", "all"), {"n": 1})
        _bump(org, "perf_n")
        if api >= COLD_MS:
            _bump(org, "cold")


def ingest(org_id: str, sid: str, width: int, seg: str, ua: str, events: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc)
    device = device_bucket(width)
    browser, os_name, source = parse_ua(ua)
    _live[(org_id, sid)] = time.monotonic()
    for e in events:
        _accept_event(org_id, device, seg, browser, os_name, source, e, now)


def admit(sid: str, now: float | None = None) -> bool:
    """Per-sid and global load shedding. Returns False when the batch should be dropped."""
    global _dropped_over_capacity
    now = time.monotonic() if now is None else now
    q = _sid_windows.get(sid)
    if q is None:
        if len(_sid_windows) >= MAX_SIDS:
            for k in list(_sid_windows)[:1000]:
                _sid_windows.pop(k, None)
        q = _sid_windows[sid] = deque()
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= 12:
        return False
    while _global_window and _global_window[0] < now - 1:
        _global_window.popleft()
    if len(_global_window) >= int(os.getenv("ANALYTICS_MAX_RPS", "200")):
        _dropped_over_capacity += 1
        return False
    _global_window.append(now)
    q.append(now)
    return True


# ============================== flush ==============================
def _conc_delta(now: datetime) -> None:
    cutoff = time.monotonic() - 300
    active: dict[str, int] = defaultdict(int)
    for (org, _sid), seen in list(_live.items()):
        if seen >= cutoff:
            active[org] += 1
        else:
            _live.pop((org, _sid), None)
    slot = now.hour * 12 + now.minute // 5
    for org, n in active.items():
        key = (org, _day_key(now), "conc", "", "", "all", "all")
        d = _deltas.setdefault(key, {})
        d[f"m.{slot}"] = max(d.get(f"m.{slot}", 0), n)


def _build_ops(deltas: dict, heat: dict):
    ops = []
    for (org, day, kind, k1, k2, device, seg), fields in deltas.items():
        ident = {"org_id": org, "day": day, "kind": kind, "k1": k1, "k2": k2, "device": device, "seg": seg}
        on_insert = {"day_dt": datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)}
        ops.append(UpdateOne(ident, {"$setOnInsert": on_insert, ("$max" if kind == "conc" else "$inc"): fields},
                             upsert=True))
    hops = [UpdateOne({"org_id": o, "page": p, "device": d, "seg": s, "kind": k, "gx": gx, "gy": gy},
                      {"$inc": {"n": n}}, upsert=True) for (o, p, d, s, k, gx, gy), n in heat.items()]
    return ops, hops


def _restore(deltas: dict, heat: dict) -> None:
    """A failed flush must not lose data: merge the snapshot back into the buffers."""
    for key, fields in deltas.items():
        if key[2] == "conc":
            d = _deltas.setdefault(key, {})
            for k, v in fields.items():
                d[k] = max(d.get(k, 0), v)
        else:
            _inc(key, fields)
    for k, n in heat.items():
        _heat[k] += n


async def _send_alerts() -> None:
    if os.getenv("ANALYTICS_ALERTS_ENABLED", "true").strip().lower() != "true":
        return
    now_min = int(time.time() // 60)
    cfg = _alert_config()
    for org, minutes in list(_minutes.items()):
        for a in evaluate_alerts(build_window_stats(minutes, now_min), cfg):
            slug = None
            try:
                slug = _org_slug_resolver(org)
            except Exception:
                pass
            subject = f"Site usage alert ({a['kind']}) - {slug or 'unknown organisation'}"
            body = (f"Metric: {a['metric']}\nValue: {a['value']}\nThreshold: {a['threshold']}\n"
                    f"Routes: {', '.join(a['routes']) if a['routes'] else 'n/a'}")
            try:
                await (alert_critical if a["level"] == "critical" else alert_warning)(subject, body)
            except Exception:
                log.debug("analytics alert send failed", exc_info=True)


async def _flush_once() -> None:
    global _deltas, _heat, _last_flush_at
    if _db is None:
        return
    now = datetime.now(timezone.utc)
    _conc_delta(now)
    deltas, _deltas = _deltas, {}
    heat, _heat = _heat, defaultdict(int)
    ops, hops = _build_ops(deltas, heat)
    try:
        if ops:
            await _db.analytics_counters.bulk_write(ops, ordered=False)
        if hops:
            await _db.analytics_heat.bulk_write(hops, ordered=False)
        _last_flush_at = now.isoformat()
    except Exception:
        _restore(deltas, heat)
        log.debug("analytics flush failed; buffers restored", exc_info=True)
    try:
        await _send_alerts()
    except Exception:
        log.debug("analytics alerts failed", exc_info=True)
    _trim_minutes(int(time.time() // 60))


async def _flusher() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await _flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("analytics flusher error", exc_info=True)


# ============================== summary (pure over documents) ==============================
def _sub(d: dict, field: str, i: int) -> int:
    """Dotted $inc keys are stored as nested documents: {'h': {'3': 5}}."""
    v = d.get(field)
    return int(v.get(str(i), 0)) if isinstance(v, dict) else 0


def _hist(d: dict, field: str, n: int = 7) -> list[int]:
    return [_sub(d, field, i) for i in range(n)]


def _add(a: list[int], b: list[int]) -> list[int]:
    return [x + y for x, y in zip(a, b)]


def _rows(m: dict, limit: int | None = None) -> list[dict]:
    items = sorted(m.items(), key=lambda x: -x[1])
    return [{"label": k, "value": v} for k, v in (items[:limit] if limit else items)]


def _timeline_buckets(now: datetime, days: int, bucket: str) -> list[str]:
    if bucket == "hour":
        start = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z") for i in range(days * 24)]
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]


def build_summary(docs, days: int, now: datetime, live: int = 0, meta: dict | None = None,
                  bucket: str | None = None) -> dict[str, Any]:
    bucket = bucket or ("hour" if days <= 7 else "day")
    tl = {k: {"t": k, "views": 0, "sessions": 0} for k in _timeline_buckets(now, days, bucket)}
    cutoff = now - timedelta(days=days)
    views = sessions = sess2 = dur_sum = 0
    pages, devices, browsers, oss = (defaultdict(int) for _ in range(4))
    src_sess, src_sess2 = defaultdict(int), defaultdict(int)
    entries, entries2, trans, elements = (defaultdict(int) for _ in range(4))
    out_trans, entry_by_page = defaultdict(int), defaultdict(int)
    dead = rage = errors = netfail = 0
    err_classes, network = defaultdict(int), defaultdict(int)
    api = defaultdict(lambda: {"n": 0, "e401": 0, "e429": 0, "e4": 0, "e5": 0, "b": [0] * 7})
    perf = defaultdict(lambda: {"n": 0, "cold": 0, "l": [0] * 7, "c": [0] * 7})
    hour = [0] * 24
    peak, peak_at = 0, None

    def put(day: str, hour_i: int | None, field: str, n: int) -> None:
        if bucket == "day":
            if day in tl:
                tl[day][field] += n
        elif hour_i is not None:
            k = f"{day}T{hour_i:02d}:00:00Z"
            if k in tl and datetime.strptime(k, "%Y-%m-%dT%H:00:00Z").replace(tzinfo=timezone.utc) > cutoff:
                tl[k][field] += n

    for d in docs:
        kind, n, k1, k2 = d.get("kind"), d.get("n", 0), d.get("k1", ""), d.get("k2", "")
        day = d.get("day", "")
        if kind == "pv":
            views += n
            dur_sum += d.get("dur_sum", 0)
            pages[k1] += n
            devices[d.get("device", "desktop")] += n
            b, o = (k2.split("|") + ["Other"])[:2]
            browsers[b] += n
            oss[o] += n
            for i in range(24):
                h = _sub(d, "h", i)
                if h:
                    hour[i] += h
                    put(day, i, "views", h)
        elif kind == "sess":
            sessions += n
            src_sess[k2] += n
            entries[(k1, k2)] += n
            entry_by_page[k1] += n
            for i in range(24):
                h = _sub(d, "h", i)
                if h:
                    put(day, i, "sessions", h)
            if bucket == "day":
                put(day, None, "sessions", n)
        elif kind == "sess2":
            sess2 += n
            src_sess2[k2] += n
            entries2[(k1, k2)] += n
        elif kind == "trans":
            trans[(k1, k2)] += n
            out_trans[k1] += n
        elif kind == "click":
            elements[(k1, k2)] += n
        elif kind == "dead":
            dead += n
        elif kind == "rage":
            rage += n
        elif kind == "err":
            if k2 in NET_ERRORS:
                netfail += n
            else:
                errors += n
            err_classes[k2] += n
        elif kind == "net":
            network[k1] += n
        elif kind == "api":
            a = api[k1]
            a["n"] += n
            for f in ("e401", "e429", "e4", "e5"):
                a[f] += d.get(f, 0)
            a["b"] = _add(a["b"], _hist(d, "b"))
        elif kind == "perf":
            p = perf[(k1, d.get("device", "all"))]
            p["n"] += n
            p["cold"] += d.get("cold", 0)
            p["l"], p["c"] = _add(p["l"], _hist(d, "l")), _add(p["c"], _hist(d, "c"))
        elif kind == "conc":
            for i in range(288):
                m = _sub(d, "m", i)
                if m > peak:
                    peak, peak_at = m, (datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                                        + timedelta(minutes=5 * i)).isoformat()
    if live > peak:
        peak, peak_at = live, now.isoformat()
    if bucket == "day":  # daily view counts come from the hour arrays already applied via put(); fine
        pass

    def pct(hist, edges, q):
        v = hist_percentile(hist, edges, q)
        return None if v is None else round(v)

    perf_n = sum(p["n"] for p in perf.values())
    cold_n = sum(p["cold"] for p in perf.values())
    api_rows = []
    for route, a in sorted(api.items(), key=lambda x: -x[1]["n"])[:50]:
        errs = a["e401"] + a["e429"] + a["e4"] + a["e5"]
        api_rows.append({"route": route, "requests": a["n"], "e401": a["e401"], "e429": a["e429"], "e4": a["e4"],
                         "e5": a["e5"], "error_rate": errs / a["n"] if a["n"] else 0,
                         "p50": pct(a["b"], API_EDGES, .5), "p95": pct(a["b"], API_EDGES, .95)})
    return {
        "totals": {"views": views, "sessions": sessions,
                   "pages_per_session": round(views / sessions, 2) if sessions else 0,
                   "bounce": max(0.0, 1 - sess2 / sessions) if sessions else 0,
                   "average_session_seconds": round(dur_sum / 1000 / sessions) if sessions else 0,
                   "live_now": live, "peak_concurrency": peak, "peak_concurrency_time": peak_at},
        "timeline": {"bucket": bucket, "points": list(tl.values())},
        "hour_of_day": hour,
        "top_pages": [{"label": k, "value": v, "exits": max(0, v - out_trans.get(k, 0)),
                       "entries": entry_by_page.get(k, 0)} for k, v in sorted(pages.items(), key=lambda x: -x[1])[:15]],
        "devices": _rows(devices), "browsers": _rows(browsers, 10), "os": _rows(oss, 10),
        "entry_sources": [{"label": s, "value": v, "bounce": max(0.0, 1 - src_sess2.get(s, 0) / v) if v else 0}
                          for s, v in sorted(src_sess.items(), key=lambda x: -x[1])],
        "entries": [{"label": f"{p} · {s}", "value": v, "bounce": max(0.0, 1 - entries2.get((p, s), 0) / v)}
                    for (p, s), v in sorted(entries.items(), key=lambda x: -x[1])[:15]],
        "transitions": [{"label": f"{a} → {b}", "value": v} for (a, b), v in
                        sorted(trans.items(), key=lambda x: -x[1])[:30]],
        "elements": [{"page": p, "label": lb, "value": v} for (p, lb), v in
                     sorted(elements.items(), key=lambda x: -x[1])[:40]],
        "quality": {"dead_clicks": dead, "rage_clicks": rage, "errors": errors, "network_failures": netfail},
        "error_classes": _rows(err_classes, 15),
        "api": api_rows,
        "perf": [{"page": k[0], "device": k[1], "sessions": v["n"], "load_p50": pct(v["l"], LOAD_EDGES, .5),
                  "load_p95": pct(v["l"], LOAD_EDGES, .95), "first_api_p50": pct(v["c"], FIRST_API_EDGES, .5),
                  "first_api_p95": pct(v["c"], FIRST_API_EDGES, .95),
                  "cold_pct": v["cold"] / v["n"] if v["n"] else 0}
                 for k, v in sorted(perf.items(), key=lambda x: -x[1]["n"])[:30]],
        "cold_starts": {"sessions": perf_n, "suspected": cold_n, "pct": cold_n / perf_n if perf_n else 0},
        "network": [{"label": k, "value": v, "share": v / max(1, sum(network.values()))}
                    for k, v in sorted(network.items(), key=lambda x: -x[1])],
        "meta": {"live_is_approximate": True, "dropped_over_capacity": _dropped_over_capacity,
                 "last_flush_at": _last_flush_at, **(meta or {})},
    }


def compact_for_compare(s: dict[str, Any]) -> dict[str, Any]:
    reqs = sum(a["requests"] for a in s["api"])
    errs = sum(a["e401"] + a["e429"] + a["e4"] + a["e5"] for a in s["api"])
    p95s = [p["load_p95"] for p in s["perf"] if p["load_p95"] is not None]
    return {"totals": s["totals"], "timeline": s["timeline"]["points"], "devices": s["devices"],
            "peak_concurrency": s["totals"]["peak_concurrency"], "top_pages": s["top_pages"][:5],
            "api_error_rate": errs / reqs if reqs else 0, "load_p95": max(p95s) if p95s else None}


def live_now(org: str) -> int:
    cutoff = time.monotonic() - 300
    return sum(1 for (o, _s), seen in _live.items() if o == org and seen >= cutoff)


# ============================== purge ==============================
def _purge_memory(org_id: str) -> None:
    for store in (_deltas, _heat):
        for k in [k for k in store if k[0] == org_id]:
            store.pop(k, None)
    for store in (_seen_pages, _seen_errors, _minutes):
        store.pop(org_id, None)
    for k in [k for k in _seen_labels if k[0] == org_id]:
        _seen_labels.pop(k, None)
    for k in [k for k in _live if k[0] == org_id]:
        _live.pop(k, None)


async def purge_org_analytics(db, org_id: str) -> None:
    _purge_memory(org_id)
    await db.analytics_counters.delete_many({"org_id": org_id})
    await db.analytics_heat.delete_many({"org_id": org_id})


# ============================== router ==============================
VALID_DAYS, VALID_SEG, VALID_DEVICE = {1, 7, 30, 90}, {"public", "staff", "all"}, {"all", "mobile", "tablet", "desktop"}


def _check_filters(days, seg, device) -> None:
    if days not in VALID_DAYS or seg not in VALID_SEG or device not in VALID_DEVICE:
        raise HTTPException(400, "Invalid analytics filters.")


def _counter_query(orgs, days, seg, device, now):
    q: dict[str, Any] = {"org_id": {"$in": orgs} if isinstance(orgs, list) else orgs,
                         "day": {"$gte": (now - timedelta(days=days)).strftime("%Y-%m-%d")}}
    if seg != "all":
        q["seg"] = {"$in": [seg, "all"]}  # api/net/conc documents are stored with seg="all"
    if device != "all":
        q["device"] = {"$in": [device, "all"]}
    return q


def build_router(get_db, require_role, log_action_fn=None) -> APIRouter:
    router = APIRouter()

    async def collect(request: Request):
        if not _enabled():
            return {"ok": True}
        try:
            org_id = getattr(request.state, "org_id", None)
            if not org_id:
                return {"ok": True}
            if int(request.headers.get("content-length") or 0) > 16384:
                return {"ok": True}
            body = await request.body()
            if len(body) > 16384:
                return {"ok": True}
            sid, w, seg, events = validate_events(await request.json())
            if events and admit(sid):
                ingest(org_id, sid, w, seg, request.headers.get("user-agent", ""), events)
        except Exception:
            log.debug("analytics collect rejected", exc_info=True)
        return {"ok": True}

    router.add_api_route("/analytics/collect", collect, methods=["POST"], status_code=202)

    def active_org(request: Request) -> str:
        org = getattr(request.state, "org_id", None)
        if not org:
            raise HTTPException(400, "Organisation context is required.")
        return org

    @router.get("/superadmin/analytics/summary")
    async def summary(request: Request, days: int = 7, seg: str = "public", device: str = "all",
                      admin: dict = Depends(require_role("superadmin"))):
        _check_filters(days, seg, device)
        org, now = active_org(request), datetime.now(timezone.utc)
        cursor = get_db().analytics_counters.find(_counter_query(org, days, seg, device, now))
        docs = [d async for d in cursor]
        return build_summary(docs, days, now, live=live_now(org))

    @router.get("/superadmin/analytics/heatmap")
    async def heatmap(request: Request, page: str, device: str = "all", kind: str = "click", seg: str = "all",
                      admin: dict = Depends(require_role("superadmin"))):
        if not page_ok(page) or kind not in {"click", "scroll"} or seg not in VALID_SEG or device not in VALID_DEVICE:
            raise HTTPException(400, "Invalid heatmap filters.")
        q: dict[str, Any] = {"org_id": active_org(request), "page": page, "kind": kind}
        if device != "all":
            q["device"] = device
        if seg != "all":
            q["seg"] = seg
        cells: dict[tuple, int] = defaultdict(int)
        async for d in get_db().analytics_heat.find(q).limit(5000):
            cells[(d["gx"], d["gy"])] += d.get("n", 0)
        return [{"gx": gx, "gy": gy, "n": n} for (gx, gy), n in cells.items()]

    @router.delete("/superadmin/analytics")
    async def clear(request: Request, body: dict = Body(...), admin: dict = Depends(require_role("superadmin"))):
        if body.get("confirm") is not True:
            raise HTTPException(400, "Confirmation required.")
        org = active_org(request)
        await purge_org_analytics(get_db(), org)
        if log_action_fn:
            try:
                await log_action_fn("analytics_cleared", admin.get("sub", "unknown"), {}, org_id=org)
            except Exception:
                log.debug("analytics audit log failed", exc_info=True)
        return {"ok": True}

    @router.get("/superadmin/analytics/compare")
    async def compare(orgs: str, days: int = 7, seg: str = "public", device: str = "all",
                      admin: dict = Depends(require_role("superadmin"))):
        slugs = list(dict.fromkeys(s.strip() for s in orgs.split(",") if s.strip()))
        if not 1 <= len(slugs) <= 4:
            raise HTTPException(400, "Between one and four organisations may be compared.")
        _check_filters(days, seg, device)
        db, now = get_db(), datetime.now(timezone.utc)
        found = await db.organizations.find({"slug": {"$in": slugs}}).to_list(length=4)
        by_slug = {o["slug"]: str(o["_id"]) for o in found}
        by_org: dict[str, list] = defaultdict(list)
        if by_slug:
            async for d in db.analytics_counters.find(_counter_query(list(by_slug.values()), days, seg, device, now)):
                by_org[d["org_id"]].append(d)
        out = []
        for slug in slugs:
            oid = by_slug.get(slug)
            if not oid:
                out.append({"slug": slug, "found": False})
                continue
            s = build_summary(by_org.get(oid, []), days, now, live=live_now(oid), bucket="day")
            out.append({"slug": slug, "found": True, **compact_for_compare(s)})
        return out

    return router


# ============================== outcome middleware (Phase 5) ==============================
def set_org_slug_resolver(fn) -> None:
    global _org_slug_resolver
    _org_slug_resolver = fn


def set_org_resolver(fn) -> None:
    """fn(slug) -> awaitable org_id; used only for guard responses sent before org context is set."""
    global _org_id_resolver
    _org_id_resolver = fn


def _record_api(org: str, route: str, status: int, ms: float) -> None:
    if route not in _seen_routes:
        if len(_seen_routes) >= CAPS["routes"]:
            return
        _seen_routes.add(route)
    fields = {"n": 1, f"b.{_hist_index(ms, API_EDGES)}": 1}
    if status == 401:
        fields["e401"] = 1
    elif status == 429:
        fields["e429"] = 1
    elif 400 <= status < 500:
        fields["e4"] = 1
    elif status >= 500:
        fields["e5"] = 1
    _inc((org, _day_key(datetime.now(timezone.utc)), "api", route, "", "all", "all"), fields)
    if status >= 500:
        _bump(org, "s5", route=route)
    elif status == 429:
        _bump(org, "s429", route=route)


async def _record_outcome(request: Request, status: int, started: float) -> None:
    org = getattr(request.state, "org_id", None)
    slug = request.headers.get("X-Org-Slug")
    if not org and slug and _org_id_resolver is not None:
        org = await _org_id_resolver(slug)
    if org:
        _record_api(org, route_template(request, status), status, (time.monotonic() - started) * 1000)


async def outcome_middleware(request: Request, call_next):
    if not _enabled() or request.method == "OPTIONS" or request.url.path in SKIP_PATHS:
        return await call_next(request)
    started, status = time.monotonic(), 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        try:
            await _record_outcome(request, status, started)
        except Exception:
            log.debug("analytics outcome record failed", exc_info=True)


# ============================== lifecycle ==============================
async def _warm_caps(db) -> None:
    """Fill the cardinality sets from existing data so caps survive restarts."""
    cur = db.analytics_counters.aggregate([
        {"$match": {"kind": {"$in": ["pv", "click", "err", "api"]}}},
        {"$group": {"_id": {"o": "$org_id", "k": "$kind", "a": "$k1", "b": "$k2"}}},
        {"$limit": 20000}])
    async for r in cur:
        i = r["_id"]
        if i["k"] == "pv":
            _seen_pages[i["o"]].add(i["a"])
        elif i["k"] == "click":
            _seen_labels[(i["o"], i["a"])].add(i["b"])
        elif i["k"] == "err":
            _seen_errors[i["o"]].add(i["b"])
        elif i["k"] == "api":
            _seen_routes.add(i["a"])


async def start(db) -> None:
    global _db, _task
    _db = db
    try:
        await db.analytics_counters.create_index(
            [("org_id", 1), ("day", 1), ("kind", 1), ("k1", 1), ("k2", 1), ("device", 1), ("seg", 1)], unique=True)
        await db.analytics_counters.create_index("day_dt", expireAfterSeconds=400 * 86400)
        await db.analytics_heat.create_index(
            [("org_id", 1), ("page", 1), ("device", 1), ("seg", 1), ("kind", 1), ("gx", 1), ("gy", 1)], unique=True)
        await _warm_caps(db)
    except Exception:
        log.warning("analytics index/cache setup failed", exc_info=True)
    if _task is None:
        _task = asyncio.create_task(_flusher())


async def stop() -> None:
    global _task
    try:
        await _flush_once()
    finally:
        if _task:
            _task.cancel()
            _task = None
