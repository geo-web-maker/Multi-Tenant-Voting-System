"""PERF-M0: tier resolution and settings validation."""
import pathlib
import re

import pytest

import perf_tiers as t


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("MONGO_TIER", "DB_OPS_CAP", "DB_CONN_CAP", "PERF_WARN_PCT", "PERF_CRIT_PCT", "PERF_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    t.swap_saved({}, 0)
    yield
    t.swap_saved({}, 0)


def test_default_is_free_100_500():
    r = t.resolve({})
    assert (r["tier"], r["ops_cap"], r["conn_cap"]) == ("free", 100, 500)
    assert r["sources"]["ops_cap"] == "preset"


def test_unknown_tier_falls_back_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("MONGO_TIER", "nonsense")
    with caplog.at_level("WARNING"):
        r = t.resolve({})
    assert r["tier"] == "free" and "Unknown tier" in caplog.text


def test_env_overrides_preset_and_saved_beats_env(monkeypatch):
    monkeypatch.setenv("DB_OPS_CAP", "250")
    r = t.resolve({})
    assert r["ops_cap"] == 250 and r["sources"]["ops_cap"] == "env"
    r = t.resolve({"ops_cap": 400})
    assert r["ops_cap"] == 400 and r["sources"]["ops_cap"] == "ui"


@pytest.mark.parametrize("raw", ["0", "none", "off", "unlimited"])
def test_no_cap_values(monkeypatch, raw):
    monkeypatch.setenv("DB_OPS_CAP", raw)
    assert t.resolve({})["ops_cap"] is None


def test_garbage_env_falls_back(monkeypatch):
    monkeypatch.setenv("DB_OPS_CAP", "lots")
    assert t.resolve({})["ops_cap"] == 100


def test_saved_none_means_no_cap():
    assert t.resolve({"ops_cap": None})["ops_cap"] is None


@pytest.mark.parametrize("payload,field", [
    ({"warn_pct": 90, "crit_pct": 90}, "warn_pct"),
    ({"ops_cap": 0}, "ops_cap"),
    ({"conn_cap": 100001}, "conn_cap"),
    ({"tier": "platinum"}, "tier"),
    ({"persist_s": 7}, "persist_s"),
    ({"slow_ms": 5}, "slow_ms"),
    ({"warn_pct": 100}, "warn_pct"),
])
def test_validate_rejects(payload, field):
    with pytest.raises(ValueError) as e:
        t.validate(payload)
    assert field in e.value.args[0]


def test_editing_a_cap_makes_the_tier_custom():
    assert t.validate({"tier": "free", "ops_cap": 150})["tier"] == "custom"
    assert t.validate({"tier": "free", "ops_cap": 100})["tier"] == "free"


def test_apply_update_rechecks_pair_on_merged_values():
    with pytest.raises(ValueError):
        t.apply_update({"crit_pct": 60}, {"warn_pct": 80})
    assert t.apply_update({}, {"tier": "free"})["ops_cap"] == 100


async def test_save_and_reset_round_trip():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["t"]
    await t.save_config(db, {"tier": "custom", "ops_cap": 300}, "root")
    assert t.current_config()["ops_cap"] == 300
    assert (await t.load_config(db))["ops_cap"] == 300
    await t.reset_config(db)
    assert await db.platform_settings.count_documents({"name": "perf_config"}) == 0
    assert t.current_config()["ops_cap"] == 100


def test_no_limit_number_outside_perf_tiers():
    """P9: the preset numbers live in perf_tiers.py only."""
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(r"\b(?:ops_cap|conn_cap)\s*=\s*\d+|\bTIERS\s*=")
    for name in ("perf_metrics.py", "perf_sinks.py", "perf_routes.py"):
        assert not pat.search((root / name).read_text()), name
