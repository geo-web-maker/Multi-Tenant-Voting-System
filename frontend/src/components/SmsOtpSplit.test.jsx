import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
vi.mock('../api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), put: (...a) => mockPut(...a) } }));
vi.mock('./UIFeedback', () => ({
  useToast: () => () => {}, useConfirm: () => async () => true, usePrompt: () => async () => 'Duplicate record entered twice',
}));

import { SmsOtpSplitSettings } from './SmsSettings';
import SharedContactsPanel from './SharedContactsPanel';

const usage = (over = {}) => ({ voters: 1000, otp_split_enabled: false, otp_first_ego_pct: 100, otp_resend_ego_pct: 0,
  sms_pricing: { egosms: { cost_per_part_ugx: 30 }, mambosms: { cost_per_part_ugx: 20 } }, ...over });

describe('SmsOtpSplitSettings', () => {
  beforeEach(() => { mockPut.mockReset(); });
  afterEach(cleanup);

  it('shows the current policy cost, then the 30:70 first / 100:0 resend preset', () => {
    render(<SmsOtpSplitSettings usage={usage()} onSaved={() => {}} />);
    // current policy: 1000 first via EgoSMS, 500 resends via MamboSMS
    expect(screen.getByTestId('otp-split-estimate').textContent).toMatch(/EgoSMS: 1,000 messages/);
    fireEvent.click(screen.getByText('First 30:70, resend 100:0'));
    const t = screen.getByTestId('otp-split-estimate').textContent;
    expect(t).toMatch(/EgoSMS: 800 messages/);
    expect(t).toMatch(/MamboSMS: 700 messages/);
    expect(t).toMatch(/UGX 38,000/);        // 800*30 + 700*20
    expect(screen.getByLabelText('First message EgoSMS percent').value).toBe('30');
  });

  it('says the total is not set when a used provider has no price', () => {
    render(<SmsOtpSplitSettings usage={usage({ sms_pricing: { egosms: { cost_per_part_ugx: 30 }, mambosms: { cost_per_part_ugx: null } } })} onSaved={() => {}} />);
    expect(screen.getByText(/Estimated total: not set/)).toBeTruthy();
  });

  it('saves the ratio with a reason', async () => {
    mockPut.mockResolvedValue({ data: {} });
    render(<SmsOtpSplitSettings usage={usage()} onSaved={() => {}} />);
    fireEvent.click(screen.getByText('First 30:70, resend 100:0'));
    fireEvent.change(screen.getByPlaceholderText(/EgoSMS is cheaper/), { target: { value: 'cheaper first codes' } });
    fireEvent.click(screen.getByText('Save voter-code delivery'));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    expect(mockPut.mock.calls[0][1]).toMatchObject({ otp_split_enabled: true, otp_first_ego_pct: 30, otp_resend_ego_pct: 100 });
  });
});

describe('SharedContactsPanel for IT admin', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });
  afterEach(cleanup);
  const group = { phone_masked: '*********111', phone_key: '256772000111', count: 2, possible_duplicate: true, acknowledged: false,
    voters: [{ student_id: 's2', full_name: 'Jane Doe', has_voted: false, holds_admin_role: false, other_numbers: 0,
      recommended: 'delete_voter', reason: 'Duplicate.', actions: { change_contact: true, remove_contact: false, delete_voter: true } }] };

  it('shows statistics and files a removal request instead of deleting', async () => {
    mockGet.mockResolvedValue({ data: { groups: [group], roster: { frozen: false },
      stats: { shared_numbers: 1, unresolved_numbers: 1, accepted_numbers: 0, voters_sharing: 2, voters_sharing_pct: 0.2,
        possible_duplicates: 1, largest_group: 2, already_voted_sharing: 0 } } });
    mockPost.mockResolvedValue({ data: {} });
    render(<SharedContactsPanel role="it_admin" requestedBy="it1" />);
    expect(await screen.findByTestId('shared-contact-stats')).toBeTruthy();
    expect(screen.getByText('Voters sharing')).toBeTruthy();
    fireEvent.click(screen.getByText('Request removal'));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][0]).toBe('/it-admin/students/request-remove');
    expect(mockPost.mock.calls[0][1]).toMatchObject({ student_id: 's2', requested_by: 'it1' });
  });
});
