import re, glob, sys
static, dynamic = set(), set()
for f in glob.glob("frontend/src/**/*.jsx", recursive=True):
    src = open(f, encoding="utf-8").read()
    static |= set(re.findall(r'data-track="([^"]+)"', src))
    dynamic |= set(re.findall(r'data-track=\{`([^`]+)`\}', src))
LABEL = re.compile(r"^[a-z0-9_-]{2,40}$")                       # same as backend LABEL_RE
bad = [n for n in static if not LABEL.fullmatch(n)]
bad += [n for n in dynamic if not LABEL.fullmatch(re.sub(r"\$\{[^}]*\}", "1", n))]
need = {"login-submit", "apply-submit", "help-fab", "otp-submit", "ballot-submit", "phase-apply-now", "export-register"}
missing = need - static
print(f"{len(static)} static, {len(dynamic)} dynamic labels")
if bad:     sys.exit(f"invalid labels (must match ^[a-z0-9_-]{{2,40}}$): {bad}")
if missing: sys.exit(f"missing required labels: {sorted(missing)}")
print("data-track labels OK")
