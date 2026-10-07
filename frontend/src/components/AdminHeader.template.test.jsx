import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, renderHook } from '@testing-library/react';
import AdminHeader from './AdminHeader.jsx';
import { getTemplate } from '../template';
import { useChrome, resetChrome } from '../templateChrome';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

beforeEach(() => { resetChrome(); });
afterEach(async () => { resetChrome(); await restoreTemplate(); });

const props = (over = {}) => ({
  title: 'Superadmin Panel', subtitle: 'Results certified', lastSynced: new Date('2026-10-06T10:20:30'),
  onRefresh: vi.fn(), refreshing: false, onLogout: vi.fn(),
  actions: <button type="button">Start Election</button>, ...over,
});

describe('AdminHeader (default)', () => {
  it('renders today\'s markup: no blueprint class, no data-template', () => {
    useDefault();
    const { container } = render(<AdminHeader {...props()} />);
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelector('.admin-header')).not.toBeNull();
  });
});

describe.each([
  ['default', useDefault],
  ['blueprint', useBlueprint],
])('AdminHeader controls (%s)', (_name, enter) => {
  it('keeps title, subtitle, Sync, actions, Refresh and Logout reachable by role/name/text', async () => {
    await enter();
    const p = props();
    render(<AdminHeader {...p} />);
    expect(screen.getByRole('heading', { name: 'Superadmin Panel' })).toBeInTheDocument();
    expect(screen.getByText(/Results certified/)).toBeInTheDocument();
    expect(screen.getByText(/Sync: /)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Election' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(p.onRefresh).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Logout' }));
    expect(p.onLogout).toHaveBeenCalledTimes(1);
  });

  it('Refresh is disabled and reads "Syncing…" while refreshing; absent without onRefresh', async () => {
    await enter();
    const { rerender } = render(<AdminHeader {...props({ refreshing: true })} />);
    expect(screen.getByRole('button', { name: 'Syncing…' })).toBeDisabled();
    rerender(<AdminHeader {...props({ onRefresh: undefined })} />);
    expect(screen.queryByRole('button', { name: /Refresh|Syncing/ })).toBeNull();
  });

  it('Logout is the last control; no separator is printed without a subtitle or sync time', async () => {
    await enter();
    const { container } = render(<AdminHeader {...props({ subtitle: '', lastSynced: null })} />);
    const buttons = [...container.querySelectorAll('button')].map((b) => b.textContent);
    expect(buttons[buttons.length - 1]).toBe('Logout');
    expect(container.textContent).not.toMatch(/·/);
  });
});

describe('AdminHeader toolbar (blueprint)', () => {
  it('renders the toolbar row, still tagged no-print and admin-header', async () => {
    await useBlueprint();
    const { container } = render(<AdminHeader {...props()} />);
    const bar = container.querySelector('.bp-toolbar');
    expect(bar).not.toBeNull();
    expect(bar).toHaveClass('no-print');
    expect(bar).toHaveClass('admin-header');
  });

  it('publishes onLogout to the chrome store and clears it on unmount', async () => {
    await useBlueprint();
    const p = props();
    const { result } = renderHook(() => useChrome());
    const { unmount } = render(<AdminHeader {...p} />);
    expect(result.current.onLogout).toBe(p.onLogout);
    unmount();
    expect(result.current.onLogout).toBeNull();
  });

  it('both Logout controls (toolbar "Logout" and sidebar "Log out") call the same handler', async () => {
    await useBlueprint();
    const { ConsoleSidebar } = getTemplate();   // via the registry: nothing outside templates/blueprint imports it statically
    const p = props();
    render(
      <>
        <AdminHeader {...p} />
        <ConsoleSidebar groups={[{ label: 'Platform', tabs: [{ id: 'x', label: 'X' }] }]} activeTab="x" onChange={() => {}} />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Logout' }));
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    expect(p.onLogout).toHaveBeenCalledTimes(2);
  });

  it('a changed onLogout replaces the published one without leaving a stale handler', async () => {
    await useBlueprint();
    const a = vi.fn(); const b = vi.fn();
    const { result } = renderHook(() => useChrome());
    const { rerender } = render(<AdminHeader {...props({ onLogout: a })} />);
    rerender(<AdminHeader {...props({ onLogout: b })} />);
    expect(result.current.onLogout).toBe(b);
  });
});
