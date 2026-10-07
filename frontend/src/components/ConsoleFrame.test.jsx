// BP-T7b: ConsoleFrame (flat-dashboard frame).
//  - Default: the frame is a passthrough fragment, so the four flat dashboards render byte-identical DOM to what
//    they rendered before the seam existed. The "before" HTML is committed under __snapshots__/ (captured from the
//    pre-edit code; any DOM drift in the default template fails here).
//  - Blueprint: nav and content become siblings inside `.dash-body` (rail on desktop, pill row on phones).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, act, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  getErrorMessage: (_e, d) => d,
  ADMIN_TOKEN_KEY: 'admin_token',
}));
// Stable function identities: the dashboards put these in useCallback deps, so fresh ones every render would loop.
const { toast, confirm, prompt } = vi.hoisted(() => ({
  toast: () => {}, confirm: () => Promise.resolve(false), prompt: () => Promise.resolve(null),
}));
vi.mock('./UIFeedback', () => ({
  useToast: () => toast,
  useConfirm: () => confirm,
  usePrompt: () => prompt,
  ScrollList: ({ children }) => <div>{children}</div>,
}));
vi.mock('./SharedAdminPanels', () => ({
  SHARED_TAB_DEFS: [{ id: 'shared_timeline', label: 'Timeline' }],
  SharedTabPanels: () => <div data-testid="shared-panels" />,
  RosterStats: () => <div data-testid="roster-stats" />,
  RecentActivity: () => <div data-testid="recent-activity" />,
  OfficialCertificationBlock: () => null,
}));
vi.mock('./ContactChangesQueue', () => ({ default: () => null }));
vi.mock('./ResetOtpLimitsPanel', () => ({ default: () => null }));
vi.mock('./VoterList', () => ({ default: () => null }));
vi.mock('./VoterRegisterExport', () => ({ default: () => null }));
vi.mock('./ITAdminStudentEdit', () => ({ default: () => null }));
vi.mock('../hooks/useRosterStatus', () => ({ default: () => ({ frozen: false }) }));

import ConsoleFrame from './ConsoleFrame';
import ITAdminDashboard from './ITAdminDashboard';
import FinancialControllerDashboard from './FinancialControllerDashboard';
import OverseerDashboard from './OverseerDashboard';
import VettingDashboard from './VettingDashboard';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };
window.matchMedia = window.matchMedia || ((q) => ({
  matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {},
  addListener: () => {}, removeListener: () => {},
}));

const OVERSEER = {
  election_status: { is_open: true, is_certified: false },
  voter_turnout: { voted_count: 3, total_voters: 10, turnout_pct: 30 },
  total_commissioners: 2, panel_count: 3, applications: [], student_changes: [],
};
const ROUTES = {
  '/overseer/dashboard': OVERSEER,
  '/admin/vetting-me': { confidentiality_required: false, confidentiality_accepted: true },
  '/admin/applications': [],
  '/admin/student-changes': [],
};
beforeEach(() => {
  mockGet.mockReset(); mockPost.mockReset();
  mockGet.mockImplementation((url) => Promise.resolve({ data: url in ROUTES ? ROUTES[url] : [] }));
  sessionStorage.clear(); localStorage.clear();
  sessionStorage.setItem('it_admin_id', 'it/001');
  sessionStorage.setItem('overseer_id', 'ov/001');
});
afterEach(async () => { await restoreTemplate(); });

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); };
// The only run-to-run noise is the clock in "Sync: hh:mm:ss".
// S2 swaps (`var(--bp-x, #2ecc71)`) must render as the old literal in the default UI: map each fallback back to the colour
// jsdom serialised before the swap, so the snapshots stay byte-for-byte the pre-seam ones.
const hexToRgb = (h) => {
  const x = h.length === 4 ? [...h.slice(1)].map((c) => c + c).join('') : h.slice(1);
  return `rgb(${parseInt(x.slice(0, 2), 16)}, ${parseInt(x.slice(2, 4), 16)}, ${parseInt(x.slice(4, 6), 16)})`;
};
const norm = (html) => html
  .replace(/Sync: [^<]*/g, 'Sync: <time>')
  .replace(/var\(--bp-[a-z-]+, (#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\)/g, (_m, h) => hexToRgb(h));

const DASHBOARDS = [
  ['it-admin', () => <ITAdminDashboard onLogout={() => {}} />, 'Overview'],
  ['financial', () => <FinancialControllerDashboard onLogout={() => {}} />, 'Voter payments'],
  ['overseer', () => <OverseerDashboard onLogout={() => {}} />, 'Applications'],
  ['vetting', () => <VettingDashboard onLogout={() => {}} />, 'Pending'],
];

describe('ConsoleFrame (unit)', () => {
  it('default: renders nav then children with no wrapper element', () => {
    useDefault();
    const { container } = render(<ConsoleFrame nav={<nav id="n" />}><p id="c" /></ConsoleFrame>);
    expect(container.innerHTML).toBe('<nav id="n"></nav><p id="c"></p>');
  });

  it('default: a null nav renders only the children', () => {
    useDefault();
    const { container } = render(<ConsoleFrame nav={null}><p id="c" /></ConsoleFrame>);
    expect(container.innerHTML).toBe('<p id="c"></p>');
  });

  it('blueprint: nav and content are siblings inside .dash-body', async () => {
    await useBlueprint();
    const { container } = render(<ConsoleFrame nav={<nav id="n" />}><p id="c" /></ConsoleFrame>);
    const body = container.querySelector('.dash-body');
    expect(body).not.toBeNull();
    expect(body.children[0].id).toBe('n');
    expect(body.children[1].classList.contains('dash-main')).toBe(true);
    expect(body.children[1].querySelector('#c')).not.toBeNull();
  });

  it('blueprint: a null nav still renders the content pane', async () => {
    await useBlueprint();
    const { container } = render(<ConsoleFrame nav={null}><p id="c" /></ConsoleFrame>);
    expect(container.querySelectorAll('.dash-body > *')).toHaveLength(1);
    expect(container.querySelector('.dash-main #c')).not.toBeNull();
  });
});

describe.each(DASHBOARDS)('flat dashboard: %s', (name, make, firstTab) => {
  it('default: DOM is byte-identical to the pre-seam snapshot, with no blueprint markup', async ({ expect }) => {
    useDefault();
    const { container } = render(make());
    await waitFor(() => expect(container.textContent).toContain(firstTab));
    await flush();
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('.dash-body')).toBeNull();
    await expect(norm(container.innerHTML)).toMatchFileSnapshot(`./__snapshots__/flat-${name}.default.html`);
  });

  it('blueprint: the tab nav and the tab content sit side by side in .dash-body', async () => {
    await useBlueprint();
    const { container } = render(make());
    await waitFor(() => expect(container.querySelector('.dash-body')).not.toBeNull());
    await flush();
    const body = container.querySelector('.dash-body');
    const nav = body.querySelector(':scope > nav.bp-side');
    expect(nav).not.toBeNull();
    expect(nav.getAttribute('aria-label')).toBe('Sections');
    expect(body.querySelector(':scope > .dash-main')).not.toBeNull();
    // the header toolbar stays above the frame, inside the card
    const toolbar = container.querySelector('.bp-toolbar');
    expect(toolbar).not.toBeNull();
    expect(body.contains(toolbar)).toBe(false);
    // exactly one tab is marked current
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  });
});

// jsdom applies no CSS, so the layout rules are asserted statically (guide section 9, L2).
describe('blueprint.css: flat rail', () => {
  const css = readFileSync(join(import.meta.dirname, '../templates/blueprint/blueprint.css'), 'utf8');
  it('turns the flat pill row into a sticky rail on desktop only', () => {
    const i = css.indexOf('.dash-body > .bp-side.bp-flat {');
    expect(i).toBeGreaterThan(0);
    expect(css.slice(css.lastIndexOf('@media', i), i)).toContain('(min-width: 769px)');
    expect(css.slice(i, css.indexOf('}', i))).toContain('position: sticky');
  });
  it('hides the empty tab-bar spacer inside the frame', () => {
    expect(css).toMatch(/\.bp-frame-main > div:first-child:empty \{ display: none; \}/);
  });
});
