// Per-organisation lines: eight hues from the theme's own --org-N tokens (defined per template in
// index.css / blueprint.css so they stay distinct there), then the same hues dashed for a ninth org onwards.
export const ORG_LINE_STYLES = [
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ color: `--org-${n}`, dash: '' })),
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ color: `--org-${n}`, dash: '7 4' })),
];
