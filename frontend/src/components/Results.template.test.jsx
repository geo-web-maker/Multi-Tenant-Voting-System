import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a) } }));
vi.mock('./TurnoutBreakdown', () => ({ PublicTurnoutBreakdown: () => <div>turnout-breakdown</div> }));
// Deterministic stand-in so the whole `.print-only` wrapper (R8) can be compared byte for byte.
vi.mock('./FinalReport', () => ({ default: (p) => <section data-report>{`${p.orgName}|${p.isCertified}|${p.isElectionOpen}|${p.totalVotes}`}</section> }));

import Results from './Results';

afterEach(restoreTemplate);

const R = (results, extra) => ({ voter_turnout: 10, results_released: true, results, ...extra });
const pos = (id, name, position, votes) => ({ id, name, position, votes });
const ROWS = [pos('1', 'Ann', 'Chair', 7), pos('2', 'Bob', 'Chair', 3), pos('3', 'Cy', 'Treasurer', 120)];
const TIE = [pos('1', 'Ann', 'Chair', 5), pos('2', 'Bob', 'Chair', 5)];
const CASES = {
  live: [{ is_open: true, voting_phase: 'open' }, R(ROWS)],
  provisional: [{ is_open: false, voting_phase: 'closed' }, R(ROWS)],
  certified: [{ is_open: false, voting_phase: 'closed', is_certified: true }, R(ROWS)],
  tie: [{ is_open: false, voting_phase: 'closed' }, R(TIE)],
  livetie: [{ is_open: true, voting_phase: 'open' }, R(TIE)],
  notstarted: [{ is_open: false, voting_phase: 'not_started', voting_opens_at: '2030-01-12T05:00:00' }, { voter_turnout: 0, results: [], results_released: true }],
  embargoed: [{ is_open: true, voting_phase: 'open' }, { voter_turnout: 9, results: [], results_released: false }],
  novotes: [{ is_open: true, voting_phase: 'open' }, { voter_turnout: 0, results: [], results_released: true }],
};

async function show(key) {
  const [st, rs] = CASES[key];
  mockGet.mockReset();
  mockGet.mockImplementation((u) => Promise.resolve({ data: u === '/election-status' ? st : u === '/election-results' ? rs : {} }));
  const out = render(<Results />);
  await waitFor(() => { if (screen.queryByText(/Loading Live Tally/)) throw new Error('loading'); });
  return out;
}
const mask = (s) => s.replace(/Last update: [^<]*/, 'Last update: T');

describe('Results template seam (BP-T5)', () => {
  it('default render has no bp- class and no data-template', async () => {
    useDefault();
    const { container } = await show('certified');
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
  });

  it.each(Object.keys(CASES))('%s: same visible text under both templates', async (key) => {
    useDefault();
    const a = await show(key);
    const defText = mask(a.container.textContent);
    cleanup();
    await useBlueprint();
    const b = await show(key);
    expect(mask(b.container.textContent)).toBe(defText);
  });

  it('print-only block markup is identical in both templates (R8)', async () => {
    useDefault();
    const a = await show('certified');
    const def = a.container.querySelector('.print-only').innerHTML;
    cleanup();
    await useBlueprint();
    const b = await show('certified');
    expect(def).toContain('data-report');
    expect(b.container.querySelector('.print-only').innerHTML).toBe(def);
  });

  it('blueprint: bar width equals the share of the position total; cand-row hook kept', async () => {
    await useBlueprint();
    const { container } = await show('provisional');
    const rows = [...container.querySelectorAll('.cand-row.bp-meter')];
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.querySelector('.bp-bar i').style.width)).toEqual(['70%', '30%', '100%']);
    expect(rows[0]).toHaveClass('bp-warn');
    expect(rows[1]).not.toHaveClass('bp-warn');
    expect(rows[0].querySelector('.cand-name').textContent).toBe('Ann');
    expect(rows[0].querySelector('.bp-bar')).toHaveAttribute('aria-hidden', 'true');
  });

  it('blueprint: position headings keep the print class', async () => {
    await useBlueprint();
    const { container } = await show('provisional');
    expect([...container.querySelectorAll('.no-print h3.position-header.bp-pos')].map((h) => h.textContent)).toEqual(['Chair', 'Treasurer']);
  });

  it('blueprint: banner is a stat card; pill tone follows live / provisional / certified', async () => {
    await useBlueprint();
    let { container } = await show('live');
    expect(container.querySelector('.bp-stat .bp-big').textContent).toBe('10');
    expect(container.querySelector('.bp-stat .bp-pill')).not.toHaveClass('bp-warn');
    cleanup();
    ({ container } = await show('provisional'));
    expect(container.querySelector('.bp-stat .bp-pill')).toHaveClass('bp-warn');
    expect(container.querySelector('.bp-stat .bp-pill').textContent).toBe('Provisional Standings');
    cleanup();
    ({ container } = await show('certified'));
    expect(container.querySelector('.bp-stat .bp-pill')).not.toHaveClass('bp-warn');
    expect(container.querySelector('.bp-stat .bp-pill').textContent).toMatch(/Official Certified Results/);
  });

  it('blueprint: ELECTED / MANDATE GAINED / TIE / LEADING keep their text, as pills with the right tone', async () => {
    await useBlueprint();
    let { container } = await show('provisional');
    const pill = (txt) => [...container.querySelectorAll('.bp-meter .bp-pill')].find((p) => p.textContent.includes(txt));
    expect(pill('ELECTED')).not.toHaveClass('bp-warn');
    expect(pill('MANDATE GAINED')).toBeTruthy();
    cleanup();
    ({ container } = await show('tie'));
    expect(pill('TIE (RE-RUN)')).toHaveClass('bp-warn');
    cleanup();
    ({ container } = await show('live'));
    expect(pill('LEADING')).toBeTruthy();
    cleanup();
    ({ container } = await show('livetie'));
    expect(pill('DEADLOCK')).toHaveClass('bp-warn');
  });
});
