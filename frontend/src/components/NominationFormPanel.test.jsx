import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import NominationFormPanel from './NominationFormPanel';

const get = vi.fn();
const put = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => get(...a), put: (...a) => put(...a), post: vi.fn() } }));
vi.mock('../template', () => ({ getTemplate: () => null }));

describe('NominationFormPanel', () => {
  beforeEach(() => {
    get.mockReset(); put.mockReset();
    get.mockResolvedValue({ data: {
      enabled: false, required: true, title: 'Nomination Form', instructions: 'Download and sign it.',
      template_file: null, accepted_types: ['pdf'], max_mb: 5,
    }});
    put.mockResolvedValue({ data: {
      enabled: true, required: true, title: 'Signed Form', instructions: 'Use the official form.',
      template_file: null, accepted_types: ['pdf'], max_mb: 5,
    }});
  });

  it('loads runtime settings and saves with a required reason', async () => {
    render(<NominationFormPanel />);
    await screen.findByDisplayValue('Nomination Form');
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    fireEvent.change(screen.getByLabelText('Nomination form title'), { target: { value: 'Signed Form' } });
    fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Enable official form' } });
    fireEvent.click(screen.getByRole('button', { name: /Save nomination-form settings/i }));
    await waitFor(() => expect(put).toHaveBeenCalledWith('/superadmin/nomination-form', expect.objectContaining({
      enabled: true, title: 'Signed Form', reason: 'Enable official form',
    })));
    expect(await screen.findByRole('status')).toHaveTextContent('Nomination-form settings saved.');
  });

  it('keeps the Require toggle disabled until the section is enabled', async () => {
    render(<NominationFormPanel />);
    await screen.findByDisplayValue('Nomination Form');
    const checks = screen.getAllByRole('checkbox');
    expect(checks[1]).toBeDisabled();
  });
});
