import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const confirm = vi.fn(); const toast = vi.fn();
vi.mock('./UIFeedback', () => ({ useToast: () => toast, useConfirm: () => confirm }));
vi.mock('../registerExport', () => ({
  fetchExportPermission: vi.fn(), downloadRegister: vi.fn(),
  exportErrorMessage: vi.fn(async () => 'Voter register export is not enabled for your account.'),
}));
import * as api from '../registerExport';
import VoterRegisterExport from './VoterRegisterExport';

beforeEach(() => { vi.clearAllMocks(); confirm.mockResolvedValue(true); });

describe('VoterRegisterExport', () => {
  it('renders NOTHING when mode is none', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'none' });
    const { container } = render(<VoterRegisterExport />);
    await waitFor(() => expect(api.fetchExportPermission).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
  it('renders nothing if the permission call fails (fail closed)', async () => {
    api.fetchExportPermission.mockRejectedValue(new Error('x'));
    const { container } = render(<VoterRegisterExport />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
  it('redacted: shows "phones hidden" button, no confirm, downloads', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'redacted' });
    api.downloadRegister.mockResolvedValue({ rows: 10, mode: 'redacted', name: 'a.xlsx' });
    render(<VoterRegisterExport />);
    await userEvent.click(await screen.findByRole('button', { name: /phones hidden/i }));
    expect(confirm).not.toHaveBeenCalled();
    expect(api.downloadRegister).toHaveBeenCalledWith('xlsx');
  });
  it('full: asks to confirm; cancelling downloads nothing', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'full' });
    confirm.mockResolvedValue(false);
    render(<VoterRegisterExport />);
    await userEvent.click(await screen.findByRole('button', { name: /full details/i }));
    expect(confirm).toHaveBeenCalled();
    expect(api.downloadRegister).not.toHaveBeenCalled();
  });
  it('double click triggers only ONE download', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'redacted' });
    let resolve; api.downloadRegister.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<VoterRegisterExport />);
    const btn = await screen.findByRole('button', { name: /phones hidden/i });
    await userEvent.dblClick(btn);
    expect(api.downloadRegister).toHaveBeenCalledTimes(1);
    resolve({ rows: 1, mode: 'redacted' });
  });
  it('403 shows the message and re-checks permission (button can disappear)', async () => {
    api.fetchExportPermission.mockResolvedValueOnce({ mode: 'redacted' }).mockResolvedValueOnce({ mode: 'none' });
    api.downloadRegister.mockRejectedValue({ response: { status: 403 } });
    const { container } = render(<VoterRegisterExport />);
    await userEvent.click(await screen.findByRole('button', { name: /phones hidden/i }));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(api.fetchExportPermission).toHaveBeenCalledTimes(2);
  });
  it('csv shows the Excel phone-number warning', async () => {
    api.fetchExportPermission.mockResolvedValue({ mode: 'redacted' });
    render(<VoterRegisterExport />);
    await userEvent.selectOptions(await screen.findByRole('combobox'), 'csv');
    expect(screen.getByText(/2\.5E\+11/)).toBeInTheDocument();
  });
});
