import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast, useConfirm } from './UIFeedback';
import AdminHeader, { useLastSynced } from './AdminHeader';
import { LoadingBlock } from './Spinner.jsx';
import ManifestoText from './ManifestoText';
import TabBar from './TabBar';
import usePolling from '../hooks/usePolling';
import { usePersistedTab } from '../session';
import { faceCropUrl } from '../cloudinaryImage';
import { regNo } from '../regNo';
import { switchHat, PANEL_LINKED_KEY } from '../hatSwitch';

const RESOLVED = ['approved', 'denied', 'removed'];

// Vetting Panel view (guide 8.2, P3). The server shapes every payload: this screen only
// shows what it is given. Progress is "x of y voted"; the split appears only once resolved.
export default function VettingDashboard({ onLogout }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [tab, setTab] = usePersistedTab('vetting', 'pending');
  const [search, setSearch] = useState('');
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastSynced, markSynced] = useLastSynced();
  const [busy, setBusy] = useState({});
  const [reasons, setReasons] = useState({});
  const [me, setMe] = useState(null);
  const [meError, setMeError] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const linked = sessionStorage.getItem(PANEL_LINKED_KEY) === '1';

  const loadMe = useCallback(async () => {
    setMeError(false);
    try {
      const res = await api.get('/admin/vetting-me');
      setMe(res.data);
    } catch (e) {
      setMeError(true);
      toast(e.response?.data?.detail || 'Could not load your panel details.', { kind: 'error' });
    }
  }, [toast]);

  const load = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const res = await api.get('/admin/applications');
      setApps(res.data || []);
      markSynced();
    } catch (e) {
      if (!silent) toast(e.response?.data?.detail || 'Could not load applications.', { kind: 'error' });
    } finally {
      setLoading(false);
    }
  }, [toast, markSynced]);

  // Externals must accept the confidentiality notice before the server returns anything else (guide 6.4).
  const accessible = Boolean(me) && !(me.confidentiality_required && !me.confidentiality_accepted);

  useEffect(() => { loadMe(); }, [loadMe]);

  useEffect(() => { if (accessible) load(); }, [accessible, load]);

  // Shared polling: pauses when the tab is hidden and backs off after failures.
  usePolling(() => load({ silent: true }), 20000, accessible);

  const accept = async () => {
    setAccepting(true);
    try {
      await api.post('/admin/vetting-confidentiality/accept');
      await loadMe();
    } catch (e) {
      toast(e.response?.data?.detail || 'Could not record your acceptance.', { kind: 'error' });
    } finally {
      setAccepting(false);
    }
  };

  const act = async (key, request, okMsg) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      await request();
      toast(okMsg);
      await load({ silent: true });
    } catch (e) {
      toast(e.response?.data?.detail || 'That did not go through. Please refresh and try again.', { kind: 'error' });
    } finally {
      setBusy((b) => ({ ...b, [key]: false }));
    }
  };

  const vote = async (app, choice) => {
    const name = app.full_name || 'this applicant';
    const ok = await confirm(`Vote to ${choice} ${name}? Your vote is final and cannot be changed.`, {
      danger: choice === 'deny', confirmText: choice === 'approve' ? 'Approve' : 'Deny',
    });
    if (!ok) return;
    return act(`vote-${app.id || app._id}`, () => api.post(`/admin/applications/${app.id || app._id}/vote`, { vote: choice, reason: '' }),
      choice === 'approve' ? 'Vote recorded: approve.' : 'Vote recorded: deny.');
  };

  const tieBreak = async (app, decision) => {
    const id = app.id || app._id;
    const name = app.full_name || 'this applicant';
    const ok = await confirm(`Break the tie and ${decision} ${name}? This is final.`, {
      danger: decision === 'deny', confirmText: decision === 'approve' ? 'Approve' : 'Deny',
    });
    if (!ok) return;
    const reason = decision === 'deny' ? (reasons[id] || '').trim() : '';
    act(`tie-${id}`, () => api.post(`/admin/applications/${id}/tie-break`, { decision, reason }),
      `Tie broken: ${decision}.`);
  };

  if (!me && meError) {
    return (
      <Shell>
        <h2 style={{ marginTop: 0 }}>Vetting Panel</h2>
        <div style={card}>
          <p style={{ margin: '0 0 12px' }}>We could not load your panel details. Check your connection and try again.</p>
          <div style={row}>
            <button style={btnApprove} onClick={loadMe}>Retry</button>
            {onLogout && <button style={hatBtn} onClick={onLogout}>Log out</button>}
          </div>
        </div>
      </Shell>
    );
  }
  if (!me) return <Shell><LoadingBlock text="Loading…" /></Shell>;

  if (!accessible) {
    return (
      <Shell>
        <h2 style={{ marginTop: 0 }}>Confidentiality notice</h2>
        <div style={card}>
          <p style={{ margin: '0 0 12px', lineHeight: 1.5 }}>{me.confidentiality_notice}</p>
          {me.access_ends_at && (
            <p style={note}>Your access ends: {new Date(me.access_ends_at).toLocaleString()}.</p>
          )}
          <button style={btnApprove} disabled={accepting} onClick={accept}>
            {accepting ? 'Recording…' : 'I have read this and accept'}
          </button>
        </div>
        {onLogout && <button style={{ ...hatBtn, marginTop: 12 }} onClick={onLogout}>Log out</button>}
      </Shell>
    );
  }

  const pending = apps.filter((a) => !RESOLVED.includes(a.status));
  const resolved = apps.filter((a) => RESOLVED.includes(a.status));
  const q = search.trim().toLowerCase();
  const matches = (a) => !q
    || (a.full_name || '').toLowerCase().includes(q)
    || (a.student_id || '').toLowerCase().includes(q)
    || (a.position_title || '').toLowerCase().includes(q);
  const list = tab === 'pending' ? pending : resolved.filter(matches);

  return (
    <Shell>
      <AdminHeader
        title="Vetting Panel"
        subtitle={`${pending.length} pending · ${resolved.length} resolved${me.access_ends_at ? ` · access ends ${new Date(me.access_ends_at).toLocaleString()}` : ''}`}
        lastSynced={lastSynced}
        onRefresh={() => load()}
        refreshing={loading}
        onLogout={onLogout}
        actions={linked ? (
          <button style={hatBtn} onClick={() => switchHat().catch(() => toast('Could not switch back.', { kind: 'error' }))}>
            Switch back to Commissioner
          </button>
        ) : null}
      />

      <TabBar
        tabs={[
          { id: 'pending', label: <>Pending</>, count: pending.length },
          { id: 'resolved', label: <>Resolved</>, count: resolved.length },
        ]}
        activeTab={tab}
        onChange={setTab}
      />
      <div style={{ marginBottom: '20px' }} />

      {tab === 'resolved' && (
        <input
          style={{ ...input, marginBottom: '16px' }}
          placeholder="Search by name, registration number or position…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      )}

      {loading && apps.length === 0 && <LoadingBlock text="Loading applications…" />}
      {!loading && list.length === 0 && (
        <p style={{ opacity: 0.6 }}>{tab === 'pending' ? 'Nothing is waiting for a decision.' : 'No decisions yet.'}</p>
      )}

      {tab === 'pending' && list.map((app) => {
        const id = app.id || app._id;
        const p = app.progress || { cast: 0, panel_count: 0 };
        const cleared = Boolean(app.finance_cleared);
        const canVote = cleared && !app.my_vote && !app.awaiting_final_decision;
        return (
          <div key={id} style={card}>
            <div style={cardHead}>
              <ApplicantBlock app={app} showReg />
              <span style={pill}>{p.cast} of {p.panel_count} voted</span>
            </div>
            <ManifestoText text={app.manifesto} />

            {!cleared && <p style={note}>Waiting for finance clearance before voting opens.</p>}
            {app.my_vote && <p style={note}>You voted to {app.my_vote}.</p>}
            {canVote && (
              <div style={row}>
                <button style={btnApprove} disabled={busy[`vote-${id}`]} onClick={() => vote(app, 'approve')}>Approve</button>
                <button style={btnDeny} disabled={busy[`vote-${id}`]} onClick={() => vote(app, 'deny')}>Deny</button>
              </div>
            )}
            {app.awaiting_final_decision && !app.tie_break_available && (
              <p style={note}>All votes in, awaiting final decision.</p>
            )}

            {app.tie_break_available && (
              <div style={tieBox}>
                <p style={{ margin: '0 0 8px', fontWeight: 600 }}>Tied: your casting decision is needed.</p>
                <input
                  style={input}
                  placeholder="Reason (optional, stored only if you deny)"
                  maxLength={500}
                  value={reasons[id] || ''}
                  onChange={(e) => setReasons((r) => ({ ...r, [id]: e.target.value }))}
                />
                <div style={row}>
                  <button style={btnApprove} disabled={busy[`tie-${id}`]} onClick={() => tieBreak(app, 'approve')}>Approve</button>
                  <button style={btnDeny} disabled={busy[`tie-${id}`]} onClick={() => tieBreak(app, 'deny')}>Deny</button>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {tab === 'resolved' && list.map((app) => {
        const id = app.id || app._id;
        const split = app.final_split;
        return (
          <div key={id} style={card}>
            <div style={cardHead}>
              <ApplicantBlock app={app} showReg />
              <span style={pill}>{app.status}</span>
            </div>
            {app.decided_at && <p style={note}>Decided {new Date(app.decided_at).toLocaleDateString()}.</p>}
            {split && <p style={note}>Panel split: {split.approve} approve, {split.deny} deny.</p>}
            {app.decided_by_tie_break && <p style={note}>Decided by the Chairperson's tie-break.</p>}
            <p style={note}>Reason: {app.final_reason || 'No reason recorded'}</p>
          </div>
        );
      })}
    </Shell>
  );
}

// Same outer-wrap + dashboard-shell frame every other dashboard uses.
function Shell({ children }) {
  return (
    <div style={outerWrap} className="outer-wrap">
      <div style={container} className="dashboard-shell">{children}</div>
    </div>
  );
}

function ApplicantBlock({ app, showReg = false }) {
  const submitted = app.submitted_at ? new Date(app.submitted_at).toLocaleDateString() : null;
  return (
    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start', minWidth: 0 }}>
      {app.image_url && <img src={faceCropUrl(app.image_url, 56, 56)} alt="" style={avatar} />}
      <div style={{ minWidth: 0 }}>
        <strong>{app.full_name || 'Applicant'}</strong>
        <div style={meta}>
          {app.position_title || ''}{showReg && app.student_id ? ` · ${regNo(app.student_id)}` : ''}
        </div>
        {showReg && submitted && <div style={meta}>Submitted {submitted}</div>}
      </div>
    </div>
  );
}

const avatar   = { width: '56px', height: '56px', borderRadius: '10px', objectFit: 'cover', flexShrink: 0 };
const outerWrap = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container = { width: '100%', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const card     = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
const cardHead = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' };
const meta     = { fontSize: '12px', opacity: 0.6, marginTop: '2px' };
const pill     = { fontSize: '12px', padding: '4px 10px', borderRadius: '999px', border: '1px solid var(--border-color)', whiteSpace: 'nowrap' };
const note     = { fontSize: '13px', margin: '10px 0 0', opacity: 0.85 };
const row      = { display: 'flex', gap: '10px', marginTop: '12px' };
const tieBox   = { marginTop: '12px', padding: '12px', borderRadius: '8px', border: '1px solid var(--warning)' };
const input    = { width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', fontSize: '13px', marginBottom: '8px' };
const btnBase  = { padding: '8px 16px', borderRadius: '8px', border: 'none', color: '#fff', fontWeight: 'bold', cursor: 'pointer', fontSize: '13px' };
const btnApprove = { ...btnBase, backgroundColor: '#2ecc71' };
const btnDeny    = { ...btnBase, backgroundColor: '#e74c3c' };
const hatBtn   = { padding: '8px 14px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', cursor: 'pointer', fontSize: '13px', fontWeight: 600 };
