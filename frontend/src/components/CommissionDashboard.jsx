import React, { useEffect, useState } from 'react';
import api from '../api';
import { usePersistedTab } from '../session';
import { useToast, ScrollList } from './UIFeedback';
import usePolling from '../hooks/usePolling';
import { SHARED_TAB_DEFS, SharedTabPanels, OfficialCertificationBlock } from './SharedAdminPanels';
import ContactChangesQueue from './ContactChangesQueue';
import ResetOtpLimitsPanel from './ResetOtpLimitsPanel';
import { Icon } from './icons.jsx';
import { faceCropUrl } from '../cloudinaryImage';
import ReceiptLink from './ReceiptLink';
import ManifestoText from './ManifestoText';
import { regNo } from '../regNo';
import AdminHeader, { useLastSynced } from './AdminHeader';
import ClosedNotice, { vettingNoticeText } from './ClosedNotice';

export default function CommissionDashboard({ onLogout }) {
  const toast = useToast();

  const [activeTab, setActiveTab]       = usePersistedTab('commission', 'pending');
  const [applications, setApplications] = useState([]);
  const [loading, setLoading]           = useState(false);
  const [lastSynced, markSynced]        = useLastSynced();
  const [commissionerId, setCommissionerId] = useState('');
  const [totalCommissioners, setTotalCommissioners] = useState(0);
  const [approvalPolicy, setApprovalPolicy] = useState('majority_total');
  const [denyReasons, setDenyReasons]   = useState({});  // { app_id: string }
  const [showDenyBox, setShowDenyBox]   = useState({});  // { app_id: bool }
  const [voting, setVoting]             = useState({});  // { app_id: bool }
  const [studentChanges, setStudentChanges] = useState([]);
  const [commissioners, setCommissioners] = useState([]);
  const [electionStatus, setElectionStatus] = useState(null);
  const [financeClearing, setFinanceClearing] = useState({});
  const [financeDenyReasons, setFinanceDenyReasons] = useState({});  // { app_id: string }
  const [showFinanceDenyBox, setShowFinanceDenyBox] = useState({});  // { app_id: bool }
  const [searchQuery, setSearchQuery] = useState('');
  const [liveResults, setLiveResults] = useState(null);
  // Chief/Deputy-Commissioner-only controls (exception grants, certification)
  // render off this flag. It is a UI affordance, not the access boundary —
  // the backend re-checks is_chief_commissioner/is_deputy_chief_commissioner
  // on every one of those endpoints (see require_chief_commissioner).
  const [isChief, setIsChief] = useState(false);
  const [isDeputyChief, setIsDeputyChief] = useState(false);

  // Identity comes from the login response, which the server issued against
  // the verified credentials. It is no longer typed in by hand: the backend
  // now rejects any request whose body claims a different commissioner than
  // the session token, so a hand-entered value would simply 403.
  useEffect(() => {
    setCommissionerId(sessionStorage.getItem('commissioner_id') || '');
    fetchAll();
  }, []);

  // `silent` = background poll: no "Syncing…" flicker.
  const fetchAll = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const [appsRes, commRes, scRes, resultsRes, policyRes, statusRes] = await Promise.all([
          api.get('/admin/applications').catch(() => ({ data: [] })),
          api.get('/admin/commissioners').catch(() => ({ data: [] })),
          api.get('/admin/student-changes').catch(() => ({ data: [] })),
          api.get('/commission/results/detailed').catch(() => ({ data: null })),
          api.get('/admin/approval-policy').catch(() => ({ data: null })),
          api.get('/election-status').catch(() => ({ data: null })),
        ]);
        setApplications(appsRes.data);
        setCommissioners(commRes.data);
        setTotalCommissioners(commRes.data.length);
        if (policyRes.data) setApprovalPolicy(policyRes.data.policy);
        setElectionStatus(statusRes.data);
        const me = (commRes.data || []).find(
          c => String(c.student_id || '').toLowerCase()
            === String(sessionStorage.getItem('commissioner_id') || '').toLowerCase()
        );
        const chief = Boolean(me?.is_chief_commissioner);
        const deputyChief = Boolean(me?.is_deputy_chief_commissioner);
        setIsChief(chief);
        setIsDeputyChief(deputyChief);
        // A regular commissioner may still have 'reset_otp' as their persisted
        // last-active tab from before this restriction existed (or from when
        // they held the chief/deputy role). Bounce them off it so they don't
        // land on a blank panel.
        if (!chief && !deputyChief) {
          setActiveTab(prev => (prev === 'reset_otp' ? 'pending' : prev));
        }
        setStudentChanges(scRes.data);
        setLiveResults(resultsRes.data);
        markSynced();
    } catch (e) {
      console.error('Fetch error:', e);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // New applications, votes and finance decisions made by others appear on their own.
  usePolling(() => fetchAll({ silent: true }), 15000);

  // ── Voting ──

  const castVote = async (appId, vote) => {
    if (!commissionerId.trim()) {
      toast('Your commissioner ID was not found in this session. Please log out and log in again.', { kind: 'error' })
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
      toast(e.response?.data?.detail || 'Vote failed. You may have already voted on this application.', { kind: 'error' })
    } finally {
      setVoting(prev => ({ ...prev, [appId]: false }));
    }
  };

  const castFinanceClear = async (appId) => {
    if (!commissionerId.trim()) {
      toast('Your commissioner ID was not found in this session. Please log out and log in again.', { kind: 'error' })
      return;
    }
    setFinanceClearing(prev => ({ ...prev, [appId]: true }));
    try {
      await api.post(`/admin/applications/${appId}/finance-clear`, {
        commissioner_id: commissionerId,
      });
      await fetchAll();
    } catch (e) {
      toast(e.response?.data?.detail || 'Finance clearance failed.', { kind: 'error' })
    } finally {
      setFinanceClearing(prev => ({ ...prev, [appId]: false }));
    }
  };

  const castFinanceReject = async (appId) => {
    if (!commissionerId.trim()) {
      toast('Your commissioner ID was not found in this session. Please log out and log in again.', { kind: 'error' })
      return;
    }
    const reason = (financeDenyReasons[appId] || '').trim();
    if (!reason) {
      toast('Please enter a reason for rejection.', { kind: 'error' });
      return;
    }
    setFinanceClearing(prev => ({ ...prev, [appId]: true }));
    try {
      await api.post(`/admin/applications/${appId}/finance-reject`, {
        commissioner_id: commissionerId,
        reason,
      });
      await fetchAll();
    } catch (e) {
      toast(e.response?.data?.detail || 'Finance rejection failed.', { kind: 'error' })
    } finally {
      setFinanceClearing(prev => ({ ...prev, [appId]: false }));
    }
  };

  // ── Helpers ──

  // The vetting window (set on the admin Timeline tab) is when commissioners may cast an
  // approve/deny vote. Finance clearance is separate and not gated by it, so the Finance
  // Commissioner can clear applications any time and they'll be ready the moment vetting opens.
  const vettingOpen = electionStatus ? electionStatus.vetting_phase_open !== false : true;
  const vettingNotice = vettingNoticeText(electionStatus);

  const safeKey = (id) => id.replace(/[./]/g, '_');

  const myVoteFor = (app) => {
    if (!app.votes) return null;
    return app.votes[safeKey(commissionerId)] || null;
  };

  const voteCount = (app) => {
    const votes = app.votes || {};
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

  const policyHeaderCopy = {
    unanimous: 'Every commissioner must agree — unanimous approval required.',
    majority_total: `Resolves once ${majorityRequired(totalCommissioners)} of ${totalCommissioners} commissioners agree (majority of total).`,
    majority_cast: 'Resolves once every commissioner has voted — whichever side has more wins.',
  }[approvalPolicy] || 'Full consensus required for approval or removal';

  const policyTallyCopy = (vc) => {
    if (approvalPolicy === 'unanimous') return `needs all ${totalCommissioners} to agree`;
    if (approvalPolicy === 'majority_cast') return `${vc.total} of ${totalCommissioners} voted — resolves once everyone's weighed in`;
    return `majority needs ${majorityRequired(totalCommissioners)}`;
  };

  // ── Filtered lists ──

  const pending  = applications.filter(a => a.status === 'pending');
  const approved = applications.filter(a => a.status === 'approved');
  const denied   = applications.filter(a => a.status === 'denied');
  const removed  = applications.filter(a => a.status === 'removed');

  const matchesSearch = (app) => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      (app.full_name || '').toLowerCase().includes(q) ||
      (app.student_id || '').toLowerCase().includes(q) ||
      (app.position_title || app.position_id || '').toLowerCase().includes(q)
    );
  };

  const listFor = (tab) => {
    let list = [];
    if (tab === 'pending')  list = pending;
    if (tab === 'approved') list = approved;
    if (tab === 'denied')   list = denied;
    if (tab === 'removed')  list = removed;
    return list.filter(matchesSearch);
  };

  const tabs = [
    { id: 'pending',         label: 'Pending',         count: pending.length },
    { id: 'approved',        label: 'Approved',        count: approved.length },
    { id: 'denied',          label: 'Denied',          count: denied.length },
    { id: 'removed',         label: 'Removed',         count: removed.length },
    { id: 'student_changes', label: 'Student Changes', count: studentChanges.filter(c => c.status === 'pending').length },
    { id: 'contact_changes', label: 'Contact Changes',  count: null },
    ...((isChief || isDeputyChief) ? [{ id: 'reset_otp', label: 'Reset OTP', count: null }] : []),
    { id: 'results',         label: 'Live Results',    count: null },
    ...SHARED_TAB_DEFS,
    { id: 'official_doc',    label: <>Official Document</>, count: null },
  ];

  const currentList = listFor(activeTab);

  return (
    <div style={outerWrap} className="outer-wrap">
      <div style={container} className="dashboard-shell">

        {/* ── Header ── */}
        <AdminHeader
          title="Election Commission"
          subtitle={`${totalCommissioners} commissioner${totalCommissioners !== 1 ? 's' : ''} total · ${policyHeaderCopy}`}
          lastSynced={lastSynced}
          onRefresh={() => fetchAll()}
          refreshing={loading}
          onLogout={onLogout}
        />

        {/* Identity is taken from the session the server issued at login —
            it is deliberately not editable here. A free-text field let the
            browser assert any commissioner's identity; the backend now binds
            every vote to the token subject, so this is display only. */}
        {!commissionerId ? (
          <div style={promptBox}>
            <p style={{ margin: 0, fontWeight: '600', color: 'var(--text-color)' }}>
              Your commissioner identity could not be read from this session.
            </p>
            <p style={{ margin: '8px 0 0', fontSize: '12px', opacity: 0.6 }}>
              Please log out and sign in again so your votes are attributed correctly.
            </p>
          </div>
        ) : (
          <div style={infoPill}>
            Signed in as: <strong>{commissionerId}</strong>
            {isChief && <span style={chiefPill}>Chief Commissioner</span>}
            {isDeputyChief && <span style={chiefPill}>Deputy Chairperson</span>}
          </div>
        )}

        {/* ── Search ── */}
        {['pending', 'approved', 'denied', 'removed'].includes(activeTab) && (
          <div style={{ marginBottom: '16px' }}>
            <input
              style={inp}
              placeholder="Search by name, student ID, or position…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>
        )}

        {/* ── Tabs ── */}
        <div style={tabBar} className="tab-scroll no-print">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              style={{ ...tab, borderBottom: activeTab === t.id ? '3px solid #2ecc71' : '3px solid transparent' }}>
              {t.label}
              {t.count !== null && <span style={countPill}>{t.count}</span>}
            </button>
          ))}
        </div>

        {activeTab === 'pending' && !vettingOpen && <ClosedNotice text={vettingNotice || 'Vetting is not currently open — commissioners cannot vote yet.'} />}

        {/* ── Empty state ── */}
        {['pending', 'approved', 'denied', 'removed'].includes(activeTab) && currentList.length === 0 && !loading && (
          <div style={emptyState}>
            <p style={{ opacity: 0.5 }}>
              No {activeTab} applications.
              {activeTab === 'pending' && ' Check back when applicants submit their forms.'}
            </p>
          </div>
        )}

        {/* ── Application cards ── */}
        {activeTab !== 'student_changes' && activeTab !== 'results' && (
        <ScrollList>
        {currentList.map(app => {
          const vc      = voteCount(app);
          const myVote  = myVoteFor(app);
          const isVotingNow        = voting[app._id];

          return (
            <div key={app._id} style={appCard}>

              {/* Top row — photo + info + status */}
              <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
                {app.image_url ? (
                  <img src={faceCropUrl(app.image_url, 64, 64)} alt="" style={avatar} />
                ) : (
                  <div style={{ ...avatar, backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '22px' }}>
                    <Icon name="user" />
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
                    Student ID: {regNo(app.student_id)}
                  </p>

                  <ManifestoText text={app.manifesto} />
                  
                  {app.payment_method && (
                    <div style={{ marginTop: '10px', padding: '10px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                      <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                        Payment method: <strong style={{ color: 'var(--text-color)' }}>{app.payment_method}</strong>
                      </p>
                      <p style={{ margin: '0 0 6px', fontSize: '13px' }}>
                        Required amount:{' '}
                        <strong style={{ color: 'var(--success)' }}>
                          {app.fee_required ? `UGX ${Number(app.fee_required).toLocaleString('en-UG')}` : 'not set for this position'}
                        </strong>
                      </p>
                      <ReceiptLink url={app.payment_proof_url} />
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
                    · {policyTallyCopy(vc)}
                  </span>
                  {app.tied_pending_chief && (
                    <span style={{ opacity: 0.8, fontSize: '12px', color: '#e67e22', fontWeight: 600 }}>
                      · Tied — awaiting Chief Commissioner tie-break
                    </span>
                  )}
                </div>
              )}

              {/* ── Pending: finance-clear gate, then approve / deny actions ── */}
              {app.status === 'pending' && !app.superadmin_override && (
                <div style={{ marginTop: '14px' }}>
                  {!app.finance_cleared ? (
                    isFinanceCommissioner ? (
                      <>
                        {showFinanceDenyBox[app._id] && (
                          <div style={{ marginBottom: '10px' }}>
                            <textarea
                              style={{ ...inp, height: '70px', resize: 'vertical' }}
                              placeholder="Reason for rejection (required)…"
                              value={financeDenyReasons[app._id] || ''}
                              onChange={e => setFinanceDenyReasons(prev => ({ ...prev, [app._id]: e.target.value }))}
                            />
                          </div>
                        )}
                        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                          <button
                            style={{ ...greenBtn, flex: 1 }}
                            disabled={financeClearing[app._id]}
                            onClick={() => castFinanceClear(app._id)}
                          >
                            {financeClearing[app._id] ? 'Clearing…' : <>Clear for Finance</>}
                          </button>
                          {showFinanceDenyBox[app._id] ? (
                            <button
                              style={{ ...redBtn, flex: 1 }}
                              disabled={financeClearing[app._id]}
                              onClick={() => castFinanceReject(app._id)}
                            >
                              {financeClearing[app._id] ? 'Rejecting…' : <>Confirm Reject</>}
                            </button>
                          ) : (
                            <button
                              style={{ ...ghostBtn, flex: 1, color: '#e74c3c', borderColor: '#e74c3c' }}
                              onClick={() => setShowFinanceDenyBox(prev => ({ ...prev, [app._id]: true }))}
                            >
                              Reject
                            </button>
                          )}
                          {showFinanceDenyBox[app._id] && (
                            <button
                              style={ghostBtn}
                              onClick={() => setShowFinanceDenyBox(prev => ({ ...prev, [app._id]: false }))}
                            >
                              Cancel
                            </button>
                          )}
                        </div>
                      </>
                    ) : (
                      <div style={lockedNote}>
                        Awaiting Finance Commissioner clearance before voting can open.
                      </div>
                    )
                  ) : myVote ? (
                    <div style={myVoteRow(myVote)}>
                      {myVote === 'approve'
                        ? <><Icon name="success" /> You voted to approve this application.</>
                        : <><Icon name="error" /> You voted to deny this application.</>}
                      <span style={{ opacity: 0.6, fontSize: '12px', marginLeft: '8px' }}>
                        Resolves once a majority is reached.
                      </span>
                    </div>
                  ) : !vettingOpen ? (
                    <div style={lockedNote}>
                      {vettingNotice || 'Vetting is not currently open — commissioners cannot vote yet.'}
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
                          {isVotingNow ? 'Submitting…' : <>Approve</>}
                        </button>
                        {showDenyBox[app._id] ? (
                          <button
                            style={{ ...redBtn, flex: 1 }}
                            disabled={isVotingNow}
                            onClick={() => castVote(app._id, 'deny')}
                          >
                            {isVotingNow ? 'Submitting…' : <>Confirm Deny</>}
                          </button>
                        ) : (
                          <button
                            style={{ ...ghostBtn, flex: 1, color: '#e74c3c', borderColor: '#e74c3c' }}
                            onClick={() => setShowDenyBox(prev => ({ ...prev, [app._id]: true }))}
                          >
                            Deny
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

              {/* ── Approved: confirm the original vote was counted, no removal UI here ── */}
              {app.status === 'approved' && myVote && (
                <div style={{ marginTop: '14px' }}>
                  <div style={myVoteRow(myVote)}>
                    <Icon name="success" /> Your vote was counted — you voted <strong>{myVote}</strong> on this application.
                  </div>
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
        </ScrollList>
        )}
        
        {/* ── Student Changes tab ── */}
        {activeTab === 'student_changes' && (
          <div>
            {studentChanges.length === 0 && (
              <div style={emptyState}>
                <p style={{ opacity: 0.5 }}>No student change requests.</p>
              </div>
            )}
            <ScrollList>
            {studentChanges.map(change => {
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
                    <small style={{ opacity: 0.45 }}>
                      {new Date(change.requested_at).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </small>
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
                    <div style={{ marginTop: '8px', padding: '8px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                      <p style={{ margin: '0 0 4px', fontSize: '12px', opacity: 0.6 }}>
                        Payment: <strong style={{ color: 'var(--text-color)' }}>{change.payment_method}</strong>
                      </p>
                      {change.payment_proof_url && (
                        <ReceiptLink url={change.payment_proof_url} />
                      )}
                    </div>
                  )}

                   {change.status === 'pending' ? (
                    <div style={lockedNote}>
                      Awaiting the Financial Controller's decision on this request.
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
          </div>
        )}

        {/* ── Live Results tab ── */}
        {activeTab === 'results' && (
          <div>
            {!liveResults ? (
              <div style={emptyState}>
                <p style={{ opacity: 0.5 }}>Loading live results…</p>
              </div>
            ) : (
              <>
                <div style={{ ...tallyRow, marginTop: 0, marginBottom: '20px' }}>
                  <span style={{ opacity: 0.6, fontSize: '12px' }}>Voter turnout:</span>
                  <span style={{ color: '#2ecc71', fontWeight: '700', fontSize: '15px' }}>
                    {liveResults.voter_turnout.voted_count} / {liveResults.voter_turnout.total_voters}
                  </span>
                  <span style={{ opacity: 0.6, fontSize: '13px' }}>
                    ({liveResults.voter_turnout.turnout_pct}%)
                  </span>
                  <span style={{ opacity: 0.5, fontSize: '12px' }}>
                    · {liveResults.voter_turnout.total_voters - liveResults.voter_turnout.voted_count} remaining
                  </span>
                  <span style={{ opacity: 0.4, fontSize: '11px', marginLeft: 'auto' }}>
                    Updated {new Date(liveResults.generated_at).toLocaleTimeString('en-UG', { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>

                {liveResults.positions.length === 0 && (
                  <div style={emptyState}>
                    <p style={{ opacity: 0.5 }}>No candidates on the ballot yet.</p>
                  </div>
                )}

                {liveResults.positions.map(pos => (
                  <div key={pos.position} style={appCard}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      <b style={{ fontSize: '15px', color: 'var(--text-color)' }}>{pos.position}</b>
                      <small style={{ opacity: 0.5 }}>
                        {pos.total_votes} vote{pos.total_votes !== 1 ? 's' : ''} cast
                        {pos.candidates.length > 1 && (
                          <span style={{ marginLeft: '8px', color: '#2ecc71', fontWeight: '600' }}>
                            +{pos.candidates[0].votes - pos.candidates[1].votes} lead
                            {' '}({(pos.candidates[0].pct_of_position - pos.candidates[1].pct_of_position).toFixed(1)}%)
                          </span>
                        )}
                      </small>
                     </div>                     
                    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {pos.candidates.map((c, idx) => (
                        <div key={c.id} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                            <span style={{ fontSize: '12px', opacity: 0.5, width: '16px', flexShrink: 0 }}>{idx + 1}.</span>
                            <span style={{ flex: 1, fontSize: '13px', color: 'var(--text-color)', fontWeight: idx === 0 ? '700' : '400' }}>
                              {c.name}
                            </span>
                            {c.unopposed && (
                              <span style={{ fontSize: '10px', opacity: 0.5, flexShrink: 0 }}>unopposed</span>
                            )}
                            <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-color)', flexShrink: 0 }}>
                              {c.votes} ({c.pct_of_position}%)
                            </span>
                          </div>
                          <div style={{ marginLeft: '24px', height: '8px', backgroundColor: 'var(--card-bg)', borderRadius: '4px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                            <div style={{ width: `${c.pct_of_position}%`, height: '100%', backgroundColor: idx === 0 ? '#2ecc71' : 'var(--border-color)' }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}

                <p style={{ fontSize: '11px', opacity: 0.4, marginTop: '4px' }}>
                  Figures are anonymous aggregate tallies — no voter's individual choice is ever linked to their identity here.
                </p>
              </>
            )}
          </div>
        )}

        {activeTab === 'contact_changes' && <ContactChangesQueue />}
        {activeTab === 'reset_otp' && (isChief || isDeputyChief) && <ResetOtpLimitsPanel canOverrideCaps />}

        <SharedTabPanels activeTab={activeTab} isChief={isChief || isDeputyChief} />
        {activeTab === 'official_doc' && <OfficialCertificationBlock />}
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
const tabBar     = { display: 'flex', rowGap: '10px', columnGap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap', alignItems: 'stretch' };
const tab        = { background: 'none', border: 'none', padding: '10px 14px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px', lineHeight: '1.3', borderRadius: '6px 6px 0 0', display: 'flex', alignItems: 'center', gap: '6px' };
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
const chiefPill = { marginLeft: '10px', fontSize: '10px', fontWeight: 800, padding: '3px 9px', borderRadius: '10px', background: 'color-mix(in srgb, var(--warning) 22%, transparent)', color: 'var(--warning)' };
const infoPill   = { fontSize: '13px', opacity: 0.7, marginBottom: '18px', padding: '8px 14px', backgroundColor: 'var(--bg-color)', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'inline-flex', alignItems: 'center' };
const overrideNote = { marginTop: '12px', fontSize: '12px', opacity: 0.55, fontStyle: 'italic' };
const lockedNote = { padding: '10px 14px', backgroundColor: 'color-mix(in srgb, var(--warning) 15%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--warning) 40%, transparent)', color: 'var(--warning)', fontSize: '12px', fontWeight: '600' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
