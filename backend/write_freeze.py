"""Process-local, auto-expiring maintenance write freeze used only for migration cutover."""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone

_started_monotonic: float | None = None
_expires_monotonic: float | None = None
_started_at: datetime | None = None

EXEMPT_PREFIXES = ("/superadmin/backups", "/internal/backup", "/verify-admin", "/superadmin/mfa",
                   "/admin/logout", "/health", "/analytics/collect")

def max_minutes() -> int:
    try: return max(1, min(30, int(os.getenv("WRITE_FREEZE_MAX_MINUTES", "30"))))
    except ValueError: return 30

def active() -> bool:
    global _started_monotonic, _expires_monotonic, _started_at
    if _expires_monotonic is None or time.monotonic() >= _expires_monotonic:
        _started_monotonic = _expires_monotonic = None; _started_at = None
        return False
    return True

def status() -> dict:
    on = active()
    remaining = max(0, int(_expires_monotonic - time.monotonic())) if on and _expires_monotonic else 0
    return {"active": on, "started_at": _started_at.isoformat() + "Z" if on and _started_at else None,
            "expires_in_seconds": remaining, "max_minutes": max_minutes()}

def start(minutes: int = 20) -> dict:
    global _started_monotonic, _expires_monotonic, _started_at
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1 or minutes > min(30, max_minutes()):
        raise ValueError(f"minutes must be between 1 and {min(30, max_minutes())}.")
    _started_monotonic = time.monotonic(); _expires_monotonic = _started_monotonic + minutes * 60
    _started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return status()

def lift() -> dict:
    global _started_monotonic, _expires_monotonic, _started_at
    _started_monotonic = _expires_monotonic = None; _started_at = None
    return status()

def path_exempt(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in EXEMPT_PREFIXES)
