import React, { useEffect, useState } from 'react';
import api from '../api';

export default function FinancialControllerDashboard({ onLogout }) {

  const [activeTab, setActiveTab]     = useState('pending');
  const [changes, setChanges]         = useState([]);
  const [loading, setLoading]         = useState(false);
  const [fcId, setFcId]               = useState('');
  const [reasons, setReasons]         = useState({});   // { change_id: string }
  const [showReasonBox, setShowReasonBox] = useState({}); // { change_id: bool }
  const [deciding, setDeciding]       = useState({});   // { change_id: bool }

  // On mount — figure out who this Financial Controller is from sessionStorage
  useEffect(() => {
    const stored = sessionStorage.getItem('financial_controller_id') || '';
    setFcId(stored);
    fetchAll();
  }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const res = await api.get('/admin/student-changes');
      setChanges(res.data);
    } catch (e) {
      console.error('Fetch error:', e);
    } finally {
      setLoading(false);
    }
  };

  // ── Decisions ──

  const decide = async (changeId, decision) => {
    if (!fcId.trim()) {
      alert('Your Financial Controller ID was not found in this session. Please log out and log in again.');
      return;
    }
    setDeciding(prev => ({ ...prev, [changeId]: true }));
    try {
      await api.post(`/admin/student-changes/${changeId}/decide`, {
        financial_controller_id: fcId,
        decision,
        reason: reasons[changeId] || '',
      });
      setShowReasonBox(prev => ({ ...prev, [changeId]: false }));
      await fetchAll();
    } catch (e) {
      alert(e.response?.data?.detail || 'Failed to record decision.');
    } finally {
      setDeciding(prev => ({ ...prev, [changeId]: false }));
    }
  };

  // ── Filtered lists ──

  const pending  = changes.filter(c => c.status === 'pending');
  const approved = changes.filter(c => c.status === 'approved');
  const denied   = changes.filter(c => c.status === 'denied');

  const listFor = (tab) => {
    if (tab === 'pending')  return pending;
    if (tab === 'approved') return approved;
    if (tab === 'denied')   return denied;
    return [];
  };

  const tabs = [
    { id: 'pending',  label: 'Pending',  count: pending.length },
    { id: 'approved', label: 'Approved', count: approved.length },
    { id: 'denied',   label: 'Denied',   count: denied.length },
  ];

  const currentList = listFor(activeTab);

  return (
    <div style={outerWrap}>
      <div style={container} className="dashboard-shell">

        {/* ── Header ── */}
        <div style={headerFlex}>
          <div>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>💰 Financial Controller</h2>
            <span style={{ fontSize: '12px', opacity: 0.5 }}>
              Verify payment status and decide on student register change requests
            </span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button style={ghostBtn} onClick={fetchAll} disabled={loading}>
              {loading ? 'Syncing…' : '🔄 Refresh'}
            </button>
            <button style={redBtn} onClick={onLogout}>Logout</button>
          </div>
        </div>

        {/* Financial Controller ID prompt — shown if not stored yet */}
        {!fcId && (
          <div style={promptBox}>
            <p style={{ margin: '0 0 10px', fontWeight: '600', color: 'var(--text-color)' }}>
              Enter your Student ID to record your decisions correctly:
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <input
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
        <div style={tabBar} className="tab-scroll">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              style={{ ...tab, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}>
              {t.label}
              <span style={countPill}>{t.count}</span>
            </button>
          ))}
        </div>

        {/* ── Empty state ── */}
        {currentList.length === 0 && !loading && (
          <div style={emptyState}>
            <div style={{ fontSize: '40px', marginBottom: '10px' }}>
              {activeTab === 'pending' ? '📭' : activeTab === 'approved' ? '✅' : '📂'}
            </div>
            <p style={{ opacity: 0.5 }}>No {activeTab} requests.</p>
          </div>
        )}

        {/* ── Request cards ── */}
        {currentList.map(change => {
          const isDecidingNow = deciding[change._id];

          return (
            <div key={change._id} style={appCard}>

              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                <div>
                  <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>
                    {change.change_type === 'add' ? '➕ Add Student' : '➖ Remove Student'}
                  </b>
                  <span style={{ ...statusBadge(change.status), marginLeft: '10px' }}>
                    {change.status.toUpperCase()}
                  </span>
                </div>
                <small style={{ opacity: 0.45 }}>
                  {new Date(change.requested_at).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' })}
                </small>
              </div>

              <p style={{ margin: '8px 0 2px', fontSize: '13px', color: 'var(--text-color)' }}>
                <b>Student:</b> {change.full_name} — <code style={{ fontSize: '12px' }}>{change.student_id}</code>
              </p>
              {change.change_type === 'add' && (
                <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.6 }}>
                  Phone: {change.phone}
                </p>
              )}
              <p style={{ margin: '6px 0', fontSize: '13px', opacity: 0.8 }}>
                <b>Reason:</b> {change.reason}
              </p>
              <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.5 }}>
                Requested by: {change.requested_by}
              </p>

              {change.payment_method && (
                <div style={{ marginTop: '10px', padding: '10px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                    Payment: <strong style={{ color: 'var(--text-color)' }}>{change.payment_method}</strong>
                  </p>
                  {change.payment_proof_url && (
                    <a href={change.payment_proof_url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: '12px', color: '#3498db', textDecoration: 'none' }}>
                      🧾 View Receipt
                    </a>
                  )}
                </div>
              )}

              {/* ── Pending: decision actions ── */}
              {change.status === 'pending' ? (
                <div style={{ marginTop: '14px' }}>
                  {showReasonBox[change._id] && (
                    <div style={{ marginBottom: '10px' }}>
                      <textarea
                        style={{ ...inp, height: '70px', resize: 'vertical' }}
                        placeholder="Optional reason for this decision…"
                        value={reasons[change._id] || ''}
                        onChange={e => setReasons(prev => ({ ...prev, [change._id]: e.target.value }))}
                      />
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button
                      style={{ ...greenBtn, flex: 1 }}
                      disabled={isDecidingNow}
                      onClick={() => decide(change._id, 'approve')}
                    >
                      {isDecidingNow ? 'Submitting…' : '✅ Approve'}
                    </button>
                    <button
                      style={{ ...redBtn, flex: 1 }}
                      disabled={isDecidingNow}
                      onClick={() => decide(change._id, 'deny')}
                    >
                      {isDecidingNow ? 'Submitting…' : '❌ Deny'}
                    </button>
                    <button
                      style={ghostBtn}
                      onClick={() => setShowReasonBox(prev => ({ ...prev, [change._id]: !prev[change._id] }))}
                    >
                      {showReasonBox[change._id] ? 'Hide reason' : '+ Add reason'}
                    </button>
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
const container  = { width: '95%', maxWidth: '1200px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const headerFlex = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' };
const tabBar     = { display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap' };
const tab        = { background: 'none', border: 'none', padding: '10px 14px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' };
const countPill  = { fontSize: '11px', backgroundColor: 'var(--border-color)', borderRadius: '10px', padding: '1px 7px', fontWeight: '700' };
const appCard    = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '18px', marginBottom: '14px', backgroundColor: 'var(--bg-color)' };
const inp        = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const btn        = { padding: '9px 16px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const greenBtn   = { ...btn, backgroundColor: '#2ecc71' };
const redBtn     = { ...btn, backgroundColor: '#e74c3c' };
const ghostBtn   = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const promptBox  = { border: '1px dashed var(--border-color)', borderRadius: '12px', padding: '20px', marginBottom: '20px', backgroundColor: 'var(--bg-color)' };
const infoPill   = { fontSize: '13px', opacity: 0.7, marginBottom: '18px', padding: '8px 14px', backgroundColor: 'var(--bg-color)', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'inline-flex', alignItems: 'center' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
