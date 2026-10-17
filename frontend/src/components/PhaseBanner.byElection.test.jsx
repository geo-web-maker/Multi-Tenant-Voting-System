import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import PhaseBanner from './PhaseBanner';

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-17T12:00:00Z')); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

const be = { timezone: 'Africa/Kampala', applications_phase: 'ended', round_kind: 'by_election',
  by_election_position: 'Deputy Projects Coordinator', by_election_eligibility: 'all_registered', by_election_scheduled: true };

describe('PhaseBanner for a by-election', () => {
  it('names the by-election and position with an opening countdown', () => {
    const { container } = render(<PhaseBanner status={{ ...be, voting_phase: 'not_started', voting_opens_at: '2026-10-20T05:00:00' }} />);
    const text = container.textContent;
    expect(text).toMatch(/By-election · Deputy Projects Coordinator/);
    expect(text).toMatch(/Voting opens/);
    expect(text).toMatch(/Voting opens in/i);
    expect(container.querySelector('[data-phase="voting_soon"]')).toBeTruthy();
  });

  it('says dates are to be announced while unscheduled, with no countdown', () => {
    const { container } = render(<PhaseBanner status={{ ...be, by_election_scheduled: false, voting_phase: 'not_started', voting_opens_at: null }} />);
    expect(container.textContent).toMatch(/Dates to be announced/);
    expect(container.textContent).not.toMatch(/Voting opens in/i);
  });

  it('shows open and closed states with the by-election label, and the Round 1 only rule', () => {
    const open = render(<PhaseBanner status={{ ...be, by_election_eligibility: 'round1_voters', voting_phase: 'open', voting_closes_at: '2026-10-17T18:00:00' }} />);
    expect(open.container.textContent).toMatch(/By-election · Deputy Projects Coordinator · voting is open/);
    expect(open.container.textContent).toMatch(/Only voters who voted in Round 1/);
    open.unmount();
    const closed = render(<PhaseBanner status={{ ...be, voting_phase: 'ended', voting_closes_at: '2026-10-16T16:00:00' }} />);
    expect(closed.container.textContent).toMatch(/voting is closed/);
  });

  it('leaves a general election banner unchanged', () => {
    const { container } = render(<PhaseBanner status={{ timezone: 'Africa/Kampala', applications_phase: 'ended', round_kind: 'general', voting_phase: 'open', voting_closes_at: '2026-10-18T12:00:00' }} />);
    expect(container.textContent).toMatch(/Voting is open/);
    expect(container.textContent).not.toMatch(/By-election/);
  });
});
