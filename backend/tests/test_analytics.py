import json
import time
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import analytics as a

SID = str(uuid.uuid4())
CFG = {"5xx": 10, "429": 30, "fe": 20, "spike_factor": 5, "spike_min": 150, "cold_pct": .3, "cold_min_sessions": 20}
CHROME_ANDROID = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
SAFARI_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
FB_IN_APP = "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/110.0 Mobile Safari/537.36 [FBAN/FB4A;FBAV/400.0]"


@pytest.fixture(autouse=True)
def clean_state():
    def wipe():
        a._deltas.clear(); a._heat.clear(); a._seen_pages.clear(); a._seen_labels.clear()
        a._seen_errors.clear(); a._seen_routes.clear(); a._sid_windows.clear(); a._global_window.clear()
        a._live.clear(); a._minutes.clear()
        a._dropped_over_capacity = 0
    wipe()
    yield
    wipe()


def body(events, sid=SID, w=390, seg="public"):
    return {"sid": sid, "w": w, "seg": seg, "events": events}


def pv(page="results", **kw):
    return {"t": "pv", "page": page, "from": "(entry)", "first": True, "ns": True, "second": False, "entry": page, **kw}


def ingest(events, org="org1", width=390, seg="public", ua=CHROME_ANDROID, sid=SID):
    _, w, seg, evs = a.validate_events(body(events, sid, width, seg))
    a.ingest(org, sid, w, seg, ua, evs)


# ---------- pure functions ----------
def test_page_ok():
    assert a.page_ok("results") and a.page_ok("superadmin:usage_analytics")
    for bad in ("results/123", "results?x=1", "unknown_page", "results:", "ab", "results:UPPER", None, 5):
        assert not a.page_ok(bad)


@pytest.mark.parametrize("w,expected", [(767, "mobile"), (768, "tablet"), (1099, "tablet"), (1100, "desktop"), ("x", "desktop")])
def test_device_bucket(w, expected):
    assert a.device_bucket(w) == expected


def test_parse_ua():
    assert a.parse_ua(CHROME_ANDROID) == ("Chrome", "Android", "browser")
    assert a.parse_ua(SAFARI_IOS) == ("Safari", "iOS", "browser")
    browser, os_name, source = a.parse_ua(FB_IN_APP)
    assert (browser, os_name, source) == ("Facebook", "Android", "in_app:facebook")
    assert a.parse_ua("") == ("Other", "Other", "browser")
    assert a.parse_ua(None) == ("Other", "Other", "browser")


def test_validate_events_rejects_and_drops():
    with pytest.raises(ValueError):
        a.validate_events(body([], sid="not-a-uuid"))
    with pytest.raises(ValueError):
        a.validate_events(body([pv()] * 26))
    with pytest.raises(ValueError):
        a.validate_events([])
    _, _, seg, ev = a.validate_events(body([
        {"t": "click", "page": "results", "label": "tab-x", "gx": 999, "gy": -4, "student_id": "S123", "url": "/x?id=1"},
        {"t": "click", "page": "results", "label": "Bad Label!", "gx": 3, "gy": 5},
        {"t": "click", "page": "bad/page", "label": "ok"},
        {"t": "weird", "page": "results"},
        {"t": "err", "page": "results", "name": "TypeError: secret message"},
        {"t": "err", "page": "results", "name": "net:timeout"},
        {"t": "perf", "page": "results", "load_ms": 999999, "first_api_ms": -5, "net": "5g"},
    ], seg="hacker"))
    assert seg == "public"
    assert (ev[0]["gx"], ev[0]["gy"]) == (49, 0) and "student_id" not in ev[0] and "url" not in ev[0]
    assert ev[1]["label"] == "unknown"
    assert [e["t"] for e in ev] == ["click", "click", "err", "err", "perf"]
    assert ev[2]["name"] == "Error" and ev[3]["name"] == "net:timeout"
    assert ev[4]["load_ms"] == 60000 and ev[4]["first_api_ms"] == 0 and ev[4]["net"] == "unknown"


def test_hist_percentile():
    assert a.hist_percentile([0, 0, 0], [100, 250], .5) is None
    assert 100 < a.hist_percentile([10, 10, 10], [100, 250, 500], .5) < 250
    assert a.hist_percentile([0, 0, 5], [100, 250], .95) == 250.0  # open bucket -> last finite edge
    assert a.hist_percentile([10, 0, 0], [100, 250], .5) == 50.0


def test_route_template_matched_guard_unmatched():
    from starlette.routing import Match

    class Route:
        path = "/vote"
        def matches(self, scope):
            return (Match.FULL, {}) if scope["path"].startswith("/vote") else (Match.NONE, {})

    class Req:
        app = type("A", (), {"router": type("R", (), {"routes": [Route()]})()})()
        def __init__(self, path, route=None):
            self.scope = {"path": path, **({"route": route} if route else {})}

    assert a.route_template(Req("/vote/ABC123", route=Route())) == "/vote"
    assert a.route_template(Req("/vote/ABC123")) == "(guard)"
    assert a.route_template(Req("/nothing/S12345")) == "(unmatched)"


# ---------- alerts: every row fires at threshold, stays quiet below ----------
@pytest.mark.parametrize("stats,kind,level,below", [
    ({"server_5xx": 10}, "5xx", "critical", {"server_5xx": 9}),
    ({"responses_429": 30}, "429", "warning", {"responses_429": 29}),
    ({"front_end_errors": 20}, "front_end", "warning", {"front_end_errors": 19}),
    ({"views": 150, "trailing_15_avg": 30}, "spike", "warning", {"views": 149, "trailing_15_avg": 1}),
    ({"sessions": 20, "cold": 6}, "cold", "warning", {"sessions": 20, "cold": 5}),
])
def test_alert_thresholds(stats, kind, level, below):
    fired = a.evaluate_alerts(stats, CFG)
    assert [(x["kind"], x["level"]) for x in fired] == [(kind, level)]
    assert a.evaluate_alerts(below, CFG) == []


def test_spike_needs_five_times_the_trailing_average():
    # Flat traffic of 150 views/min must NOT be a spike (regression: the 15-minute total was compared to itself).
    assert a.evaluate_alerts({"views": 150, "trailing_15_avg": 150}, CFG) == []
    assert a.evaluate_alerts({"views": 150, "trailing_15_avg": 29}, CFG)[0]["kind"] == "spike"


def test_cold_needs_twenty_sessions():
    assert a.evaluate_alerts({"sessions": 19, "cold": 19}, CFG) == []


def test_alert_body_fields_and_route_limit():
    x = a.evaluate_alerts({"server_5xx": 12, "routes_5xx": ["/a", "/b", "/c", "/d"]}, CFG)[0]
    assert x["value"] == 12 and x["threshold"] == 10 and x["routes"] == ["/a", "/b", "/c"] and x["metric"]


def test_window_stats_from_minute_counters():
    now = 1000
    minutes = {now: {"s5": 4, "r5": {"/x": 4}}, now - 1: {"s5": 11, "r5": {"/x": 7, "/y": 4}, "views": 200},
               **{now - i: {"views": 10} for i in range(2, 17)}}
    s = a.build_window_stats(minutes, now)
    assert s["server_5xx"] == 11 and s["routes_5xx"][0] == "/x" and s["views"] == 200
    assert s["trailing_15_avg"] == 10 and a.evaluate_alerts(s, CFG)[0]["kind"] in {"5xx", "spike"}


def test_evaluator_touches_no_database():
    class Boom:
        def __getattr__(self, n): raise AssertionError("database touched")
    a._db = Boom()
    try:
        assert a.evaluate_alerts({"server_5xx": 99}, CFG)
    finally:
        a._db = None


# ---------- aggregation / limits / privacy ----------
def test_thousand_identical_events_coalesce_into_one_delta():
    ingest([pv(first=False, ns=False)] * 25)
    for _ in range(39):
        ingest([pv(first=False, ns=False)] * 25, sid=str(uuid.uuid4()))
    pv_keys = [k for k in a._deltas if k[2] == "pv" and k[3] == "results"]
    assert len(pv_keys) == 1 and a._deltas[pv_keys[0]]["n"] == 1000


def test_durations_go_to_the_previous_page():
    ingest([pv("voter_ballot", **{"from": "voter_identity", "from_dur": 5000})])
    prev = next(v for k, v in a._deltas.items() if k[2] == "pv" and k[3] == "voter_identity")
    cur = next(v for k, v in a._deltas.items() if k[2] == "pv" and k[3] == "voter_ballot")
    assert prev["dur_sum"] == 5000 and cur["dur_sum"] == 0


def test_per_sid_limit_and_global_shed_do_not_raise(monkeypatch):
    assert [a.admit("s1", now=100.0) for _ in range(13)] == [True] * 12 + [False]
    a._global_window.clear(); a._sid_windows.clear()
    monkeypatch.setenv("ANALYTICS_MAX_RPS", "5")
    results = [a.admit(f"sid{i}", now=200.0) for i in range(8)]
    assert results == [True] * 5 + [False] * 3 and a._dropped_over_capacity == 3


def test_sid_dictionary_is_capped():
    for i in range(a.MAX_SIDS + 10):
        a._sid_windows[f"s{i}"] = a.deque()
    a.admit("new", now=1.0)
    assert len(a._sid_windows) <= a.MAX_SIDS + 10 - 1000 + 1


def test_random_pages_do_not_grow_past_caps():
    for i in range(1000):
        ingest([pv(f"superadmin:tab_{i}")], sid=str(uuid.uuid4()))
    assert len(a._seen_pages["org1"]) == a.CAPS["pages"]
    assert len({k[3] for k in a._deltas if k[2] == "pv"}) == a.CAPS["pages"]
    a._seen_pages.clear()  # the page cap is exercised above; test label and error caps separately
    for i in range(200):
        ingest([{"t": "click", "page": "results", "label": f"label-{i}", "gx": 1, "gy": 1}])
        ingest([{"t": "err", "page": "results", "name": f"Err{i}"}])
    assert len(a._seen_labels[("org1", "results")]) == a.CAPS["labels"]
    assert len(a._seen_errors["org1"]) == a.CAPS["errors"]
    for i in range(500):
        a._record_api("org1", f"/route/{i}", 200, 10)
    assert len(a._seen_routes) == a.CAPS["routes"]


def test_heat_is_kept_even_when_label_cap_is_reached():
    for i in range(70):
        ingest([{"t": "click", "page": "results", "label": f"label-{i}", "gx": i % 50, "gy": 3}])
    assert sum(a._heat.values()) == 70


def test_stored_documents_contain_no_forbidden_data():
    ingest([
        pv("voter_identity", **{"student_id": "S1234567", "url": "https://x/?id=S1234567", "ip": "1.2.3.4"}),
        {"t": "click", "page": "voter_identity", "label": "nav-vote", "gx": 4, "gy": 9, "innerText": "Jane Doe", "id": "otp"},
        {"t": "err", "page": "voter_identity", "name": "TypeError", "message": "otp 123456"},
    ])
    dumped = json.dumps([[list(k), v] for k, v in a._deltas.items()] + [[list(k), v] for k, v in a._heat.items()], default=str)
    for secret in ("S1234567", "1.2.3.4", "Jane", "123456", "http", "otp"):
        assert secret not in dumped
    assert SID not in dumped


# ---------- flush ----------
class FakeColl:
    def __init__(self, docs=None, fail=False):
        self.ops, self.docs, self.fail = [], docs or [], fail
    async def bulk_write(self, ops, ordered=True):
        if self.fail: raise RuntimeError("db down")
        self.ops.append(ops)
    def find(self, q=None):
        coll = self
        class Cur:
            def __init__(s): s.it = iter(coll.docs)
            def limit(s, n): return s
            def __aiter__(s): return s
            async def __anext__(s):
                try: return next(s.it)
                except StopIteration: raise StopAsyncIteration
        return Cur()
    async def delete_many(self, q): self.deleted = q


class FakeDb:
    def __init__(self, **kw):
        self.analytics_counters = kw.get("counters", FakeColl())
        self.analytics_heat = kw.get("heat", FakeColl())
        self.organizations = kw.get("orgs", FakeColl())


async def test_flush_writes_one_coalesced_bulk_and_clears_buffers(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    db = FakeDb(); a._db = db
    try:
        for _ in range(4):
            ingest([pv(first=False, ns=False), {"t": "click", "page": "results", "label": "nav-vote", "gx": 1, "gy": 2}] * 10)
        assert not db.analytics_counters.ops  # nothing written by collection
        await a._flush_once()
        assert len(db.analytics_counters.ops) == 1 and len(db.analytics_heat.ops) == 1
        assert not a._deltas and not a._heat
    finally:
        a._db = None


async def test_failed_flush_restores_buffers(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ALERTS_ENABLED", "false")
    a._db = FakeDb(counters=FakeColl(fail=True))
    try:
        ingest([pv(first=False, ns=False)] * 5)
        await a._flush_once()
        assert next(v for k, v in a._deltas.items() if k[2] == "pv")["n"] == 5
    finally:
        a._db = None


# ---------- summary over stored-shape documents ----------
def test_summary_reads_nested_histograms_and_builds_all_sections():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    base = {"org_id": "o", "day": "2026-10-12", "device": "mobile", "seg": "public"}
    docs = [
        {**base, "kind": "pv", "k1": "results", "k2": "Chrome|Android", "n": 10, "uv": 5, "dur_sum": 100000, "h": {"9": 4, "11": 6}},
        {**base, "kind": "pv", "k1": "voter_identity", "k2": "Safari|iOS", "n": 4, "h": {"9": 4}},
        {**base, "kind": "sess", "k1": "results", "k2": "in_app:facebook", "n": 5, "h": {"9": 2, "11": 3}},
        {**base, "kind": "sess2", "k1": "results", "k2": "in_app:facebook", "n": 3},
        {**base, "kind": "trans", "k1": "voter_identity", "k2": "results", "n": 2},
        {**base, "kind": "click", "k1": "results", "k2": "nav-vote", "n": 7},
        {**base, "kind": "dead", "k1": "results", "k2": "div", "n": 2},
        {**base, "kind": "rage", "k1": "results", "k2": "div", "n": 1},
        {**base, "kind": "err", "k1": "results", "k2": "TypeError", "n": 3},
        {**base, "kind": "err", "k1": "results", "k2": "net:network", "n": 2},
        {**base, "kind": "net", "k1": "4g", "k2": "", "device": "all", "seg": "all", "n": 4},
        {**base, "kind": "api", "k1": "/vote", "k2": "", "device": "all", "seg": "all", "n": 10, "e429": 2, "e5": 1, "b": {"1": 5, "2": 5}},
        {**base, "kind": "perf", "k1": "results", "k2": "", "n": 4, "cold": 1, "l": {"1": 2, "2": 2}, "c": {"1": 3, "5": 1}},
        {**base, "kind": "conc", "k1": "", "k2": "", "device": "all", "seg": "all", "m": {"150": 42, "151": 30}},
    ]
    s = a.build_summary(docs, 1, now, live=3)
    t = s["totals"]
    assert (t["views"], t["sessions"]) == (14, 5) and t["bounce"] == pytest.approx(0.4)
    assert t["average_session_seconds"] == 20 and t["peak_concurrency"] == 42
    assert t["peak_concurrency_time"].startswith("2026-10-12T12:30")
    assert s["timeline"]["bucket"] == "hour" and any(p["views"] for p in s["timeline"]["points"])
    assert sum(p["sessions"] for p in s["timeline"]["points"]) == 5
    assert s["hour_of_day"][9] == 8 and s["hour_of_day"][11] == 6
    assert {r["label"] for r in s["browsers"]} == {"Chrome", "Safari"} and {r["label"] for r in s["os"]} == {"Android", "iOS"}
    assert s["quality"] == {"dead_clicks": 2, "rage_clicks": 1, "errors": 3, "network_failures": 2}
    assert s["elements"][0] == {"page": "results", "label": "nav-vote", "value": 7}
    api = s["api"][0]
    assert api["route"] == "/vote" and api["e429"] == 2 and api["p50"] is not None and api["error_rate"] == pytest.approx(.3)
    assert s["perf"][0]["cold_pct"] == .25 and s["cold_starts"]["pct"] == .25 and s["perf"][0]["first_api_p50"] is not None
    assert s["top_pages"][0]["exits"] == 10 and s["entry_sources"][0]["bounce"] == pytest.approx(0.4)
    assert s["network"][0]["label"] == "4g"
    assert a.build_summary(docs, 30, now)["timeline"]["bucket"] == "day"


# ---------- routes: authorisation, heatmap, purge, compare, middleware ----------
def make_app(db):
    def require_role(role):
        async def dep(request: Request):
            if request.headers.get("authorization") != "Bearer super":
                raise HTTPException(403, "Superadmin access required.")
            return {"sub": "root"}
        return dep
    logged = []
    async def log_action(action, actor, details, org_id=None): logged.append((action, actor, org_id))
    app = FastAPI()

    @app.middleware("http")
    async def org_ctx(request: Request, call_next):
        request.state.org_id = "org1" if request.headers.get("X-Org-Slug") == "one" else None
        return await call_next(request)

    app.include_router(a.build_router(lambda: db, require_role, log_action))

    @app.get("/items/{item_id}")
    async def item(item_id: str):
        if item_id == "boom":
            raise RuntimeError("x")
        if item_id == "limited":
            raise HTTPException(429, "slow down")
        return {"ok": True}
    return app, logged


AUTH = {"Authorization": "Bearer super", "X-Org-Slug": "one"}


def test_admin_routes_reject_non_superadmin():
    c = TestClient(make_app(FakeDb())[0])
    h = {"X-Org-Slug": "one"}
    assert c.get("/superadmin/analytics/summary", headers=h).status_code == 403
    assert c.get("/superadmin/analytics/heatmap?page=results", headers=h).status_code == 403
    assert c.request("DELETE", "/superadmin/analytics", json={"confirm": True}, headers=h).status_code == 403
    assert c.get("/superadmin/analytics/compare?orgs=one", headers=h).status_code == 403


def test_summary_heatmap_delete_and_compare_work_for_superadmin():
    heat = FakeColl(docs=[{"gx": 1, "gy": 2, "n": 3}, {"gx": 1, "gy": 2, "n": 4}, {"gx": 5, "gy": 6, "n": 1}])
    orgs = FakeColl()
    async def to_list(length=None): return [{"slug": "one", "_id": "org1"}]
    orgs.find = lambda q=None: type("C", (), {"to_list": staticmethod(to_list)})()
    db = FakeDb(heat=heat, orgs=orgs)
    app, logged = make_app(db)
    c = TestClient(app)
    s = c.get("/superadmin/analytics/summary?days=7&seg=all", headers=AUTH)
    assert s.status_code == 200 and s.json()["totals"]["views"] == 0
    assert c.get("/superadmin/analytics/summary?days=5", headers=AUTH).status_code == 400
    h = c.get("/superadmin/analytics/heatmap?page=results&kind=click", headers=AUTH)
    assert h.status_code == 200 and {(x["gx"], x["gy"]): x["n"] for x in h.json()} == {(1, 2): 7, (5, 6): 1}
    assert c.get("/superadmin/analytics/heatmap?page=bad/page", headers=AUTH).status_code == 400
    ingest([pv()])
    assert c.request("DELETE", "/superadmin/analytics", json={"confirm": False}, headers=AUTH).status_code == 400
    assert c.request("DELETE", "/superadmin/analytics", json={"confirm": True}, headers=AUTH).status_code == 200
    assert not a._deltas and logged == [("analytics_cleared", "root", "org1")]
    ok = c.get("/superadmin/analytics/compare?orgs=one,ghost", headers=AUTH)
    assert ok.status_code == 200 and ok.json()[0]["found"] and ok.json()[0]["totals"]["views"] == 0
    assert c.get("/superadmin/analytics/compare?orgs=a,b,c,d,e", headers=AUTH).status_code == 400


def collect(c, events, **kw):
    return c.post("/analytics/collect", json=body(events, **kw), headers={"X-Org-Slug": "one", "User-Agent": CHROME_ANDROID})


def test_collect_makes_no_db_calls_and_always_answers_202():
    class Boom:
        def __getattr__(self, n): raise AssertionError("database touched by collect")
    c = TestClient(make_app(Boom())[0])
    r = collect(c, [pv()])
    assert r.status_code == 202 and r.json() == {"ok": True} and a._deltas
    assert c.post("/analytics/collect", content=b"not json", headers={"X-Org-Slug": "one"}).status_code == 202
    assert c.post("/analytics/collect", content=b"x" * 20000, headers={"X-Org-Slug": "one"}).status_code == 202
    assert TestClient(make_app(Boom())[0]).post("/analytics/collect", json=body([pv()])).status_code == 202  # no org


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    c = TestClient(make_app(FakeDb())[0])
    assert collect(c, [pv()]).status_code == 202 and not a._deltas


def test_outcome_middleware_records_templates_only_never_ids():
    app, _ = make_app(FakeDb())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/items/blocked"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "no"})
        return await call_next(request)

    app.middleware("http")(a.outcome_middleware)

    async def resolver(slug): return "org1" if slug == "one" else None
    a.set_org_resolver(resolver)
    c = TestClient(app, raise_server_exceptions=False)
    h = {"X-Org-Slug": "one"}
    assert c.get("/items/S1234567", headers=h).status_code == 200
    assert c.get("/items/limited", headers=h).status_code == 429
    assert c.get("/items/boom", headers=h).status_code == 500
    assert c.get("/items/blocked-S99", headers=h).status_code == 401
    assert c.get("/nowhere/S1234567", headers=h).status_code == 404
    c.get("/health", headers=h); c.options("/items/x", headers=h)
    api = {k[3]: v for k, v in a._deltas.items() if k[2] == "api"}
    assert api["/items/{item_id}"]["n"] == 3 and api["/items/{item_id}"]["e429"] == 1 and api["/items/{item_id}"]["e5"] == 1
    assert "(guard)" in api and api["(guard)"]["e401"] == 1 and "(unmatched)" in api
    assert "/health" not in api and not any("S1234567" in json.dumps(k) or "S99" in json.dumps(k) for k in a._deltas)
    stats = a.build_window_stats(a._minutes["org1"], int(time.time() // 60))
    assert stats["server_5xx"] == 1 and stats["responses_429"] == 1 and "/items/{item_id}" in stats["routes_429"]
