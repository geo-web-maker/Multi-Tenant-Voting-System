"""WP-9.3 backend (card D1b): `tracking_since` = earliest counter `day` for the org, in the summary response."""
import pytest
from fastapi.testclient import TestClient

import analytics as a
from tests.test_analytics import make_app, FakeDb, AUTH


class SortableColl:
    """Minimal motor-like collection: find(filter, projection).sort(key, dir).limit(n), async-iterable."""
    def __init__(self, docs):
        self.docs, self.queries = docs, []

    def find(self, q=None, projection=None):
        self.queries.append(q)
        rows = [d for d in self.docs if d.get("org_id") == (q or {}).get("org_id")]
        coll = self

        class Cur:
            def __init__(s): s.rows = list(rows)
            def sort(s, key, direction=1):
                s.rows.sort(key=lambda d: d[key], reverse=direction == -1); return s
            def limit(s, n): s.rows = s.rows[:n]; return s
            def __aiter__(s): s.it = iter(s.rows); return s
            async def __anext__(s):
                try: return next(s.it)
                except StopIteration: raise StopAsyncIteration
        return Cur()


DOCS = [
    {"org_id": "org1", "day": "2026-09-20"}, {"org_id": "org1", "day": "2026-09-12"},
    {"org_id": "org1", "day": "2026-09-30"},
    {"org_id": "org2", "day": "2026-10-01"}, {"org_id": "org2", "day": "2026-09-28"},
]


class Db:
    def __init__(self, docs): self.analytics_counters = SortableColl(docs)


@pytest.mark.asyncio
async def test_two_orgs_get_their_own_earliest_day():
    db = Db(DOCS)
    assert await a.tracking_since(db, "org1") == "2026-09-12"
    assert await a.tracking_since(db, "org2") == "2026-09-28"


@pytest.mark.asyncio
async def test_empty_org_returns_none():
    assert await a.tracking_since(Db(DOCS), "org3") is None
    assert await a.tracking_since(Db([]), "org1") is None


@pytest.mark.asyncio
async def test_lookup_is_scoped_to_the_org_and_not_the_summary_window():
    db = Db(DOCS)
    await a.tracking_since(db, "org1")
    assert db.analytics_counters.queries == [{"org_id": "org1"}]  # no day/seg/device filter


@pytest.mark.asyncio
async def test_db_failure_returns_none_instead_of_breaking_summary():
    class Broken:
        class analytics_counters:
            @staticmethod
            def find(*_a, **_k): raise RuntimeError("db down")
    assert await a.tracking_since(Broken(), "org1") is None


def test_summary_response_includes_tracking_since():
    c = TestClient(make_app(Db(DOCS))[0])
    r = c.get("/superadmin/analytics/summary?days=7&seg=all", headers=AUTH)
    assert r.status_code == 200 and r.json()["tracking_since"] == "2026-09-12"


def test_summary_tracking_since_is_null_for_empty_org():
    c = TestClient(make_app(FakeDb())[0])  # existing fake has no sort(): lookup degrades to null, summary still 200
    r = c.get("/superadmin/analytics/summary?days=7&seg=all", headers=AUTH)
    assert r.status_code == 200 and r.json()["tracking_since"] is None
