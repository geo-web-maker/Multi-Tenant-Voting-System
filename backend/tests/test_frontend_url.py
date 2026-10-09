"""Per-organisation frontend URL (used in SMS links) with the FRONTEND_URL env var as fallback."""
import pytest
from fastapi import HTTPException

import main


class FakeOrgs:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query, projection=None):
        return self.doc


class FakeDb:
    def __init__(self, doc):
        self.organizations = FakeOrgs(doc)


class Req:
    class state:
        org_id = "64b0f0f0f0f0f0f0f0f0f0f0"


@pytest.mark.parametrize("raw,expected", [
    ("", ""), ("  ", ""),
    ("https://vote.kyuccu.org/", "https://vote.kyuccu.org"),
    ("https://a.vercel.app", "https://a.vercel.app"),
    ("http://localhost:5173", "http://localhost:5173"),
])
def test_normalize_accepts(raw, expected):
    assert main.normalize_frontend_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "http://vote.example.org", "vote.example.org", "https://x.org/path", "https://x.org?a=1",
    "https://user:pw@x.org", "javascript:alert(1)", "ftp://x.org",
])
def test_normalize_rejects(raw):
    with pytest.raises(HTTPException):
        main.normalize_frontend_url(raw)


async def test_org_value_wins(monkeypatch):
    monkeypatch.setattr(main, "db", FakeDb({"frontend_url": "https://org-a.example/"}))
    assert await main.frontend_url_for(Req()) == "https://org-a.example"


async def test_falls_back_to_env_when_unset(monkeypatch):
    monkeypatch.setattr(main, "db", FakeDb({}))
    assert await main.frontend_url_for(Req()) == main.FRONTEND_URL


def test_clean_id_wording_trims_and_bounds():
    class D:
        id_label = "  Student Number  "
        id_examples = ["2100712345", "  ", "x" * 200] + ["a"] * 20
        name_examples = []
        id_format_hint = "  Ten digits.  "
    out = main._clean_id_wording(D())
    assert out["id_label"] == "Student Number"
    assert out["id_examples"][0] == "2100712345" and len(out["id_examples"]) == 8
    assert all(len(x) <= 80 for x in out["id_examples"])
    assert out["id_format_hint"] == "Ten digits."


def test_id_noun_follows_org_label():
    assert main._id_noun_from({}) == "registration number"
    assert main._id_noun_from(None) == "registration number"
    assert main._id_noun_from({"id_label": "  Student Number "}) == "student number"
    assert main._cap("student number") == "Student number"


def test_shape_warnings_use_the_org_noun():
    from roster_utils import shape_warnings
    r = {"outliers": ["abc"], "reference": "x", "example": "2100712345", "source": "roster", "share": 1.0}
    w = shape_warnings(r, 10, {"abc": 3}, noun="student number")
    assert "student number doesn't match" in w[0] and "registration" not in w[0]
