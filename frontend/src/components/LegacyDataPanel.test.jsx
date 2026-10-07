import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockConfirm = vi.fn(async () => true);
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
  getErrorMessage: (_e, d) => d,
}));
vi.mock('./UIFeedback', () => ({ useToast: () => () => {}, useConfirm: () => mockConfirm }));

import LegacyDataPanel from './LegacyDataPanel';

const ORGS = [{ _id: 'o1', name: 'Alpha', slug: 'alpha' }, { _id: 'o2', name: 'Beta', slug: 'beta' }];
const serve = (scan) => mockGet.mockImplementation((url) => (
  url === '/superadmin/legacy-data' ? Promise.resolve({ data: scan }) : Promise.resolve({ data: ORGS })));
const DIRTY = { total: 5, collections: [
  { name: 'voters', count: 3, assignable: true },
  { name: 'candidates', count: 0, assignable: true },
  { name: 'vote_events', count: 2, assignable: false },
] };

describe('Legacy data check panel', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); mockConfirm.mockClear(); });

  it('says so when nothing is left over', async () => {
    serve({ total: 0, collections: [{ name: 'voters', count: 0, assignable: true }] });
    render(<LegacyDataPanel />);
    expect(await screen.findByTestId('legacy-clean')).toBeTruthy();
    expect(screen.queryByText('Assign selected')).toBeNull();
  });

  it('lists only groups that have records, and flags remove-only ones', async () => {
    serve(DIRTY);
    render(<LegacyDataPanel />);
    expect(await screen.findByText('Voters / staff')).toBeTruthy();
    expect(screen.queryByText('Candidates')).toBeNull();
    expect(screen.getByText('(remove only)')).toBeTruthy();
  });

  it('assigns the ticked groups to the chosen organization', async () => {
    serve(DIRTY);
    mockPost.mockResolvedValue({ data: { results: [{ name: 'voters', moved: 3 }], remaining: 2 } });
    render(<LegacyDataPanel />);
    fireEvent.click(await screen.findByLabelText(/Voters \/ staff/));
    fireEvent.change(screen.getByLabelText('Organization to assign to'), { target: { value: 'o2' } });
    fireEvent.click(screen.getByText('Assign selected'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/legacy-data/assign', { org_id: 'o2', collections: ['voters'] }));
    expect(mockConfirm).toHaveBeenCalled();
  });

  it('does not call the API when no organization is chosen', async () => {
    serve(DIRTY);
    render(<LegacyDataPanel />);
    fireEvent.click(await screen.findByLabelText(/Voters \/ staff/));
    fireEvent.click(screen.getByText('Assign selected'));
    await new Promise(r => setTimeout(r, 0));
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('refuses to assign a remove-only group', async () => {
    serve(DIRTY);
    render(<LegacyDataPanel />);
    fireEvent.click(await screen.findByLabelText(/Ballots \(vote events\)/));
    fireEvent.change(screen.getByLabelText('Organization to assign to'), { target: { value: 'o1' } });
    fireEvent.click(screen.getByText('Assign selected'));
    await new Promise(r => setTimeout(r, 0));
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('removal asks for the typed phrase and sends it', async () => {
    serve(DIRTY);
    mockPost.mockResolvedValue({ data: { deleted: { vote_events: 2 }, remaining: 3 } });
    render(<LegacyDataPanel />);
    fireEvent.click(await screen.findByLabelText(/Ballots \(vote events\)/));
    fireEvent.click(screen.getByText('Remove selected'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/legacy-data/delete',
      { collections: ['vote_events'], confirm: 'DELETE LEGACY DATA' }));
    expect(mockConfirm.mock.calls[0][1]).toMatchObject({ danger: true, requireText: 'DELETE LEGACY DATA' });
  });
});
