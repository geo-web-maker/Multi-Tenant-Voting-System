import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import LiveStatus from './LiveStatus';
import TitleBlockHeader from './TitleBlockHeader';
import { statusDetail } from './labels';

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T12:00:00Z')); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

const base = { timezone: 'Africa/Kampala' };
const S = {
  apply_open: { ...base, applications_phase: 'open', voting_phase: 'not_started', voting_opens_at: '2026-10-09T21:30:00', applications_closes_at: '2026-10-05T12:00:00' },
  voting_soon: { ...base, applications_phase: 'ended', voting_phase: 'not_started', voting_opens_at: '2026-10-09T21:30:00' },
  voting_open: { ...base, applications_phase: 'ended', voting_phase: 'open', voting_closes_at: '2026-10-12T12:00:00' },
  voting_closed: { ...base, applications_phase: 'ended', voting_phase: 'ended', voting_closes_at: '2026-10-12T12:00:00' },
};

describe('LiveStatus (header status cell)', () => {
  it('label per phase, from the raw election status', () => {
    const want = { apply_open: 'Applications Open', voting_soon: 'Not Started', voting_open: 'Voting Open', voting_closed: 'Closed' };
    for (const [state, label] of Object.entries(want)) {
      const { unmount } = render(<LiveStatus status={S[state]} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it('renders nothing while the status is unknown', () => {
    const { container } = render(<LiveStatus status={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('counts down to voting opening and ticks every second', () => {
    vi.setSystemTime(new Date('2026-10-09T21:29:50Z'));
    render(<LiveStatus status={S.voting_soon} />);
    expect(screen.getByText('Opens in 00h 00m 10s')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText('Opens in 00h 00m 07s')).toBeInTheDocument();
  });

  it('apply_open counts down to the applications deadline', () => {
    render(<LiveStatus status={S.apply_open} />);
    expect(screen.getByText(/^Apps close in /)).toBeInTheDocument();
  });

  it('drops the seconds when more than a day away, keeps them inside the last day', () => {
    vi.setSystemTime(new Date('2026-10-07T12:00:00Z'));
    const { unmount } = render(<LiveStatus status={S.voting_soon} />);
    expect(screen.getByText('Opens in 2d 09h 30m')).toBeInTheDocument();
    unmount();
    vi.setSystemTime(new Date('2026-10-09T21:29:50Z'));
    render(<LiveStatus status={S.voting_soon} />);
    expect(screen.getByText('Opens in 00h 00m 10s')).toBeInTheDocument();
  });

  it('Apply tab is highlighted only while applications are open (and not when it is the active page)', () => {
    const p = { orgName: 'KES', view: 'voter', step: 1, theme: 'light', onToggleTheme() {}, onVoteNow() {}, onNavigate() {} };
    const { rerender } = render(<TitleBlockHeader {...p} status={S.apply_open} />);
    expect(screen.getByRole('button', { name: 'Apply' })).toHaveClass('bp-hl');
    rerender(<TitleBlockHeader {...p} status={S.voting_open} />);
    expect(screen.getByRole('button', { name: 'Apply' })).not.toHaveClass('bp-hl');
    rerender(<TitleBlockHeader {...p} phase="apply_open" />);
    expect(screen.getByRole('button', { name: 'Apply' })).toHaveClass('bp-hl');
    rerender(<TitleBlockHeader {...p} view="apply" status={S.apply_open} />);
    expect(screen.getByRole('button', { name: 'Apply' })).toHaveClass('bp-on');
    expect(screen.getByRole('button', { name: 'Apply' })).not.toHaveClass('bp-hl');
  });

  it('open voting shows when it closes; closed shows no detail', () => {
    const { unmount } = render(<LiveStatus status={S.voting_open} />);
    expect(screen.getByText(/^Closes 12 Oct, 15:00/)).toBeInTheDocument();
    unmount();
    const { container } = render(<LiveStatus status={S.voting_closed} />);
    expect(container.querySelector('.bp-sd')).toBeNull();
  });

  it('only the label is a live region, never the ticking detail', () => {
    const { container } = render(<LiveStatus status={S.voting_soon} />);
    expect(container.querySelectorAll('[role="status"]')).toHaveLength(1);
    expect(container.querySelector('.bp-sd').closest('[role="status"]')).toBeNull();
  });

  it('header uses it when given `status`, and the static label when only `phase` is given', () => {
    const p = { orgName: 'KES', view: 'voter', step: 1, theme: 'light', onToggleTheme() {}, onVoteNow() {}, onNavigate() {} };
    const { rerender } = render(<TitleBlockHeader {...p} status={S.voting_soon} />);
    expect(screen.getByText(/^Opens in /)).toBeInTheDocument();
    rerender(<TitleBlockHeader {...p} phase="voting_open" />);
    expect(screen.getByText('Voting Open')).toBeInTheDocument();
    expect(screen.queryByText(/^Opens in /)).toBeNull();
  });
});

describe('statusDetail()', () => {
  it('empty for a null phase', () => expect(statusDetail(null, null, null)).toBe(''));
});
