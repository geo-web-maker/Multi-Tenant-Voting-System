import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import PhaseBanner from './PhaseBanner';

afterEach(() => { cleanup(); vi.useRealTimers(); });

const base = { timezone: 'Africa/Kampala' };
const S = {
  apply_open: { ...base, applications_phase: 'open', voting_phase: 'not_started', voting_opens_at: '2026-10-09T21:30:00', applications_closes_at: '2026-10-05T12:00:00' },
  voting_soon: { ...base, applications_phase: 'ended', voting_phase: 'not_started', voting_opens_at: '2026-10-09T21:30:00' },
  voting_open: { ...base, applications_phase: 'ended', voting_phase: 'open', voting_closes_at: '2026-10-12T12:00:00' },
  voting_closed: { ...base, applications_phase: 'ended', voting_phase: 'ended', voting_closes_at: '2026-10-12T12:00:00' },
};

describe('A1: PhaseBanner', () => {
  it('renders nothing without status', () => {
    const { container } = render(<PhaseBanner status={null} />);
    expect(container.innerHTML).toBe('');
  });

  for (const [state, status] of Object.entries(S)) {
    it(`${state}: exactly one banner, with that state`, () => {
      const { container } = render(<PhaseBanner status={status} onApply={() => {}} />);
      const all = container.querySelectorAll('[data-phase]');
      expect(all.length).toBe(1);
      expect(all[0].getAttribute('data-phase')).toBe(state);
      expect(all[0].textContent.trim().length).toBeGreaterThan(0); // state is stated in words, not colour alone
    });
  }

  it('Apply now appears only for apply_open', () => {
    for (const [state, status] of Object.entries(S)) {
      const { unmount } = render(<PhaseBanner status={status} onApply={() => {}} />);
      const btn = screen.queryByRole('button', { name: 'Apply now' });
      if (state === 'apply_open') {
        expect(btn).toBeTruthy();
        expect(btn.getAttribute('data-track')).toBe('phase-apply-now');
      } else {
        expect(btn).toBeNull();
      }
      unmount();
    }
  });

  it('clicking Apply now calls onApply', () => {
    const onApply = vi.fn();
    render(<PhaseBanner status={S.apply_open} onApply={onApply} />);
    fireEvent.click(screen.getByRole('button', { name: 'Apply now' }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it('text is at least 16px', () => {
    const { container } = render(<PhaseBanner status={S.apply_open} onApply={() => {}} />);
    expect(container.querySelector('[data-phase]').style.fontSize).toBe('16px');
    expect(screen.getByRole('button', { name: 'Apply now' }).style.fontSize).toBe('16px');
  });

  it('countdown ticks with fake timers and only for the upcoming phase', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-09T21:29:50Z')); // 10 s before voting opens
    render(<PhaseBanner status={S.voting_soon} />);
    expect(screen.getByText('Voting opens in 00h 00m 10s')).toBeTruthy();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText('Voting opens in 00h 00m 07s')).toBeTruthy();
  });

  it('no countdown while voting is open or closed', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-09T21:29:50Z'));
    for (const k of ['voting_open', 'voting_closed']) {
      const { unmount } = render(<PhaseBanner status={S[k]} />);
      expect(screen.queryByText(/Voting opens in/)).toBeNull();
      unmount();
    }
  });

  it('shows the election-zone date near midnight (next local day)', () => {
    render(<PhaseBanner status={S.voting_soon} />);
    expect(screen.getByText(/It opens 10 Oct 2026/)).toBeTruthy();
  });
});
