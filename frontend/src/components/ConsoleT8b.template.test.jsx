// BP-T8b: Commission + Overseer consoles, AlertPanel, TurnoutBreakdown. Default DOM must be untouched; Blueprint must keep every value.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  getErrorMessage: (_e, d) => d,
  ADMIN_TOKEN_KEY: 'admin_token',
}));
// Stable function identities (the dashboards put these in useCallback deps).
const { toast, confirm, prompt } = vi.hoisted(() => ({ toast: () => {}, confirm: () => Promise.resolve(false), prompt: () => Promise.resolve(null) }));
vi.mock('./UIFeedback', () => ({
  useToast: () => toast, useConfirm: () => confirm, usePrompt: () => prompt,
  ScrollList: ({ children }) => <div>{children}</div>,
}));
vi.mock('./SharedAdminPanels', () => ({
  SHARED_TAB_DEFS: [{ id: 'shared_timeline', label: 'Timeline' }],
  SharedTabPanels: () => null, RosterStats: () => null, RecentActivity: () => null, OfficialCertificationBlock: () => null,
}));
vi.mock('./ContactChangesQueue', () => ({ default: () => null }));
vi.mock('./ResetOtpLimitsPanel', () => ({ default: () => null }));

import CommissionDashboard from './CommissionDashboard';
import OverseerDashboard from './OverseerDashboard';
import AlertPanel from './AlertPanel';
import { AdminTurnoutBreakdown, PublicTurnoutBreakdown } from './TurnoutBreakdown';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };
window.matchMedia = window.matchMedia || ((q) => ({
  matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
}));

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); };
const hasBp = (c) => c.querySelector('[class*="bp-"]');

const RESULTS = {
  generated_at: '2026-10-06T10:00:00Z',
  voter_turnout: { voted_count: 3, total_voters: 10, turnout_pct: 30 },
  positions: [{
    position: 'President', total_votes: 3,
    candidates: [
      { id: 'c1', name: 'Amina Okello', votes: 2, pct_of_position: 66.7 },
      { id: 'c2', name: 'Ben Kato', votes: 1, pct_of_position: 33.3 },
    ],
  }],
};
const APPS = [
  { id: 'a1', full_name: 'Amina Okello', status: 'approved', position_title: 'President', student_id: '22/U/001' },
  { id: 'a2', full_name: 'Ben Kato', status: 'denied', position_title: 'Treasurer', student_id: '22/U/002' },
  { id: 'a3', full_name: 'Cara Mugisha', status: 'removed', position_title: 'Secretary', student_id: '22/U/003' },
];
const OVERSEER = {
  election_status: { is_open: true, is_certified: true },
  voter_turnout: { voted_count: 3, total_voters: 10, turnout_pct: 30 },
  total_commissioners: 2, panel_count: 3,
  applications: [{ id: 'o1', full_name: 'Amina Okello', status: 'force_approved', position_id: 'President' }],
  student_changes: [
    { id: 's1', change_type: 'add', full_name: 'Dan Opio', student_id: '22/U/004', status: 'pending', requested_by: 'it1' },
    { id: 's2', change_type: 'remove', full_name: 'Eve Nambi', student_id: '22/U/005', status: 'cancelled', requested_by: 'it1' },
  ],
};

let routes;
beforeEach(() => {
  routes = {
    '/admin/vetting-outcomes': APPS, '/admin/commissioners': [], '/admin/student-changes': [],
    '/commission/results/detailed': RESULTS, '/admin/panel-link': null, '/overseer/dashboard': OVERSEER,
  };
  mockGet.mockReset();
  mockGet.mockImplementation((url) => (url in routes ? Promise.resolve({ data: routes[url] }) : Promise.resolve({ data: [] })));
  sessionStorage.clear(); localStorage.clear();
  sessionStorage.setItem('commissioner_id', 'c/001');
  sessionStorage.setItem('overseer_id', 'ov/001');
});
afterEach(async () => { await restoreTemplate(); });

describe('Commission: outcomes', () => {
  it('default: plain badges, no blueprint markup', async () => {
    useDefault();
    const { container } = render(<CommissionDashboard onLogout={() => {}} />);
    await flush();
    expect(screen.getByText('APPROVED')).toBeTruthy();
    expect(hasBp(container)).toBeNull();
    expect(document.documentElement.dataset.template).toBeUndefined();
  });

  it('blueprint: every status is one pill with the shared tone, same text', async () => {
    await useBlueprint();
    const { container } = render(<CommissionDashboard onLogout={() => {}} />);
    await flush();
    expect(screen.getByText('APPROVED').className).toBe('bp-pill');
    expect(screen.getByText('DENIED').className).toBe('bp-pill bp-neg');
    expect(screen.getByText('REMOVED').className).toBe('bp-pill bp-mute');
    expect(container.querySelectorAll('.bp-pill')).toHaveLength(3);
  });
});

describe('Commission: live results', () => {
  const open = async () => { await flush(); fireEvent.click(screen.getByRole('button', { name: /Live Results/ })); await flush(); };

  it('default: original rows with the inline bar, no meter', async () => {
    useDefault();
    const { container } = render(<CommissionDashboard onLogout={() => {}} />);
    await open();
    expect(screen.getByText('Amina Okello')).toBeTruthy();
    expect(container.querySelector('.bp-meter')).toBeNull();
    expect(hasBp(container)).toBeNull();
    expect(container.querySelectorAll('div[style*="width: 66.7%"]')).toHaveLength(1);
  });

  it('blueprint: one meter per candidate, bar width = percentage, leader gets the accent, text unchanged', async () => {
    await useBlueprint();
    const { container } = render(<CommissionDashboard onLogout={() => {}} />);
    await open();
    const meters = container.querySelectorAll('.bp-meter');
    expect(meters).toHaveLength(2);
    expect(meters[0].classList.contains('bp-warn')).toBe(true);   // accent = leader
    expect(meters[1].classList.contains('bp-warn')).toBe(false);
    expect(meters[0].querySelector('.bp-bar i').style.width).toBe('66.7%');
    expect(meters[1].querySelector('.bp-bar i').style.width).toBe('33.3%');
    expect(meters[0].textContent).toContain('Amina Okello');
    expect(meters[0].textContent).toContain('2 (66.7%)');
    expect(screen.getByText(/3 \/ 10/)).toBeTruthy();
    expect(screen.getByText(/\+1 lead/)).toBeTruthy();
  });
});

describe('Overseer', () => {
  const labels = ['Election Status', 'Voter Turnout', 'Commissioners', 'Vetting Panel'];

  it('default: original summary cards, no blueprint markup', async () => {
    useDefault();
    const { container } = render(<OverseerDashboard onLogout={() => {}} />);
    await flush();
    for (const l of labels) expect(screen.getByText(l)).toBeTruthy();
    expect(hasBp(container)).toBeNull();
  });

  it('blueprint: four stat cards with the same labels and values', async () => {
    await useBlueprint();
    const { container } = render(<OverseerDashboard onLogout={() => {}} />);
    await flush();
    const cards = [...container.querySelectorAll('.bp-stat')];
    expect(cards.map((c) => c.firstChild.textContent)).toEqual(labels);
    expect(cards[0].textContent).toMatch(/Open · Certified/);
    expect(cards[1].textContent).toContain('3 / 10 (30%)');
    expect(cards[2].textContent).toContain('2');
    expect(cards[3].textContent).toContain('3');
  });

  it('blueprint: no Vetting Panel card when the count is absent', async () => {
    await useBlueprint();
    routes['/overseer/dashboard'] = { ...OVERSEER, panel_count: null };
    const { container } = render(<OverseerDashboard onLogout={() => {}} />);
    await flush();
    expect(container.querySelectorAll('.bp-stat')).toHaveLength(3);
    expect(screen.queryByText('Vetting Panel')).toBeNull();
  });

  it('blueprint: status and change-type pills', async () => {
    await useBlueprint();
    const { container } = render(<OverseerDashboard onLogout={() => {}} />);
    await flush();
    expect(screen.getByText('FORCE_APPROVED').className).toBe('bp-pill');
    fireEvent.click(screen.getByRole('button', { name: /Student Changes/ }));
    await flush();
    expect(screen.getByText('PENDING').className).toBe('bp-pill bp-warn');
    expect(screen.getByText('CANCELLED').className).toBe('bp-pill bp-mute');
    expect(screen.getByText(/ADD/).className).toBe('bp-pill');
    expect(screen.getByText(/REMOVE/).className).toBe('bp-pill bp-mute');
    expect(container.querySelectorAll('.bp-pill')).toHaveLength(4);
  });

  it('blueprint: candidate results are meters; default has none', async () => {
    await useBlueprint();
    const { container } = render(<OverseerDashboard onLogout={() => {}} />);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: /Candidate Results/ }));
    await flush();
    const meters = container.querySelectorAll('.bp-meter');
    expect(meters).toHaveLength(2);
    expect(meters[0].querySelector('.bp-bar i').style.width).toBe('66.7%');
  });
});

describe('AlertPanel', () => {
  const crit = [{ kind: '5xx', level: 'critical', metric: 'Server 5xx responses per minute', value: 12, threshold: 10 }];
  const warn = [{ kind: '429', level: 'warning', metric: 'HTTP 429 responses per minute', value: 31, threshold: 30 }];

  it('default: unchanged markup (dot + strong, plain list)', () => {
    useDefault();
    const { container } = render(<AlertPanel alerts={crit} />);
    expect(hasBp(container)).toBeNull();
    expect(container.querySelector('.card-pad')).toBeTruthy();
    expect(container.querySelector('li').className).toBe('');
  });

  it.each([
    [[], 'Healthy', 'bp-pill'],
    [warn, 'Warning', 'bp-pill bp-warn'],
    [crit, 'Critical', 'bp-pill bp-neg'],
  ])('blueprint state pill: %j -> %s', async (alerts, label, cls) => {
    await useBlueprint();
    const { container } = render(<AlertPanel alerts={alerts} />);
    expect(container.querySelector('.bp-pill').textContent).toBe(label);
    expect(container.querySelector('.bp-pill').className).toBe(cls);
    expect(container.firstChild.className).toBe('bp-card');
  });

  it('blueprint: items keep their text; critical = alert box, warning = warn banner', async () => {
    await useBlueprint();
    const { container, rerender } = render(<AlertPanel alerts={crit} />);
    expect(container.querySelector('li').className).toBe('bp-alt');
    expect(screen.getByText(/Server 5xx responses per minute is 12 \(threshold 10\)/)).toBeTruthy();
    rerender(<AlertPanel alerts={warn} />);
    expect(container.querySelector('li').className).toBe('bp-ban bp-warn');
    expect(screen.getByText(/HTTP 429 responses per minute is 31 \(threshold 30\)/)).toBeTruthy();
  });

  it('renders nothing without an alerts array in both templates', async () => {
    await useBlueprint();
    expect(render(<AlertPanel alerts={undefined} />).container.innerHTML).toBe('');
  });
});

describe('TurnoutBreakdown', () => {
  const FIELDS = [{ key: 'gender', label: 'Gender', public: true, groups: [
    { label: 'Female', registered: 40, voted: 30, pct: 75 },
    { label: 'Male', registered: 60, voted: 30, pct: 130 },   // out-of-range value must clamp to 100
  ] }];

  beforeEach(() => {
    routes['/admin/analytics/turnout-breakdown'] = { fields: FIELDS };
    routes['/election-results/turnout-breakdown'] = { available: true, min_group_size: 5, fields: FIELDS };
  });

  it('default: inline bars, no blueprint markup', async () => {
    useDefault();
    const { container } = render(<AdminTurnoutBreakdown />);
    await flush();
    expect(screen.getByText('Turnout by group')).toBeTruthy();
    expect(screen.getByText('public after close')).toBeTruthy();
    expect(hasBp(container)).toBeNull();
    expect(container.querySelectorAll('div[style*="width: 100%"]')).toHaveLength(1);
  });

  it('blueprint (admin): card, meters with clamped widths, muted pill, same text', async () => {
    await useBlueprint();
    const { container } = render(<AdminTurnoutBreakdown />);
    await flush();
    expect(container.firstChild.className).toBe('bp-card');
    const meters = container.querySelectorAll('.bp-meter');
    expect([...meters].map((m) => m.querySelector('.bp-bar i').style.width)).toEqual(['75%', '100%']);
    expect(container.querySelector('.bp-pill.bp-mute').textContent).toBe('public after close');
    expect(screen.getByText('Female')).toBeTruthy();
    expect(meters[0].textContent).toContain('30 / 40 (75%)');
  });

  it('blueprint (public): card and meters; footnote text unchanged', async () => {
    await useBlueprint();
    const { container } = render(<PublicTurnoutBreakdown />);
    await flush();
    expect(container.firstChild.className).toBe('bp-card');
    expect(container.querySelectorAll('.bp-meter')).toHaveLength(2);
    expect(screen.getByText(/Turnout only, not how anyone voted/)).toBeTruthy();
  });
});
