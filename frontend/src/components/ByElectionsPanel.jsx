import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useConfirm, useToast, usePrompt } from './UIFeedback';
import { LoadingBlock } from './Spinner.jsx';
import { askEarlyReason } from '../electionControls';
import { DEFAULT_TZ, parseUtc, utcToZonedInput, zonedInputToUtcISO, fmtZoned, utcOffsetLabel } from '../tz';

const STATE_TEXT = {
  unscheduled: 'Not scheduled yet. Voting stays closed until you set a start and end.',
  upcoming: 'Scheduled. Voting has not opened yet.',
  active: 'Voting is open for this by-election.',
  closed: 'Voting for this by-election has ended.',
};

function fmtCountdown(sec) {
  if (sec == null || sec < 0) return '';
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return [d && `${d}d`, (d || h) && `${h}h`, `${m}m`].filter(Boolean).join(' ');
}

/** Voting window for one by-election. Lives in this tab so it is set next to the tie it resolves. */
export function ByElectionSchedule({ roundId, position }) {
  const confirm = useConfirm();
  const prompt = usePrompt();
  const toast = useToast();
  const [info, setInfo] = useState(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/superadmin/by-elections/${encodeURIComponent(roundId)}/schedule`);
      setInfo(res.data);
      setDirty(prev => {
        if (!prev) {
          const tz = res.data.timezone || DEFAULT_TZ;
          setStart(utcToZonedInput(res.data.voting?.start, tz));
          setEnd(utcToZonedInput(res.data.voting?.end, tz));
        }
        return prev;
      });
      setError('');
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load the by-election schedule.');
    }
  }, [roundId]);

  useEffect(() => { load(); }, [load]);

  const tz = info?.timezone || DEFAULT_TZ;
  const canEdit = info && info.is_active_round && info.status !== 'certified' && info.state !== 'closed';

  const save = async () => {
    if (!start || !end) { setError('Choose both a start and an end time.'); return; }
    const startIso = zonedInputToUtcISO(start, tz);
    const endIso = zonedInputToUtcISO(end, tz);
    if (new Date(endIso) <= new Date(startIso)) { setError('The end time must be after the start time.'); return; }
    const ok = await confirm(
      <div style={{ textAlign: 'left', fontSize: 13, lineHeight: 1.6 }}>
        <b>All times are in {tz} ({utcOffsetLabel(tz)}).</b>
        <div>Voting opens: {fmtZoned(startIso, tz)}</div>
        <div>Voting closes: {fmtZoned(endIso, tz)}</div>
      </div>,
      { confirmText: 'Save by-election schedule' });
    if (!ok) return;
    setSaving(true); setError('');
    const url = `/superadmin/by-elections/${encodeURIComponent(roundId)}/schedule`;
    const body = { start: startIso, end: endIso, timezone: tz };
    try {
      try {
        await api.post(url, body);
      } catch (e) {
        const d = e?.response?.data?.detail;
        if (e?.response?.status !== 409 || d?.code !== 'early_end_reason_required') throw e;
        const reason = await askEarlyReason(d, prompt,
          'This change closes the by-election while it is still open (it was due to close {ends}).', 'Save schedule');
        if (reason == null) return;
        await api.post(url, { ...body, reason });
      }
      setDirty(false);
      toast('By-election schedule saved.', { kind: 'success' });
      await load();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not save the by-election schedule.');
    } finally {
      setSaving(false);
    }
  };

  const startsIn = fmtCountdown(info?.seconds_until_start);
  const endsIn = fmtCountdown(info?.seconds_until_end);

  return (
    <div className="perf-row" style={{ display: 'grid', gap: 8, padding: 12 }} data-testid="by-election-schedule">
      <div className="perf-row-title">By-election timeline{position ? ` · ${position}` : ''}</div>
      {!info && !error && <LoadingBlock text="Loading schedule…" />}
      {info && (
        <>
          <div className="perf-note">{STATE_TEXT[info.state] || ''}
            {info.state === 'upcoming' && startsIn ? ` Opens in ${startsIn}.` : ''}
            {info.state === 'active' && endsIn ? ` Closes in ${endsIn}.` : ''}</div>
          {info.voting?.start && info.voting?.end && parseUtc(info.voting.start) && (
            <div className="perf-note">Current window: {fmtZoned(info.voting.start, tz)} to {fmtZoned(info.voting.end, tz)}</div>
          )}
          {!info.is_active_round && <div className="perf-note">This is not the current round, so its schedule can no longer be changed.</div>}
          {canEdit && (
            <>
              <label style={{ display: 'grid', gap: 5 }}>
                <span className="perf-row-text">Voting opens ({tz})</span>
                <input type="datetime-local" className="perf-field" value={start}
                  onChange={e => { setStart(e.target.value); setDirty(true); }} />
              </label>
              <label style={{ display: 'grid', gap: 5 }}>
                <span className="perf-row-text">Voting closes ({tz})</span>
                <input type="datetime-local" className="perf-field" value={end}
                  onChange={e => { setEnd(e.target.value); setDirty(true); }} />
              </label>
              <div className="perf-btnbar">
                <button type="button" className="perf-btn perf-btn-primary" disabled={saving} onClick={save}>
                  {saving ? 'Saving…' : 'Save by-election schedule'}</button>
              </div>
            </>
          )}
        </>
      )}
      {error && <p className="perf-msg" data-kind="error" role="alert">{error}</p>}
    </div>
  );
}

/** Superadmin-only tie review and by-election creation. The API is the security boundary. */
export default function ByElectionsPanel() {
  const confirm = useConfirm();
  const toast = useToast();
  const [ties, setTies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [busyId, setBusyId] = useState('');
  const [reasonById, setReasonById] = useState({});
  const [eligibilityById, setEligibilityById] = useState({});
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const loadTies = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get('/superadmin/election-ties');
      setTies(Array.isArray(response.data?.ties) ? response.data.ties : []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load tie records. Confirm that this account has superadmin access.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTies(); }, [loadTies, refreshKey]);

  const createByElection = async (tie) => {
    const reason = (reasonById[tie.id] || '').trim();
    const eligibility_rule = eligibilityById[tie.id] || 'all_registered';
    if (reason.length < 10) {
      setError('Enter a reason of at least 10 characters before creating the by-election.');
      return;
    }
    const confirmed = await confirm(
      `Create a by-election for ${tie.position}? This cannot be undone. Round 1 results are kept.`,
      { title: 'Create by-election', danger: true, confirmText: 'Create by-election' },
    );
    if (!confirmed) return;

    setBusyId(tie.id); setError(''); setSuccess('');
    try {
      const response = await api.post('/superadmin/by-elections', {
        tie_id: tie.id, reason, eligibility_rule,
      });
      const roundId = response.data?.round_id || 'new round';
      setSuccess(`By-election created for ${tie.position}. Round ID: ${roundId}. Set its voting schedule below before opening voting.`);
      toast('By-election created. The new round is closed until it is scheduled.', { kind: 'success' });
      setRefreshKey(v => v + 1);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not create the by-election. Refresh the tie list and review the response.');
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="perf-stack" style={{ display: 'grid', gap: 16 }}>
      <section className="perf-card card-pad">
        <h3 style={{ margin: '0 0 6px', fontSize: 15 }}>Tie review and by-elections</h3>
        <p className="perf-lead">Review automatically detected ties. A by-election can only be created from a persisted tie record; Round 1 ballots remain unchanged.</p>
        <p className="perf-note">After creation, set the new round’s opening and closing times in its timeline below. It does not open automatically.</p>
        <div className="perf-btnbar">
          <button type="button" className="perf-btn" onClick={() => setRefreshKey(v => v + 1)} disabled={loading}>Refresh ties</button>
        </div>
        {error && <p className="perf-msg" data-kind="error" role="alert">{error}</p>}
        {success && <p className="perf-msg" data-kind="ok" role="status">{success}</p>}
        {loading ? <LoadingBlock text="Loading tie records…" /> : ties.length === 0 ? (
          <p className="perf-note">No tie records have been detected. Detection runs when a round has ended and its results are requested.</p>
        ) : (
          <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
            {ties.map(tie => {
              const ordered = tie.candidates || [];
              const names = ordered.map(c => c.name).join(' and ') || 'Candidate records unavailable';
              const created = Boolean(tie.by_election_round_id);
              const pending = ['pending', 'tie_pending_decision', undefined].includes(tie.status);
              return (
                <article key={tie.id} className="perf-row" style={{ display: 'grid', gap: 10, padding: 12 }}>
                  <div>
                    <div className="perf-row-title">{tie.position || 'Position'}{tie.tie_type === 'cutoff' ? ' · Seat cut-off tie' : ''} · {tie.count} vote{tie.count === 1 ? '' : 's'}</div>
                    <div className="perf-row-text">{names}</div>
                    <div className="perf-note">Status: {created ? 'By-election ordered' : tie.status === 'pending' ? 'Tie, pending decision' : tie.status || 'Tie, pending decision'}{tie.round_id ? ` · Source round: ${tie.round_id}` : ''}</div>
                    {created && <div className="perf-note">By-election round: {tie.by_election_round_id}</div>}
                  </div>
                  {created && <ByElectionSchedule roundId={tie.by_election_round_id} position={tie.position} />}
                  {!created && pending && (
                    <>
                      <label style={{ display: 'grid', gap: 5 }}>
                        <span className="perf-row-text">Reason for ordering the by-election</span>
                        <textarea className="perf-field" rows={2} maxLength={500} minLength={10} value={reasonById[tie.id] || ''}
                          onChange={e => setReasonById(prev => ({ ...prev, [tie.id]: e.target.value }))}
                          placeholder="Record the committee decision (at least 10 characters)" />
                      </label>
                      <label style={{ display: 'grid', gap: 5 }}>
                        <span className="perf-row-text">Who is eligible to vote?</span>
                        <select className="perf-field" value={eligibilityById[tie.id] || 'all_registered'}
                          onChange={e => setEligibilityById(prev => ({ ...prev, [tie.id]: e.target.value }))}>
                          <option value="all_registered">All registered voters</option>
                          <option value="round1_voters">Only voters who voted in Round 1</option>
                        </select>
                      </label>
                      <div className="perf-btnbar perf-btnbar-stack">
                        <button type="button" className="perf-btn perf-btn-primary" disabled={busyId === tie.id || ordered.length < 2}
                          onClick={() => createByElection(tie)}>{busyId === tie.id ? 'Creating…' : 'Create by-election'}</button>
                      </div>
                    </>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
