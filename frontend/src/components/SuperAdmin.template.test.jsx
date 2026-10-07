// BP-T8a: Super Admin console content (voter stats, voter list, status pills). Default must be untouched; Blueprint must keep every value.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: vi.fn(), patch: vi.fn() },
  getErrorMessage: (_e, d) => d,
}));

import VoterStats from './VoterStats';
import VoterList from './VoterList';
import { statusTone } from '../templates/blueprint/labels.js';
import { StatusPill } from '../templates/blueprint/primitives.jsx';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

const STATS = {
  total: 200, voted: 50, turnout_pct: 25, not_voted: 150, with_phone: 180, without_phone: 20,
  sms: { sent_total: 7, budget_total: 100, budget_left: 93 },
  sections: [{ key: 'faculty', label: 'Faculty', groups: [
    { label: 'Engineering', registered: 80, voted: 20, pct: 25 },
    { label: 'Arts', registered: 120, voted: 30, pct: 25 },
  ] }],
};
const VOTERS = { results: [
  { student_id: '22/U/001', full_name: 'Amina Okello', phone_numbers: ['0700'], attrs: { faculty: 'Engineering' }, has_voted: true },
  { student_id: '22/U/002', full_name: 'Ben Kato', phone_numbers: [], attrs: {}, has_voted: false, last_status: 'otp_sent' },
], total: 2, page: 1, page_size: 25 };

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockImplementation((url) => Promise.resolve({
    data: url === '/admin/voters/stats' ? STATS : url === '/admin/voter-fields' ? [{ key: 'faculty', label: 'Faculty' }] : VOTERS,
  }));
});
afterEach(async () => { await restoreTemplate(); });

describe('statusTone', () => {
  it.each([
    ['approved', 'ok'], ['APPROVED', 'ok'], ['force_approved', 'ok'], ['voted', 'ok'], ['paid', 'ok'],
    ['pending', 'warn'], ['idle', 'warn'], ['denied', 'neg'], ['rejected', 'neg'], ['force denied', 'neg'],
    ['removed', 'mute'], ['cancelled', 'mute'], ['unpaid', 'mute'], ['something_new', 'mute'], [undefined, 'mute'],
  ])('%s -> %s', (s, tone) => expect(statusTone(s)).toBe(tone));
});

describe('StatusPill', () => {
  it.each([['approved', 'bp-pill'], ['pending', 'bp-pill bp-warn'], ['denied', 'bp-pill bp-neg'], ['removed', 'bp-pill bp-mute']])('%s', (st, c) => {
    const { container } = render(<StatusPill status={st}>X</StatusPill>);
    expect(container.firstChild.className).toBe(c);
  });
  it('tone overrides the status map', () => {
    const { container } = render(<StatusPill status="approved" tone="neg">X</StatusPill>);
    expect(container.firstChild.className).toBe('bp-pill bp-neg');
  });
});

describe('VoterStats', () => {
  const texts = ['Total voters', 'Voted', 'Not yet voted', 'Phone on file', 'No phone', 'SMS sent', 'SMS budget left',
    '50 (25%)', '93 / 100', 'Voters by Faculty', 'Engineering', 'Arts'];

  it('default: no blueprint markup', async () => {
    useDefault();
    const { container } = render(<VoterStats />);
    await screen.findByTestId('voter-stats');
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    for (const t of texts) expect(container.textContent).toContain(t);
  });

  it('blueprint: same labels and values, as stat cards and meters', async () => {
    await useBlueprint();
    const { container } = render(<VoterStats />);
    await screen.findByTestId('voter-stats');
    for (const t of texts) expect(container.textContent).toContain(t);
    expect(container.querySelectorAll('.bp-stat')).toHaveLength(7);
    const meters = container.querySelectorAll('.bp-meter');
    expect(meters).toHaveLength(2);
    expect(meters[0].querySelector('.bp-bar i').style.width).toBe('40%');   // 80 / 200
    expect(meters[1].querySelector('.bp-bar i').style.width).toBe('60%');
    expect(container.querySelector('.bp-big.bp-neg').textContent).toBe('20');   // no-phone count is flagged
  });
});

describe('VoterList', () => {
  const cells = (c) => [...c.querySelectorAll('tbody td')].map((td) => td.textContent);

  it('default: no blueprint markup, no data-l', async () => {
    useDefault();
    const { container } = render(<VoterList showStatus onEdit={() => {}} />);
    await waitFor(() => expect(screen.getByText('Amina Okello')).toBeTruthy());
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('[data-l]')).toBeNull();
  });

  it('blueprint: identical cell text, every td labelled, status as pills', async () => {
    useDefault();
    const d = render(<VoterList showStatus onEdit={() => {}} />);
    await waitFor(() => expect(screen.getByText('Amina Okello')).toBeTruthy());
    const before = cells(d.container);
    d.unmount();

    await useBlueprint();
    const { container } = render(<VoterList showStatus onEdit={() => {}} />);
    await waitFor(() => expect(screen.getByText('Amina Okello')).toBeTruthy());
    expect(cells(container)).toEqual(before);
    expect(container.querySelector('table').classList.contains('bp-rs')).toBe(true);
    const tds = [...container.querySelectorAll('tbody td')];
    expect(tds.every((td) => td.getAttribute('data-l'))).toBe(true);
    expect(tds[0].getAttribute('data-l')).toBe('Name');
    const pills = [...container.querySelectorAll('.bp-pill')];
    expect(pills.map((p) => p.textContent)).toEqual(['VOTED', 'OTP_SENT']);
    expect(pills[0].className).toBe('bp-pill');
    expect(pills[1].className).toBe('bp-pill bp-warn');
  });
});
