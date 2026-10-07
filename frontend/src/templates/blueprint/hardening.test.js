import { describe, it, expect } from 'vitest';
import { css, legacyCss } from './cssTools.js';

// BP-T10: static guards for keyboard focus and reduced motion (jsdom cannot judge rendering; these pin the CSS).
const focusRule = css.match(/html\[data-template="blueprint"\]\s*:where\(([^)]*\)?[^)]*)\):focus-visible\s*\{([^}]*)\}/);

describe('focus ring (R10)', () => {
  it('one :focus-visible rule covers native and role-based keyboard stops', () => {
    expect(focusRule).not.toBeNull();
    const sel = focusRule[1];
    for (const k of ['button', 'a', 'input', 'select', 'textarea', 'summary', '[role="button"]', '[tabindex]:not([tabindex="-1"])']) {
      expect(sel, k).toContain(k);
    }
  });
  it('ring is 2px accent with an offset (never removed)', () => {
    expect(focusRule[2]).toMatch(/outline:\s*2px solid var\(--bp-ac\)/);
    expect(focusRule[2]).toMatch(/outline-offset:\s*2px/);
    expect(css).not.toMatch(/outline:\s*(none|0)\b/);
  });
  it('a selected candidate keeps a distinguishable keyboard ring', () => {
    expect(css).toMatch(/\.bp-cand\.bp-on:focus-visible\s*\{[^}]*outline-offset:/);
  });
});

describe('reduced motion (R10)', () => {
  const block = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([^]*?\})\s*\}/);
  it('stops the status-dot pulse and the meter-bar width transition', () => {
    expect(block).not.toBeNull();
    expect(block[1]).toMatch(/\.bp-dot\s*\{\s*animation:\s*none/);
    expect(block[1]).toMatch(/\.bp-bar i\s*\{\s*transition:\s*none/);
  });
  it('every blueprint animation/transition sits next to a reduced-motion rule', () => {
    expect(css.match(/animation:\s*bp-/g)?.length ?? 0).toBeGreaterThan(0);
    expect(css).toMatch(/\.bp-dot\s*\{\s*animation:\s*none/);
  });
  it('the global index.css reduced-motion net still exists (covers legacy and blueprint alike)', () => {
    expect(legacyCss).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\*,\s*\*::before,\s*\*::after/);
  });
});
