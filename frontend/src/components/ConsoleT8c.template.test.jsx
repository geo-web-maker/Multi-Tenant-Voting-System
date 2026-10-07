// BP-T8c: IT Admin, Finance and Vetting consoles. Default DOM must be untouched; Blueprint must keep every value.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';

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

import ITAdminDashboard from './ITAdminDashboard';
import FinancialControllerDashboard from './FinancialControllerDashboard';
import VettingPanelManager from './VettingPanelManager';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };
window.matchMedia = window.matchMedia || ((q) => ({
  matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
}));

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); };
const hasBp = (c) => c.querySelector('[class*="bp-"]');

const IT_REQUESTS = [
  { _id: 'r1', change_type: 'add', status: 'pending', full_name: 'Dan Opio', student_id: '22/U/004', requested_at: '2026-10-01T10:00:00' },
  { _id: 'r2', change_type: 'remove', status: 'approved', full_name: 'Eve Nambi', student_id: '22/U/005', requested_at: '2026-10-01T11:00:00' },
  { _id: 'r3', change_type: 'add', status: 'force_approved', superadmin_override: true, full_name: 'Fay Auma', student_id: '22/U/006', requested_at: '2026-10-01T12:00:00' },
  { _id: 'r4', change_type: 'add', status: 'denied', full_name: 'Gus Ocen', student_id: '22/U/007', requested_at: '2026-10-01T13:00:00' },
  { _id: 'r5', change_type: 'add', status: 'cancelled', full_name: 'Hal Ssebu', student_id: '22/U/008', requested_at: '2026-10-01T14:00:00' },
];
const FIN_CHANGES = [{ _id: 'f1', change_type: 'add', status: 'pending', full_name: 'Ivy Lamu', student_id: '22/U/009', requested_at: '2026-10-02T09:00:00' }];
const FIN_APPS = [{ _id: 'p1', id: 'p1', full_name: 'Amina Okello', status: 'pending', position_title: 'President', submitted_at: '2026-10-02T09:00:00', finance_cleared: false, finance_rejected: false }];
const PANEL = {
  panel_count: 2, vetting_open: false,
  panel: [
    { panel_member_id: 'm1', full_name: 'Joan Akello', is_member: true, is_chair: true, active: true, student_id: '22/U/101' },
    { panel_member_id: 'm2', full_name: 'Kim Byaruhanga', is_member: false, is_chair: false, active: false },
  ],
};

let routes;
beforeEach(() => {
  routes = {
    '/it-admin/students/my-requests/it%2F001': IT_REQUESTS,
    '/admin/student-changes': FIN_CHANGES, '/admin/applications': FIN_APPS,
    '/superadmin/vetting-panel': PANEL,
  };
  mockGet.mockReset();
  mockGet.mockImplementation((url) => (url in routes ? Promise.resolve({ data: routes[url] }) : Promise.resolve({ data: [] })));
  sessionStorage.clear(); localStorage.clear();
  sessionStorage.setItem('it_admin_id', 'it/001');
  sessionStorage.setItem('financial_controller_id', 'fc/001');
});
afterEach(async () => { await restoreTemplate(); });

const openItRequests = async () => { await flush(); fireEvent.click(screen.getByRole('button', { name: /My Requests/ })); await flush(); };

describe('IT Admin: My Requests', () => {
  it('default: plain badges, no blueprint markup', async () => {
    useDefault();
    const { container } = render(<ITAdminDashboard onLogout={() => {}} />);
    await openItRequests();
    expect(screen.getByText('PENDING')).toBeTruthy();
    expect(hasBp(container)).toBeNull();
    expect(document.documentElement.dataset.template).toBeUndefined();
  });

  it('blueprint: every status is one pill with the shared tone, same text', async () => {
    await useBlueprint();
    const { container } = render(<ITAdminDashboard onLogout={() => {}} />);
    await openItRequests();
    expect(screen.getByText('PENDING').className).toBe('bp-pill bp-warn');
    expect(screen.getByText('APPROVED').className).toBe('bp-pill');
    expect(screen.getByText(/FORCE APPROVED/).className).toBe('bp-pill');
    expect(screen.getByText(/FORCE APPROVED/).textContent).toBe('FORCE APPROVED · SA');
    expect(screen.getByText('DENIED').className).toBe('bp-pill bp-neg');
    expect(screen.getByText('CANCELLED').className).toBe('bp-pill bp-mute');
    expect(container.querySelectorAll('.bp-pill')).toHaveLength(IT_REQUESTS.length);
  });
});

describe('Finance', () => {
  it('default: plain badge, no blueprint markup', async () => {
    useDefault();
    const { container } = render(<FinancialControllerDashboard onLogout={() => {}} />);
    await flush();
    expect(screen.getByText('PENDING')).toBeTruthy();
    expect(container.textContent).toContain('Ivy Lamu');
    expect(hasBp(container)).toBeNull();
  });

  it('blueprint: voter-register request is a warn pill, candidate payment is a warn pill, text unchanged', async () => {
    await useBlueprint();
    const { container } = render(<FinancialControllerDashboard onLogout={() => {}} />);
    await flush();
    const pills = container.querySelectorAll('.bp-pill');
    expect(pills).toHaveLength(1);
    expect(pills[0].className).toBe('bp-pill bp-warn');
    expect(pills[0].textContent).toBe('PENDING');
    fireEvent.click(screen.getByRole('button', { name: /Candidate payments/ }));
    await flush();
    const cand = container.querySelectorAll('.bp-pill');
    expect(cand).toHaveLength(1);
    expect(cand[0].className).toBe('bp-pill bp-warn');
    expect(container.textContent).toContain('Amina Okello');
  });
});

describe('Vetting panel manager', () => {
  it('default: the Inactive tag is the same inline span, no blueprint markup', async () => {
    useDefault();
    const { container } = render(<VettingPanelManager />);
    await flush();
    const tag = screen.getByText('Inactive');
    expect(tag.tagName).toBe('SPAN');
    expect(tag.getAttribute('style')).toContain('--bp-no');   // S2 fallback = the old literal, so the pixels are the same
    expect(hasBp(container)).toBeNull();
  });

  it('blueprint: Inactive becomes a negative pill; Member / Chairperson tags are untouched', async () => {
    await useBlueprint();
    const { container } = render(<VettingPanelManager />);
    await flush();
    expect(screen.getByText('Inactive').className).toBe('bp-pill bp-neg');
    expect(container.querySelectorAll('.bp-pill')).toHaveLength(1);
    expect(screen.getByText('Chairperson')).toBeTruthy();
    expect(screen.getByText('External')).toBeTruthy();
  });
});

describe('S2 literals and IT Edit Student CSS', () => {
  const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
  const files = ['ITAdminDashboard.jsx', 'FinancialControllerDashboard.jsx', 'VettingDashboard.jsx', 'VettingPanelManager.jsx', 'ITAdminDashboard.css'];

  it('no bare #2ecc71 / #e74c3c / #fff / #95a5a6 is left in the T8c files (each is a var(--bp-*, <same literal>) fallback)', () => {
    for (const f of files) {
      const stripped = read(`./${f}`).replace(/var\(--bp-[a-z-]+, #[0-9a-fA-F]{3,8}\)/g, '');
      expect(stripped.match(/#(2ecc71|e74c3c|fff|95a5a6)[0-9a-fA-F]{0,2}\b/g) ?? [], f).toEqual([]);
    }
  });

  it('the IT Edit Student rules sit in the screen block, use tokens only and need no !important', () => {
    const css = read('../templates/blueprint/blueprint.css');
    const start = css.indexOf('/* BP-T8c');
    const end = css.indexOf('/* ===== NEUTRALISERS ===== */');
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    const block = css.slice(start, end);
    expect(block).toContain('.itadmin-card');
    expect(block).toContain('.itadmin-input');
    expect(block).toContain('.itadmin-btn');
    expect(block).not.toContain('!important');
    expect(block).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css.lastIndexOf('@media screen', start)).toBeGreaterThan(-1);
  });
});
