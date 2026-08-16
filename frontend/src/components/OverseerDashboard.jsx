import React, { useEffect, useState } from 'react';
import api from '../api';

export default function OverseerDashboard({ onLogout }) {
  const overseerId   = sessionStorage.getItem('overseer_id')   || '';
  const overseerName = sessionStorage.getItem('overseer_name') || '';

  const [data, setData]       = useState(null);
  const [liveResults, setLiveResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab]         = useState('applications');

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 20000);
    return () => clearInterval(interval);
  }, []);

  const fetchDashboard = async () => {
    setLoading(true);
    try {
      const [dashRes, resultsRes] = await Promise.all([
        api.get('/overseer/dashboard'),
        api.get('/commission/results/detailed').catch(() => ({ data: null })),
      ]);
      setData(dashRes.data);
      setLiveResults(resultsRes.data);
    } catch (e) {
      console.error('Failed to fetch overseer dashboard:', e);
    } finally {
      setLoading(false);
    }
  };

  const tabs = [
    { id: 'applications', label: '🗳️ Applications', count: data?.applications?.length },
    { id: 'changes',      label: '📋 Student Changes', count: data?.student_changes?.length },
    { id: 'results',      label: '📊 Candidate Results' },
  ];

  return (
    <div style={outerWrap}>
      <div style={container}  className="dashboard-shell">

        {/* ── Header ── */}
        <div style={headerFlex}>
          <div>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>👁️ Overseer Panel</h2>
            <span style={{ fontSize: '12px', opacity: 0.6 }}>
              Logged in as <strong>{overseerName || overseerId}</strong> · read-only
            </span>
          </div>
          <button style={redBtn} onClick={onLogout}>Logout</button>
        </div>

        {!overseerId && (
          <div style={{ ...infoBox, borderColor: '#e74c3c40', marginBottom: '20px' }}>
            <p style={{ margin: 0, color: '#e74c3c', fontSize: '13px' }}>
              ⚠️ Your Overseer session could not be identified. Please log out and log back in.
            </p>
          </div>
        )}

        {!data && loading && (
          <div style={emptyState}><p style={{ opacity: 0.5 }}>Loading platform data…</p></div>
        )}

        {data && (
          <>
            {/* ── Summary cards ── */}
            <div style={summaryGrid}>
              <div style={summaryCard}>
                <span style={summaryLabel}>Election Status</span>
                <span style={summaryValue}>
                  {data.election_status.is_open ? '🟢 Open' : '🔴 Closed'}
                  {data.election_status.is_certified && ' · Certified'}
                </span>
              </div>
              <div style={summaryCard}>
                <span style={summaryLabel}>Voter Turnout</span>
                <span style={summaryValue}>
                  {data.voter_turnout.voted_count} / {data.voter_turnout.total_voters} ({data.voter_turnout.turnout_pct}%)
                </span>
              </div>
              <div style={summaryCard}>
                <span style={summaryLabel}>Commissioners</span>
                <span style={summaryValue}>{data.total_commissioners}</span>
              </div>
            </div>

            {/* ── Tabs ── */}
            <div style={tabBar} className="tab-scroll">
              {tabs.map(t => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  style={{
                    ...tabBtn,
                    borderBottom: tab === t.id ? '2px solid #3498db' : '2px solid transparent',
                    opacity: tab === t.id ? 1 : 0.6,
                  }}
                >
                  {t.label}{t.count != null && ` (${t.count})`}
                </button>
              ))}
              <button style={{ ...ghostBtn, marginLeft: 'auto' }} onClick={fetchDashboard} disabled={loading}>
                {loading ? 'Syncing…' : '🔄 Refresh'}
              </button>
            </div>

            {/* ── Applications (read-only) ── */}
            {tab === 'applications' && (
              <div>
                {data.applications.length === 0 && <div style={emptyState}><p style={{ opacity: 0.5 }}>No applications yet.</p></div>}
                {data.applications.map(a => (
                  <div key={a.id} style={appCard}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                      <b style={{ color: 'var(--text-color)', fontSize: '14px' }}>{a.full_name}</b>
                      <span style={statusBadge(a.status)}>{a.status.toUpperCase()}</span>
                    </div>
                    <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.7 }}>{a.position_id}</p>
                    <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.6 }}>
                      ✅ {a.approve_count} · ❌ {a.deny_count} · {a.votes_cast} vote(s) cast
                      {a.finance_cleared && ' · 💰 Finance cleared'}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {/* ── Student changes (read-only) ── */}
            {tab === 'changes' && (
              <div>
                {data.student_changes.length === 0 && <div style={emptyState}><p style={{ opacity: 0.5 }}>No student changes yet.</p></div>}
                {data.student_changes.map(c => (
                  <div key={c.id} style={appCard}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                      <b style={{ color: 'var(--text-color)', fontSize: '14px' }}>
                        {c.change_type === 'add' ? '➕' : '➖'} {c.full_name} <code style={{ fontSize: '11px' }}>{c.student_id}</code>
                      </b>
                      <span style={statusBadge(c.status)}>{c.status.toUpperCase().replace('_', ' ')}</span>
                    </div>
                    <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.6 }}>
                      Requested by {c.requested_by}{c.decided_by && ` · decided by ${c.decided_by}`}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {/* ── Candidate results (read-only) ── */}
            {tab === 'results' && (
              <div>
                {!liveResults ? (
                  <div style={emptyState}><p style={{ opacity: 0.5 }}>Loading live results…</p></div>
                ) : (
                  <>
                    <div style={{ ...summaryCard, flexDirection: 'row', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                      <span style={{ opacity: 0.6, fontSize: '12px' }}>Voter turnout:</span>
                      <span style={{ color: '#2ecc71', fontWeight: '700', fontSize: '15px' }}>
                        {liveResults.voter_turnout.voted_count} / {liveResults.voter_turnout.total_voters}
                      </span>
                      <span style={{ opacity: 0.6, fontSize: '13px' }}>({liveResults.voter_turnout.turnout_pct}%)</span>
                      <span style={{ opacity: 0.5, fontSize: '12px' }}>
                        · {liveResults.voter_turnout.total_voters - liveResults.voter_turnout.voted_count} remaining
                      </span>
                    </div>

                    {liveResults.positions.length === 0 && (
                      <div style={emptyState}><p style={{ opacity: 0.5 }}>No candidates on the ballot yet.</p></div>
                    )}

                    {liveResults.positions.map(pos => (
                      <div key={pos.position} style={appCard}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
                        <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          {pos.candidates.map((c, idx) => (
                            <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <span style={{ fontSize: '12px', opacity: 0.5, width: '18px' }}>{idx + 1}.</span>
                              <span style={{ flex: 1, fontSize: '13px', color: 'var(--text-color)', fontWeight: idx === 0 ? '700' : '400' }}>
                                {c.name}
                              </span>
                              {c.unopposed && <span style={{ fontSize: '10px', opacity: 0.5 }}>unopposed</span>}
                              <div style={{ width: '120px', height: '8px', backgroundColor: 'var(--card-bg)', borderRadius: '4px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                                <div style={{ width: `${c.pct_of_position}%`, height: '100%', backgroundColor: idx === 0 ? '#2ecc71' : 'var(--border-color)' }} />
                              </div>
                              <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-color)', width: '70px', textAlign: 'right' }}>
                                {c.votes} ({c.pct_of_position}%)
                              </span>
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
          </>
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
    force_approved: { background: 'color-mix(in srgb, var(--success) 20%, transparent)', color: 'var(--success)' },
    denied:         { background: 'color-mix(in srgb, var(--danger) 20%, transparent)',  color: 'var(--danger)' },
    force_denied:   { background: 'color-mix(in srgb, var(--danger) 20%, transparent)',  color: 'var(--danger)' },
    cancelled:      { background: '#95a5a620', color: '#95a5a6' },
  };
  return {
    fontSize: '10px', padding: '3px 8px', borderRadius: '10px', fontWeight: 'bold',
    ...(map[status] || {}),
  };
}

// ── Styles ──
const outerWrap    = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container    = { width: '95%', maxWidth: '1200px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const headerFlex   = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' };
const summaryGrid   = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '20px' };
const summaryCard   = { padding: '14px 16px', border: '1px solid var(--border-color)', borderRadius: '10px', backgroundColor: 'var(--bg-color)', display: 'flex', flexDirection: 'column', gap: '4px' };
const summaryLabel  = { fontSize: '11px', opacity: 0.55, fontWeight: '600', textTransform: 'uppercase' };
const summaryValue  = { fontSize: '15px', fontWeight: '700', color: 'var(--text-color)' };
const tabBar        = { display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', flexWrap: 'wrap', alignItems: 'center' };
const tabBtn         = { background: 'none', border: 'none', padding: '10px 16px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-color)', fontSize: '13px' };
const ghostBtn      = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const redBtn        = { padding: '10px 18px', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', backgroundColor: '#e74c3c' };
const appCard       = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
const infoBox     = { padding: '12px 16px', backgroundColor: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--info) 30%, transparent)' };
const emptyState    = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
