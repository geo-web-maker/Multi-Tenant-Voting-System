import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
const mockConfirm = vi.fn();
vi.mock('../api', () => ({
  default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), patch: (...a) => mockPatch(...a) },
  getErrorMessage: (_e, d) => d,
  ADMIN_TOKEN_KEY: 'admin_token',
}));
vi.mock('./UIFeedback', () => ({
  useToast: () => () => {},
  useConfirm: () => mockConfirm,
  ScrollList: ({ children }) => <div>{children}</div>,
}));
vi.mock('./SharedAdminPanels', () => ({
  SHARED_TAB_DEFS: [{ id: 'shared_timeline', label: 'Timeline', icon: 'calendar' }],
  SharedTabPanels: () => null,
  OfficialCertificationBlock: () => null,
}));
vi.mock('./ContactChangesQueue', () => ({ default: () => null }));
vi.mock('./ResetOtpLimitsPanel', () => ({ default: () => null }));

import CommissionDashboard from './CommissionDashboard';
import VettingDashboard from './VettingDashboard';
import VettingPanelManager from './VettingPanelManager';
import ApplicationStages from './ApplicationStages';

// Backend-shaped payloads (see shape_application_for_role / list endpoints in main.py).
const PENDING_APP = {
  id: 'a1', full_name: 'Amina Okello', student_id: 'u123/001', position_title: 'Guild President',
  manifesto: 'Better study spaces for everyone.', image_url: null, status: 'pending',
  finance_cleared: true, my_vote: null, progress: { cast: 1, panel_count: 3 },
  awaiting_final_decision: false, tie_break_available: false,
};

// jsdom has no ResizeObserver either; the flat TabBar uses it to detect overflow.
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };

// jsdom has no matchMedia; TabBar reads it to pick the rail vs. mobile layout.
window.matchMedia = window.matchMedia || ((q) => ({
  matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {},
  addListener: () => {}, removeListener: () => {},
}));

beforeEach(() => {
  mockGet.mockReset(); mockPost.mockReset(); mockPatch.mockReset(); mockConfirm.mockReset();
  sessionStorage.clear();
  sessionStorage.setItem('commissioner_id', 'u999/001');
});

function routeGet(map) {
  mockGet.mockImplementation((url) => (url in map ? Promise.resolve({ data: map[url] }) : Promise.reject(new Error('404 ' + url))));
}

describe('CommissionDashboard', () => {
  const base = {
    '/admin/vetting-outcomes': [],
    '/admin/commissioners': [{ student_id: 'u999/001', is_chief_commissioner: false }],
    '/admin/student-changes': [],
    '/commission/results/detailed': null,
  };

  it('renders without throwing and shows the tab rail', async () => {
    routeGet({ ...base, '/admin/panel-link': { panel_linked: false } });
    render(<CommissionDashboard onLogout={() => {}} />);
    await waitFor(() => expect(screen.getAllByText('Outcomes').length).toBeGreaterThan(0));
    expect(screen.getAllByText('Live Results').length).toBeGreaterThan(0);
  });

  it('hides the Switch to Vetting Panel button for a commissioner not on the panel', async () => {
    routeGet({ ...base, '/admin/panel-link': { panel_linked: false } });
    render(<CommissionDashboard onLogout={() => {}} />);
    await waitFor(() => expect(screen.getByText(/No decisions yet/)).toBeTruthy());
    expect(screen.queryByText('Switch to Vetting Panel')).toBeNull();
  });

  it('shows the button for a linked commissioner', async () => {
    routeGet({ ...base, '/admin/panel-link': { panel_linked: true } });
    render(<CommissionDashboard onLogout={() => {}} />);
    expect(await screen.findByText('Switch to Vetting Panel')).toBeTruthy();
  });

  it('tells the Chairperson when a tie is waiting for them', async () => {
    routeGet({ ...base, '/admin/panel-link': { panel_linked: true, tie_waiting: 2 } });
    render(<CommissionDashboard onLogout={() => {}} />);
    expect(await screen.findByText(/2 applications are tied/)).toBeTruthy();
  });

  it('tells the Chairperson when vetting closed without a decision', async () => {
    routeGet({ ...base, '/admin/panel-link': { panel_linked: true, closeout_waiting: 1 } });
    render(<CommissionDashboard onLogout={() => {}} />);
    expect(await screen.findByText(/Vetting closed on an application without a decision/)).toBeTruthy();
  });

  it('says so when decisions fail to load instead of claiming there are none', async () => {
    const { ['/admin/vetting-outcomes']: _omit, ...rest } = base;
    routeGet({ ...rest, '/admin/panel-link': { panel_linked: false } });
    render(<CommissionDashboard onLogout={() => {}} />);
    expect(await screen.findByText(/Could not load decisions/)).toBeTruthy();
    expect(screen.queryByText(/No decisions yet/)).toBeNull();
  });
});

describe('VettingDashboard', () => {
  const me = { confidentiality_required: false, confidentiality_accepted: true };

  it("shows the applicant's name and manifesto, with the registration number formatted", async () => {
    routeGet({ '/admin/vetting-me': me, '/admin/applications': [PENDING_APP] });
    render(<VettingDashboard onLogout={() => {}} />);
    expect(await screen.findByText('Amina Okello')).toBeTruthy();
    expect(screen.getByText(/Better study spaces/)).toBeTruthy();
    expect(screen.getByText(/U123\/001/)).toBeTruthy();
    expect(screen.queryByText('Applicant')).toBeNull();
  });

  it('asks for confirmation before recording a vote, and does not vote if declined', async () => {
    routeGet({ '/admin/vetting-me': me, '/admin/applications': [PENDING_APP] });
    mockConfirm.mockResolvedValue(false);
    render(<VettingDashboard onLogout={() => {}} />);
    fireEvent.click(await screen.findByText('Approve'));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
    expect(mockConfirm.mock.calls[0][0]).toMatch(/Amina Okello/);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('records the vote once confirmed', async () => {
    routeGet({ '/admin/vetting-me': me, '/admin/applications': [PENDING_APP] });
    mockConfirm.mockResolvedValue(true);
    mockPost.mockResolvedValue({ data: {} });
    render(<VettingDashboard onLogout={() => {}} />);
    fireEvent.click(await screen.findByText('Deny'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/admin/applications/a1/vote', { vote: 'deny', reason: '' }));
  });

  it('offers Retry and Log out when the panel details fail to load', async () => {
    routeGet({});
    const onLogout = vi.fn();
    render(<VettingDashboard onLogout={onLogout} />);
    expect(await screen.findByText('Retry')).toBeTruthy();
    fireEvent.click(screen.getByText('Log out'));
    expect(onLogout).toHaveBeenCalled();
  });

  it('asks the Chairperson to decide an application left open when vetting closed', async () => {
    const closed = {
      ...PENDING_APP,
      vetting_closed_undecided: true,
      closeout_counts: { approve: 1, deny: 1 },
      closeout_decider: 'chair',
      closeout_decision_available: true,
    };
    routeGet({ '/admin/vetting-me': me, '/admin/applications': [closed] });
    mockConfirm.mockResolvedValue(true);
    mockPost.mockResolvedValue({ data: {} });
    render(<VettingDashboard onLogout={() => {}} />);
    expect(await screen.findByText(/Votes cast: 1 approve, 1 deny/)).toBeTruthy();
    expect(screen.queryByText(/of 3 voted/)).toBeNull();
    fireEvent.click(screen.getByText('Deny'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/applications/a1/closeout-decision', { decision: 'deny', reason: '' }));
  });

  it('hides voting when the decision belongs to someone else', async () => {
    const closed = {
      ...PENDING_APP,
      vetting_closed_undecided: true,
      closeout_counts: { approve: 0, deny: 0 },
      closeout_decider: 'superadmin',
      closeout_decision_available: false,
    };
    routeGet({ '/admin/vetting-me': me, '/admin/applications': [closed] });
    render(<VettingDashboard onLogout={() => {}} />);
    expect(await screen.findByText(/Waiting for the Chairperson or the superadmin/)).toBeTruthy();
    expect(screen.queryByText('Approve')).toBeNull();
  });

  it('says when a resolved application was decided because vetting closed', async () => {
    const done = {
      ...PENDING_APP, status: 'approved', decided_by_closeout: true,
      final_split: { approve: 3, deny: 1 },
    };
    routeGet({ '/admin/vetting-me': me, '/admin/applications': [done] });
    render(<VettingDashboard onLogout={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /Resolved/ }));
    expect(await screen.findByText(/Decided when the vetting window closed/)).toBeTruthy();
    expect(screen.getByText(/3 approve, 1 deny/)).toBeTruthy();
  });
});

describe('ApplicationStages', () => {
  it('can filter applications left undecided when vetting closed', async () => {
    routeGet({
      '/it-admin/applications': [{
        _id: 'a1', full_name: 'Amina Okello', student_id: 'u123/001', position_title: 'President',
        stage: 'needs_decision', stage_label: 'Vetting closed without a decision',
      }],
    });
    render(<ApplicationStages />);
    expect(await screen.findAllByText(/Vetting closed without a decision/)).toHaveLength(2);
  });
});

describe('VettingPanelManager', () => {
  const panel = {
    panel: [
      { panel_member_id: 'PM-AAA', full_name: 'Grace Namu', email: 'g@x.org', is_member: true, student_id: 'U1', active: true, is_chair: true, affiliation: '' },
      { panel_member_id: 'PM-BBB', full_name: 'Ivan Ext', email: 'i@x.org', is_member: false, active: false, is_chair: false, affiliation: 'Alumni' },
    ],
    panel_count: 1, tie_risk: 'none', frozen: false, min_panel: 3,
  };

  it('shows the Chairperson, the rules, and View as only for active panelists', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    render(<VettingPanelManager />);
    expect(await screen.findByText('Grace Namu')).toBeTruthy();
    expect(screen.getByText('Chairperson')).toBeTruthy();
    expect(screen.getByText(/at least 3 active panelists/)).toBeTruthy();
    expect(screen.getAllByText('View as')).toHaveLength(1);
  });

  it('opens a View as session for the panelist id', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    mockPost.mockResolvedValue({ data: { access_token: 't', role: 'vetting', student_id: 'PM-AAA', full_name: 'Grace Namu' } });
    window.open = vi.fn(() => ({ location: {}, close: () => {} }));
    render(<VettingPanelManager />);
    fireEvent.click(await screen.findByText('View as'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/view-as', { student_id: 'PM-AAA', role: 'vetting' }));
  });

  it('appoints a member by picking them from the voter roll, not by typing an ID', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    mockPost.mockResolvedValue({ data: {} });
    const voters = [
      { student_id: 'u1', full_name: 'Grace Namu' },            // already on the panel: must not be offered
      { student_id: 'u9/009', full_name: 'Paul Okello' },
      { student_id: 'u8/008', full_name: 'Sarah Auma' },
    ];
    render(<VettingPanelManager voters={voters} />);
    await screen.findByText('Ivan Ext');
    fireEvent.click(screen.getByText('Voter roll'));
    fireEvent.change(screen.getByPlaceholderText(/Search voters/), { target: { value: 'okello' } });
    expect(screen.queryByText('Sarah Auma')).toBeNull();
    fireEvent.click(screen.getByText('+ Add to Panel'));
    expect(screen.getByText('U9/009')).toBeTruthy();            // shown as a registration number
    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'p@x.org' } });
    fireEvent.change(screen.getByPlaceholderText(/Phone/), { target: { value: '0700000000' } });
    fireEvent.change(screen.getByPlaceholderText(/Reason for appointment/), { target: { value: 'Alumni rep' } });
    fireEvent.click(screen.getByText('Add panelist'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/vetting-panel', expect.objectContaining({
      is_member: true, student_id: 'u9/009', full_name: 'Paul Okello', email: 'p@x.org',
    })));
  });

  it('adds a commissioner with only a reason: no email, phone or password', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    mockPost.mockResolvedValue({ data: {} });
    const commissioners = [
      { student_id: 'u1', full_name: 'Grace Namu', commissioner_email: 'g@x.org' },          // already on the panel
      { student_id: 'u7/007', full_name: 'Moses Ibanda', commissioner_email: 'm@x.org', is_chief_commissioner: true },
    ];
    render(<VettingPanelManager commissioners={commissioners} />);
    await screen.findByText('Ivan Ext');
    expect(screen.queryAllByText('+ Add to Panel')).toHaveLength(1);
    fireEvent.click(screen.getByText('+ Add to Panel'));
    expect(screen.queryByPlaceholderText('Email')).toBeNull();
    expect(screen.queryByPlaceholderText(/Phone/)).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/Reason for appointment/), { target: { value: 'Serving commissioner' } });
    fireEvent.click(screen.getByText('Add to Panel'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/vetting-panel/link-commissioner', {
      student_id: 'u7/007', appointment_reason: 'Serving commissioner',
    }));
  });

  it('lists every kind of admin, labelled by role, from the server', async () => {
    routeGet({
      '/superadmin/vetting-panel': panel,
      '/superadmin/panel-eligible-admins': [
        { student_id: 'it1', full_name: 'Ian Tumusiime', roles: ['IT Admin'] },
        { student_id: 'ov1', full_name: 'Olive Auma', roles: ['Overseer'] },
        { student_id: 'u1', full_name: 'Grace Namu', roles: ['Commissioner'] },   // already on the panel
      ],
    });
    render(<VettingPanelManager />);
    await screen.findByText('Ian Tumusiime');
    expect(screen.getByText('IT Admin')).toBeTruthy();
    expect(screen.getByText('Overseer')).toBeTruthy();
    expect(screen.getByText(/Overseer access is paused while they serve/)).toBeTruthy();
    expect(screen.queryAllByText('+ Add to Panel')).toHaveLength(2);
  });

  it('does not offer someone who is already on the panel', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    render(<VettingPanelManager voters={[{ student_id: 'U1', full_name: 'Grace Namu' }]} />);
    await screen.findByText('Ivan Ext');
    fireEvent.click(screen.getByText('Voter roll'));
    expect(screen.queryByText('+ Add to Panel')).toBeNull();
  });

  it('still lets the superadmin appoint an outside person', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    mockPost.mockResolvedValue({ data: {} });
    render(<VettingPanelManager voters={[]} />);
    await screen.findByText('Ivan Ext');
    fireEvent.click(screen.getByText('Outside person'));
    fireEvent.change(screen.getByPlaceholderText('Full name'), { target: { value: 'Dr. Ext' } });
    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'e@x.org' } });
    fireEvent.change(screen.getByPlaceholderText(/Phone/), { target: { value: '0711111111' } });
    fireEvent.change(screen.getByPlaceholderText(/Reason for appointment/), { target: { value: 'Independent' } });
    fireEvent.change(screen.getByLabelText(/Or when a timeline phase closes/), { target: { value: 'vetting' } });
    fireEvent.click(screen.getByText('Add panelist'));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/superadmin/vetting-panel', expect.objectContaining({
      is_member: false, student_id: null, expires_with_phase: 'vetting',
    })));
  });

  it('edits a panelist in place', async () => {
    routeGet({ '/superadmin/vetting-panel': panel });
    mockPatch.mockResolvedValue({ data: {} });
    render(<VettingPanelManager />);
    fireEvent.click((await screen.findAllByText('Edit'))[1]);
    fireEvent.change(screen.getByPlaceholderText('Affiliation'), { target: { value: 'Alumni association' } });
    fireEvent.click(screen.getByText('Save changes'));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/superadmin/vetting-panel/PM-BBB', { affiliation: 'Alumni association' }));
  });
});

describe('VettingDashboard resolved tab', () => {
  it('searches resolved applications and shows decision date and registration number', async () => {
    const resolved = [
      { id: 'r1', full_name: 'Zed One', student_id: 'u5/001', position_title: 'Treasurer', status: 'approved', decided_at: '2026-09-30T10:00:00Z', final_split: { approve: 2, deny: 1 } },
      { id: 'r2', full_name: 'Yan Two', student_id: 'u6/002', position_title: 'Secretary', status: 'denied', final_split: { approve: 1, deny: 2 } },
    ];
    routeGet({ '/admin/vetting-me': { confidentiality_required: false, confidentiality_accepted: true }, '/admin/applications': resolved });
    render(<VettingDashboard onLogout={() => {}} />);
    fireEvent.click(await screen.findByText('Resolved'));
    expect(await screen.findByText('Zed One')).toBeTruthy();
    expect(screen.getByText(/U5\/001/)).toBeTruthy();
    expect(screen.getByText(/Decided /)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/Search by name/), { target: { value: 'yan' } });
    expect(screen.queryByText('Zed One')).toBeNull();
    expect(screen.getByText('Yan Two')).toBeTruthy();
  });
});
