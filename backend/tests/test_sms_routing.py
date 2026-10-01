"""SMS routing: which provider(s) carry a message, in what order, and when fallback happens."""
import pytest
import main


def test_default_order_matches_original_behaviour():
    assert main.sms_provider_order("default", "otp") == ["egosms", "mambosms"]
    assert main.sms_provider_order("default", "notice") == ["mambosms", "egosms"]


@pytest.mark.parametrize("route,order", [
    ("egosms_first", ["egosms", "mambosms"]),
    ("mambosms_first", ["mambosms", "egosms"]),
    ("egosms_only", ["egosms"]),
    ("mambosms_only", ["mambosms"]),
    ("garbage", ["egosms", "mambosms"]),      # unknown value falls back to default
])
def test_explicit_routes_ignore_kind(route, order):
    assert main.sms_provider_order(route, "otp") == order
    if route != "garbage":
        assert main.sms_provider_order(route, "notice") == order


def test_route_group():
    assert main.sms_route_group("otp") == "otp"
    for k in ("admin", "notice", "test", "candidate_status_link"):
        assert main.sms_route_group(k) == "other"


@pytest.fixture
def rig(monkeypatch):
    calls = {"sent": [], "counted": 0, "alerts": []}
    results = {"egosms": "ok", "mambosms": "ok"}
    sec = {**main._SEC_DEFAULTS}

    async def ego(to, msg):
        calls["sent"].append("egosms"); return results["egosms"]

    async def mambo(to, msg):
        calls["sent"].append("mambosms"); return results["mambosms"] == "ok"

    async def sec_for(org): return dict(sec)
    async def count(org, kind): calls["counted"] += 1
    async def log(*a, **k): pass
    async def alert(title, body, level="warning", **k): calls["alerts"].append((title, level))

    monkeypatch.setattr(main, "send_sms_via_egosms", ego)
    monkeypatch.setattr(main, "send_sms_via_mambosms", mambo)
    monkeypatch.setattr(main, "security_settings_for", sec_for)
    monkeypatch.setattr(main, "_safe_count_sms", count)
    monkeypatch.setattr(main, "log_action", log)
    monkeypatch.setattr(main, "send_alert", alert)
    return calls, results, sec


async def test_otp_default_uses_ego_only_when_it_works(rig):
    calls, _, _ = rig
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "ok"
    assert calls["sent"] == ["egosms"] and calls["counted"] == 1


async def test_force_mambo_first_for_otp(rig):
    calls, _, sec = rig
    sec["sms_route_otp"] = "mambosms_first"
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "ok"
    assert calls["sent"] == ["mambosms"]


async def test_only_route_never_falls_back(rig):
    calls, results, sec = rig
    sec["sms_route_otp"] = "mambosms_only"
    results["mambosms"] = "failed"
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "failed"
    assert calls["sent"] == ["mambosms"]
    assert calls["alerts"] == [("SMS send failed (otp)", "critical")]


async def test_definite_failure_falls_back_and_counts_only_the_success(rig):
    calls, results, _ = rig
    results["egosms"] = "failed"
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "ok"
    assert calls["sent"] == ["egosms", "mambosms"] and calls["counted"] == 1


async def test_ambiguous_only_falls_back_when_enabled(rig):
    calls, results, sec = rig
    results["egosms"] = "ambiguous"
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "ambiguous"
    assert calls["sent"] == ["egosms"] and calls["counted"] == 1     # billed-maybe, no double send
    calls["sent"].clear()
    sec["sms_fallback_on_timeout"] = True
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "ok"
    assert calls["sent"] == ["egosms", "mambosms"]


async def test_other_kinds_follow_their_own_route(rig):
    calls, _, sec = rig
    sec["sms_route_otp"] = "egosms_only"
    sec["sms_route_other"] = "egosms_first"          # would be mambo-first by default
    assert await main._send_sms_routed("+256700000000", "x", "o", "notice") == "ok"
    assert calls["sent"] == ["egosms"]


async def test_settings_read_failure_does_not_block_send(rig, monkeypatch):
    calls, _, _ = rig
    async def boom(org): raise RuntimeError("mongo down")
    monkeypatch.setattr(main, "security_settings_for", boom)
    assert await main._send_sms_routed("+256700000000", "x", "o", "otp") == "ok"
    assert calls["sent"] == ["egosms"]
