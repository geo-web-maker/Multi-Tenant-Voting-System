import React, { useCallback, useEffect, useState } from 'react';
import QRCode from 'qrcode';
import api from '../api';
import { docFileName } from '../documentTemplates';
import { paginate, fmtStamp } from '../candidateListPages';
import { CandidateListPage, ScaledPage } from './CandidateListSheet';
import { LoadingBlock } from './Spinner.jsx';
import { CL } from '../candidateListColors';
import { PRINT_CSS } from '../candidateListPrint';

// Official List of Candidates. The system issues it by itself (when vetting closes, and after real changes to the
// approved candidates), so this block is mostly "download the current one". Download changes nothing: it prints
// the latest issued list. Superadmin and Commission also get a tucked-away "Issue now" for the case where
// something went wrong. The server enforces who may do what; the UI only mirrors it.

const errText = (e, fallback) => e?.response?.data?.detail || fallback;
const card = { padding: 16, border: '1px solid var(--border-color)', borderRadius: 12, background: 'var(--card-bg, transparent)', marginBottom: 16 };


const muted = { fontSize: 13, opacity: 0.7, margin: '4px 0 12px' };

export default function CandidateListBlock() {
  const [state, setState] = useState({ loading: true });
  const [qr, setQr] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get('/admin/candidate-list');
      setState({ data: res.data });
      setError('');
    } catch (e) {
      setState({});
      setError(errText(e, 'Could not load the candidate list.'));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const data = state.data;
  const list = data?.available ? data.list : null;
  const verifyUrl = list ? `${window.location.origin}/verify-list/${list.list_id}` : '';
  useEffect(() => {
    if (!verifyUrl) { setQr(''); return; }
    // Client-side only: no network call to render the QR.
    QRCode.toDataURL(verifyUrl, { width: 240, margin: 4, errorCorrectionLevel: 'M' }).then(setQr).catch(() => setQr(''));
  }, [verifyUrl]);

  const download = () => {
    const prevTitle = document.title;
    document.title = docFileName('Official List of Candidates', '', list.org_name || data.branding?.org_name);
    document.body.dataset.printing = 'candidate-list';
    const done = () => { document.title = prevTitle; delete document.body.dataset.printing; window.removeEventListener('afterprint', done); };
    window.addEventListener('afterprint', done);
    window.print();
  };

  const issueNow = async () => {
    setBusy(true);
    try {
      const res = await api.post('/admin/candidate-list/issue');
      await load();
      setError(res.data.status === 'unchanged' ? 'The current list already matches the approved candidates. Nothing new was issued.' : '');
    } catch (e) {
      setError(errText(e, 'Could not issue the list.'));
    } finally {
      setBusy(false);
    }
  };

  if (state.loading) return <LoadingBlock text="Loading candidate list…" />;
  const pages = list ? paginate(list.sections) : [];

  return (
    <div style={{ marginBottom: 24 }}>
      <style>{PRINT_CSS}</style>
      <div className="no-print">
        <h4 style={{ margin: '0 0 4px', fontSize: 15, fontWeight: 600, color: 'var(--text-color)' }}>Official List of Candidates</h4>
        <p style={muted}>
          Approved candidates only, in ballot order: names and positions, nothing else. The system issues it when vetting
          closes and again after any real change, so everyone downloads the same current list.
        </p>
        {error && <p style={{ color: `var(--danger, ${CL.danger})`, fontSize: 13 }}>{error}</p>}

        {!data?.available && data && (
          <div style={card}>
            {data.reason === 'not_closed'
              ? 'Not available until vetting closes. The list is issued automatically then.'
              : 'No official list issued yet. It appears here as soon as there are approved candidates after vetting closes.'}
          </div>
        )}

        {list && (
          <div style={card}>
            <div style={{ fontWeight: 700 }}>{list.current ? 'Current list' : 'Superseded list'} · {list.list_id}</div>
            <div style={muted}>
              Issued {fmtStamp(list.issued_at)} · {list.count} candidate{list.count === 1 ? '' : 's'} · {list.reason}
              {!list.current && ` · superseded ${fmtStamp(list.superseded_at)}`}
            </div>
            <button  onClick={download} className="perf-btn perf-btn-primary">Download PDF</button>
            <span style={{ fontSize: 12, opacity: 0.6, marginLeft: 10 }}>Choose “Save as PDF” in the print dialog.</span>
          </div>
        )}

        {data?.can_issue && (
          <details style={{ marginBottom: 16, fontSize: 13 }}>
            <summary style={{ cursor: 'pointer', opacity: 0.8 }}>Something wrong with the list?</summary>
            <p style={muted}>Issuing builds a new list from the approved candidates right now and marks the previous one as superseded.</p>
            <button  onClick={issueNow} disabled={busy} className="perf-btn">{busy ? 'Issuing…' : 'Issue now'}</button>
          </details>
        )}
      </div>

      {list && (
        <div className="cl-sheets">
          {pages.map((items, i) => (
            <ScaledPage key={i} isLast={i === pages.length - 1}>
              <CandidateListPage list={list} branding={data.branding || {}} items={items} page={i + 1} total={pages.length}
                verifyUrl={verifyUrl} qrDataUrl={qr} />
            </ScaledPage>
          ))}
        </div>
      )}
    </div>
  );
}
