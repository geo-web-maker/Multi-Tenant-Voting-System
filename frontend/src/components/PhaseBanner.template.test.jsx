import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import PhaseBanner from './PhaseBanner';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T12:00:00Z')); });
afterEach(async () => { cleanup(); vi.useRealTimers(); await restoreTemplate(); });

const base = { timezone: 'Africa/Kampala' };
const S = {
  apply_open: { ...base, applications_phase: 'open', voting_phase: 'not_started', voting_opens_at: '2026-10-09T21:30:00', applications_closes_at: '2026-10-05T12:00:00' },
  voting_soon: { ...base, applications_phase: 'ended', voting_phase: 'not_started', voting_opens_at: '2026-10-09T21:30:00' },
  voting_open: { ...base, applications_phase: 'ended', voting_phase: 'open', voting_closes_at: '2026-10-12T12:00:00' },
  voting_closed: { ...base, applications_phase: 'ended', voting_phase: 'ended', voting_closes_at: '2026-10-12T12:00:00' },
};
const VARIANT = { voting_open: null, voting_soon: 'bp-warn', apply_open: 'bp-acc', voting_closed: 'bp-mute' };

describe('PhaseBanner template seam', () => {
  it('default render has no bp- class', () => {
    useDefault();
    const { container } = render(<PhaseBanner status={S.apply_open} onApply={() => {}} />);
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
  });

  for (const [state, status] of Object.entries(S)) {
    it(`blueprint ${state}: exactly one [data-phase], variant class, role=status, text in words`, async () => {
      await useBlueprint();
      const { container } = render(<PhaseBanner status={status} onApply={() => {}} />);
      const all = container.querySelectorAll('[data-phase]');
      expect(all).toHaveLength(1);
      expect(all[0]).toHaveAttribute('data-phase', state);
      expect(all[0]).toHaveAttribute('role', 'status');
      expect(all[0]).toHaveClass('bp-ban');
      if (VARIANT[state]) expect(all[0]).toHaveClass(VARIANT[state]);
      expect(all[0].textContent.trim().length).toBeGreaterThan(0);
    });
  }

  it('Apply now only for apply_open, with data-track', async () => {
    await useBlueprint();
    for (const [state, status] of Object.entries(S)) {
      const { unmount } = render(<PhaseBanner status={status} onApply={() => {}} />);
      const btn = screen.queryByRole('button', { name: 'Apply now' });
      if (state === 'apply_open') expect(btn).toHaveAttribute('data-track', 'phase-apply-now');
      else expect(btn).toBeNull();
      unmount();
    }
  });

  it('countdown ticks with fake timers', async () => {
    await useBlueprint();
    vi.setSystemTime(new Date('2026-10-09T21:29:50Z'));
    render(<PhaseBanner status={S.voting_soon} />);
    expect(screen.getByText('00h 00m 10s')).toBeTruthy();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText('00h 00m 07s')).toBeTruthy();
  });

  it('no hex colour in the blueprint branch', async () => {
    await useBlueprint();
    const { container } = render(<PhaseBanner status={S.apply_open} onApply={() => {}} />);
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });
});
