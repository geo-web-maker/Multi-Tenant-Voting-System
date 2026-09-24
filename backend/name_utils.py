"""Name normalisation shared by main.py, the backfill endpoint and backfill_names.py."""
import re


_NAME_SEP_RE = re.compile(r"([-'’])")

def _fix_name_word(word: str) -> str:
    """Capitalise one whitespace-delimited word. Hyphen/apostrophe parts are
    handled individually (o'kello -> O'Kello, anne-marie -> Anne-Marie).
    A part that is ALL lower or ALL upper is re-cased; a part that is already
    mixed-case (McDonald, DeLacy) is trusted and left alone apart from making
    sure it starts with a capital."""
    out = []
    for part in _NAME_SEP_RE.split(word):
        if not part or _NAME_SEP_RE.fullmatch(part):
            out.append(part)
        elif part.islower() or part.isupper():
            out.append(part[0].upper() + part[1:].lower())
        else:
            out.append(part[0].upper() + part[1:])
    return "".join(out)

def normalize_name(full_name: str) -> str:
    """Single source of truth for person-name normalisation: collapse runs of
    whitespace and capitalise each word ('john OKELLO' -> 'John Okello').
    Idempotent. Only ever changes letter case and spacing, so names_match()
    (which is case-insensitive) is unaffected. Used at every write site and by
    the backfill (backfill_names.py / POST /superadmin/maintenance/normalize-names)."""
    if not full_name:
        return full_name or ""
    return " ".join(_fix_name_word(w) for w in str(full_name).split())
