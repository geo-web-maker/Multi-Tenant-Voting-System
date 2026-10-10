"""Tier presets and the resolved performance settings.

Limit numbers for the cluster live here, in the environment, or in the saved
settings document. Nothing else in the app should hard-code an operations cap
or a connection cap.
"""
import logging
import os
import threading
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# name: (ops_per_s_cap, connection_cap, note). Add a line only to make a plan appear by name.
TIERS = {
    "free": (100, 500, "Atlas Free (M0): 100 ops/s; operations queue and are throttled above it."),
}
PRESETS_VERIFIED_ON = "2026-10-10"
DEFAULT_TIER = "free"
NO_CAP = ("0", "none", "off", "unlimited")

# Status and alert thresholds. Not tier caps; kept here so the numbers have one home (P9).
THROTTLE_CAP_PCT = 95
THROTTLE_P95_MS = 800
LOOP_LAG_P95_MS = 100
HTTP_SLOW_P95_MS = 1500
HTTP_SLOW_MIN_REQUESTS = 50
COLD_START_SECONDS = 300
AUDIT_OPS_PER_VOTER = 26
VOTER_SEQUENCES_MIN = 30
CMD_LAT_EDGES = [1, 2, 5, 10, 25, 50, 100, 250, 500, 800, 1500, 5000]
ALERT_COOLDOWN_S = {
    "ops_warn": 10 * 60,
    "ops_critical": 5 * 60,
    "throttle_suspect": 5 * 60,
    "pool_pressure": 5 * 60,
    "loop_lag": 15 * 60,
    "latency": 15 * 60,
    "cold_start": None,  # once per process start
}

_lock = threading.Lock()
_saved: dict = {}
_version = 0
_listeners = []


def on_change(fn) -> None:
    """Called after the in-memory settings are swapped. Used by the collector."""
    _listeners.append(fn)


def perf_enabled() -> bool:
    return os.getenv("PERF_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def _env_cap(name):
    """(found, value): value None means an explicit 'no hard cap'."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return False, None
    if raw.strip().lower() in NO_CAP:
        return True, None
    try:
        v = int(float(raw))
        return (True, v) if v > 0 else (False, None)
    except ValueError:
        log.warning("%s=%r is not a number; ignoring it", name, raw)
        return False, None


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


def _pick(key, saved, env_value, preset_value):
    """Precedence: saved (UI) > environment > preset. A saved None means 'no cap' and is honoured."""
    if key in saved:
        return saved[key], "ui"
    found, v = env_value
    if found:
        return v, "env"
    return preset_value, "preset"


def _pick_int(key, saved, env_name, default):
    if key in saved:
        try:
            return int(saved[key]), "ui"
        except (TypeError, ValueError):
            pass
    raw = os.getenv(env_name)
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw), "env"
        except ValueError:
            log.warning("%s=%r is not a number; ignoring it", env_name, raw)
    return int(default), "preset"


def saved_values() -> dict:
    with _lock:
        return dict(_saved)


def config_version() -> int:
    return _version


def swap_saved(values: dict | None, version: int | None = None) -> None:
    """Atomic swap of the in-memory settings. Listeners see the new values."""
    global _saved, _version
    with _lock:
        _saved = dict(values or {})
        if version is not None:
            _version = int(version)
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            log.warning("perf config listener failed", exc_info=True)


def resolve(saved: dict | None = None) -> dict:
    """saved = the `values` of platform_settings/perf_config, or None."""
    saved = dict(saved or {})
    requested = str(saved.get("tier") or os.getenv("MONGO_TIER", DEFAULT_TIER)).strip().lower()
    custom = requested == "custom"
    base = DEFAULT_TIER if custom or requested not in TIERS else requested
    if not custom and requested not in TIERS:
        log.warning("Unknown tier %r; using %r", requested, DEFAULT_TIER)
    if "tier" in saved:
        tier_source = "ui"
    elif os.getenv("MONGO_TIER"):
        tier_source = "env"
    else:
        tier_source = "preset"
    ops, conns, note = TIERS[base]
    ops_cap, ops_src = _pick("ops_cap", saved, _env_cap("DB_OPS_CAP"), ops)
    conn_cap, conn_src = _pick("conn_cap", saved, _env_cap("DB_CONN_CAP"), conns)
    warn_pct, warn_src = _pick_int("warn_pct", saved, "PERF_WARN_PCT", "70")
    crit_pct, crit_src = _pick_int("crit_pct", saved, "PERF_CRIT_PCT", "90")
    slow_ms, slow_src = _pick_int("slow_ms", saved, "PERF_SLOW_COMMAND_MS", "250")
    persist_s, persist_src = _pick_int("persist_s", saved, "PERF_PERSIST_SECONDS", "300")
    if "paused" in saved:
        paused, paused_src = bool(saved.get("paused")), "ui"
    else:
        paused, paused_src = False, "preset"
    return {
        "tier": "custom" if custom else base,
        "tier_source": tier_source,
        "note": "Custom caps" if custom else note,
        "ops_cap": ops_cap, "ops_cap_source": ops_src,
        "conn_cap": conn_cap, "conn_cap_source": conn_src,
        "warn_pct": warn_pct, "warn_pct_source": warn_src,
        "crit_pct": crit_pct, "crit_pct_source": crit_src,
        "slow_ms": slow_ms, "slow_ms_source": slow_src,
        "persist_s": persist_s, "persist_s_source": persist_src,
        "paused": paused, "paused_source": paused_src,
        "retention_days": _env_int("PERF_RETENTION_DAYS", "14"),
        "presets_verified_on": PRESETS_VERIFIED_ON,
        "sources": {
            "tier": tier_source, "ops_cap": ops_src, "conn_cap": conn_src,
            "warn_pct": warn_src, "crit_pct": crit_src, "slow_ms": slow_src,
            "persist_s": persist_src, "paused": paused_src,
        },
    }


def current_config() -> dict:
    return resolve(saved_values())


def percent_of(value, cap) -> int | None:
    """value as a percentage of cap. None when there is no hard cap."""
    if not cap:
        return None
    try:
        return int(round(float(value) / float(cap) * 100))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def preset_options() -> list[dict]:
    out = [{"id": name, "ops_cap": ops, "conn_cap": conns, "note": note} for name, (ops, conns, note) in TIERS.items()]
    out.append({"id": "custom", "ops_cap": None, "conn_cap": None, "note": "Custom caps"})
    return out


def validate(payload: dict) -> dict:
    """Return the cleaned values to save, or raise ValueError({field: message}). Mirrors the UI."""
    errs, out = {}, {}

    def cap(field):
        if field not in payload:
            return
        v = payload[field]
        if v is None or (isinstance(v, str) and v.strip().lower() in NO_CAP):
            out[field] = None
        elif isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 100_000):
            errs[field] = "Enter a whole number from 1 to 100,000, or choose no hard cap."
        else:
            out[field] = v

    tier = payload.get("tier")
    if tier is not None:
        if str(tier).lower() not in (*TIERS, "custom"):
            errs["tier"] = "Unknown tier."
        else:
            out["tier"] = str(tier).lower()
    cap("ops_cap")
    cap("conn_cap")
    if "ops_cap" in out or "conn_cap" in out:
        chosen = out.get("tier")
        preset = TIERS.get(chosen) if chosen else None
        matches = (
            preset is not None
            and out.get("ops_cap", preset[0]) == preset[0]
            and out.get("conn_cap", preset[1]) == preset[1]
        )
        out["tier"] = chosen if matches else "custom"
    warn, crit = payload.get("warn_pct"), payload.get("crit_pct")
    for k, v, lo, hi in (("warn_pct", warn, 1, 99), ("crit_pct", crit, 2, 100)):
        if k in payload:
            if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
                errs[k] = f"Enter a whole number from {lo} to {hi}."
            else:
                out[k] = v
    if "warn_pct" in out and "crit_pct" in out and out["warn_pct"] >= out["crit_pct"]:
        errs["warn_pct"] = "Warning must be below critical."
    if "slow_ms" in payload:
        v = payload["slow_ms"]
        if isinstance(v, bool) or not isinstance(v, int) or not (10 <= v <= 10_000):
            errs["slow_ms"] = "Enter a whole number from 10 to 10,000."
        else:
            out["slow_ms"] = v
    if "persist_s" in payload:
        v = payload["persist_s"]
        if v not in (0, 60, 300, 900, 3600):
            errs["persist_s"] = "Choose Off, 1, 5, 15 or 60 minutes."
        else:
            out["persist_s"] = v
    if "paused" in payload:
        out["paused"] = bool(payload["paused"])
    if errs:
        raise ValueError(errs)
    return out


def apply_update(saved: dict | None, payload: dict) -> dict:
    """Merge a settings edit over the saved document and re-check warn < critical.

    Choosing a known preset without sending caps fills the caps from that preset.
    Saving only one of warn/critical cannot leave an invalid pair.
    """
    saved = dict(saved or {})
    data = dict(payload or {})
    tier = str(data.get("tier") or "").lower()
    if tier in TIERS and "ops_cap" not in data and "conn_cap" not in data:
        data["ops_cap"], data["conn_cap"] = TIERS[tier][0], TIERS[tier][1]
    cleaned = validate(data)
    merged = {**saved, **cleaned}
    resolved = resolve(merged)
    if resolved["warn_pct"] >= resolved["crit_pct"]:
        raise ValueError({"warn_pct": "Warning must be below critical."})
    # Persist the fields the tab owns, not the derived source labels.
    keep = ("tier", "ops_cap", "conn_cap", "warn_pct", "crit_pct", "slow_ms", "persist_s", "paused")
    return {k: merged[k] for k in keep if k in merged}


def _db(db):
    from tenant_db import cross_tenant
    return cross_tenant(db)


async def load_config(db) -> dict:
    doc = await _db(db).platform_settings.find_one({"name": "perf_config"})
    values = (doc or {}).get("values") or {}
    swap_saved(values, (doc or {}).get("version") or 0)
    return values


async def save_config(db, values: dict, actor: str) -> dict:
    """One write. The caller records the audit entry (the second operation)."""
    await _db(db).platform_settings.update_one(
        {"name": "perf_config"},
        {"$set": {
            "name": "perf_config",
            "values": values,
            "updated_at": datetime.now(timezone.utc),
            "updated_by": actor,
        }, "$inc": {"version": 1}},
        upsert=True,
    )
    swap_saved(values, config_version() + 1)
    return values


async def reset_config(db) -> None:
    await _db(db).platform_settings.delete_one({"name": "perf_config"})
    swap_saved({}, 0)


def public_config(extra: dict | None = None) -> dict:
    """Resolved settings for the tab, with where each value came from. No secrets."""
    cfg = current_config()
    body = {
        "enabled": perf_enabled(),
        "paused": cfg["paused"],
        "tier": cfg["tier"],
        "note": cfg["note"],
        "ops_cap": cfg["ops_cap"],
        "conn_cap": cfg["conn_cap"],
        "warn_pct": cfg["warn_pct"],
        "crit_pct": cfg["crit_pct"],
        "slow_ms": cfg["slow_ms"],
        "persist_s": cfg["persist_s"],
        "retention_days": cfg["retention_days"],
        "sources": cfg["sources"],
        "presets": preset_options(),
        "presets_verified_on": cfg["presets_verified_on"],
        "sink": (os.getenv("PERF_SINK") or "mongo").strip().lower(),
    }
    if extra:
        body.update(extra)
    return body
