import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import otp_limits as ol

T0 = datetime(2026, 1, 1, 12, 0, 0)


def test_ladder_arithmetic():
    # wait imposed AFTER send n: 30s, 60s, 2m, 5m, 10m, then capped at 10m
    assert [ol.next_wait(n) for n in range(1, 8)] == [30, 60, 120, 300, 600, 600, 600]


def test_daily_ceiling_rolls_off():
    sends = [T0 + timedelta(hours=h) for h in range(8)]
    assert len(ol.prune_24h(sends, T0 + timedelta(hours=23))) == 8
    assert len(ol.prune_24h(sends, T0 + timedelta(hours=24, minutes=30))) == 7  # first one aged out


def test_budget_default_is_90():
    assert round(ol.guess_budget(0.0001)) == 90


def test_refill_interval_matches_design_table():
    day = 86400
    expect = {  # window seconds -> minutes per extra guess (design doc section 5.2, +-3%)
        2 * 3600: 1.41, 6 * 3600: 4.2, day: 16.9, 3 * day: 50.8,
        7 * day: 118.6, 14 * day: 237.2,
    }
    for w, minutes in expect.items():
        got = ol.refill_interval(w) / 60
        assert abs(got - minutes) / minutes < 0.03, (w, got, minutes)


def test_clamps():
    assert ol.refill_interval(60) == ol.LOCK_MIN_S              # tiny window -> 30 s floor
    assert ol.refill_interval(365 * 86400) == ol.LOCK_MAX_S      # huge window -> 12 h cap
    assert ol.refill_interval(30 * 86400) / 3600 < 12            # 30 days ~ 8.5 h


def test_total_guesses_bounded_by_budget():
    """Over the whole window an attacker gets B + W/interval guesses ~ G (<= epsilon x 900k)."""
    for days in (1, 7, 30):
        w = days * 86400
        total = ol.FREE_GUESSES + w / ol.refill_interval(w)
        assert total <= ol.guess_budget() + 0.5 or ol.refill_interval(w) == ol.LOCK_MAX_S


def test_bucket_simulation():
    interval = ol.refill_interval(86400)
    tokens = float(ol.FREE_GUESSES)
    for _ in range(5):
        tokens -= 1
    assert tokens < 1 and ol.retry_after(tokens, interval) == round(interval) or ol.retry_after(tokens, interval) >= int(interval)
    tokens = ol.refill(tokens, interval, interval)   # one interval later -> one guess back
    assert 0.99 <= tokens <= 1.01
    assert ol.refill(0, 10 * 86400, interval) == ol.FREE_GUESSES  # never above capacity


def test_missing_window_uses_default_and_flags_it():
    assert ol.window_seconds(None, None, False) == (24 * 3600.0, True)
    assert ol.window_seconds(T0, T0 + timedelta(days=3), True) == (3 * 86400.0, False)
    assert ol.window_seconds(T0, T0 + timedelta(days=3), False)[1] is True  # unenforced


def test_schedule_change_recomputes():
    short = ol.refill_interval(ol.window_seconds(T0, T0 + timedelta(days=1), True)[0])
    long = ol.refill_interval(ol.window_seconds(T0, T0 + timedelta(days=7), True)[0])
    assert long > short * 6


def test_under_attack_and_ip_guard():
    sends = [T0 + timedelta(seconds=i) for i in range(60)]
    now = T0 + timedelta(minutes=5)
    assert ol.under_attack(sends, [], now)
    assert not ol.under_attack(sends, sends[:40], now)               # 67% verified -> healthy
    assert not ol.under_attack(sends[:49], [], now)                  # not enough volume
    assert not ol.under_attack(sends, [], T0 + timedelta(hours=2))   # outside the 30 min window
    assert ol.ip_needs_captcha(sends[:40], [], [], now)
    assert ol.ip_needs_captcha([], [], sends[:40], now)
    assert not ol.ip_needs_captcha(sends[:39], [], [], now)
