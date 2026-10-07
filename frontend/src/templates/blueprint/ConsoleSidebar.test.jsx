import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import ConsoleSidebar from './ConsoleSidebar';
import TabBar from '../../components/TabBar.jsx';
import { ROLE_LABELS, textOf } from './labels';
import { setChrome, resetChrome, useChrome } from '../../templateChrome';
import { useBlueprint, useDefault, restoreTemplate } from '../../test/template';

// jsdom has no ResizeObserver / matchMedia; the DEFAULT TabBar reads both.
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };
window.matchMedia = window.matchMedia || ((q) => ({
  matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {},
  addListener: () => {}, removeListener: () => {},
}));

// Mirrors the shape of tabGroups in SuperAdminDashboard / CommissionDashboard: labels are JSX fragments.
const groups = () => [
  { label: 'Election Setup', icon: 'vote', tabs: [
    { id: 'candidates', label: <>Candidates</> },
    { id: 'applications', label: <>Applications</>, count: 4 },
  ] },
  { label: 'People & Roles', icon: 'users', tabs: [
    { id: 'voters', label: <>Voters</> },
    { id: 'it_admins', label: <>IT Admins</>, count: 0 },
  ] },
  { label: 'Security', icon: 'shield', tabs: [
    { id: 'security', label: <>Security &amp; SMS</> },
  ] },
];
const flat = () => [
  { id: 'overview', label: 'Overview' },
  { id: 'voters', label: 'Voters', count: 12 },
  { id: 'edit', label: 'Edit Student' },
];

beforeEach(() => { sessionStorage.clear(); resetChrome(); });
afterEach(async () => { resetChrome(); await restoreTemplate(); });

describe('textOf()', () => {
  it.each([
    ['Plain', 'Plain'],
    [<>Fragment</>, 'Fragment'],
    [<>Security &amp; SMS</>, 'Security & SMS'],
    [<><b>Bold</b> and text</>, 'Bold and text'],
    [['a', 1, null, false, <i key="x">z</i>], 'a1z'],
    [null, ''],
    [undefined, ''],
  ])('%#', (node, out) => expect(textOf(node)).toBe(out));
});

describe('ROLE_LABELS', () => {
  it('maps every console view to its display name', () => {
    expect(ROLE_LABELS).toEqual({
      superadmin: 'Super Admin', commission: 'Commission', it_admin: 'IT Admin',
      financial_controller: 'Financial Controller', overseer: 'Overseer', vetting: 'Vetting Panel',
    });
  });
});

describe('ConsoleSidebar (grouped)', () => {
  it('renders every group and tab from the real arrays, in order', () => {
    render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    const nav = screen.getByRole('navigation', { name: 'Sections' });
    expect(nav).toBeInTheDocument();
    expect(screen.getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual(['Election Setup', 'People & Roles', 'Security']);
    const labels = screen.getAllByRole('button').map((b) => b.textContent);
    expect(labels).toEqual(['Candidates', 'Applications4', 'Voters', 'IT Admins0', 'Security & SMS']);
  });

  it('clicking a tab calls onChange(id)', () => {
    const onChange = vi.fn();
    render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /^Candidates/ }));
    expect(onChange).toHaveBeenCalledWith('candidates');
  });

  it('aria-current="page" follows activeTab and is on exactly one button', () => {
    const { rerender } = render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Voters' })).toHaveAttribute('aria-current', 'page');
    rerender(<ConsoleSidebar groups={groups()} activeTab="security" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Security & SMS' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: 'Voters' })).not.toHaveAttribute('aria-current');
  });

  it('shows counts (including 0) and keeps the data-track labels of the default bar', () => {
    render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: /^Applications/ })).toHaveTextContent('4');
    expect(screen.getByRole('button', { name: /^IT Admins/ })).toHaveTextContent('0');
    expect(screen.getByRole('button', { name: 'Voters' })).toHaveAttribute('data-track', 'tab-voters');
    expect(screen.getByRole('button', { name: /^IT Admins/ })).toHaveAttribute('data-track', 'tab-it_admins');
  });

  it('publishes the crumb to the chrome store: group text, tab text, 1-based index across groups, total', () => {
    const store = renderHook(() => useChrome());
    const { rerender } = render(<ConsoleSidebar groups={groups()} activeTab="it_admins" onChange={() => {}} />);
    expect(store.result.current).toMatchObject({ group: 'People & Roles', tab: 'IT Admins', tabIndex: 4, tabCount: 5 });
    rerender(<ConsoleSidebar groups={groups()} activeTab="security" onChange={() => {}} />);
    expect(store.result.current).toMatchObject({ group: 'Security', tab: 'Security & SMS', tabIndex: 5, tabCount: 5 });
  });

  it('adds a Session -> Log out item only when a logout handler was published, and it calls that handler', () => {
    const { rerender } = render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull();
    const onLogout = vi.fn();
    act(() => setChrome({ onLogout }));
    rerender(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    expect(screen.getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toContain('Session');
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it('the Log out item is never a tab: it has no tab data-track label and no aria-current', () => {
    act(() => setChrome({ onLogout: () => {} }));
    render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    const out = screen.getByRole('button', { name: 'Log out' });
    expect(out.getAttribute('data-track') || '').not.toMatch(/^tab-/);
    expect(out).not.toHaveAttribute('aria-current');
  });

  it('on unmount clears the crumb but leaves the logout handler alone (the toolbar owns it)', async () => {
    const onLogout = vi.fn();
    act(() => setChrome({ onLogout }));
    const { unmount } = render(<ConsoleSidebar groups={groups()} activeTab="voters" onChange={() => {}} />);
    unmount();
    const { result } = renderHook(() => useChrome());
    expect(result.current).toMatchObject({ group: '', tab: '', tabIndex: 0, tabCount: 0 });
    expect(result.current.onLogout).toBe(onLogout);
  });

  it('records analytics page views like the default bar (role:tab from session storage)', async () => {
    const analytics = await import('../../analytics');
    const spy = vi.spyOn(analytics, 'trackPage').mockImplementation(() => {});
    sessionStorage.setItem('admin_role', 'superadmin');
    render(<ConsoleSidebar groups={groups()} activeTab="it_admins" onChange={() => {}} />);
    expect(spy).toHaveBeenCalledWith('superadmin:it_admins');
    spy.mockRestore();
  });
});

describe('ConsoleSidebar (flat)', () => {
  it('renders one pill row: no group labels, no Session item, same buttons and handlers', () => {
    const onChange = vi.fn();
    act(() => setChrome({ onLogout: () => {} }));
    render(<ConsoleSidebar tabs={flat()} activeTab="voters" onChange={onChange} />);
    expect(screen.queryAllByRole('group')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull();
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Overview', 'Voters12', 'Edit Student']);
    fireEvent.click(screen.getByRole('button', { name: 'Edit Student' }));
    expect(onChange).toHaveBeenCalledWith('edit');
    expect(screen.getByRole('navigation', { name: 'Sections' }).className).toMatch(/bp-flat/);
  });

  it('uses the role label (from the chrome store) as the crumb group', async () => {
    act(() => setChrome({ role: 'IT Admin' }));
    render(<ConsoleSidebar tabs={flat()} activeTab="edit" onChange={() => {}} />);
    const { result } = renderHook(() => useChrome());
    expect(result.current).toMatchObject({ group: 'IT Admin', tab: 'Edit Student', tabIndex: 3, tabCount: 3 });
  });

  it('copes with an empty tab list and an unknown active tab', () => {
    const { container } = render(<ConsoleSidebar tabs={[]} activeTab="nope" onChange={() => {}} />);
    expect(container.querySelectorAll('button')).toHaveLength(0);
  });
});

describe('TabBar seam (R12 wrapper)', () => {
  it('default: today\'s rail, no blueprint markup', () => {
    useDefault();
    const { container } = render(<TabBar groups={groups()} activeTab="voters" onChange={() => {}} />);
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('.tabbar-rail')).not.toBeNull();
  });

  it('blueprint: the same props render the console sidebar instead', async () => {
    await useBlueprint();
    const onChange = vi.fn();
    const { container } = render(<TabBar groups={groups()} activeTab="voters" onChange={onChange} />);
    expect(container.querySelector('.tabbar-rail')).toBeNull();
    expect(container.querySelector('nav.bp-side')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /^Candidates/ }));
    expect(onChange).toHaveBeenCalledWith('candidates');
  });

  it('blueprint, flat: pill row with every tab, still reachable by role and name', async () => {
    await useBlueprint();
    render(<TabBar tabs={flat()} activeTab="overview" onChange={() => {}} />);
    for (const name of ['Overview', /^Voters/, 'Edit Student']) expect(screen.getByRole('button', { name })).toBeInTheDocument();
  });
});
