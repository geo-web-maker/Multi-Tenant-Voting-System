#!/usr/bin/env bash
# G1 + G2 build gates for the Blueprint template (BLUEPRINT_TEMPLATE_GUIDE.md §10).
# Usage: BASELINE_ENTRY_GZ=<bytes> bash scripts/check_template_build.sh
set -euo pipefail
cd "$(dirname "$0")/.."
gz() { gzip -c "$1" | wc -c; }   # bytes, gzipped

echo "== G1: default build =="
rm -rf dist && npx vite build >/dev/null
if ls dist/assets | grep -qi blueprint; then echo "FAIL: blueprint chunk in default build"; exit 1; fi
# S2 fallback tokens (var(--bp-x, #literal)) legitimately appear in default JS; only bp- CLASS names (not preceded by - or a word char) are forbidden.
if grep -lP '(?<![-\w])bp-' dist/assets/*.js >/dev/null 2>&1; then echo "FAIL: bp- strings in default JS"; exit 1; fi
ENTRY=$(ls dist/assets/index-*.js | head -1); D=$(gz "$ENTRY"); echo "default entry gz: $D bytes"
if [ -n "${BASELINE_ENTRY_GZ:-}" ] && [ "$D" -gt $((BASELINE_ENTRY_GZ + 1536)) ]; then echo "FAIL: entry grew > 1.5 KB"; exit 1; fi

echo "== G2: blueprint build =="
rm -rf dist-blueprint && VITE_UI_TEMPLATE=blueprint npx vite build --outDir dist-blueprint >/dev/null
BP=$(ls dist-blueprint/assets | grep -i -E "blueprint|templates" || true)
[ -n "$BP" ] || { echo "FAIL: no blueprint chunk"; exit 1; }
TOTAL=0
for f in $(find dist-blueprint/assets -type f \( -name '*lueprint*.js' -o -name '*lueprint*.css' \)); do TOTAL=$((TOTAL + $(gz "$f"))); done
echo "blueprint chunk gz: $TOTAL bytes"
[ "$TOTAL" -le 30720 ] || { echo "FAIL: blueprint chunk > 30 KB gz"; exit 1; }
E2=$(ls dist-blueprint/assets/index-*.js | head -1); E2G=$(gz "$E2")
echo "blueprint entry gz: $E2G bytes (budget: default + 2048)"
if [ "$E2G" -gt $((D + 2048)) ]; then echo "FAIL: blueprint entry grew > 2 KB over default"; exit 1; fi
echo OK
