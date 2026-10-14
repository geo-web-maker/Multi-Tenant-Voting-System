import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DeletedApplicationsPanel from './DeletedApplicationsPanel';

const get = vi.fn();
const post = vi.fn();
const toast = vi.fn();
const confirm = vi.fn();
const prompt = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => get(...a), post: (...a) => post(...a) } }));
vi.mock('./UIFeedback', () => ({
  useToast: () => toast, useConfirm: () => confirm, usePrompt: () => prompt,
  ScrollList: ({ children }) => <div>{children}</div>,
}));

const ROW = { _id: 'a1', student_id: 'v1', full_name: 'Ayebale Elizabeth', position_title: 'President', status: 'approved',
  deleted_at: '2026-10-14T08:00:00Z', deleted_by: 'root', delete_reason: 'Entered by mistake', had_candidate: true };

describe('DeletedApplicationsPanel', () => {
  beforeEach(() => { [get, post, toast, confirm, prompt].forEach((m) => m.mockReset()); });

  it('lists the archive, or says it is empty', async () => {
    get.mockResolvedValueOnce({ data: [] });
    const { unmount } = render(<DeletedApplicationsPanel />);
    expect(await screen.findByText('No deleted applications.')).toBeTruthy();
    unmount();
    get.mockResolvedValueOnce({ data: [ROW] });
    render(<DeletedApplicationsPanel />);
    expect(await screen.findByText('Ayebale Elizabeth')).toBeTruthy();
    expect(screen.getByText(/Entered by mistake/)).toBeTruthy();
  });

  it('restores with a reason and tells the parent to refresh', async () => {
    get.mockResolvedValue({ data: [ROW] });
    post.mockResolvedValue({ data: { status: 'restored', candidate_was_on_ballot: true } });
    prompt.mockResolvedValue(' Deleted by mistake ');
    const onChanged = vi.fn();
    render(<DeletedApplicationsPanel onChanged={onChanged} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith('/superadmin/deleted-applications/a1/restore', { reason: 'Deleted by mistake' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(toast.mock.calls[0][0]).toMatch(/not on the ballot/);
  });

  it('does nothing when the reason prompt is cancelled', async () => {
    get.mockResolvedValue({ data: [ROW] });
    prompt.mockResolvedValue(null);
    render(<DeletedApplicationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(prompt).toHaveBeenCalled());
    expect(post).not.toHaveBeenCalled();
  });

  it('a permanent delete asks for the reason, then the typed phrase, and sends DELETE', async () => {
    get.mockResolvedValue({ data: [ROW] });
    post.mockResolvedValue({ data: { status: 'purged' } });
    prompt.mockResolvedValue('Clear it out');
    confirm.mockResolvedValue(true);
    render(<DeletedApplicationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete permanently' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith('/superadmin/deleted-applications/a1/purge', { reason: 'Clear it out', confirm: 'DELETE' }));
    expect(confirm.mock.calls[0][1]).toMatchObject({ danger: true, requireText: 'DELETE' });
  });

  it('declining the typed confirmation sends nothing', async () => {
    get.mockResolvedValue({ data: [ROW] });
    prompt.mockResolvedValue('Clear it out');
    confirm.mockResolvedValue(false);
    render(<DeletedApplicationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete permanently' }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(post).not.toHaveBeenCalled();
  });

  it('shows a load failure in the error message style', async () => {
    get.mockRejectedValue({ response: { data: { detail: 'Not allowed.' } } });
    render(<DeletedApplicationsPanel />);
    expect((await screen.findByText('Not allowed.')).getAttribute('data-kind')).toBe('error');
  });
});
