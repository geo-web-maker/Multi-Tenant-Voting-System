import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) } }));
vi.mock('./UIFeedback', () => ({
  useToast: () => () => {}, useConfirm: () => async () => true, usePrompt: () => async () => 'because the window must close now',
}));

import ByElectionsPanel from './ByElectionsPanel';

const tie = { id: 't1', round_id: 'round-1', position: 'Chair', tie_type: 'top', count: 5, status: 'by_election_ordered',
  candidates: [{ id: 'a', name: 'Ann' }, { id: 'b', name: 'Ben' }], by_election_round_id: 'by-election-x' };
const sched = (over = {}) => ({ round_id: 'by-election-x', position: 'Chair', status: 'scheduled', is_active_round: true,
  timezone: 'Africa/Kampala', voting: { start: null, end: null, enforced: false }, state: 'unscheduled',
  seconds_until_start: null, seconds_until_end: null, ...over });

function serve(s) {
  mockGet.mockImplementation(async (url) => {
    if (url === '/superadmin/election-ties') return { data: { ties: [tie] } };
    if (url.endsWith('/schedule')) return { data: s };
    throw new Error('unexpected ' + url);
  });
}

describe('ByElectionsPanel schedule', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });
  afterEach(cleanup);

  it('shows the by-election timeline inside the tab, unscheduled at first', async () => {
    serve(sched());
    render(<ByElectionsPanel />);
    expect(await screen.findByTestId('by-election-schedule')).toBeTruthy();
    expect(await screen.findByText(/Not scheduled yet/)).toBeTruthy();
  });

  it('shows an opening countdown when scheduled and an upcoming window', async () => {
    const start = new Date(Date.now() + 3 * 3600e3).toISOString().slice(0, 19);
    const end = new Date(Date.now() + 6 * 3600e3).toISOString().slice(0, 19);
    serve(sched({ state: 'upcoming', voting: { start, end, enforced: true }, seconds_until_start: 10800, seconds_until_end: 21600 }));
    render(<ByElectionsPanel />);
    expect(await screen.findByText(/Opens in 3h/)).toBeTruthy();
  });

  it('shows a closing countdown while voting is open and hides editing once closed', async () => {
    serve(sched({ state: 'active', seconds_until_end: 5400 }));
    const { unmount } = render(<ByElectionsPanel />);
    expect(await screen.findByText(/Closes in 1h 30m/)).toBeTruthy();
    unmount();
    serve(sched({ state: 'closed' }));
    render(<ByElectionsPanel />);
    expect(await screen.findByText(/has ended/)).toBeTruthy();
    expect(screen.queryByText('Save by-election schedule')).toBeNull();
  });

  it('saves the window to the by-election endpoint', async () => {
    serve(sched());
    mockPost.mockResolvedValue({ data: { status: 'scheduled' } });
    render(<ByElectionsPanel />);
    await screen.findByText(/Not scheduled yet/);
    const inputs = document.querySelectorAll('input[type="datetime-local"]');
    fireEvent.change(inputs[0], { target: { value: '2030-01-10T08:00' } });
    fireEvent.change(inputs[1], { target: { value: '2030-01-10T17:00' } });
    fireEvent.click(screen.getByText('Save by-election schedule'));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const [url, body] = mockPost.mock.calls[0];
    expect(url).toBe('/superadmin/by-elections/by-election-x/schedule');
    expect(body.start).toMatch(/2030-01-10T05:00/);
    expect(body.end).toMatch(/2030-01-10T14:00/);
  });
});

describe('ByElectionsPanel shared contacts', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });
  afterEach(cleanup);
  const group = { phone_masked: '*********111', phone_key: '256772000111', count: 2, severity: 'high', possible_duplicate: true,
    acknowledged: false, voters: [
      { student_id: 's1', full_name: 'Jane Doe', has_voted: true, holds_admin_role: false, other_numbers: 0, recommended: 'keep', reason: 'Keep it.', actions: { change_contact: true, remove_contact: false, delete_voter: false } },
      { student_id: 's2', full_name: 'Jane Doe', has_voted: false, holds_admin_role: false, other_numbers: 0, recommended: 'delete_voter', reason: 'Duplicate.', actions: { change_contact: true, remove_contact: false, delete_voter: true } },
    ] };

  it('hides the shared-contact check when there is no tie', async () => {
    mockGet.mockImplementation(async (url) => { if (url === '/superadmin/election-ties') return { data: { ties: [] } }; throw new Error(url); });
    render(<ByElectionsPanel />);
    await screen.findByText(/No tie records/);
    expect(screen.queryByTestId('shared-contacts')).toBeNull();
    expect(mockGet).not.toHaveBeenCalledWith('/admin/shared-contacts');
  });

  it('lists shared numbers with recommendations and deletes the duplicate', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/superadmin/election-ties') return { data: { ties: [{ ...tie, by_election_round_id: undefined, status: 'pending' }] } };
      if (url === '/admin/shared-contacts') return { data: { groups: [group], roster: { frozen: false } } };
      throw new Error(url);
    });
    mockPost.mockResolvedValue({ data: {} });
    render(<ByElectionsPanel />);
    expect(await screen.findByText(/possible duplicate record/)).toBeTruthy();
    expect(screen.getByText(/Recommended: delete this duplicate record/)).toBeTruthy();
    expect(screen.getAllByText('Delete voter')).toHaveLength(1);
    fireEvent.click(screen.getByText('Delete voter'));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][0]).toBe('/superadmin/students/remove');
    expect(mockPost.mock.calls[0][1].student_id).toBe('s2');
  });
});
