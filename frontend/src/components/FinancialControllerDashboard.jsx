import React, { useEffect, useState } from 'react';
import api from '../api';
import { usePersistedTab } from '../session';
import { useToast, ScrollList } from './UIFeedback';
import usePolling from '../hooks/usePolling';
import { SHARED_TAB_DEFS, SharedTabPanels } from './SharedAdminPanels';
import TabBar from './TabBar';
import ReceiptLink from './ReceiptLink';
import { regNo } from '../regNo';
import AdminHeader, { useLastSynced } from './AdminHeader';

// All money in one place: voter-register payments (IT Admin add/remove requests) and candidate
// nomination payments. Commissioners no longer clear payments, so whoever confirms the money never
// votes on the candidate.

const SECTION_IDS = ['voters', 'candidates'];
const SHARED_IDS = SHARED_TAB_DEFS.map(t => t.id);

// Same three views for both sections; only the wording differs.
const STATUS_LABELS = {
  voters:     { pending: 'Pending',  approved: 'Approved', denied: 'Denied' },
  candidates: { pending: 'Awaiting', approved: 'Cleared',  denied: 'Rejected' },
};

const money = (n) => `UGX ${Number(n).toLocaleString('en-UG')}`;
const shortDate = (d) => (d ? new Date(d).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' }) : '');

export default function FinancialControllerDashboard({ onLogout }) {
  const toast = useToast();

  const [rawTab, setActiveTab]      = usePersistedTab('financial_controller', 'voters');
  const [statusView, setStatusView] = usePersistedTab('financial_controller_status', 'pending');
  const [changes, setChanges]       = useState([]);   // voter-register requests
  const [apps, setApps]             = useState([]);   // candidate applications (payment side only)
  const [loading, setLoading]       = useState(false);
  const [lastSynced, markSynced]    = useLastSynced();
  const [fcId, setFcId]             = useState('');
  const [reasons, setReasons]       = useState({});   // { id: string }
  const [showReasonBox, setShowReasonBox] = useState({}); // { id: bool }
  const [deciding, setDeciding]     = useState({});   // { id: bool }

  // Older sessions stored 'pending' / 'approved' / 'denied' as the tab; fall back to the voter tab.
  const activeTab = SECTION_IDS.includes(rawTab) || SHARED_IDS.includes(rawTab) ? rawTab : 'voters';
  const isSection = SECTION_IDS.includes(activeTab);
  const view = STATUS_LABELS.voters[statusView] ? statusView : 'pending';

  // On mount — figure out who this Financial Controller is from sessionStorage
  useEffect(() => {
    const stored = sessionStorage.getItem('financial_controller_id') || '';
    setFcId(stored);
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only load
  }, []);

  const fetchAll = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      // Independent calls: one failing must not blank the other list.
      const [ch, ap] = await Promise.allSettled([
        api.get('/admin/student-changes'),
        api.get('/admin/applications'),
      ]);
      if (ch.status === 'fulfilled') setChanges(ch.value.data);
      else console.error('Fetch error (voter requests):', ch.reason);
      if (ap.status === 'fulfilled') setApps(ap.value.data);
      else console.error('Fetch error (candidate payments):', ap.reason);
      if (ch.status === 'fulfilled' || ap.status === 'fulfilled') markSynced();
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // New requests appear on their own.
  usePolling(() => fetchAll({ silent: true }), 15000);

  // ── Decisions ──

  const missingId = () => {
    if (fcId.trim()) return false;
    toast('Your Financial Controller ID was not found in this session. Please log out and log in again.', { kind: 'error' });
    return true;
  };

  // A denial / rejection needs a reason (server-enforced too); open the box instead of failing silently.
  const needReason = (id, what) => {
    if ((reasons[id] || '').trim()) return false;
    setShowReasonBox(prev => ({ ...prev, [id]: true }));
    toast(`Please enter a reason for ${what}.`, { kind: 'error' });
    return true;
  };

  const run = async (id, request, failMessage) => {
    setDeciding(prev => ({ ...prev, [id]: true }));
    try {
      await request();
      setShowReasonBox(prev => ({ ...prev, [id]: false }));
      setReasons(prev => ({ ...prev, [id]: '' }));
      await fetchAll();
    } catch (e) {
      toast(e.response?.data?.detail || failMessage, { kind: 'error' });
    } finally {
      setDeciding(prev => ({ ...prev, [id]: false }));
    }
  };

  const decideVoterRequest = async (changeId, decision) => {
    if (missingId()) return;
    if (decision === 'deny' && needReason(changeId, 'denying this request')) return;
    await run(changeId, () => api.post(`/admin/student-changes/${changeId}/decide`, {
      financial_controller_id: fcId,
      decision,
      reason: (reasons[changeId] || '').trim(),
    }), 'Failed to record decision.');
  };

  const decideCandidatePayment = async (appId, verb) => {
    if (missingId()) return;
    if (verb === 'reject' && needReason(appId, 'rejecting this payment')) return;
    await run(appId, () => api.post(`/admin/applications/${appId}/${verb === 'clear' ? 'finance-clear' : 'finance-reject'}`, {
      financial_controller_id: fcId,
      reason: (reasons[appId] || '').trim(),
    }), verb === 'clear' ? 'Payment clearance failed.' : 'Payment rejection failed.');
  };

  // ── Filtered lists ──

  const voterLists = {
    pending:  changes.filter(c => c.status === 'pending'),
    approved: changes.filter(c => c.status === 'approved'),
    denied:   changes.filter(c => c.status === 'denied'),
  };
  const candidateLists = {
    pending:  apps.filter(a => a.status === 'pending' && !a.finance_cleared),
    approved: apps.filter(a => a.finance_cleared),
    denied:   apps.filter(a => a.finance_rejected),
  };

  const tabs = [
    { id: 'voters',     label: 'Voter payments',     count: voterLists.pending.length },
    { id: 'candidates', label: 'Candidate payments', count: candidateLists.pending.length },
    ...SHARED_TAB_DEFS,
  ];

  const lists = activeTab === 'candidates' ? candidateLists : voterLists;
  const labels = STATUS_LABELS[activeTab] || STATUS_LABELS.voters;
  const currentList = isSection ? lists[view] : [];

  // Reason box + shared "reason" control used by both card types.
  const reasonBox = (id, placeholder) => showReasonBox[id] && (
    <div style={{ marginBottom: '10px' }}>
      <textarea
        style={{ ...inp, height: '70px', resize: 'vertical' }}
        placeholder={placeholder}
        value={reasons[id] || ''}
        onChange={e => setReasons(prev => ({ ...prev, [id]: e.target.value }))}
      />
    </div>
  );
  const reasonToggle = (id) => (
    <button style={ghostBtn} onClick={() => setShowReasonBox(prev => ({ ...prev, [id]: !prev[id] }))}>
      {showReasonBox[id] ? 'Hide reason' : '+ Add reason'}
    </button>
  );

  return (
    <div style={outerWrap} className="outer-wrap">
      <div style={container} className="dashboard-shell">

        {/* ── Header ── */}
        <AdminHeader
          title="Financial Controller"
          subtitle="Verify voter and candidate payments. Every clearance and rejection is logged."
          lastSynced={lastSynced}
          onRefresh={() => fetchAll()}
          refreshing={loading}
          onLogout={onLogout}
        />

        {/* Financial Controller ID prompt — shown if not stored yet */}
        {!fcId && (
          <div style={promptBox}>
            <p style={{ margin: '0 0 10px', fontWeight: '600', color: 'var(--text-color)' }}>
              Enter your Student ID to record your decisions correctly:
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <input
                data-fcid-input
                style={{ ...inp, flex: 1 }}
                placeholder="e.g. 22/U/IED/1086/GV"
                onBlur={e => {
                  const val = e.target.value.trim();
                  if (val) {
                    setFcId(val);
                    sessionStorage.setItem('financial_controller_id', val);
                  }
                }}
              />
              <button style={greenBtn} onClick={() => {
                const el = document.querySelector('[data-fcid-input]');
                if (el && el.value.trim()) {
                  setFcId(el.value.trim());
                  sessionStorage.setItem('financial_controller_id', el.value.trim());
                }
              }}>Confirm</button>
            </div>
            <p style={{ margin: '8px 0 0', fontSize: '12px', opacity: 0.5 }}>
              This is stored only for this browser session and used to tag your decisions.
            </p>
          </div>
        )}

        {fcId && (
          <div style={infoPill}>
            Deciding as: <strong>{fcId}</strong>
            <button style={{ ...ghostBtn, padding: '3px 10px', marginLeft: '10px', fontSize: '12px' }}
              onClick={() => { setFcId(''); sessionStorage.removeItem('financial_controller_id'); }}>
              Change
            </button>
          </div>
        )}

        {/* ── Tabs ── */}
        <TabBar tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />
        <div style={{ marginBottom: '20px' }} />

        {/* ── Pending / Approved / Denied view (both money tabs) ── */}
        {isSection && (
          <>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
              {['pending', 'approved', 'denied'].map(v => (
                <button
                  key={v}
                  style={pill(view === v)}
                  onClick={() => setStatusView(v)}
                >
                  {labels[v]} ({lists[v].length})
                </button>
              ))}
            </div>

            {activeTab === 'candidates' && view === 'pending' && (
              <p style={{ margin: '0 0 14px', fontSize: '12px', opacity: 0.6 }}>
                The Vetting Panel can only vote on a candidate once you clear their payment.
              </p>
            )}

            {currentList.length === 0 && !loading && (
              <div style={emptyState}>
                <p style={{ opacity: 0.5 }}>
                  {activeTab === 'candidates'
                    ? `No ${labels[view].toLowerCase()} candidate payments.`
                    : `No ${view} requests.`}
                </p>
              </div>
            )}
          </>
        )}

        {/* ── Voter-register request cards ── */}
        {activeTab === 'voters' && (
        <ScrollList>
        {currentList.map(change => {
          const isDecidingNow = deciding[change._id];

          return (
            <div key={change._id} style={appCard}>

              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                <div>
                  <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>
                    {change.change_type === 'add' ? <>Add Student</> : <>Remove Student</>}
                  </b>
                  <span style={{ ...statusBadge(change.status), marginLeft: '10px' }}>
                    {change.status.toUpperCase()}
                  </span>
                </div>
                <small style={{ opacity: 0.45 }}>{shortDate(change.requested_at)}</small>
              </div>

              <p style={{ margin: '8px 0 2px', fontSize: '13px', color: 'var(--text-color)' }}>
                <b>Student:</b> {change.full_name} — <code style={{ fontSize: '12px' }}>{regNo(change.student_id)}</code>
              </p>
              {change.change_type === 'add' && (change.phones?.length > 0 || change.phone) && (
                <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.6 }}>
                  Phone{(change.phones?.length || 1) > 1 ? 's' : ''}: {change.phones?.length ? change.phones.join(', ') : change.phone}
                </p>
              )}
              <p style={{ margin: '6px 0', fontSize: '13px', opacity: 0.8 }}>
                <b>Reason:</b> {change.reason}
              </p>
              <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.5 }}>
                Requested by: {change.requested_by}
              </p>

              {change.payment_method && (
                <div style={payBox}>
                  <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                    Payment: <strong style={{ color: 'var(--text-color)' }}>{change.payment_method}</strong>
                  </p>
                  <ReceiptLink url={change.payment_proof_url} />
                </div>
              )}

              {/* ── Pending: decision actions ── */}
              {change.status === 'pending' ? (
                <div style={{ marginTop: '14px' }}>
                  {reasonBox(change._id, 'Reason (required to deny)…')}
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button
                      style={{ ...greenBtn, flex: 1 }}
                      disabled={isDecidingNow}
                      onClick={() => decideVoterRequest(change._id, 'approve')}
                    >
                      {isDecidingNow ? 'Submitting…' : <>Approve</>}
                    </button>
                    <button
                      style={{ ...redBtn, flex: 1 }}
                      disabled={isDecidingNow}
                      onClick={() => decideVoterRequest(change._id, 'deny')}
                    >
                      {isDecidingNow ? 'Submitting…' : <>Deny</>}
                    </button>
                    {reasonToggle(change._id)}
                  </div>
                </div>
              ) : (
                <p style={{ margin: '10px 0 0', fontSize: '12px', opacity: 0.6 }}>
                  Decided by: {change.decided_by || '—'}
                  {change.decision_reason && ` · "${change.decision_reason}"`}
                </p>
              )}
            </div>
          );
        })}
        </ScrollList>
        )}

        {/* ── Candidate payment cards ── */}
        {activeTab === 'candidates' && (
        <ScrollList>
        {currentList.map(app => {
          const isDecidingNow = deciding[app._id];
          const state = app.finance_rejected ? 'denied' : app.finance_cleared ? 'approved' : 'pending';

          return (
            <div key={app._id} style={appCard}>

              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                <div>
                  <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>{app.full_name}</b>
                  <span style={{ ...statusBadge(state), marginLeft: '10px' }}>
                    {labels[state].toUpperCase()}
                  </span>
                </div>
                <small style={{ opacity: 0.45 }}>{shortDate(app.submitted_at)}</small>
              </div>

              <p style={{ margin: '6px 0 2px', fontSize: '13px', color: 'var(--success)', fontWeight: '600' }}>
                {app.position_title || app.position_id}
              </p>
              <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.55 }}>
                Student ID: {regNo(app.student_id)}
              </p>

              <div style={payBox}>
                {app.payment_method && (
                  <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                    Payment method: <strong style={{ color: 'var(--text-color)' }}>{app.payment_method}</strong>
                  </p>
                )}
                <p style={{ margin: '0 0 6px', fontSize: '13px' }}>
                  Required amount:{' '}
                  <strong style={{ color: 'var(--success)' }}>
                    {app.fee_required ? money(app.fee_required) : 'not set for this position'}
                  </strong>
                </p>
                {app.payment_proof_url
                  ? <ReceiptLink url={app.payment_proof_url} />
                  : <small style={{ opacity: 0.5 }}>No receipt attached.</small>}
              </div>

              {state === 'pending' && (
                <div style={{ marginTop: '14px' }}>
                  {reasonBox(app._id, 'Reason (required to reject; optional note when clearing)…')}
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button
                      style={{ ...greenBtn, flex: 1 }}
                      disabled={isDecidingNow}
                      onClick={() => decideCandidatePayment(app._id, 'clear')}
                    >
                      {isDecidingNow ? 'Submitting…' : <>Clear payment</>}
                    </button>
                    <button
                      style={{ ...redBtn, flex: 1 }}
                      disabled={isDecidingNow}
                      onClick={() => decideCandidatePayment(app._id, 'reject')}
                    >
                      {isDecidingNow ? 'Submitting…' : <>Reject</>}
                    </button>
                    {reasonToggle(app._id)}
                  </div>
                </div>
              )}

              {state === 'approved' && (
                <p style={{ margin: '10px 0 0', fontSize: '12px', opacity: 0.6 }}>
                  Cleared by: {app.finance_cleared_by === 'superadmin_override' ? 'Superadmin override' : (app.finance_cleared_by || '—')}
                  {app.finance_clear_note && ` · "${app.finance_clear_note}"`}
                  {' · '}Application: {app.status}
                </p>
              )}

              {state === 'denied' && (
                <p style={{ margin: '10px 0 0', fontSize: '12px', opacity: 0.6 }}>
                  Rejected by: {app.finance_rejected_by || '—'}
                  {app.finance_rejection_reason && ` · "${app.finance_rejection_reason}"`}
                </p>
              )}
            </div>
          );
        })}
        </ScrollList>
        )}

        <SharedTabPanels activeTab={activeTab} />
      </div>
    </div>
  );
}

// ── Helpers ──
function statusBadge(status) {
  const map = {
    pending:  { background: 'color-mix(in srgb, var(--warning) 20%, transparent)', color: 'var(--warning)' },
    approved: { background: 'color-mix(in srgb, var(--success) 20%, transparent)', color: 'var(--success)' },
    denied:   { background: 'color-mix(in srgb, var(--danger) 20%, transparent)',  color: 'var(--danger)' },
  };
  return {
    fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
    ...(map[status] || {}),
  };
}

// ── Styles (mirrors CommissionDashboard.jsx) ──
const outerWrap  = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container  = { width: '100%', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const appCard    = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '18px', marginBottom: '14px', backgroundColor: 'var(--bg-color)' };
const payBox     = { marginTop: '10px', padding: '10px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' };
const inp        = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const btn        = { padding: '9px 16px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const greenBtn   = { ...btn, backgroundColor: '#2ecc71' };
const redBtn     = { ...btn, backgroundColor: '#e74c3c' };
const ghostBtn   = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const pill       = (active) => ({
  padding: '6px 14px', borderRadius: '999px', cursor: 'pointer', fontSize: '12px', fontWeight: active ? 'bold' : 'normal',
  border: `1px solid ${active ? 'var(--success)' : 'var(--border-color)'}`,
  background: active ? 'color-mix(in srgb, var(--success) 15%, transparent)' : 'none',
  color: active ? 'var(--success)' : 'var(--text-color)',
});
const promptBox  = { border: '1px dashed var(--border-color)', borderRadius: '12px', padding: '20px', marginBottom: '20px', backgroundColor: 'var(--bg-color)' };
const infoPill   = { fontSize: '13px', opacity: 0.7, marginBottom: '18px', padding: '8px 14px', backgroundColor: 'var(--bg-color)', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'inline-flex', alignItems: 'center' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
