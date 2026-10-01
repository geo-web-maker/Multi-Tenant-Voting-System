import asyncio

import pytest

from name_utils import normalize_name
from name_backfill import run_backfill


@pytest.mark.parametrize("raw,expected", [
    ("john OKELLO", "John Okello"),
    ("mary anne", "Mary Anne"),
    ("  ssebunya   j. ", "Ssebunya J."),
    ("o'kello anne-marie", "O'Kello Anne-Marie"),
    ("McDonald peter", "McDonald Peter"),     # mixed-case words are trusted
    ("OKELLO", "Okello"),
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_idempotent():
    for raw in ["john OKELLO", "o'kello anne-marie", "McDonald peter"]:
        once = normalize_name(raw)
        assert normalize_name(once) == once


# --- backfill against a tiny in-memory stand-in for a motor collection -------
class _Coll:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        org = query.get("org_id")
        rows = [d for d in self.docs if (org is None or d.get("org_id") == org)
                and any(isinstance(v, str) for k, v in d.items() if k not in ("_id", "org_id"))]

        async def gen():
            for d in rows:
                yield d
        return gen()

    async def bulk_write(self, ops, ordered=False):
        for op in ops:
            flt, upd = op._filter, op._doc["$set"]
            for d in self.docs:
                if all(d.get(k) == v for k, v in flt.items()):
                    d.update(upd)


class _DB(dict):
    def __getitem__(self, k):
        return dict.get(self, k) or _Coll([])


def _db():
    return _DB(
        voters=_Coll([{"_id": 1, "org_id": "a", "full_name": "john OKELLO"},
                      {"_id": 2, "org_id": "a", "full_name": "Mary Anne"},
                      {"_id": 3, "org_id": "b", "full_name": "peter pan"}]),
        candidates=_Coll([{"_id": 4, "org_id": "a", "name": "grace AKELLO"}]),
    )


def test_backfill_dry_run_writes_nothing():
    db = _db()
    r = asyncio.run(run_backfill(db, org_id="a", dry_run=True))
    assert r["total_changed"] == 2
    assert db["voters"].docs[0]["full_name"] == "john OKELLO"


def test_backfill_apply_is_org_scoped_and_idempotent():
    db = _db()
    r = asyncio.run(run_backfill(db, org_id="a", dry_run=False))
    assert r["total_changed"] == 2
    assert db["voters"].docs[0]["full_name"] == "John Okello"
    assert db["voters"].docs[2]["full_name"] == "peter pan"      # other org untouched
    assert db["candidates"].docs[0]["name"] == "Grace Akello"
    assert asyncio.run(run_backfill(db, org_id="a", dry_run=False))["total_changed"] == 0


# --- registration-number audit -----------------------------------------------------------
from regno_audit import audit_reg_numbers


class _RColl(_Coll):
    def find(self, query, projection=None):
        org = query.get("org_id")
        rows = [d for d in self.docs if (org is None or d.get("org_id") == org)
                and isinstance(d.get("student_id"), str)]

        async def gen():
            for d in rows:
                yield d
        return gen()

    async def bulk_write(self, ops, ordered=False):
        class R: modified_count = 0
        r = R()
        for op in ops:
            flt, upd = op._filter, op._doc["$set"]
            for d in self.docs:
                if all(d.get(k) == v for k, v in flt.items()):
                    d.update(upd); r.modified_count += 1
        return r


def _rdb():
    return _DB(
        voters=_RColl([
            {"_id": 1, "org_id": "a", "student_id": "2021/u/001"},                    # fine
            {"_id": 2, "org_id": "a", "student_id": "2021/U/002"},                    # fixable
            {"_id": 3, "org_id": "a", "student_id": " 2021/u/003 "},                   # fixable (spaces)
            {"_id": 4, "org_id": "a", "student_id": "2021/U/001"},                    # conflict with #1
            {"_id": 5, "org_id": "a", "student_id": "2021/U/005", "has_voted": True},  # review
            {"_id": 6, "org_id": "b", "student_id": "2021/U/002"},                    # other org: separate
        ]),
        applications=_RColl([{"_id": 9, "org_id": "a", "student_id": "2021/U/002"}]),
    )


def test_regno_check_only_changes_nothing():
    db = _rdb()
    r = asyncio.run(audit_reg_numbers(db, org_id="a", fix=False))
    assert r["voters"]["non_canonical"] == 4
    assert r["voters"]["fixable"] == 2 and r["voters"]["conflicts"] == 1 and r["voters"]["voted_review"] == 1
    assert db["voters"].docs[1]["student_id"] == "2021/U/002"


def test_regno_fix_safe_and_idempotent():
    db = _rdb()
    r = asyncio.run(audit_reg_numbers(db, org_id="a", fix=True))
    ids = {d["_id"]: d["student_id"] for d in db["voters"].docs}
    assert ids[2] == "2021/u/002" and ids[3] == "2021/u/003"
    assert ids[4] == "2021/U/001" and ids[5] == "2021/U/005"      # conflict + voted untouched
    assert ids[6] == "2021/U/002"                                 # other org untouched
    assert db["applications"].docs[0]["student_id"] == "2021/u/002"
    assert r["needs_review"] == 2
    r2 = asyncio.run(audit_reg_numbers(db, org_id="a", fix=True))
    assert r2["voters"]["fixed"] == 0
