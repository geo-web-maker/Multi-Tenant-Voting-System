import React, { useEffect, useState, useCallback } from 'react';
import api from '../api';

/*
 * One set of panels, mounted identically in all five dashboards.
 *
 * The audit log and integrity chain used to be reachable only under
 * /superadmin/* — no other role could see either, even read-only. Full
 * transparency was the explicit decision, so these read from the /admin/*
 * endpoints which any valid admin token can reach.
 *
 * Nothing here writes. The only write control in this file is the phase
 * editor inside <Timeline>, which renders solely when canEdit is passed
 * (SuperAdmin), and the exception-grant control, which renders solely when
 * isChief is passed. Overseer gains visibility and no write actions at all,
 * by design.
 */

const PHASE_LABELS = {
  applications: 'Applications',
  campaign: 'Campaign',
  voting: 'Voting',
  results: 'Results',
};

const STATE_COLORS = {
  active: 'var(--success)',
  upcoming: 'var(--info)',
  closed: 'var(--text-muted)',
  unscheduled: 'var(--warning)',
};

function errText(e, fallback = 'Request failed.') {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map(x => x?.msg || JSON.stringify(x)).join(', ');
  if (typeof d === 'string' && d.trim()) return d;
  return fallback;
}

function countdown(seconds) {
  if (seconds == null || seconds < 0) return null;
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

function fmt(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString('en-UG', { dateStyle: 'medium', timeStyle: 'short' });
}

// Backend sends naive UTC ISO strings; <input type="datetime-local"> needs
// local wall-clock. Convert both ways rather than letting the browser drift
// the schedule by the timezone offset on every save.
function toLocalInput(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ══════════════════════════ TIMELINE ══════════════════════════ */

export function Timeline({ canEdit = false, isChief = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({});
  const [grants, setGrants] = useState([]);
  const [grantForm, setGrantForm] = useState({ student_id: '', phase: 'applications', reason: '', expires_at: '' });

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/schedule');
      setData(res.data);
      setDraft(Object.fromEntries(res.data.phases.map(p => [
        p.name, { start: toLocalInput(p.start), end: toLocalInput(p.end), enforced: p.enforced },
      ])));
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load the schedule.'));
    }
  }, []);

  const loadGrants = useCallback(async () => {
    try {
      const res = await api.get('/admin/exception-grants');
      setGrants(res.data || []);
    } catch { /* non-fatal: the panel still shows the timeline */ }
  }, []);

  useEffect(() => {
    load();
    loadGrants();
    // Re-fetch rather than counting down locally off a stale clock, so the
    // countdown stays anchored to server time.
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load, loadGrants]);

  const saveSchedule = async () => {
    setSaving(true);
    try {
      const phases = {};
      Object.entries(draft).forEach(([name, w]) => {
        phases[name] = {
          start: w.start ? new Date(w.start).toISOString() : null,
          end: w.end ? new Date(w.end).toISOString() : null,
          enforced: Boolean(w.enforced),
        };
      });
      await api.post('/admin/schedule/phases', { phases, round_id: data?.round_id || 'round-1' });
      await load();
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not save the schedule.'));
    } finally {
      setSaving(false);
    }
  };

  const grantException = async (e) => {
    e.preventDefault();
    if (!grantForm.reason.trim()) return;
    try {
      await api.post('/admin/exception-grants', {
        student_id: grantForm.student_id,
        phase: grantForm.phase,
        reason: grantForm.reason,
        expires_at: grantForm.expires_at ? new Date(grantForm.expires_at).toISOString() : null,
      });
      setGrantForm({ student_id: '', phase: 'applications', reason: '', expires_at: '' });
      loadGrants();
    } catch (err) {
      alert(errText(err, 'Could not create the grant.'));
    }
  };

  const revoke = async (id) => {
    if (!window.confirm('Revoke this exception grant?')) return;
    try {
      await api.post(`/admin/exception-grants/${id}/revoke`);
      loadGrants();
    } catch (err) {
      alert(errText(err, 'Could not revoke.'));
    }
  };

  if (error && !data) return <p style={errStyle}>{error}</p>;
  if (!data) return <p style={mutedStyle}>Loading schedule…</p>;

  return (
    <div>
      <h4 style={panelTitle}>Election Timeline <span style={roundPill}>{data.round_id}</span></h4>

      <div style={phaseGrid}>
        {data.phases.map(p => (
          <div key={p.name} style={{ ...phaseCard, borderLeft: `4px solid ${STATE_COLORS[p.state]}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
              <strong style={{ fontSize: '13px' }}>{PHASE_LABELS[p.name]}</strong>
              <span style={{ ...statePill, color: STATE_COLORS[p.state] }}>{p.state}</span>
            </div>
            <p style={phaseMeta}>Opens: {fmt(p.start)}</p>
            <p style={phaseMeta}>Closes: {fmt(p.end)}</p>
            {p.state === 'upcoming' && p.seconds_until_start != null && (
              <p style={countdownStyle}>Opens in {countdown(p.seconds_until_start)}</p>
            )}
            {p.state === 'active' && p.seconds_until_end != null && (
              <p style={countdownStyle}>Closes in {countdown(p.seconds_until_end)}</p>
            )}
            <p style={{ ...phaseMeta, opacity: 0.6 }}>
              {p.enforced ? '🔒 Enforced — closed means blocked' : '👁 Advisory only — not enforced'}
            </p>
          </div>
        ))}
      </div>

      {canEdit && (
        <div style={{ ...panel, marginTop: '16px' }} className="card-pad">
          <h4 style={panelTitle}>Edit Phase Schedule</h4>
          <p style={mutedStyle}>
            A phase with no times set, or with enforcement off, behaves exactly as the system
            did before phases existed. Turning enforcement on blocks the action outright once
            the window closes.
          </p>
          <div className="table-scroll">
            <table style={tableStyle}>
              <thead>
                <tr>{['Phase', 'Start', 'End', 'Enforce'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {data.phases.map(p => (
                  <tr key={p.name}>
                    <td style={tdStyle}><strong>{PHASE_LABELS[p.name]}</strong></td>
                    <td style={tdStyle}>
                      <input type="datetime-local" style={inputStyle}
                        value={draft[p.name]?.start || ''}
                        onChange={e => setDraft({ ...draft, [p.name]: { ...draft[p.name], start: e.target.value } })} />
                    </td>
                    <td style={tdStyle}>
                      <input type="datetime-local" style={inputStyle}
                        value={draft[p.name]?.end || ''}
                        onChange={e => setDraft({ ...draft, [p.name]: { ...draft[p.name], end: e.target.value } })} />
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'center' }}>
                      <input type="checkbox" style={{ width: '20px', height: '20px' }}
                        checked={Boolean(draft[p.name]?.enforced)}
                        aria-label={`Enforce the ${PHASE_LABELS[p.name]} phase`}
                        onChange={e => setDraft({ ...draft, [p.name]: { ...draft[p.name], enforced: e.target.checked } })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button style={primaryBtn} onClick={saveSchedule} disabled={saving}>
            {saving ? 'Saving…' : 'Save Schedule'}
          </button>
          {error && <p style={errStyle}>{error}</p>}
        </div>
      )}

      {isChief && (
        <div style={{ ...panel, marginTop: '16px' }} className="card-pad">
          <h4 style={panelTitle}>Grant a Phase Exception</h4>
          <p style={mutedStyle}>
            Scoped to one named student, with a written reason, and logged. This is
            deliberately not a "reopen the phase" switch — a blanket reopen would let
            everyone back in and leave no record of who used the window.
          </p>
          <form onSubmit={grantException} style={formCol}>
            <input style={inputStyle} placeholder="Student ID" required
              value={grantForm.student_id}
              onChange={e => setGrantForm({ ...grantForm, student_id: e.target.value })} />
            <select style={inputStyle} value={grantForm.phase}
              aria-label="Phase"
              onChange={e => setGrantForm({ ...grantForm, phase: e.target.value })}>
              {Object.entries(PHASE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <textarea style={{ ...inputStyle, minHeight: '70px' }} required
              placeholder="Reason (required — this is the decision record)"
              value={grantForm.reason}
              onChange={e => setGrantForm({ ...grantForm, reason: e.target.value })} />
            <label style={mutedStyle}>Expires (optional)</label>
            <input type="datetime-local" style={inputStyle} value={grantForm.expires_at}
              onChange={e => setGrantForm({ ...grantForm, expires_at: e.target.value })} />
            <button style={primaryBtn} type="submit">Grant Exception</button>
          </form>
        </div>
      )}

      {grants.length > 0 && (
        <div style={{ ...panel, marginTop: '16px' }} className="card-pad">
          <h4 style={panelTitle}>Exception Grants ({grants.length})</h4>
          <div className="table-scroll">
            <table style={tableStyle}>
              <thead>
                <tr>{['Student', 'Phase', 'Reason', 'By', 'Expires', ''].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {grants.map(g => (
                  <tr key={g._id} style={{ opacity: g.revoked ? 0.4 : 1 }}>
                    <td style={tdStyle}>{g.full_name || g.student_id}</td>
                    <td style={tdStyle}>{PHASE_LABELS[g.phase] || g.phase}</td>
                    <td style={{ ...tdStyle, maxWidth: '260px' }}>{g.reason}</td>
                    <td style={tdStyle}>{g.granted_by}</td>
                    <td style={tdStyle}>{g.expires_at ? fmt(g.expires_at) : 'No expiry'}</td>
                    <td style={tdStyle}>
                      {isChief && !g.revoked && (
                        <button style={linkBtn} onClick={() => revoke(g._id)}>Revoke</button>
                      )}
                      {g.revoked && <span style={mutedStyle}>Revoked</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════ ACTIVITY LOG ══════════════════════════ */

export function ActivityLog() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('');
  const [actor, setActor] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (f = filter, a = actor) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (f) params.set('action', f);
      if (a) params.set('actor', a);
      const res = await api.get(`/admin/audit-log?${params.toString()}`);
      setEntries(res.data.entries || []);
      setTotal(res.data.total || 0);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load the activity log.'));
    } finally {
      setLoading(false);
    }
  }, [filter, actor]);

  useEffect(() => { load('', ''); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <h4 style={panelTitle}>Activity Log <span style={roundPill}>{total} entries</span></h4>
      <div style={filterRow} className="stack-mobile">
        <input style={{ ...inputStyle, maxWidth: '260px' }} placeholder="Filter by action…"
          value={filter} onChange={e => setFilter(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()} />
        <input style={{ ...inputStyle, maxWidth: '260px' }} placeholder="Filter by actor…"
          value={actor} onChange={e => setActor(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()} />
        <button style={ghostBtn} onClick={() => load()}>Search</button>
        {(filter || actor) && (
          <button style={ghostBtn} onClick={() => { setFilter(''); setActor(''); load('', ''); }}>Clear</button>
        )}
      </div>

      {error && <p style={errStyle}>{error}</p>}
      {loading && <p style={mutedStyle}>Loading…</p>}

      <div style={scrollBox} className="table-scroll">
        <table style={tableStyle}>
          <thead>
            <tr>{['When', 'Action', 'Actor', 'Details'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e._id} style={rowStyle}>
                <td style={{ ...tdStyle, whiteSpace: 'nowrap', fontSize: '11px', opacity: 0.7 }}>
                  {new Date(e.timestamp).toLocaleString('en-UG', { dateStyle: 'short', timeStyle: 'short' })}
                </td>
                <td style={{ ...tdStyle, fontWeight: 600 }}>{String(e.action).replace(/_/g, ' ')}</td>
                <td style={{ ...tdStyle, fontSize: '12px' }}>{e.actor}</td>
                <td style={{ ...tdStyle, fontSize: '11px', opacity: 0.75 }}>
                  {Object.entries(e.details || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </td>
              </tr>
            ))}
            {!entries.length && !loading && (
              <tr><td colSpan={4} style={emptyCell}>No log entries found.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ══════════════════════════ CHAIN VERIFY ══════════════════════════ */

export function ChainView() {
  const [checkpoints, setCheckpoints] = useState([]);
  const [anchorFailures, setAnchorFailures] = useState(0);
  const [verdict, setVerdict] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/audit/checkpoints');
      setCheckpoints(res.data.checkpoints || []);
      setAnchorFailures(res.data.anchor_failures || 0);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load checkpoints.'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const verify = async () => {
    setVerifying(true);
    setVerdict(null);
    try {
      const res = await api.get('/admin/audit/verify');
      setVerdict(res.data);
    } catch (e) {
      setError(errText(e, 'Verification failed to run.'));
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div>
      <h4 style={panelTitle}>Integrity Chain</h4>
      <p style={mutedStyle}>
        Every checkpoint is a SHA-256 fold over the ballot events it covers, anchored to
        immutable off-site storage. Verifying re-derives the whole chain from the raw
        events rather than trusting the stored hashes — so the checkpoints either match
        the ballot log or they do not.
      </p>

      <div style={filterRow} className="stack-mobile">
        <button style={primaryBtn} onClick={verify} disabled={verifying}>
          {verifying ? 'Verifying…' : '🔐 Verify Chain'}
        </button>
        <button style={ghostBtn} onClick={load}>Refresh</button>
      </div>

      {anchorFailures > 0 && (
        <p style={warnBanner}>
          ⚠️ {anchorFailures} checkpoint(s) failed to anchor off-site. The local chain is
          intact, but those checkpoints have no external witness.
        </p>
      )}

      {verdict && (
        <div style={verdict.valid ? okBanner : badBanner}>
          {verdict.valid ? (
            <>✅ Chain valid — {verdict.checkpoints_verified} checkpoint(s) re-derived and matched.
              <div className="hash-cell" style={{ fontSize: '11px', marginTop: '6px' }}>
                Head: {verdict.head_hash || '—'}
              </div>
            </>
          ) : (
            <>🚨 Chain MISMATCH at checkpoint {verdict.first_mismatch_checkpoint_id}.
              <div className="hash-cell" style={{ fontSize: '11px', marginTop: '6px' }}>
                Expected {verdict.expected} · Recomputed {verdict.recomputed}
              </div>
            </>
          )}
        </div>
      )}

      {error && <p style={errStyle}>{error}</p>}

      <div style={scrollBox} className="table-scroll">
        <table style={tableStyle}>
          <thead>
            <tr>{['Created', 'Events', 'Chain Hash'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {checkpoints.map(c => (
              <tr key={c.id} style={rowStyle}>
                <td style={{ ...tdStyle, whiteSpace: 'nowrap', fontSize: '11px' }}>{fmt(c.created_at)}</td>
                <td style={{ ...tdStyle, textAlign: 'center' }}>{c.event_count}</td>
                <td style={{ ...tdStyle, fontSize: '10px' }} className="hash-cell">{c.chain_hash}</td>
              </tr>
            ))}
            {!checkpoints.length && (
              <tr><td colSpan={3} style={emptyCell}>No checkpoints recorded yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ══════════════════════════ ANALYTICS ══════════════════════════ */

export function Analytics() {
  const [velocity, setVelocity] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [undervote, setUndervote] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [isOpen, setIsOpen] = useState(true);
  const [bucket, setBucket] = useState('hour');
  const [error, setError] = useState('');

  const load = useCallback(async (b = bucket) => {
    try {
      const [v, f, u, a, o] = await Promise.all([
        api.get(`/admin/analytics/turnout-velocity?bucket=${b}`),
        api.get('/admin/analytics/funnel'),
        api.get('/admin/analytics/undervote'),
        api.get('/admin/analytics/anomalies'),
        api.get('/admin/analytics/overview'),
      ]);
      setVelocity(v.data); setFunnel(f.data); setUndervote(u.data); setAnomalies(a.data);
      setIsOpen(o.data.is_open);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load analytics.'));
    }
  }, [bucket]);

  useEffect(() => { load(); }, [load]);

  const peakVotes = velocity?.series?.reduce((m, p) => Math.max(m, p.votes), 0) || 0;

  return (
    <div>
      <h4 style={panelTitle}>
        Analytics <span style={roundPill}>{isOpen ? 'Live' : 'Final'}</span>
      </h4>
      {error && <p style={errStyle}>{error}</p>}

      {/* Turnout velocity */}
      <div style={panel} className="card-pad">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: '13px' }}>Turnout Velocity</strong>
          <select style={{ ...inputStyle, width: 'auto' }} value={bucket}
            aria-label="Time bucket"
            onChange={e => { setBucket(e.target.value); load(e.target.value); }}>
            <option value="hour">Per hour</option>
            <option value="day">Per day</option>
          </select>
        </div>
        {velocity?.series?.length ? (
          <>
            <div style={sparkRow}>
              {velocity.series.map(p => (
                <div key={p.bucket} style={sparkCol} title={`${p.bucket}: ${p.votes} votes`}>
                  <div style={{
                    height: `${peakVotes ? (p.votes / peakVotes) * 100 : 0}%`,
                    background: 'var(--info)', width: '100%', borderRadius: '2px 2px 0 0',
                    minHeight: p.votes ? '2px' : '0',
                  }} />
                </div>
              ))}
            </div>
            <p style={mutedStyle}>
              {velocity.total_votes} ballots total · peak {velocity.peak?.votes} in {velocity.peak?.bucket}
            </p>
          </>
        ) : <p style={mutedStyle}>No ballots cast yet.</p>}
      </div>

      {/* Funnel */}
      <div style={{ ...panel, marginTop: '14px' }} className="card-pad">
        <strong style={{ fontSize: '13px' }}>Voter Funnel</strong>
        <p style={mutedStyle}>Conversion between stages, not just a count at each.</p>
        {funnel?.steps?.map(s => (
          <div key={s.stage} style={{ marginBottom: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
              <span style={{ textTransform: 'capitalize' }}>{s.stage.replace(/_/g, ' ')}</span>
              <span>{s.reached} · {s.conversion_from_previous_pct}%</span>
            </div>
            <div style={barTrack}>
              <div style={{
                width: `${funnel.total_registered ? (s.reached / funnel.total_registered) * 100 : 0}%`,
                height: '100%', background: 'var(--success)', borderRadius: '4px',
              }} />
            </div>
            {s.dropped_off > 0 && (
              <span style={{ fontSize: '11px', color: 'var(--danger)' }}>
                {s.dropped_off} dropped off here
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Undervote */}
      <div style={{ ...panel, marginTop: '14px' }} className="card-pad">
        <strong style={{ fontSize: '13px' }}>Per-Position Undervote</strong>
        <p style={mutedStyle}>
          Positions where fewer ballots were cast than there were voters who completed —
          i.e. voters who skipped that race.
        </p>
        <div className="table-scroll">
          <table style={tableStyle}>
            <thead>
              <tr>{['Position', 'Votes', 'Skipped', 'Rate'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {undervote?.positions?.map(p => (
                <tr key={p.position} style={rowStyle}>
                  <td style={tdStyle}>{p.position}</td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}>{p.votes_cast}</td>
                  <td style={{ ...tdStyle, textAlign: 'center' }}>{p.undervotes}</td>
                  <td style={{
                    ...tdStyle, textAlign: 'center', fontWeight: 600,
                    color: p.undervote_rate_pct > 25 ? 'var(--danger)' : 'var(--text-color)',
                  }}>{p.undervote_rate_pct}%</td>
                </tr>
              ))}
              {!undervote?.positions?.length && (
                <tr><td colSpan={4} style={emptyCell}>Nothing to report yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Anomalies */}
      <div style={{ ...panel, marginTop: '14px' }} className="card-pad">
        <strong style={{ fontSize: '13px' }}>Anomalies</strong>
        <p style={mutedStyle}>
          Blocked-access attempts, login and OTP lockouts, off-site anchor failures and
          high-impact actions, pulled out of the general log into one feed.
        </p>
        {anomalies?.summary_24h?.length ? (
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '10px' }}>
            {anomalies.summary_24h.map(s => (
              <span key={s.action} style={anomalyPill}>
                {s.action.replace(/_/g, ' ')}: <strong>{s.count_24h}</strong>
              </span>
            ))}
          </div>
        ) : <p style={mutedStyle}>Nothing flagged in the last 24 hours.</p>}

        <div style={scrollBox} className="table-scroll">
          <table style={tableStyle}>
            <thead>
              <tr>{['When', 'Event', 'Actor', 'Details'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {anomalies?.events?.map(e => (
                <tr key={e._id} style={rowStyle}>
                  <td style={{ ...tdStyle, whiteSpace: 'nowrap', fontSize: '11px' }}>
                    {new Date(e.timestamp).toLocaleString('en-UG', { dateStyle: 'short', timeStyle: 'short' })}
                  </td>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>{String(e.action).replace(/_/g, ' ')}</td>
                  <td style={{ ...tdStyle, fontSize: '12px' }}>{e.actor}</td>
                  <td style={{ ...tdStyle, fontSize: '11px', opacity: 0.75 }}>
                    {Object.entries(e.details || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                  </td>
                </tr>
              ))}
              {!anomalies?.events?.length && (
                <tr><td colSpan={4} style={emptyCell}>No anomalies recorded.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ══════════════ ROSTER STATS (IT Admin landing view) ══════════════ */

export function RosterStats() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await api.get('/admin/analytics/overview');
        if (alive) { setData(res.data); setError(''); }
      } catch (e) {
        if (alive) setError(errText(e, 'Could not load the roster snapshot.'));
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (error) return <p style={errStyle}>{error}</p>;
  if (!data) return <p style={mutedStyle}>Loading…</p>;

  const cards = [
    { label: 'Registered voters', value: data.total_registered },
    { label: 'Ballots cast', value: data.voted },
    { label: 'Turnout', value: `${data.turnout_pct}%` },
    { label: 'Phone on file', value: data.with_phone_on_file },
    { label: 'Candidates', value: data.candidates },
    { label: 'Positions', value: data.positions },
    { label: 'Pending applications', value: data.applications_pending },
    { label: 'Pending roster changes', value: data.student_changes_pending },
  ];

  return (
    <div>
      <h4 style={panelTitle}>
        Roster & Election Snapshot{' '}
        <span style={{ ...roundPill, color: data.is_open ? 'var(--success)' : 'var(--warning)' }}>
          {data.is_open ? 'Voting open' : 'Voting closed'}
          {data.is_certified ? ' · Certified' : ''}
        </span>
      </h4>
      <div style={statGrid}>
        {cards.map(c => (
          <div key={c.label} style={statCard}>
            <div style={{ fontSize: '24px', fontWeight: 800 }}>{c.value}</div>
            <div style={{ fontSize: '11px', opacity: 0.7 }}>{c.label}</div>
          </div>
        ))}
      </div>
      <div style={barTrack}>
        <div style={{ width: `${data.turnout_pct}%`, height: '100%', background: 'var(--success)', borderRadius: '4px' }} />
      </div>
    </div>
  );
}

/* ══════════ OFFICIAL CERTIFICATION BLOCK (admin-only) ══════════ */

export function OfficialCertificationBlock() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get('/admin/official-report');
      setReport(res.data);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not build the official report.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h4 style={panelTitle}>Official Certification Document</h4>
      <p style={mutedStyle}>
        The sworn declaration, signature grid and distribution list. These are served only
        by an authenticated endpoint — the public results page never receives them, so the
        boundary is what data is fetchable rather than a hidden element.
      </p>

      <div style={filterRow} className="stack-mobile">
        <button style={primaryBtn} onClick={load} disabled={loading}>
          {loading ? 'Building…' : '📄 Generate Official Document'}
        </button>
        {report && <button style={ghostBtn} onClick={() => window.print()}>🖨️ Print</button>}
      </div>

      {error && <p style={errStyle}>{error}</p>}

      {report && (
        <div style={officialDoc} className="official-doc">
          <div style={{ textAlign: 'center', marginBottom: '16px' }}>
            {report.university_name && <h3 style={{ margin: 0, fontSize: '16px' }}>{report.university_name}</h3>}
            <h3 style={{ margin: '4px 0', fontSize: '15px' }}>{report.org_name}</h3>
            <span style={report.is_certified ? okPill : warnPill}>
              {report.is_certified ? 'CERTIFIED' : 'NOT YET CERTIFIED'}
            </span>
          </div>

          {report.declaration ? (
            <div style={declarationBox} className="declaration-block">
              <h4 style={{ textAlign: 'center', textDecoration: 'underline', fontSize: '14px' }}>
                OFFICIAL DECLARATION OF {String(report.org_name).toUpperCase()} ELECTION RESULTS
              </h4>
              <p style={{ fontSize: '13px', textAlign: 'justify', lineHeight: 1.6 }}>
                {report.declaration}
              </p>
            </div>
          ) : (
            <p style={warnBanner}>
              The declaration is withheld until results are certified. Certification is the
              Chief Commissioner's action.
            </p>
          )}

          <div style={signatureGrid} className="signature-grid">
            {report.signatories.map((s, i) => (
              <div key={`${s.full_name}-${i}`}>
                <p style={{ fontWeight: 'bold', margin: 0, fontSize: '13px' }}>{s.full_name || '\u00a0'}</p>
                <p style={{ fontSize: '11px', margin: 0, fontStyle: 'italic', opacity: 0.8 }}>{s.role}</p>
                <div style={{ borderTop: '1px solid currentColor', marginTop: '26px' }} />
              </div>
            ))}
          </div>

          {report.cc_list?.length > 0 && (
            <div style={{ marginTop: '22px', fontSize: '11px', borderTop: '1px solid currentColor', paddingTop: '10px' }}>
              {report.cc_list.map((c, i) => <div key={i}>Cc: {c}</div>)}
            </div>
          )}

          <div style={{ marginTop: '24px', fontSize: '11px', borderTop: '1px dashed currentColor', paddingTop: '10px' }}>
            <p style={{ margin: '2px 0' }}>
              Integrity chain:{' '}
              <strong style={{ color: report.chain.valid ? 'var(--success)' : 'var(--danger)' }}>
                {report.chain.valid ? 'VERIFIED' : 'MISMATCH'}
              </strong>{' '}
              ({report.chain.checkpoints_verified} checkpoint(s))
            </p>
            <p style={{ margin: '2px 0' }} className="hash-cell">Fingerprint: {report.fingerprint}</p>
            <p style={{ margin: '2px 0', opacity: 0.7 }}>
              Generated {fmt(report.generated_at)} by {report.generated_by}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════ SHARED TAB HELPER ══════════════════════════ */

// The four tabs every dashboard gets. Keeping the id/label pairs here means a
// future tab is added once, not five times.
export const SHARED_TAB_DEFS = [
  { id: 'shared_timeline', label: '🗓 Timeline' },
  { id: 'shared_analytics', label: '📈 Analytics' },
  { id: 'shared_activity', label: '📜 Activity Log' },
  { id: 'shared_chain', label: '🔐 Chain Verify' },
];

export function SharedTabPanels({ activeTab, canEditSchedule = false, isChief = false }) {
  if (activeTab === 'shared_timeline') return <Timeline canEdit={canEditSchedule} isChief={isChief} />;
  if (activeTab === 'shared_analytics') return <Analytics />;
  if (activeTab === 'shared_activity') return <ActivityLog />;
  if (activeTab === 'shared_chain') return <ChainView />;
  return null;
}

/* ══════════════════════════ STYLES ══════════════════════════ */

const panel = { padding: '18px', border: '1px solid var(--border-color)', borderRadius: '12px', backgroundColor: 'var(--bg-color)' };
const panelTitle = { margin: '0 0 12px', fontSize: '15px', fontWeight: 600, color: 'var(--text-color)', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' };
const mutedStyle = { fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 10px' };
const errStyle = { fontSize: '12px', color: 'var(--danger)', margin: '8px 0' };
const roundPill = { fontSize: '10px', fontWeight: 700, padding: '3px 8px', borderRadius: '10px', background: 'color-mix(in srgb, var(--info) 18%, transparent)', color: 'var(--info)' };
const statePill = { fontSize: '10px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px' };
const phaseGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px' };
const phaseCard = { ...panel, padding: '14px' };
const phaseMeta = { fontSize: '11px', margin: '4px 0', color: 'var(--text-muted)' };
const countdownStyle = { fontSize: '12px', margin: '6px 0', fontWeight: 700, color: 'var(--info)' };
const filterRow = { display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '12px', alignItems: 'center' };
const formCol = { display: 'flex', flexDirection: 'column', gap: '10px' };
const inputStyle = { padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };
const primaryBtn = { padding: '10px 18px', color: '#fff', backgroundColor: 'var(--info)', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 700, fontSize: '13px' };
const ghostBtn = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const linkBtn = { background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontWeight: 700, fontSize: '12px' };
const scrollBox = { maxHeight: '460px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px', marginTop: '10px' };
const tableStyle = { width: '100%', borderCollapse: 'collapse' };
const thStyle = { padding: '10px 12px', textAlign: 'left', fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)', background: 'var(--surface-2)', position: 'sticky', top: 0 };
const tdStyle = { padding: '10px 12px', color: 'var(--text-color)', fontSize: '13px' };
const rowStyle = { borderBottom: '1px solid var(--border-color)' };
const emptyCell = { ...tdStyle, textAlign: 'center', opacity: 0.45, padding: '28px' };
const barTrack = { width: '100%', height: '8px', background: 'var(--surface-2)', borderRadius: '4px', overflow: 'hidden', marginTop: '6px' };
const sparkRow = { display: 'flex', alignItems: 'flex-end', gap: '2px', height: '90px', marginTop: '12px', overflowX: 'auto' };
const sparkCol = { flex: '1 0 6px', minWidth: '6px', height: '100%', display: 'flex', alignItems: 'flex-end' };
const statGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px', marginBottom: '14px' };
const statCard = { ...panel, padding: '14px', textAlign: 'center' };
const anomalyPill = { fontSize: '11px', padding: '4px 10px', borderRadius: '10px', background: 'color-mix(in srgb, var(--warning) 18%, transparent)', color: 'var(--warning)', fontWeight: 600 };
const okBanner = { padding: '12px', borderRadius: '8px', background: 'color-mix(in srgb, var(--success) 15%, transparent)', color: 'var(--success)', fontSize: '13px', fontWeight: 600, marginBottom: '10px' };
const badBanner = { padding: '12px', borderRadius: '8px', background: 'color-mix(in srgb, var(--danger) 15%, transparent)', color: 'var(--danger)', fontSize: '13px', fontWeight: 700, marginBottom: '10px' };
const warnBanner = { padding: '12px', borderRadius: '8px', background: 'color-mix(in srgb, var(--warning) 15%, transparent)', color: 'var(--warning)', fontSize: '12px', fontWeight: 600, marginBottom: '10px' };
const officialDoc = { ...panel, marginTop: '14px', background: 'var(--card-bg)' };
const declarationBox = { border: '2px solid currentColor', padding: '20px', marginBottom: '20px', fontFamily: '"Times New Roman", Times, serif' };
const signatureGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '26px', marginTop: '30px' };
const okPill = { fontSize: '10px', fontWeight: 800, padding: '4px 10px', borderRadius: '10px', background: 'color-mix(in srgb, var(--success) 18%, transparent)', color: 'var(--success)' };
const warnPill = { fontSize: '10px', fontWeight: 800, padding: '4px 10px', borderRadius: '10px', background: 'color-mix(in srgb, var(--warning) 18%, transparent)', color: 'var(--warning)' };
