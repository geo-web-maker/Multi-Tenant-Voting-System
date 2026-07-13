import React, { useEffect, useState } from 'react';
import api from '../api';

export default function CommissionDashboard({ onLogout }) {

  const [activeTab, setActiveTab]       = useState('pending');
  const [applications, setApplications] = useState([]);
  const [loading, setLoading]           = useState(false);
  const [commissionerId, setCommissionerId] = useState('');
  const [totalCommissioners, setTotalCommissioners] = useState(0);
  const [denyReasons, setDenyReasons]   = useState({});  // { app_id: string }
  const [showDenyBox, setShowDenyBox]   = useState({});  // { app_id: bool }
  const [voting, setVoting]             = useState({});  // { app_id: bool }
  const [studentChanges, setStudentChanges] = useState([]);
  const [commissioners, setCommissioners] = useState([]);
  const [financeClearing, setFinanceClearing] = useState({});

  // On mount — figure out who this commissioner is from sessionStorage
  useEffect(() => {
    const stored = sessionStorage.getItem('commissioner_id') || '';
    setCommissionerId(stored);
    fetchAll();
  }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [appsRes, commRes, scRes] = await Promise.all([
          api.get('/admin/applications'),
          api.get('/superadmin/commissioners'),
          api.get('/admin/student-changes'),
        ]);
        setApplications(appsRes.data);
        setCommissioners(commRes.data);
        setTotalCommissioners(commRes.data.length);
        setStudentChanges(scRes.data);
    } catch (e) {
      console.error('Fetch error:', e);
    } finally {
      setLoading(false);
    }
  };

  // ── Voting ──

  const castVote = async (appId, vote) => {
    if (!commissionerId.trim()) {
      alert('Your commissioner ID was not found in this session. Please log out and log in again.');
      return;
    }
    setVoting(prev => ({ ...prev, [appId]: true }));
    try {
      await api.post(`/admin/applications/${appId}/vote`, {
        commissioner_id: commissionerId,
        vote,
        reason: denyReasons[appId] || '',
      });
      setShowDenyBox(prev => ({ ...prev, [appId]: false }));
      setDenyReasons(prev => ({ ...prev, [appId]: '' }));
      await fetchAll();
    } catch (e) {
      alert(e.response?.data?.detail || 'Vote failed. You may have already voted on this application.');
    } finally {
      setVoting(prev => ({ ...prev, [appId]: false }));
    }
  };

  const castRemovalVote = async (appId, vote) => {
    if (!commissionerId.trim()) {
      alert('Your commissioner ID was not found in this session. Please log out and log in again.');
      return;
    }
    setVoting(prev => ({ ...prev, [`remove_${appId}`]: true }));
    try {
      await api.post(`/admin/applications/${appId}/vote-remove`, {
        commissioner_id: commissionerId,
        vote,
        reason: denyReasons[`remove_${appId}`] || '',
      });
      await fetchAll();
    } catch (e) {
      alert(e.response?.data?.detail || 'Removal vote failed.');
    } finally {
      setVoting(prev => ({ ...prev, [`remove_${appId}`]: false }));
    }
  };

  const castFinanceClear = async (appId) => {
    if (!commissionerId.trim()) {
      alert('Your commissioner ID was not found in this session. Please log out and log in again.');
      return;
    }
    setFinanceClearing(prev => ({ ...prev, [appId]: true }));
    try {
      await api.post(`/admin/applications/${appId}/finance-clear`, {
        commissioner_id: commissionerId,
      });
      await fetchAll();
    } catch (e) {
      alert(e.response?.data?.detail || 'Finance clearance failed.');
    } finally {
      setFinanceClearing(prev => ({ ...prev, [appId]: false }));
    }
  };

  // ── Helpers ──

  const safeKey = (id) => id.replace(/[./]/g, '_');

  const myVoteFor = (app) => {
    if (!app.votes) return null;
    return app.votes[safeKey(commissionerId)] || null;
  };

  const myRemovalVoteFor = (app) => {
    if (!app.removal_votes) return null;
    return app.removal_votes[safeKey(commissionerId)] || null;
  };

  const voteCount = (app) => {
    const votes = app.votes || {};
    return {
      approve: Object.values(votes).filter(v => v === 'approve').length,
      deny:    Object.values(votes).filter(v => v === 'deny').length,
      total:   Object.keys(votes).length,
    };
  };

  const removalVoteCount = (app) => {
    const votes = app.removal_votes || {};
    return {
      approve: Object.values(votes).filter(v => v === 'approve').length,
      deny:    Object.values(votes).filter(v => v === 'deny').length,
      total:   Object.keys(votes).length,
    };
  };

  const isFinanceCommissioner = commissioners.some(
    c => c.student_id === commissionerId && c.is_finance_commissioner
  );

  const majorityRequired = (total) => Math.floor(total / 2) + 1;

  // ── Filtered lists ──

  const pending  = applications.filter(a => a.status === 'pending');
  const approved = applications.filter(a => a.status === 'approved');
  const denied   = applications.filter(a => a.status === 'denied');
  const removed  = applications.filter(a => a.status === 'removed');

  const listFor = (tab) => {
    if (tab === 'pending')  return pending;
    if (tab === 'approved') return approved;
    if (tab === 'denied')   return denied;
    if (tab === 'removed')  return removed;
    return [];
  };

  const tabs = [
    { id: 'pending',         label: 'Pending',         count: pending.length },
    { id: 'approved',        label: 'Approved',        count: approved.length },
    { id: 'denied',          label: 'Denied',          count: denied.length },
    { id: 'removed',         label: 'Removed',         count: removed.length },
    { id: 'student_changes', label: 'Student Changes', count: studentChanges.filter(c => c.status === 'pending').length },
  ];

  const currentList = listFor(activeTab);

  return (
    <div style={outerWrap}>
      <div style={container}>

        {/* ── Header ── */}
        <div style={headerFlex}>
          <div>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>🏛️ Election Commission</h2>
            <span style={{ fontSize: '12px', opacity: 0.5 }}>
              {totalCommissioners} commissioner{totalCommissioners !== 1 ? 's' : ''} total ·
              Full consensus required for approval or removal
            </span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button style={ghostBtn} onClick={fetchAll} disabled={loading}>
              {loading ? 'Syncing…' : '🔄 Refresh'}
            </button>
            <button style={redBtn} onClick={onLogout}>Logout</button>
          </div>
        </div>

        {/* Commissioner ID prompt — shown if not stored yet */}
        {!commissionerId && (
          <div style={promptBox}>
            <p style={{ margin: '0 0 10px', fontWeight: '600', color: 'var(--text-color)' }}>
              Enter your Student ID to record your votes correctly:
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <input
                style={{ ...inp, flex: 1 }}
                placeholder="e.g. 22/U/IED/1086/GV"
                onBlur={e => {
                  const val = e.target.value.trim();
                  if (val) {
                    setCommissionerId(val);
                    sessionStorage.setItem('commissioner_id', val);
                  }
                }}
              />
              <button style={greenBtn} onClick={() => {
                const el = document.querySelector('[data-cid-input]');
                if (el && el.value.trim()) {
                  setCommissionerId(el.value.trim());
                  sessionStorage.setItem('commissioner_id', el.value.trim());
                }
              }}>Confirm</button>
            </div>
            <p style={{ margin: '8px 0 0', fontSize: '12px', opacity: 0.5 }}>
              This is stored only for this browser session and used to tag your votes.
            </p>
          </div>
        )}

        {commissionerId && (
          <div style={infoPill}>
            Voting as: <strong>{commissionerId}</strong>
            <button style={{ ...ghostBtn, padding: '3px 10px', marginLeft: '10px', fontSize: '12px' }}
              onClick={() => { setCommissionerId(''); sessionStorage.removeItem('commissioner_id'); }}>
              Change
            </button>
          </div>
        )}

        {/* ── Tabs ── */}
        <div style={tabBar}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              style={{ ...tab, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}>
              {t.label}
              <span style={countPill}>{t.count}</span>
            </button>
          ))}
        </div>

        {/* ── Empty state ── */}
        {activeTab !== 'student_changes' && currentList.length === 0 && !loading && (
          <div style={emptyState}>
            <div style={{ fontSize: '40px', marginBottom: '10px' }}>
              {activeTab === 'pending' ? '📭' : activeTab === 'approved' ? '✅' : '📂'}
            </div>
            <p style={{ opacity: 0.5 }}>
              No {activeTab} applications.
              {activeTab === 'pending' && ' Check back when applicants submit their forms.'}
            </p>
          </div>
        )}

        {/* ── Application cards ── */}
        {activeTab !== 'student_changes' && currentList.map(app => {
          const vc      = voteCount(app);
          const rvc     = removalVoteCount(app);
          const myVote  = myVoteFor(app);
          const myRVote = myRemovalVoteFor(app);
          const isVotingNow        = voting[app._id];
          const isRemovalVotingNow = voting[`remove_${app._id}`];

          return (
            <div key={app._id} style={appCard}>

              {/* Top row — photo + info + status */}
              <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
                {app.image_url ? (
                  <img src={app.image_url} alt="" style={avatar} />
                ) : (
                  <div style={{ ...avatar, backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '22px' }}>
                    👤
                  </div>
                )}

                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '6px' }}>
                    <div>
                      <b style={{ fontSize: '15px', color: 'var(--text-color)' }}>{app.full_name}</b>
                      <span style={{ ...statusBadge(app.status), marginLeft: '10px' }}>
                        {app.status.toUpperCase()}
                        {app.superadmin_override && ' · SA Override'}
                      </span>
                    </div>
                    <small style={{ opacity: 0.45 }}>
                      {new Date(app.submitted_at).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </small>
                  </div>

                  <p style={{ margin: '4px 0', fontSize: '13px', color: '#2ecc71', fontWeight: '600' }}>
                    {app.position_title || app.position_id}
                  </p>
                  <p style={{ margin: '2px 0', fontSize: '12px', opacity: 0.55 }}>
                    Student ID: {app.student_id}
                  </p>

                  {app.manifesto && (
                    <p style={{ margin: '10px 0 0', fontSize: '13px', opacity: 0.85, lineHeight: '1.6', whiteSpace: 'pre-line' }}>
                      {app.manifesto}
                    </p>
                  )}
                  
                  {app.payment_method && (
                    <div style={{ marginTop: '10px', padding: '10px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                      <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                        Payment method: <strong style={{ color: 'var(--text-color)' }}>{app.payment_method}</strong>
                      </p>
                      {app.payment_proof_url && (
                        <a
                          href={app.payment_proof_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ fontSize: '12px', color: '#3498db', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                        >
                          🧾 View Receipt
                        </a>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Vote tally */}
              {app.status === 'pending' && app.finance_cleared && totalCommissioners > 0 && (
                <div style={tallyRow}>
                  <span style={{ opacity: 0.6, fontSize: '12px' }}>
                    Commission votes ({vc.total} of {totalCommissioners}):
                  </span>
                  <span style={{ color: '#2ecc71', fontWeight: '600', fontSize: '13px' }}>
                    {vc.approve} approve
                  </span>
                  <span style={{ color: '#e74c3c', fontWeight: '600', fontSize: '13px' }}>
                    {vc.deny} deny
                  </span>
                  <span style={{ opacity: 0.45, fontSize: '12px' }}>
                    · majority needs {majorityRequired(totalCommissioners)}
                  </span>
                </div>
              )}

              {/* Removal vote tally */}
              {app.status === 'approved' && (
                <div style={tallyRow}>
                  <span style={{ opacity: 0.6, fontSize: '12px' }}>
                    Removal votes ({rvc.total} of {totalCommissioners}):
                  </span>
                  <span style={{ color: '#e74c3c', fontWeight: '600', fontSize: '13px' }}>
                    {rvc.approve} for removal
                  </span>
                  <span style={{ color: '#2ecc71', fontWeight: '600', fontSize: '13px' }}>
                    {rvc.deny} against
                  </span>
                  <span style={{ opacity: 0.45, fontSize: '12px' }}>
                    · majority needs {majorityRequired(totalCommissioners)}
                  </span>
                </div>
              )}

              {/* ── Pending: finance-clear gate, then approve / deny actions ── */}
              {app.status === 'pending' && !app.superadmin_override && (
                <div style={{ marginTop: '14px' }}>
                  {!app.finance_cleared ? (
                    isFinanceCommissioner ? (
                      <button
                        style={{ ...greenBtn, width: '100%' }}
                        disabled={financeClearing[app._id]}
                        onClick={() => castFinanceClear(app._id)}
                      >
                        {financeClearing[app._id] ? 'Clearing…' : '💰 Clear for Finance'}
                      </button>
                    ) : (
                      <div style={lockedNote}>
                        🔒 Awaiting Finance Commissioner clearance before voting can open.
                      </div>
                    )
                  ) : myVote ? (
                    <div style={myVoteRow(myVote)}>
                      {myVote === 'approve'
                        ? '✅ You voted to approve this application.'
                        : '❌ You voted to deny this application.'}
                      <span style={{ opacity: 0.6, fontSize: '12px', marginLeft: '8px' }}>
                        Resolves once a majority is reached.
                      </span>
                    </div>
                  ) : (
                    <>
                      {showDenyBox[app._id] && (
                        <div style={{ marginBottom: '10px' }}>
                          <textarea
                            style={{ ...inp, height: '70px', resize: 'vertical' }}
                            placeholder="Optional reason for denial…"
                            value={denyReasons[app._id] || ''}
                            onChange={e => setDenyReasons(prev => ({ ...prev, [app._id]: e.target.value }))}
                          />
                        </div>
                      )}
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        <button
                          style={{ ...greenBtn, flex: 1 }}
                          disabled={isVotingNow}
                          onClick={() => castVote(app._id, 'approve')}
                        >
                          {isVotingNow ? 'Submitting…' : '✅ Approve'}
                        </button>
                        {showDenyBox[app._id] ? (
                          <button
                            style={{ ...redBtn, flex: 1 }}
                            disabled={isVotingNow}
                            onClick={() => castVote(app._id, 'deny')}
                          >
                            {isVotingNow ? 'Submitting…' : '❌ Confirm Deny'}
                          </button>
                        ) : (
                          <button
                            style={{ ...ghostBtn, flex: 1, color: '#e74c3c', borderColor: '#e74c3c' }}
                            onClick={() => setShowDenyBox(prev => ({ ...prev, [app._id]: true }))}
                          >
                            ❌ Deny
                          </button>
                        )}
                        {showDenyBox[app._id] && (
                          <button
                            style={ghostBtn}
                            onClick={() => setShowDenyBox(prev => ({ ...prev, [app._id]: false }))}
                          >
                            Cancel
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* ── Approved: removal voting ── */}
              {app.status === 'approved' && (
                <div style={{ marginTop: '14px' }}>
                  {myRVote ? (
                    <div style={myVoteRow(myRVote === 'approve' ? 'deny' : 'approve')}>
                      {myRVote === 'approve'
                        ? '🗑️ You voted to remove this candidate.'
                        : '🛡️ You voted to keep this candidate.'}
                      <span style={{ opacity: 0.6, fontSize: '12px', marginLeft: '8px' }}>
                        Resolves once a majority is reached.
                      </span>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                      <button
                        style={{ ...redBtn, flex: 1 }}
                        disabled={isRemovalVotingNow}
                        onClick={() => castRemovalVote(app._id, 'approve')}
                      >
                        {isRemovalVotingNow ? 'Submitting…' : '🗑️ Vote to Remove'}
                      </button>
                      <button
                        style={{ ...ghostBtn, flex: 1 }}
                        disabled={isRemovalVotingNow}
                        onClick={() => castRemovalVote(app._id, 'deny')}
                      >
                        🛡️ Vote to Keep
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Superadmin override notice */}
              {app.superadmin_override && (
                <div style={overrideNote}>
                  This was decided by the superadmin — commission voting bypassed.
                </div>
              )}

            </div>
          );
        })}
        
        {/* ── Student Changes tab ── */}
        {activeTab === 'student_changes' && (
          <div>
            {studentChanges.length === 0 && (
              <div style={emptyState}>
                <div style={{ fontSize: '40px', marginBottom: '10px' }}>👥</div>
                <p style={{ opacity: 0.5 }}>No student change requests.</p>
              </div>
            )}
            {studentChanges.map(change => {
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
                    <div style={{ marginTop: '8px', padding: '8px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
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

                   {change.status === 'pending' ? (
                    <div style={lockedNote}>
                      🔒 Awaiting the Financial Controller's decision on this request.
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
        )}
        
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
    removed:  { background: '#95a5a620', color: '#95a5a6' },
  };
  return {
    fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
    ...(map[status] || {}),
  };
}

function myVoteRow(vote) {
  return {
    padding: '10px 14px',
    borderRadius: '8px',
    fontSize: '13px',
    fontWeight: '600',
    backgroundColor: vote === 'approve' ? '#2ecc7115' : '#e74c3c15',
    color: vote === 'approve' ? '#2ecc71' : '#e74c3c',
    border: `1px solid ${vote === 'approve' ? '#2ecc7140' : '#e74c3c40'}`,
  };
}

// ── Styles ──
const outerWrap  = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container  = { width: '95%', maxWidth: '1200px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const headerFlex = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' };
const tabBar     = { display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap' };
const tab        = { background: 'none', border: 'none', padding: '10px 14px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' };
const countPill  = { fontSize: '11px', backgroundColor: 'var(--border-color)', borderRadius: '10px', padding: '1px 7px', fontWeight: '700' };
const appCard    = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '18px', marginBottom: '14px', backgroundColor: 'var(--bg-color)' };
const avatar     = { width: '64px', height: '64px', borderRadius: '10px', objectFit: 'cover', flexShrink: 0 };
const tallyRow   = { display: 'flex', gap: '14px', alignItems: 'center', flexWrap: 'wrap', marginTop: '12px', padding: '8px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' };
const inp        = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const btn        = { padding: '9px 16px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const greenBtn   = { ...btn, backgroundColor: '#2ecc71' };
const redBtn     = { ...btn, backgroundColor: '#e74c3c' };
const ghostBtn   = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const promptBox  = { border: '1px dashed var(--border-color)', borderRadius: '12px', padding: '20px', marginBottom: '20px', backgroundColor: 'var(--bg-color)' };
const infoPill   = { fontSize: '13px', opacity: 0.7, marginBottom: '18px', padding: '8px 14px', backgroundColor: 'var(--bg-color)', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'inline-flex', alignItems: 'center' };
const overrideNote = { marginTop: '12px', fontSize: '12px', opacity: 0.55, fontStyle: 'italic' };
const lockedNote = { padding: '10px 14px', backgroundColor: '#f1c40f15', borderRadius: '8px', border: '1px solid #f1c40f40', color: '#f1c40f', fontSize: '12px', fontWeight: '600' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
