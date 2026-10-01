import { describe, it, expect } from 'vitest';
import { buildInsights } from './insights';

const full = {
  funnels: {
    voting: {
      steps: [{ key: 'identity_page', value: 200 }],
      identity: { attempts: 150, ok: 120, failed: 30, reasons: [{ label: 'not_on_roll', value: 20 }, { label: 'name_mismatch', value: 10 }] },
    },
    apply: { steps: [{ key: 'form_page', value: 50 }], submit: { ok: 12 } },
  },
  network: [{ label: '4g', value: 60 }, { label: '3g', value: 30 }, { label: 'unknown', value: 10 }],
  network_perf: [{ net: '3g', load_p95: 6000 }, { net: 'unknown', load_p95: 4000 }, { net: '4g', load_p95: 1000 }],
  friction: { dead_by_element: [{ page: 'voter_identity', label: 'help-fab', value: 17 }] },
};

describe('D2c: buildInsights', () => {
  it('produces one sentence per insight from a full fixture', () => {
    const s = buildInsights(full);
    expect(s).toHaveLength(5);
    expect(s[0]).toBe('The application form was opened in 50 sessions, 25% of the 200 sessions that opened the voter login.');
    expect(s[1]).toBe('30 of 150 identity checks failed (20%). Most common reason: not on roll.');
    expect(s[2]).toBe('40% of sessions are on 3G or an unknown network; their slowest loads take up to 6.0 s.');
    expect(s[3]).toBe('Most dead clicks (taps that did nothing): "help-fab" on the voter identity page, 17 times.');
    expect(s[4]).toBe('50 sessions opened the application form and 12 applications were submitted.');
  });

  it.each([undefined, null, {}, { funnels: {}, network: [], friction: {} }])('gives no sentences for empty input %j', (x) => {
    expect(buildInsights(x)).toEqual([]);
  });

  it('never prints NaN, Infinity or undefined, even for all-zero data', () => {
    const zeros = {
      funnels: { voting: { steps: [{ key: 'identity_page', value: 0 }], identity: { attempts: 0, failed: 0, reasons: [] } },
                 apply: { steps: [{ key: 'form_page', value: 0 }], submit: { ok: 0 } } },
      network: [{ label: '3g', value: 0 }], network_perf: [], friction: { dead_by_element: [{ page: 'x', label: 'y', value: 0 }] },
    };
    const text = JSON.stringify(buildInsights(zeros));
    expect(text).not.toMatch(/NaN|Infinity|undefined|null/);
    expect(buildInsights(zeros)).toEqual([]);
  });

  it('tolerates junk field types without throwing', () => {
    const junk = { funnels: { voting: { steps: 'x', identity: { attempts: 'a', failed: NaN } }, apply: { steps: [null], submit: {} } },
                   network: [null, { label: '3g', value: 'z' }], network_perf: [null], friction: { dead_by_element: [null] } };
    expect(() => buildInsights(junk)).not.toThrow();
    expect(JSON.stringify(buildInsights(junk))).not.toMatch(/NaN|Infinity|undefined/);
  });

  it('skips the reason clause when there is no reason, and the p95 clause when there is no timing', () => {
    const s = buildInsights({ funnels: { voting: { identity: { attempts: 10, failed: 2, reasons: [] } } },
                              network: [{ label: 'unknown', value: 5 }] });
    expect(s).toEqual(['2 of 10 identity checks failed (20%).', '100% of sessions are on 3G or an unknown network.']);
  });

  it('only uses counts and labels: ids and names in the fixture never appear', () => {
    const noisy = { ...full, students: [{ student_id: 'KYU-2231', name: 'Jane Doe' }], meta: { user: 'jane@example.org' },
                    funnels: { ...full.funnels, voting: { ...full.funnels.voting, identity: { ...full.funnels.voting.identity, sample_id: 'KYU-2231' } } } };
    const text = buildInsights(noisy).join(' ');
    expect(text).not.toMatch(/KYU-2231|Jane|jane@/);
  });
});
