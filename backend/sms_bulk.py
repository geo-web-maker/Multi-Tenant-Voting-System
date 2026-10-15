"""Pure helpers for the Bulk SMS tab (no database, no FastAPI).

Kept separate from main.py so the counting, rendering and validation rules can be unit-tested on their own.
The browser has a twin of count_parts() in frontend/src/smsCalc.js: keep the two in step (the shared test
vectors in tests/test_sms_bulk.py and smsCalc.test.js use the same cases).
"""
from __future__ import annotations

import math
import re

PROVIDERS = ("egosms", "mambosms")
LIMIT_KEYS = ("single_limit", "multi_limit", "unicode_single_limit", "unicode_multi_limit")
DEFAULT_LIMITS = {"single_limit": 160, "multi_limit": 153, "unicode_single_limit": 70, "unicode_multi_limit": 67}


def default_pricing() -> dict:
    """Starting values. cost_per_part_ugx stays None on purpose: an unset price must never look like 0."""
    return {p: {"cost_per_part_ugx": None, **DEFAULT_LIMITS} for p in PROVIDERS}


# ── GSM-7 counting ───────────────────────────────────────────────────────────
_GSM_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXT = "^{}\\[]~|€\f"
GSM_BASIC = frozenset(_GSM_BASIC)
GSM_EXT = frozenset(_GSM_EXT)


def count_parts(text: str, limits: dict | None = None) -> dict:
    """{chars, encoding, parts, remaining}. `chars` counts extended GSM characters as 2.
    Any character outside GSM-7 switches the WHOLE message to UCS-2 (one unit per UTF-16 code unit)."""
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    text = text or ""
    if all(c in GSM_BASIC or c in GSM_EXT for c in text):
        encoding = "GSM-7"
        chars = sum(2 if c in GSM_EXT else 1 for c in text)
        single, multi = lim["single_limit"], lim["multi_limit"]
    else:
        encoding = "UCS-2"
        chars = sum(2 if ord(c) > 0xFFFF else 1 for c in text)
        single, multi = lim["unicode_single_limit"], lim["unicode_multi_limit"]
    if chars == 0:
        return {"chars": 0, "encoding": encoding, "parts": 0, "remaining": single}
    if chars <= single:
        return {"chars": chars, "encoding": encoding, "parts": 1, "remaining": single - chars}
    parts = math.ceil(chars / multi)
    return {"chars": chars, "encoding": encoding, "parts": parts, "remaining": parts * multi - chars}


# ── Variables ────────────────────────────────────────────────────────────────
BASE_VARIABLES = ("name", "first_name", "reg_no")
_TOKEN_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


def variable_names(field_keys) -> list[str]:
    """Base set plus one variable per enabled optional field (never a duplicate of a base name)."""
    out = list(BASE_VARIABLES)
    out += [k for k in field_keys if k not in out]
    return out


def unknown_tokens(template: str, known) -> list[str]:
    known = set(known)
    seen, bad = set(), []
    for m in _TOKEN_RE.finditer(template or ""):
        t = m.group(1)
        if t not in known and t not in seen:
            seen.add(t)
            bad.append(t)
    return bad


def voter_values(voter: dict, field_keys) -> dict:
    """Values for every variable for one voter document. Missing -> empty string."""
    name = " ".join(str(voter.get("full_name") or "").split())
    attrs = voter.get("attrs") or {}
    vals = {"name": name, "first_name": name.split(" ")[0] if name else "",
            "reg_no": str(voter.get("student_id") or "").upper()}
    for k in field_keys:
        if k not in vals:
            vals[k] = str(attrs.get(k) or "")
    return vals


def render(template: str, values: dict) -> str:
    """Plain replace over the known list: no str.format, no evaluator. Unknown {tokens} are left as typed
    (the UI flags them before sending), braces that are not tokens are untouched."""
    out = template or ""
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


# ── Pricing validation ───────────────────────────────────────────────────────
def validate_pricing(raw, current: dict | None = None) -> dict:
    """Validate an `sms_pricing` update and return the full merged dict. Raises ValueError (user-facing)."""
    if not isinstance(raw, dict):
        raise ValueError("Pricing must be an object keyed by provider.")
    unknown = [k for k in raw if k not in PROVIDERS]
    if unknown:
        raise ValueError(f"Unknown provider: {unknown[0]}.")
    merged = {p: dict((current or default_pricing()).get(p) or default_pricing()[p]) for p in PROVIDERS}
    for prov, vals in raw.items():
        if not isinstance(vals, dict):
            raise ValueError(f"Pricing for {prov} must be an object.")
        bad = [k for k in vals if k != "cost_per_part_ugx" and k not in LIMIT_KEYS]
        if bad:
            raise ValueError(f"Unknown pricing field for {prov}: {bad[0]}.")
        if "cost_per_part_ugx" in vals:
            c = vals["cost_per_part_ugx"]
            if c is None or c == "":
                merged[prov]["cost_per_part_ugx"] = None
            else:
                if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c) or c < 0:
                    raise ValueError(f"Cost per part for {prov} must be a number of 0 or more.")
                merged[prov]["cost_per_part_ugx"] = c
        for k in LIMIT_KEYS:
            if k in vals:
                n = vals[k]
                if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 1000:
                    raise ValueError(f"{k} for {prov} must be a whole number from 1 to 1000.")
                merged[prov][k] = n
        m = merged[prov]
        if m["multi_limit"] > m["single_limit"]:
            raise ValueError(f"For {prov}, the multi-part limit cannot be larger than the single-part limit.")
        if m["unicode_multi_limit"] > m["unicode_single_limit"]:
            raise ValueError(f"For {prov}, the multi-part unicode limit cannot be larger than the single-part unicode limit.")
    return merged


def pricing_for(sec_pricing, provider: str) -> dict:
    """Stored pricing for one provider with defaults filled in (stored docs may predate a key)."""
    base = default_pricing()[provider]
    got = (sec_pricing or {}).get(provider) or {}
    return {**base, **{k: v for k, v in got.items() if k in base}}


# ── Audience filters ─────────────────────────────────────────────────────────
VOTED_CHOICES = ("any", "voted", "not_voted")
MAX_REG_LIST = 5000


def build_voter_query(filters: dict, enabled_keys, normalize_sid) -> dict:
    """Mongo filter from the request filters. Attribute keys are accepted ONLY if they are enabled fields of
    the org (never straight from the request). Fields combine with AND, values within a field with OR.
    Raises ValueError on bad input. The caller adds the tenant filter via tdb()."""
    filters = filters or {}
    q: dict = {}
    voted = filters.get("voted", "any")
    if voted not in VOTED_CHOICES:
        raise ValueError("Voted filter must be any, voted or not_voted.")
    if voted == "voted":
        q["has_voted"] = True
    elif voted == "not_voted":
        q["has_voted"] = {"$ne": True}
    enabled = set(enabled_keys)
    ands = []
    for key, values in (filters.get("attrs") or {}).items():
        if key not in enabled:
            raise ValueError(f"Unknown or disabled voter field: {key}")
        if isinstance(values, str):
            values = [values]
        vals = [str(v).strip() for v in (values or []) if str(v).strip()]
        if vals:
            ands.append({f"attrs.{key}": {"$in": vals}})
    regs = filters.get("reg_numbers") or []
    if isinstance(regs, str):
        regs = re.split(r"[\s,;]+", regs)
    regs = [normalize_sid(r) for r in regs if str(r).strip()]
    if len(regs) > MAX_REG_LIST:
        raise ValueError(f"At most {MAX_REG_LIST} registration numbers can be pasted.")
    if regs:
        ands.append({"student_id": {"$in": regs}})
    if ands:
        q["$and"] = ands
    return q


def first_phone(voter: dict, normalize_phone) -> str | None:
    """First usable number: imports can join numbers with '/', so each stored entry is split too."""
    for raw in voter.get("phone_numbers") or []:
        for piece in str(raw or "").split("/"):
            if not piece.strip():
                continue
            try:
                return normalize_phone(piece)
            except Exception:
                continue
    return None


def estimate(voters, template: str, field_keys, limits: dict, unit_cost, normalize_phone) -> dict:
    """Exact estimate over already-fetched voters (one query, projected). Pure."""
    by_parts: dict[int, int] = {}
    recipients = no_phone = total_parts = 0
    min_len = max_len = None
    samples, missing = [], {}
    for v in voters:
        if not first_phone(v, normalize_phone):
            no_phone += 1
            continue
        vals = voter_values(v, field_keys)
        for k, val in vals.items():
            if not val:
                missing[k] = missing.get(k, 0) + 1
        c = count_parts(render(template, vals), limits)
        recipients += 1
        total_parts += c["parts"]
        by_parts[c["parts"]] = by_parts.get(c["parts"], 0) + 1
        min_len = c["chars"] if min_len is None else min(min_len, c["chars"])
        max_len = c["chars"] if max_len is None else max(max_len, c["chars"])
        if len(samples) < 3:
            samples.append({"name": vals["name"], "text": render(template, vals), **c})
    used = {t for t in (m.group(1) for m in _TOKEN_RE.finditer(template or ""))}
    return {
        "recipients": recipients, "no_phone": no_phone, "total_parts": total_parts,
        "by_parts": {str(k): n for k, n in sorted(by_parts.items())},
        "unit_cost": unit_cost,
        "total_cost": None if unit_cost is None else round(total_parts * unit_cost, 2),
        "min_len": min_len, "max_len": max_len, "samples": samples,
        "missing": {k: n for k, n in missing.items() if k in used},
    }
