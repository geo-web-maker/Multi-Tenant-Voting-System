import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a) } }));
vi.mock('./TurnoutBreakdown', () => ({ PublicTurnoutBreakdown: () => <div>turnout-breakdown</div> }));
vi.mock('./FinalReport', () => ({ default: () => null }));

import Results from './Results';

const serve = (status, results) => mockGet.mockImplementation((url) => {
  if (url === '/election-status') return Promise.resolve({ data: status });
  if (url === '/election-results') return Promise.resolve({ data: results });
  return Promise.resolve({ data: {} });
});

describe('WP-7d Results page states', () => {
  beforeEach(() => mockGet.mockReset());

  it('not started: opening date, no "Live Tallying", no turnout or roll', async () => {
    serve({ is_open: false, voting_phase: 'not_started', voting_opens_at: '2030-01-12T05:00:00' }, { voter_turnout: 0, results: [], results_released: true });
    render(<Results />);
    await waitFor(() => screen.getByText(/Voting opens/));
    expect(screen.getByText(/Results will appear here live\./)).toBeTruthy();
    expect(screen.queryByText(/Live Tallying/)).toBeNull();
    expect(screen.queryByText(/Total Verified Ballots Cast/)).toBeNull();
    expect(screen.queryByText(/Voter Participation Roll/)).toBeNull();
    expect(screen.queryByText('turnout-breakdown')).toBeNull();
  });

  it('open with no votes: "No votes yet." and no roll', async () => {
    serve({ is_open: true, voting_phase: 'open' }, { voter_turnout: 0, results: [], results_released: true });
    render(<Results />);
    await waitFor(() => screen.getByText('No votes yet.'));
    expect(screen.queryByText(/Voter Participation Roll/)).toBeNull();
  });

  it('live: banner and roll section are shown', async () => {
    serve({ is_open: true, voting_phase: 'open' }, { voter_turnout: 4, results: [{ id: '1', name: 'Ann', position: 'Chair', votes: 4 }], results_released: true });
    render(<Results />);
    await waitFor(() => screen.getByText(/Live Tallying/));
    expect(screen.getByText(/Voter Participation Roll/)).toBeTruthy();
  });

  it('embargoed (results_released false): turnout stays, candidate numbers withheld', async () => {
    serve({ is_open: true, voting_phase: 'open' }, { voter_turnout: 9, results: [], results_released: false });
    render(<Results />);
    await waitFor(() => screen.getByText(/Candidate results not yet published/));
    expect(screen.getByText(/Total Verified Ballots Cast/)).toBeTruthy();
  });
});
