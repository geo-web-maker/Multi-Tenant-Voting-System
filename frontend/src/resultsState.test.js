import { describe, it, expect } from 'vitest';
import { resultsState, notStartedMessage } from './resultsState';

const cand = (votes) => ({ id: String(votes), name: 'C', position: 'P', votes });

describe('WP-7d resultsState', () => {
  it('not_started: voting has not opened', () => {
    expect(resultsState({ is_open: false, voting_phase: 'not_started' }, { voter_turnout: 0, results: [] })).toBe('not_started');
  });
  it('not_started wins over an unreleased flag', () => {
    expect(resultsState({ is_open: false, voting_phase: 'not_started' }, { results_released: false })).toBe('not_started');
  });
  it('embargoed: results_released === false once voting has begun', () => {
    expect(resultsState({ is_open: true, voting_phase: 'open' }, { voter_turnout: 12, results: [], results_released: false })).toBe('embargoed');
    expect(resultsState({ is_open: false, voting_phase: 'ended' }, { voter_turnout: 12, results: [], results_released: false })).toBe('embargoed');
  });
  it('a missing results_released flag is NOT embargoed', () => {
    expect(resultsState({ is_open: true, voting_phase: 'open' }, { voter_turnout: 3, results: [cand(3)] })).toBe('live');
  });
  it('no_votes: open or closed with nothing cast', () => {
    expect(resultsState({ is_open: true, voting_phase: 'open' }, { voter_turnout: 0, results: [cand(0)] })).toBe('no_votes');
    expect(resultsState({ is_open: false, voting_phase: 'ended' }, { voter_turnout: 0, results: [] })).toBe('no_votes');
  });
  it('live: open with ballots in', () => {
    expect(resultsState({ is_open: true, voting_phase: 'open' }, { voter_turnout: 5, results: [cand(5)] })).toBe('live');
  });
  it('closed: finished with ballots', () => {
    expect(resultsState({ is_open: false, voting_phase: 'ended', is_certified: true }, { voter_turnout: 5, results: [cand(5)] })).toBe('closed');
  });
  it('survives empty / missing payloads', () => {
    expect(resultsState(undefined, undefined)).toBe('no_votes');
    expect(resultsState({}, { voter_turnout: 'x', results: null })).toBe('no_votes');
  });
  it('message wording', () => {
    expect(notStartedMessage('12 Jan 2026, 08:00 EAT')).toBe('Voting opens 12 Jan 2026, 08:00 EAT. Results will appear here live.');
    expect(notStartedMessage('')).toBe('Voting opens soon. Results will appear here live.');
    expect(notStartedMessage('—')).toBe('Voting opens soon. Results will appear here live.');
  });
});
