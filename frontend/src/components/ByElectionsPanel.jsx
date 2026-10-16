import React, { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useConfirm, useToast } from './UIFeedback';
import { LoadingBlock } from './Spinner.jsx';

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
      setSuccess(`By-election created for ${tie.position}. Round ID: ${roundId}. Set its voting schedule before opening voting.`);
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
        <p className="perf-note">After creation, use the Timeline / schedule controls to set the new round’s opening and closing times. It does not open automatically.</p>
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
