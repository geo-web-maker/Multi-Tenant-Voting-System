import { describe, it, expect } from 'vitest';
import { derivePhase, formatCountdown } from './phase';

const P = ['not_started', 'open', 'ended'];
// applications x voting -> expected banner state
const EXPECT = {
  'not_started|not_started': 'voting_soon',
  'not_started|open': 'voting_open',
  'not_started|ended': 'voting_closed',
  'open|not_started': 'apply_open',
  'open|open': 'voting_open',
  'open|ended': 'voting_closed',
  'ended|not_started': 'voting_soon',
  'ended|open': 'voting_open',
  'ended|ended': 'voting_closed',
};

describe('A1: derivePhase', () => {
  for (const a of P) for (const v of P) {
    it(`applications ${a} x voting ${v} -> ${EXPECT[`${a}|${v}`]}`, () => {
      const r = derivePhase({ applications_phase: a, voting_phase: v, timezone: 'Africa/Kampala' });
      expect(r.state).toBe(EXPECT[`${a}|${v}`]);
    });
  }

  it('returns null for no status or an unknown shape', () => {
    expect(derivePhase(null)).toBeNull();
    expect(derivePhase({})).toBeNull();
  });

  it('master switch off means closed, even inside the voting window', () => {
    expect(derivePhase({ is_open: false, voting_phase: 'open', applications_phase: 'open' }).state).toBe('voting_closed');
  });

  it('countdown only for the next upcoming phase', () => {
    const at = '2026-10-10T05:00:00';
    expect(derivePhase({ voting_phase: 'not_started', applications_phase: 'open', voting_opens_at: at }).countdownTo).toBe(at);
    expect(derivePhase({ voting_phase: 'not_started', applications_phase: 'ended', voting_opens_at: at }).countdownTo).toBe(at);
    expect(derivePhase({ voting_phase: 'open', applications_phase: 'open' }).countdownTo).toBeNull();
    expect(derivePhase({ voting_phase: 'ended', applications_phase: 'ended' }).countdownTo).toBeNull();
  });

  it('formats dates in the election zone: a UTC instant near midnight is the next local day', () => {
    // 21:30 UTC on 9 Oct = 00:30 on 10 Oct in Africa/Kampala (UTC+3)
    const r = derivePhase({ voting_phase: 'not_started', applications_phase: 'ended', voting_opens_at: '2026-10-09T21:30:00', timezone: 'Africa/Kampala' });
    expect(r.dates.votingOpensAt).toMatch(/^10 Oct 2026/);
    const utc = derivePhase({ voting_phase: 'not_started', applications_phase: 'ended', voting_opens_at: '2026-10-09T21:30:00', timezone: 'UTC' });
    expect(utc.dates.votingOpensAt).toMatch(/^9 Oct 2026/);
  });

  it('falls back to Africa/Kampala when no timezone is sent', () => {
    const r = derivePhase({ voting_phase: 'not_started', applications_phase: 'ended', voting_opens_at: '2026-10-09T21:30:00' });
    expect(r.tz).toBe('Africa/Kampala');
    expect(r.dates.votingOpensAt).toMatch(/^10 Oct 2026/);
  });
});

describe('A1: formatCountdown', () => {
  it('drops days when zero and pads', () => {
    expect(formatCountdown(((2 * 24 + 3) * 3600 + 4 * 60 + 5) * 1000)).toBe('2d 03h 04m 05s');
    expect(formatCountdown((3600 + 60 + 1) * 1000)).toBe('01h 01m 01s');
  });
  it('is null when passed or missing', () => {
    expect(formatCountdown(0)).toBeNull();
    expect(formatCountdown(-5)).toBeNull();
    expect(formatCountdown(null)).toBeNull();
  });
});
