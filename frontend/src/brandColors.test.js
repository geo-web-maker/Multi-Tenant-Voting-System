import { describe, it, expect, beforeEach } from 'vitest';
import { parseHex, contrast, inkOn, ensureContrast, deriveBrandVars, setBrand } from './brandColors.js';

const GOLD = '#f1c40f', NAVY = '#003366';

describe('brandColors maths', () => {
  it('parses #rgb and #rrggbb, rejects everything else', () => {
    expect(parseHex('#fc0')).toEqual([255, 204, 0]);
    expect(parseHex('#F1C40F')).toEqual([241, 196, 15]);
    for (const bad of ['', 'red', '#12', '#12345g', null, undefined]) expect(parseHex(bad)).toBeNull();
  });
  it('inkOn picks the readable ink', () => {
    expect(inkOn(GOLD)).toBe('#0b1220');
    expect(inkOn(NAVY)).toBe('#ffffff');
  });
  it('ensureContrast leaves a passing colour alone and keeps the hue otherwise', () => {
    expect(ensureContrast('#c2410c', ['#ffffff'])).toBe('#c2410c');
    const fixed = ensureContrast(GOLD, ['#ffffff']);
    expect(fixed).not.toBe(GOLD);
    expect(contrast(fixed, '#ffffff')).toBeGreaterThanOrEqual(4.5);
  });
});

describe('deriveBrandVars: every brand is readable in both templates and themes', () => {
  const brands = [[NAVY, GOLD], ['#ffffff', '#ffffff'], ['#000000', '#000000'], ['#e11d48', '#fde047'], ['#7c3aed', '#0b2545'], ['#fc0', '#fc0']];
  for (const template of ['default', 'blueprint']) for (const theme of ['light', 'dark']) {
    it.each(brands)(`${template}/${theme}: primary %s accent %s`, (primary, accent) => {
      const v = deriveBrandVars({ primary, accent, template, theme });
      // ink on the accent that the template draws with
      expect(contrast(v['--bp-ac'], v['--bp-ai'])).toBeGreaterThanOrEqual(4.5);
      // ink on both raw fills
      expect(contrast(parseHex(primary) && primary, v['--brand-on-primary'])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(accent, v['--brand-on-accent'])).toBeGreaterThanOrEqual(4.5);
      // text-safe variants against the card surface
      const card = { default: { light: '#ffffff', dark: '#1a2030' }, blueprint: { light: '#ffffff', dark: '#10335f' } }[template][theme];
      expect(contrast(v['--bp-ac'], card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(v['--brand-accent-ui'], card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(v['--brand-primary-ui'], card)).toBeGreaterThanOrEqual(4.5);
    });
  }
  it('uses the primary when no accent is set, and nothing when neither is usable', () => {
    expect(deriveBrandVars({ primary: '#e11d48' })['--bp-ac']).toBeTruthy();
    expect(deriveBrandVars({ primary: 'nonsense', accent: '' })).toEqual({});
  });
  it('stripe separates from the accent fill', () => {
    const v = deriveBrandVars({ primary: GOLD, accent: GOLD });
    expect(contrast(v['--brand-stripe'], GOLD)).toBeGreaterThanOrEqual(1.8);
  });
});

describe('setBrand writes <html> and follows the theme', () => {
  const root = document.documentElement;
  beforeEach(() => { root.removeAttribute('style'); root.removeAttribute('data-theme'); delete root.dataset.template; });

  it('sets raw + derived variables, and clears derived ones for an empty brand', () => {
    setBrand({ primary_color: NAVY, accent_color: GOLD });
    expect(root.style.getPropertyValue('--brand-accent')).toBe(GOLD);
    expect(root.style.getPropertyValue('--brand-on-accent')).toBe('#0b1220');
    expect(root.style.getPropertyValue('--bp-ac')).toMatch(/^#/);
    setBrand({ primary_color: '', accent_color: '' });
    for (const k of ['--brand-accent', '--brand-primary', '--bp-ac', '--bp-ai', '--bp-tint']) expect(root.style.getPropertyValue(k)).toBe('');
  });
  it('recomputes the accent when the theme flips', async () => {
    root.setAttribute('data-theme', 'light');
    setBrand({ primary_color: NAVY, accent_color: GOLD });
    const light = root.style.getPropertyValue('--bp-ac');
    root.setAttribute('data-theme', 'dark');
    await new Promise((r) => setTimeout(r, 0));
    const dark = root.style.getPropertyValue('--bp-ac');
    expect(light).not.toBe(dark);
    expect(contrast(light, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    expect(dark).toBe(GOLD); // already readable on dark cards, so left as the org typed it
  });
});
