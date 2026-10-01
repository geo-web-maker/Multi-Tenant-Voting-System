"""Card D2d-be: the summary response carries `alerts` (org-scoped, read-only, [] when healthy)."""
import time

from fastapi.testclient import TestClient

import analytics as a
from tests.test_analytics import make_app, FakeDb, AUTH

KEYS = {"kind", "level", "metric", "value", "threshold"}


def _now_min():
    return int(time.time() // 60)


def setup_function(_):
    a._minutes.clear()


def test_healthy_org_gets_empty_list():
    assert a.current_alerts("org1") == []
    assert "org1" not in a._minutes  # reading must not create state


def test_each_threshold_maps_to_kind_and_level():
    m = _now_min()
    a._minutes["org1"][m] = {"s5": 10, "s429": 30, "fe": 20}
    got = {x["kind"]: x for x in a.current_alerts("org1", m)}
    assert set(got) == {"5xx", "429", "front_end"}
    assert got["5xx"]["level"] == "critical" and got["429"]["level"] == "warning" and got["front_end"]["level"] == "warning"
    assert all(set(x) == KEYS for x in got.values())  # no routes, nothing else leaks
    assert got["5xx"]["value"] == 10 and got["5xx"]["threshold"] == 10


def test_below_threshold_is_healthy():
    m = _now_min()
    a._minutes["org1"][m] = {"s5": 9, "s429": 29, "fe": 19}
    assert a.current_alerts("org1", m) == []


def test_alerts_are_org_scoped():
    m = _now_min()
    a._minutes["org2"][m] = {"s5": 50}
    assert a.current_alerts("org1", m) == []
    assert [x["kind"] for x in a.current_alerts("org2", m)] == ["5xx"]


def test_summary_response_includes_alerts_and_stays_read_only():
    a._minutes["org1"][_now_min()] = {"s5": 12}
    c = TestClient(make_app(FakeDb())[0])
    r = c.get("/superadmin/analytics/summary?days=7&seg=all", headers=AUTH)
    assert r.status_code == 200
    assert [x["kind"] for x in r.json()["alerts"]] == ["5xx"]
    assert c.post("/superadmin/analytics/summary", headers=AUTH).status_code == 405  # no write path


def test_summary_alerts_empty_when_healthy():
    c = TestClient(make_app(FakeDb())[0])
    r = c.get("/superadmin/analytics/summary?days=7&seg=all", headers=AUTH)
    assert r.status_code == 200 and r.json()["alerts"] == []
