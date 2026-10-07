import React, { useEffect, useState } from 'react';
import api from '../api';
import { usePersistedTab } from '../session';
import { switchHat } from '../hatSwitch';
import { useToast, ScrollList } from './UIFeedback';
import usePolling from '../hooks/usePolling';
import { SHARED_TAB_DEFS, SharedTabPanels, OfficialCertificationBlock } from './SharedAdminPanels';
import TabBar from './TabBar';
import ContactChangesQueue from './ContactChangesQueue';
import ResetOtpLimitsPanel from './ResetOtpLimitsPanel';
import ReceiptLink from './ReceiptLink';
import { regNo } from '../regNo';
import AdminHeader, { useLastSynced } from './AdminHeader';
import { LoadingBlock } from './Spinner.jsx';
import { getTemplate } from '../template';

// Pre-P4 tab ids that may still be remembered in this tab's session.
const LEGACY_TABS = ['pending', 'approved', 'denied', 'removed'];

export default function CommissionDashboard({ onLogout }) {
  const toast = useToast();
  const bp = getTemplate(); // render-time: null => the standard UI

  const [activeTab, setActiveTab]       = usePersistedTab('commission', 'outcomes');
  const [applications, setApplications] = useState([]);
  const [loading, setLoading]           = useState(false);
  const [outcomesFailed, setOutcomesFailed] = useState(false);
  const [panelLinked, setPanelLinked] = useState(false);
  const [tieWaiting, setTieWaiting] = useState(0);
  const [lastSynced, markSynced]        = useLastSynced();
  const [commissionerId, setCommissionerId] = useState('');
  const [studentChanges, setStudentChanges] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [liveResults, setLiveResults] = useState(null);
  // Chairperson/Deputy-Chairperson-only controls (exception grants, certification)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only load
  }, []);

  // `silent` = background poll: no "Syncing…" flicker.
  const fetchAll = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const [appsRes, commRes, scRes, resultsRes, linkRes] = await Promise.all([
          api.get('/admin/vetting-outcomes').catch(() => ({ data: null })),
          api.get('/admin/commissioners').catch(() => ({ data: [] })),
          api.get('/admin/student-changes').catch(() => ({ data: [] })),
          api.get('/commission/results/detailed').catch(() => ({ data: null })),
          api.get('/admin/panel-link').catch(() => ({ data: null })),
        ]);
        setOutcomesFailed(appsRes.data === null);
        // Keep the last good list on a failed refresh instead of blanking it.
        if (appsRes.data !== null) setApplications(appsRes.data);
        const me = (commRes.data || []).find(
          c => String(c.student_id || '').toLowerCase()
            === String(sessionStorage.getItem('commissioner_id') || '').toLowerCase()
        );
        const chief = Boolean(me?.is_chief_commissioner);
        const deputyChief = Boolean(me?.is_deputy_chief_commissioner);
        setPanelLinked(Boolean(linkRes.data?.panel_linked));
        setTieWaiting(Number(linkRes.data?.tie_waiting) || 0);
        setIsChief(chief);
        setIsDeputyChief(deputyChief);
        // A regular commissioner may still have 'reset_otp' as their persisted
        // last-active tab from before this restriction existed (or from when
        // they held the chief/deputy role). Bounce them off it so they don't
        // land on a blank panel.
        setActiveTab(prev => (
          LEGACY_TABS.includes(prev) || (prev === 'reset_otp' && !chief && !deputyChief)
            ? 'outcomes'
            : prev
        ));
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

  // Guide 5.2: a commissioner linked to an active panelist can switch to the panel view.
  const [switchingHat, setSwitchingHat] = useState(false);
  const goToPanel = async () => {
    setSwitchingHat(true);
    try {
      await switchHat();
    } catch (e) {
      toast(e.response?.data?.detail || 'Could not switch to the Vetting Panel.', { kind: 'error' });
      setSwitchingHat(false);
    }
  };

  // ── Helpers ──

  const outcomeSubtitle = 'Final decisions of the Vetting Panel. Votes and progress are not shown here.';

  const matchesSearch = (app) => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      (app.full_name || '').toLowerCase().includes(q) ||
      (app.student_id || '').toLowerCase().includes(q) ||
      (app.position_title || '').toLowerCase().includes(q)
    );
  };

  const currentList = applications.filter(matchesSearch);

  const tabGroups = [
    { label: 'Oversight', icon: 'eye', tabs: [
      { id: 'outcomes', label: <>Outcomes</>, icon: 'award' },
      { id: 'results',  label: <>Live Results</>, icon: 'chart' },
    ] },
    { label: 'Requests', icon: 'inbox', tabs: [
      { id: 'student_changes', label: <>Student Changes</>, icon: 'log' },
      { id: 'contact_changes', label: <>Contact Changes</>, icon: 'phone' },
      ...((isChief || isDeputyChief) ? [{ id: 'reset_otp', label: <>Reset OTP</>, icon: 'refresh' }] : []),
    ] },
    { label: 'Platform', icon: 'settings', tabs: [
      ...SHARED_TAB_DEFS,
      { id: 'official_doc', label: <>Official Document</>, icon: 'file' },
    ] },
  ];

  return (
    <div style={outerWrap} className="outer-wrap">

        {/* ── Header ──
            Lives outside the content card, like SuperAdmin's — the card
            (.dashboard-shell) now wraps only the rail's content pane via
            .dash-main below, not the header/identity/search chrome above
            the rail. */}
        <AdminHeader
          title="Election Commission"
          subtitle={outcomeSubtitle}
          lastSynced={lastSynced}
          onRefresh={() => fetchAll()}
          refreshing={loading}
          onLogout={onLogout}
          actions={panelLinked ? (
            <button onClick={goToPanel} disabled={switchingHat} style={{ ...hatBtn, opacity: switchingHat ? 0.6 : 1 }}>
              {switchingHat ? 'Switching…' : 'Switch to Vetting Panel'}
            </button>
          ) : null}
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
              Please log out and sign in again.
            </p>
          </div>
        ) : (
          <div style={infoPill}>
            Signed in as: <strong>{commissionerId}</strong>
            {isChief && <span style={chiefPill}>Chairperson</span>}
            {isDeputyChief && <span style={chiefPill}>Deputy Chairperson</span>}
          </div>
        )}

        {/* Guide 7.2: the Chairperson is told when a tie needs their casting decision. */}
        {panelLinked && tieWaiting > 0 && (
          <div style={tieHint}>
            {tieWaiting === 1 ? 'An application is tied and needs your casting decision.' : `${tieWaiting} applications are tied and need your casting decision.`}
            {' '}Switch to the Vetting Panel to decide.
          </div>
        )}

        {/* ── Search ── */}
        {activeTab === 'outcomes' && (
          <div style={{ marginBottom: '16px' }}>
            <input
              style={inp}
              placeholder="Search by name, student ID, or position…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>
        )}

        {/* ── Tabs ──
            TabBar renders a sticky rail on desktop and a group-pill row
            on mobile; .dash-body/.dash-main lay it out beside the content
            on desktop and stack it above on mobile, off the same 768px
            breakpoint TabBar itself uses. */}
        <div className="dash-body">
        {/* ── Rail: independent of the content card, not nested inside it ── */}
        <TabBar groups={tabGroups} activeTab={activeTab} onChange={setActiveTab} />
        <div style={container} className="dashboard-shell dash-main">


        {/* ── Empty state ── */}
        {activeTab === 'outcomes' && outcomesFailed && (
          <div style={emptyState}>
            <p style={{ opacity: 0.7 }}>Could not load decisions. Use Refresh to try again.</p>
          </div>
        )}
        {activeTab === 'outcomes' && !outcomesFailed && currentList.length === 0 && !loading && (
          <div style={emptyState}>
            <p style={{ opacity: 0.5 }}>
              No decisions yet.
            </p>
          </div>
        )}

        {/* ── Outcomes (guide 5.2): final decisions only; never pending, votes or tallies ── */}
        {activeTab === 'outcomes' && (
        <ScrollList>
        {currentList.map(app => (
          <div key={app.id} style={outcomeCard}>
            <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
              <b style={{ color: 'var(--text-color)', fontSize: '14px' }}>{app.full_name || 'Applicant'}</b>
              <StatusBadge status={app.status}>{(app.status || '').toUpperCase()}</StatusBadge>
            </div>
            <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.7 }}>
              {app.position_title}{app.student_id ? ` · ${regNo(app.student_id)}` : ''}
            </p>
            <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.6 }}>
              Decided: {app.decided_at ? new Date(app.decided_at).toLocaleDateString() : 'date not recorded'}
            </p>
            <p style={{ margin: '8px 0 0', fontSize: '13px' }}>
              Reason: {app.final_reason || 'No reason recorded'}
            </p>
            {app.superadmin_override && (
              <div style={overrideNote}>This was decided by the superadmin. Panel voting was bypassed.</div>
            )}
          </div>
        ))}
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
                      <StatusBadge status={change.status} style={{ marginLeft: '10px' }}>
                        {change.status.toUpperCase()}
                      </StatusBadge>
                    </div>
                    <small style={{ opacity: 0.45 }}>
                      {new Date(change.requested_at).toLocaleDateString('en-UG', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </small>
                  </div>

                  <p style={{ margin: '8px 0 2px', fontSize: '13px', color: 'var(--text-color)' }}>
                    <b>Student:</b> {change.full_name}: <code style={{ fontSize: '12px' }}>{regNo(change.student_id)}</code>
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
                      Decided by: {change.decided_by || 'N/A'}
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
                <LoadingBlock text="Loading live results…" />
              </div>
            ) : (
              <>
                <div style={{ ...tallyRow, marginTop: 0, marginBottom: '20px' }}>
                  <span style={{ opacity: 0.6, fontSize: '12px' }}>Voter turnout:</span>
                  <span style={{ color: 'var(--bp-ok, #2ecc71)', fontWeight: '700', fontSize: '15px' }}>
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
                          <span style={{ marginLeft: '8px', color: 'var(--bp-ok, #2ecc71)', fontWeight: '600' }}>
                            +{pos.candidates[0].votes - pos.candidates[1].votes} lead
                            {' '}({(pos.candidates[0].pct_of_position - pos.candidates[1].pct_of_position).toFixed(1)}%)
                          </span>
                        )}
                      </small>
                     </div>                     
                    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {pos.candidates.map((c, idx) => {
                        // Blueprint: the row becomes a meter (bar = accent for the leader); default keeps the original div + inline bar.
                        const Row = bp ? bp.Meter : 'div';
                        const rowProps = bp ? { pct: c.pct_of_position, accent: idx === 0 } : { style: { display: 'flex', flexDirection: 'column', gap: '4px' } };
                        return (
                        <Row key={c.id} {...rowProps}>
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
                          {!bp && (
                          <div style={{ marginLeft: '24px', height: '8px', backgroundColor: 'var(--card-bg)', borderRadius: '4px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                            <div style={{ width: `${c.pct_of_position}%`, height: '100%', backgroundColor: idx === 0 ? 'var(--bp-ok, #2ecc71)' : 'var(--border-color)' }} />
                          </div>
                        )}
                        </Row>
                      );
                      })}
                    </div>
                  </div>
                ))}

                <p style={{ fontSize: '11px', opacity: 0.4, marginTop: '4px' }}>
                  Figures are anonymous aggregate tallies. No individual choice is ever linked to a voter's identity.
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
    </div>
  );
}

// ── Helpers ──
function statusBadge(status) {
  const map = {
    pending:  { background: 'color-mix(in srgb, var(--warning) 20%, transparent)', color: 'var(--warning)' },
    approved: { background: 'color-mix(in srgb, var(--success) 20%, transparent)', color: 'var(--success)' },
    denied:   { background: 'color-mix(in srgb, var(--danger) 20%, transparent)',  color: 'var(--danger)' },
    removed:  { background: 'var(--bp-mu-tint, #95a5a620)', color: 'var(--bp-mu, #95a5a6)' },
  };
  return {
    fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
    ...(map[status] || {}),
  };
}

// Status badge. Default: the same <span> as before. Blueprint: the shared status pill (one tone map for every console).
function StatusBadge({ status, style, children }) {
  const bp = getTemplate();
  if (bp?.StatusPill) return <bp.StatusPill status={status} style={style}>{children}</bp.StatusPill>;
  return <span style={{ ...statusBadge(status), ...style }}>{children}</span>;
}

// ── Styles ──
const outerWrap  = { width: '100%', minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'stretch', justifyContent: 'flex-start', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container  = { width: '100%', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const appCard    = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '18px', marginBottom: '14px', backgroundColor: 'var(--bg-color)' };
const tallyRow   = { display: 'flex', gap: '14px', alignItems: 'center', flexWrap: 'wrap', marginTop: '12px', padding: '8px 12px', backgroundColor: 'var(--card-bg)', borderRadius: '8px', border: '1px solid var(--border-color)' };
const inp        = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const promptBox  = { border: '1px dashed var(--border-color)', borderRadius: '12px', padding: '20px', marginBottom: '20px', backgroundColor: 'var(--bg-color)' };
const chiefPill = { marginLeft: '10px', fontSize: '10px', fontWeight: 800, padding: '3px 9px', borderRadius: '10px', background: 'color-mix(in srgb, var(--warning) 22%, transparent)', color: 'var(--warning)' };
const infoPill   = { fontSize: '13px', opacity: 0.7, marginBottom: '18px', padding: '8px 14px', backgroundColor: 'var(--bg-color)', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'inline-flex', alignItems: 'center' };
const overrideNote = { marginTop: '12px', fontSize: '12px', opacity: 0.55, fontStyle: 'italic' };
const lockedNote = { padding: '10px 14px', backgroundColor: 'color-mix(in srgb, var(--warning) 15%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--warning) 40%, transparent)', color: 'var(--warning)', fontSize: '12px', fontWeight: '600' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };

const tieHint = { padding: '10px 14px', marginBottom: '16px', borderRadius: '8px', fontSize: '13px', fontWeight: 600, backgroundColor: 'color-mix(in srgb, var(--warning) 15%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 40%, transparent)', color: 'var(--warning)' };
const hatBtn = { padding: '8px 14px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', cursor: 'pointer', fontSize: '13px', fontWeight: '600' };

const outcomeCard = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
