"""Roster helpers shared by main.py and the tests. Pure functions, no DB access.

1. Registration-number "shape" check  - learns the format from the data, so no tenant-specific regex.
2. Configurable voter attributes      - per-org optional fields (gender / programme / anything else).
3. Turnout small-group suppression    - keeps published turnout splits from exposing individuals.
"""
import re
from collections import Counter

# ── 1. Registration-number shape ────────────────────────────────────────────

SHAPE_MIN_ROWS = 20      # a reference needs at least this many IDs ...
SHAPE_MIN_SHARE = 0.80   # ... and this share of them must have the same shape

_DIGIT_RUN = re.compile(r"\d+")
_LETTER_RUN = re.compile(r"[^\W\d_]+")


def id_shape(student_id: str) -> str:
    """'24/u/afd/02107/pd' -> '9/A/A/9/A'. Digit runs -> 9, letter runs -> A, everything else kept.
    Collapsing runs means serial length and programme codes never cause a mismatch."""
    return _LETTER_RUN.sub("A", _DIGIT_RUN.sub("9", student_id))


def _dominant_shape(ids, min_rows: int, min_share: float):
    ids = list(ids)
    if len(ids) < min_rows:
        return None
    counts = Counter(id_shape(i) for i in ids)
    shape, n = counts.most_common(1)[0]
    if n / len(ids) < min_share:
        return None
    return shape, next(i for i in ids if id_shape(i) == shape), n / len(ids)


def check_id_shapes(file_ids, roster_ids=(), min_rows: int = SHAPE_MIN_ROWS, min_share: float = SHAPE_MIN_SHARE):
    """Find registration numbers whose shape differs from the dominant one.

    Reference = the existing register's dominant shape if it has a clear majority (so a whole file in
    the wrong format is caught), otherwise the file's own. min_rows / min_share apply to the
    *reference* only, so a small file can still be checked against an established register.
    Expects IDs already passed through normalize_student_id().
    Returns None when there is no clear reference, else
    {"reference", "example", "source": "roster"|"file", "share", "outliers": [ids]}."""
    file_ids = list(file_ids)
    ref = _dominant_shape(roster_ids, min_rows, min_share)
    source = "roster"
    if ref is None:
        ref, source = _dominant_shape(file_ids, min_rows, min_share), "file"
    if ref is None:
        return None
    shape, example, share = ref
    return {"reference": shape, "example": example, "source": source, "share": share,
            "outliers": [i for i in file_ids if id_shape(i) != shape]}


def shape_warnings(result: dict | None, total: int, row_nums: dict, per_row_cap: int = 20) -> list[str]:
    """Warning strings for check_id_shapes(). One summary line when many rows mismatch (wrong file /
    new numbering scheme), otherwise one line per outlier. Never blocks a row."""
    if not result or not result["outliers"]:
        return []
    out, ref, ex = result["outliers"], result["reference"], result["example"]
    where = "the existing voter register" if result["source"] == "roster" else "most of this file"
    if len(out) > per_row_cap or len(out) > total * 0.5:
        return [f"{len(out)} of {total} registration numbers don't match the format of {where} "
                f"(e.g. \"{ex}\"). Check you uploaded the right file. They are still included."]
    return [f"Row {row_nums.get(i, '?')} ({i}): registration number doesn't match the format of {where} "
            f"(e.g. \"{ex}\") - check for a typo. It is still included."
            for i in out]


# ── 2. Configurable voter attributes ────────────────────────────────────────

# Standard fields every org gets (toggle only, can't be deleted). Custom fields are added per org.
STANDARD_FIELDS = (
    {"key": "gender", "label": "Gender", "aliases": ("gender", "sex")},
    {"key": "programme", "label": "Programme", "aliases": ("programme", "program", "course")},
)
MAX_VOTER_FIELDS = 8
ATTR_VALUE_MAX_LEN = 60
LABEL_MAX_LEN = 40
DEFAULT_MIN_GROUP = 10
MIN_GROUP_RANGE = (5, 100)
FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
# CSV columns / voter-document fields the importer already owns.
RESERVED_KEYS = {"student_id", "student-id", "full_name", "full-name", "name", "phone", "phone_numbers", "attrs"}


def _std(key: str):
    return next((f for f in STANDARD_FIELDS if f["key"] == key), None)


def merge_voter_fields(stored) -> list[dict]:
    """Stored per-org config overlaid on the standard fields (always present, off by default).
    Returns [{"key","label","standard","enabled","public"}]. public implies enabled."""
    stored = {f.get("key"): f for f in (stored or []) if isinstance(f, dict) and f.get("key")}
    out = []
    for s in STANDARD_FIELDS:
        c = stored.pop(s["key"], {})
        en = bool(c.get("enabled", False))
        out.append({"key": s["key"], "label": c.get("label") or s["label"], "standard": True,
                    "enabled": en, "public": en and bool(c.get("public", False))})
    for key, c in stored.items():
        en = bool(c.get("enabled", False))
        out.append({"key": key, "label": c.get("label") or key, "standard": False,
                    "enabled": en, "public": en and bool(c.get("public", False))})
    return out


def apply_field_changes(current: list[dict], upserts: list[dict], remove: list[str]) -> tuple[list[dict], list[str]]:
    """Validate and apply an admin edit to the field config.
    upserts: [{"key", "label"?, "enabled"?, "public"?}]  - unknown key = new custom field.
    remove:  custom field keys to delete (their stored values are purged by the caller).
    Returns (new_config, removed_keys). Raises ValueError with a user-facing message."""
    fields = {f["key"]: dict(f) for f in current}
    order = [f["key"] for f in current]
    removed = []
    for key in remove:
        f = fields.get(key)
        if f is None:
            raise ValueError(f"Unknown field \"{key}\".")
        if f["standard"]:
            raise ValueError(f"\"{f['label']}\" is a standard field - turn it off instead of removing it.")
        del fields[key]
        order.remove(key)
        removed.append(key)
    for u in upserts:
        key = str(u.get("key", "")).strip().lower()
        f = fields.get(key)
        if f is None:
            if not FIELD_KEY_RE.match(key):
                raise ValueError("Field key must start with a letter and use only a-z, 0-9 and _ (max 30).")
            if key in RESERVED_KEYS:
                raise ValueError(f"\"{key}\" is reserved for a built-in column.")
            f = {"key": key, "label": key, "standard": False, "enabled": False, "public": False}
            fields[key] = f
            order.append(key)
        if u.get("label") is not None:
            label = " ".join(str(u["label"]).split())
            if not label or len(label) > LABEL_MAX_LEN:
                raise ValueError(f"Label must be 1-{LABEL_MAX_LEN} characters.")
            f["label"] = label
        elif f["label"] == key and not f["standard"]:
            f["label"] = key.replace("_", " ").title()
        if u.get("enabled") is not None:
            f["enabled"] = bool(u["enabled"])
        if u.get("public") is not None:
            f["public"] = bool(u["public"])
        f["public"] = f["public"] and f["enabled"]
    if len(order) > MAX_VOTER_FIELDS:
        raise ValueError(f"At most {MAX_VOTER_FIELDS} fields per organisation.")
    labels = [fields[k]["label"].casefold() for k in order]
    if len(set(labels)) != len(labels):
        raise ValueError("Two fields have the same label.")
    return [fields[k] for k in order], removed


def normalize_attr_value(raw) -> str:
    """Free-text cell -> stored value. Collapses whitespace; re-cases ALL-lower / ALL-UPPER text so
    'baf', 'BAF' and 'Baf' group together (<=5 chars -> UPPER, longer -> Title Case). Mixed case is
    trusted. Idempotent. Blank -> ''. Over-long values are cut, not skipped."""
    v = " ".join(str(raw or "").split())[:ATTR_VALUE_MAX_LEN]
    if v and (v.islower() or v.isupper()):
        v = v.upper() if len(v) <= 5 else v.title()
    return v


def _norm_header(h) -> str:
    return re.sub(r"[\s\-]+", "_", str(h or "").strip().lower())


def attr_columns(headers, fields: list[dict]) -> dict[str, str]:
    """{field key: original CSV header} for enabled fields that have a column. Matches on key, label
    or (standard fields) aliases, case/space/hyphen-insensitive."""
    by_norm = {}
    for h in headers or []:
        by_norm.setdefault(_norm_header(h), h)
    cols = {}
    for f in fields:
        if not f["enabled"]:
            continue
        names = {f["key"], _norm_header(f["label"])}
        if f["standard"]:
            names |= set((_std(f["key"]) or {}).get("aliases", ()))
        hit = next((by_norm[n] for n in names if n in by_norm), None)
        if hit is not None:
            cols[f["key"]] = hit
    return cols


def row_attrs(row: dict, cols: dict[str, str]) -> dict[str, str]:
    """Non-blank normalized values for one CSV row. Blank cell = 'not provided', never a wipe."""
    out = {}
    for key, header in cols.items():
        v = normalize_attr_value(row.get(header))
        if v:
            out[key] = v
    return out


def attr_set_paths(attrs: dict) -> dict:
    """{'gender': 'F'} -> {'attrs.gender': 'F'} for a Mongo $set that never replaces the whole dict."""
    return {f"attrs.{k}": v for k, v in (attrs or {}).items()}


def diff_attrs(old: dict | None, new: dict, enabled_keys) -> tuple[dict, dict]:
    """Compare a file row's attributes to a voter's stored ones (only fields present in the file).
    Returns (fills, overwrites): fills = previously-empty values (safe, applied automatically);
    overwrites = {key: {"old","new"}} where a different value already exists (admin decides)."""
    old = old or {}
    fills, over = {}, {}
    for k, nv in new.items():
        nv = normalize_attr_value(nv)
        if k not in enabled_keys or not nv:
            continue
        ov = normalize_attr_value(old.get(k))
        if not ov:
            fills[k] = nv
        elif ov != nv:
            over[k] = {"old": ov, "new": nv}
    return fills, over


# ── 3. Turnout small-group suppression ──────────────────────────────────────

OTHER_LABEL = "Other"
UNRECORDED_LABEL = "Not recorded"


def _pct(voted: int, registered: int) -> float:
    return round(voted / registered * 100, 1) if registered else 0.0


def finish_groups(groups: list[dict]) -> list[dict]:
    """Add pct and sort (largest first, 'Other' last). Used for the un-suppressed admin view."""
    out = [{**g, "pct": _pct(g["voted"], g["registered"])} for g in groups]
    out.sort(key=lambda g: (g["label"] in (OTHER_LABEL,), -g["registered"], g["label"]))
    return out


def suppress_small_groups(groups: list[dict], k: int = DEFAULT_MIN_GROUP) -> dict:
    """Public-safe version of [{"label","registered","voted"}].
    Groups with fewer than k registered voters are folded into "Other". If "Other" is itself below k it
    absorbs the next-smallest group until it reaches k, so it can't be subtracted out of the totals.
    If nothing meaningful is left (total < k, or one bucket only) nothing is published.
    Returns {"groups": [...], "suppressed": bool}."""
    big = sorted((g for g in groups if g["registered"] >= k), key=lambda g: g["registered"])
    small = [g for g in groups if g["registered"] < k]
    if not small:
        return {"groups": [], "suppressed": True} if len(big) < 2 else {"groups": finish_groups(big), "suppressed": False}
    other = {"label": OTHER_LABEL, "registered": sum(g["registered"] for g in small),
             "voted": sum(g["voted"] for g in small)}
    while other["registered"] < k and big:
        g = big.pop(0)
        other["registered"] += g["registered"]
        other["voted"] += g["voted"]
    if other["registered"] < k or not big:
        return {"groups": [], "suppressed": True}
    return {"groups": finish_groups(big + [other]), "suppressed": False}
