import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import TitleBlockHeader from './TitleBlockHeader';
import { Stamp, StatusCell } from './primitives';
import { initials, STATUS_LABELS } from './labels';
import { setChrome, resetChrome, useChrome } from '../../templateChrome';

const base = (over = {}) => ({
  orgName: 'Kyambogo Engineering Society', logoUrl: '', logoNeedsInvert: false, phase: 'voting_open',
  view: 'voter', step: 1, theme: 'light', onToggleTheme: vi.fn(), onVoteNow: vi.fn(), onNavigate: vi.fn(),
  showBackToAdmin: false, onBackToAdmin: vi.fn(), ...over,
});
const ui = (over) => render(<TitleBlockHeader {...base(over)} />);

describe('initials()', () => {
  it.each([
    ['Kyambogo Engineering Society', 'KES'],
    ['Makerere Guild', 'MG'],
    ['  solo ', 'S'],
    ['', 'EP'],
    [undefined, 'EP'],
    ['A B C D E F', 'ABC'],
  ])('%j -> %s', (n, out) => expect(initials(n)).toBe(out));
});

describe('Stamp', () => {
  it('shows the logo image (contained) when a url exists, otherwise initials', () => {
    const { container, rerender } = render(<Stamp name="Makerere Guild" logoUrl="https://x/l.png" />);
    expect(container.querySelector('img')).toHaveAttribute('src', 'https://x/l.png');
    rerender(<Stamp name="Makerere Guild" logoUrl="" />);
    expect(container.querySelector('img')).toBeNull();
    expect(container).toHaveTextContent('MG');
  });
});

describe('StatusCell (E10)', () => {
  it.each([
    ['voting_open', 'Voting Open'], ['apply_open', 'Applications Open'],
    ['voting_soon', 'Not Started'], ['voting_closed', 'Closed'],
  ])('%s -> %s', (state, label) => {
    render(<StatusCell phase={state} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(STATUS_LABELS[state]).toBe(label);
  });
  it('renders nothing for an unknown phase', () => {
    const { container } = render(<StatusCell phase={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('TitleBlockHeader (public variant)', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => document.documentElement.removeAttribute('data-theme'));

  it('keeps the three nav labels and their data-track values', () => {
    ui();
    expect(screen.getByRole('button', { name: 'Vote Now' })).toHaveAttribute('data-track', 'nav-vote');
    expect(screen.getByRole('button', { name: 'Live Results' })).toHaveAttribute('data-track', 'nav-results');
    expect(screen.getByRole('button', { name: 'Apply' })).toHaveAttribute('data-track', 'nav-apply');
  });

  it('brand: title is the org name, subtitle is "Election Portal", full name in title attribute', () => {
    const long = 'The Very Long Name Of A Student Society That Would Break A Header';
    ui({ orgName: long });
    expect(screen.getByText(long)).toHaveAttribute('title', long);
    expect(screen.getByText('Election Portal')).toBeInTheDocument();
  });

  it.each([
    [{ view: 'voter', step: 1 }, 'Vote Now'],
    [{ view: 'results', step: 1 }, 'Live Results'],
    [{ view: 'apply', step: 1 }, 'Apply'],
  ])('active item %j has aria-current="page" (and only it)', (over, label) => {
    ui(over);
    const current = document.querySelectorAll('[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent(label);
  });

  it('no active item deeper in the voter flow (matches the default nav)', () => {
    ui({ view: 'voter', step: 2 });
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(0);
  });

  it('nav buttons call the same handlers', () => {
    const p = base();
    render(<TitleBlockHeader {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Vote Now' }));
    fireEvent.click(screen.getByRole('button', { name: 'Live Results' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(p.onVoteNow).toHaveBeenCalledTimes(1);
    expect(p.onNavigate.mock.calls).toEqual([['results'], ['apply']]);
  });

  it('theme toggle keeps today\'s labels and calls the handler', () => {
    const p = base({ theme: 'light' });
    const { rerender } = render(<TitleBlockHeader {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dark' }));
    expect(p.onToggleTheme).toHaveBeenCalledTimes(1);
    rerender(<TitleBlockHeader {...p} theme="dark" />);
    expect(screen.getByRole('button', { name: 'Light' })).toBeInTheDocument();
  });

  it('Back to Admin only when asked, and calls its handler', () => {
    const p = base({ showBackToAdmin: false });
    const { rerender } = render(<TitleBlockHeader {...p} />);
    expect(screen.queryByRole('button', { name: 'Back to Admin' })).toBeNull();
    rerender(<TitleBlockHeader {...p} showBackToAdmin />);
    fireEvent.click(screen.getByRole('button', { name: 'Back to Admin' }));
    expect(p.onBackToAdmin).toHaveBeenCalledTimes(1);
  });

  it('sheet cell (D5): step n / 3 in the voter flow, hidden on results and apply', () => {
    const { rerender } = render(<TitleBlockHeader {...base({ step: 1.5 })} />);
    expect(screen.getByText('01 / 03')).toBeInTheDocument();
    rerender(<TitleBlockHeader {...base({ step: 2 })} />);
    expect(screen.getByText('02 / 03')).toBeInTheDocument();
    rerender(<TitleBlockHeader {...base({ view: 'results' })} />);
    expect(screen.queryByText(/ \/ 03/)).toBeNull();
    rerender(<TitleBlockHeader {...base({ view: 'apply' })} />);
    expect(screen.queryByText(/ \/ 03/)).toBeNull();
  });

  it('status cell shows the phase label', () => {
    ui({ phase: 'apply_open' });
    expect(screen.getByText('Applications Open')).toBeInTheDocument();
  });
});

describe('TitleBlockHeader (console variant, BP-T7a)', () => {
  beforeEach(() => resetChrome());
  afterEach(() => resetChrome());
  const con = (over = {}) => base({ view: 'superadmin', step: 1, role: 'Super Admin', ...over });

  it('shows the role as the brand subtitle instead of "Election Portal"', () => {
    render(<TitleBlockHeader {...con()} />);
    expect(screen.getByText('Super Admin')).toBeInTheDocument();
    expect(screen.queryByText('Election Portal')).toBeNull();
  });

  it('public views are unchanged: no role -> "Election Portal", no crumb', () => {
    const { container } = ui({});
    expect(screen.getByText('Election Portal')).toBeInTheDocument();
    expect(container.querySelector('.bp-crumb')).toBeNull();
  });

  it('crumb reads "group / tab" from the chrome store and follows it', () => {
    const { container } = render(<TitleBlockHeader {...con()} />);
    expect(container.querySelector('.bp-crumb')).toBeNull();      // nothing published yet
    act(() => setChrome({ group: 'People & Roles', tab: 'Voters', tabIndex: 3, tabCount: 17 }));
    const crumb = container.querySelector('.bp-crumb');
    expect(crumb).toHaveTextContent('People & Roles / Voters');
    act(() => setChrome({ tab: 'IT Admins', tabIndex: 4 }));
    expect(container.querySelector('.bp-crumb')).toHaveTextContent('People & Roles / IT Admins');
  });

  it('sheet cell (D5) is "active tab / tab count" in consoles', () => {
    render(<TitleBlockHeader {...con()} />);
    expect(screen.queryByText(/ \/ \d\d/)).toBeNull();
    act(() => setChrome({ group: 'Platform', tab: 'Site Usage', tabIndex: 3, tabCount: 18 }));
    expect(screen.getByText('03 / 18')).toBeInTheDocument();
  });

  it('publishes the role label for flat dashboards and clears it on unmount', () => {
    const { result } = renderHook(() => useChrome());
    const { unmount } = render(<TitleBlockHeader {...con({ role: 'IT Admin' })} />);
    expect(result.current.role).toBe('IT Admin');
    unmount();
    expect(result.current.role).toBe('');
  });

  it('keeps the public nav (admins reach Results / Apply from here today), theme toggle and status cell', () => {
    const p = con({ phase: 'voting_closed' });
    render(<TitleBlockHeader {...p} />);
    for (const n of ['Vote Now', 'Live Results', 'Apply']) expect(screen.getByRole('button', { name: n })).toBeInTheDocument();
    expect(screen.getByText('Closed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Dark' }));
    expect(p.onToggleTheme).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Live Results' }));
    expect(p.onNavigate).toHaveBeenCalledWith('results');
  });

  it('no nav item is "current" on a dashboard', () => {
    const { container } = render(<TitleBlockHeader {...con()} />);
    expect(container.querySelector('[aria-current="page"]')).toBeNull();
  });
});
