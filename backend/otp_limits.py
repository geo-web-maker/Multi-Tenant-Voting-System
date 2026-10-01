"""
Pure OTP-throttling maths for BallotBox (design doc: OTP_SMS_Design_v2).

No I/O and no clock reads here: every function takes `now` / elapsed seconds
as an argument so the whole file can be unit-tested with a fake clock
(see tests/test_otp_limits.py). main.py owns all database access.
"""
import math
import os
from datetime import datetime, timedelta

CODE_SPACE = 900_000  # secrets.randbelow(900000) + 100000


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


# ── Part A: send ladder ─────────────────────────────────────────────────────
try:
    SEND_LADDER = tuple(int(x) for x in os.getenv("OTP_SEND_LADDER_SECONDS", "0,30,60,120,300,600").split(",") if x.strip())
except ValueError:
    SEND_LADDER = (0, 30, 60, 120, 300, 600)
if len(SEND_LADDER) < 2:
    SEND_LADDER = (0, 30, 60, 120, 300, 600)
LADDER_RESET_S = env_int("OTP_LADDER_RESET_MINUTES", 30) * 60
DAILY_SEND_CEILING = env_int("OTP_DAILY_SEND_CEILING", 8)
CODE_TTL_MINUTES = env_int("OTP_CODE_TTL_MINUTES", 10)

# ── Part B: guess bucket ────────────────────────────────────────────────────
FREE_GUESSES = env_int("OTP_FREE_GUESSES", 5)
TARGET_RISK = env_float("OTP_TARGET_RISK", 0.0001)
LOCK_MIN_S = env_int("OTP_LOCK_MIN_SECONDS", 30)
LOCK_MAX_S = env_int("OTP_LOCK_MAX_SECONDS", 43_200)
DEFAULT_WINDOW_HOURS = env_int("OTP_DEFAULT_WINDOW_HOURS", 24)

# ── Part C: pumping guards ──────────────────────────────────────────────────
ATTACK_MIN_SENDS = 50        # org-wide, 30 min window
ATTACK_RATIO = 0.35
IP_MIN_SENDS = 40            # per IP, 30 min window
IP_RATIO = 0.25
IP_MAX_FAILS = 40
GUARD_WINDOW_S = 30 * 60


def next_wait(send_count: int) -> int:
    """Seconds the voter must wait after send number `send_count` (1-based) before the next one."""
    return SEND_LADDER[min(max(send_count, 0), len(SEND_LADDER) - 1)]


def prune_24h(sends: list[datetime], now: datetime) -> list[datetime]:
    cutoff = now - timedelta(hours=24)
    return [t for t in sends if t > cutoff]


def guess_budget(target_risk: float = TARGET_RISK, free: int = FREE_GUESSES) -> float:
    """G = epsilon x 900,000 wrong guesses per voter over the whole window (always > free)."""
    return max(target_risk * CODE_SPACE, free + 1)


def window_seconds(start, end, enforced: bool, default_hours: int = DEFAULT_WINDOW_HOURS) -> tuple[float, bool]:
    """(W, is_default). No enforced voting window -> the default, flagged so the UI can warn."""
    if enforced and start and end and end > start:
        return (end - start).total_seconds(), False
    return float(default_hours * 3600), True


def refill_interval(window_s: float, target_risk: float = TARGET_RISK, free: int = FREE_GUESSES) -> float:
    """clamp(W / (G - B), LOCK_MIN, LOCK_MAX): each extra wrong guess costs ~1% of the election."""
    g = guess_budget(target_risk, free)
    return min(max(window_s / (g - free), LOCK_MIN_S), LOCK_MAX_S)


def refill(tokens: float, elapsed_s: float, interval_s: float, cap: int = FREE_GUESSES) -> float:
    return min(float(cap), tokens + max(elapsed_s, 0.0) / interval_s)


def retry_after(tokens: float, interval_s: float) -> int:
    """Seconds until one whole token is available."""
    return max(1, math.ceil((1.0 - tokens) * interval_s))


def under_attack(sends: list[datetime], verifies: list[datetime], now: datetime) -> bool:
    """Org-wide send-to-verify ratio < 35% over >= 50 sends in 30 min."""
    cutoff = now - timedelta(seconds=GUARD_WINDOW_S)
    s = sum(1 for t in sends if t > cutoff)
    v = sum(1 for t in verifies if t > cutoff)
    return s >= ATTACK_MIN_SENDS and (v / s) < ATTACK_RATIO


def ip_needs_captcha(sends: list[datetime], verifies: list[datetime], fails: list[datetime], now: datetime) -> bool:
    """Challenge (never block) an IP with many sends and few verifies, or many failures."""
    cutoff = now - timedelta(seconds=GUARD_WINDOW_S)
    s = sum(1 for t in sends if t > cutoff)
    v = sum(1 for t in verifies if t > cutoff)
    f = sum(1 for t in fails if t > cutoff)
    return (s >= IP_MIN_SENDS and (v / s) < IP_RATIO) or f >= IP_MAX_FAILS


def fmt_wait(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 5400:
        return f"{math.ceil(seconds / 60)} minutes"
    return f"{seconds / 3600:.1f} hours"
