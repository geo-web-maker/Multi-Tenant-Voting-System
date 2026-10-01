import { describe, it, expect, beforeEach, vi } from 'vitest';

// D1a (guide 5.3): performance.mark('usable') when the voter login form is interactive; sent as usable_ms.
async function fresh() {
  vi.resetModules();
  return import('./analytics');
}

describe('usable mark', () => {
  beforeEach(() => {
    sessionStorage.clear();
    document.body.innerHTML = '';
    performance.clearMarks?.('usable');
  });

  it('markUsable records a single "usable" mark with a value >= 0', async () => {
    const { markUsable, usableMs } = await fresh();
    expect(usableMs()).toBe(0);
    markUsable();
    markUsable(); // idempotent: first interactive moment wins
    expect(performance.getEntriesByName('usable')).toHaveLength(1);
    expect(usableMs()).toBeGreaterThanOrEqual(0);
    expect(Number.isInteger(usableMs())).toBe(true);
  });

  it('marks when the login input is already on the page at init', async () => {
    document.body.innerHTML = '<input name="voter-reg-no" />';
    const { initAnalytics } = await fresh();
    initAnalytics();
    expect(performance.getEntriesByName('usable')).toHaveLength(1);
  });

  it('marks once the login input appears after init (React renders after boot)', async () => {
    const { initAnalytics } = await fresh();
    initAnalytics();
    expect(performance.getEntriesByName('usable')).toHaveLength(0);
    document.body.appendChild(Object.assign(document.createElement('input'), { name: 'voter-reg-no' }));
    await new Promise((r) => setTimeout(r, 0)); // MutationObserver callbacks are microtasks
    expect(performance.getEntriesByName('usable')).toHaveLength(1);
  });

  it('does not mark for other inputs (admin login, apply form)', async () => {
    const { initAnalytics } = await fresh();
    initAnalytics();
    document.body.appendChild(Object.assign(document.createElement('input'), { name: 'email' }));
    await new Promise((r) => setTimeout(r, 0));
    expect(performance.getEntriesByName('usable')).toHaveLength(0);
  });
});
