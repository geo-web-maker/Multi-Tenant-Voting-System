import React, { useEffect, useState } from 'react';
import api from '../api';
import { LoadingBlock } from './Spinner.jsx';
import { CL } from '../candidateListColors';

/** Public page a candidate list's QR code opens (/verify-list/<list_id>). Says whether the printed list is still current. */
export default function VerifyCandidateList({ listId }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    api.get(`/verify-list/${encodeURIComponent(listId)}`)
      .then((res) => setState({ data: res.data }))
      .catch((e) => setState({ notFound: e?.response?.status === 404, failed: e?.response?.status !== 404 }));
  }, [listId]);
  const { loading, data, notFound, failed } = state;
  const current = data?.current;
  const color = current ? `var(--bp-ok, ${CL.ok})` : `var(--bp-no, ${CL.danger})`;
  const when = (d) => (d ? new Date(d).toLocaleString(undefined, { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
  return (
    <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 20, background: 'var(--bg-color)' }}>
      <div style={{ width: '100%', maxWidth: 460, background: 'var(--card-bg)', border: '1px solid var(--border-color)', borderRadius: 16, padding: 28, textAlign: 'center', color: 'var(--text-color)' }}>
        <div style={{ fontSize: 12, letterSpacing: 1, textTransform: 'uppercase', opacity: 0.55, marginBottom: 12 }}>Candidate list verification</div>
        {loading && <LoadingBlock text="Checking our records…" />}
        {failed && <p style={{ color: `var(--bp-no, ${CL.danger})` }}>Could not reach the server. Please try again.</p>}
        {notFound && (
          <>
            <div style={{ fontSize: 22, fontWeight: 800, color: `var(--bp-no, ${CL.danger})`, marginBottom: 6 }}>List not found</div>
            <p style={{ fontSize: 13, opacity: 0.65 }}>No candidate list with this ID exists. It may be forged or mistyped.</p>
          </>
        )}
        {data && (
          <>
            <div style={{ fontSize: 22, fontWeight: 800, color, marginBottom: 6 }}>{current ? 'Current list' : 'Superseded list'}</div>
            <p style={{ fontSize: 13, opacity: 0.65, margin: '0 0 16px' }}>
              {current
                ? 'This is the most recent official list of candidates.'
                : `A newer list was issued on ${when(data.superseded_at)}. Please get the latest copy from the organisation.`}
            </p>
            <dl style={{ margin: 0, textAlign: 'left', fontSize: 14 }}>
              {[['Organisation', data.org_name], ['Issued', when(data.issued_at)]].map(([l, v]) => (
                <div key={l} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-color)' }}>
                  <dt style={{ opacity: 0.6 }}>{l}</dt><dd style={{ margin: 0, fontWeight: 600, textAlign: 'right' }}>{v}</dd>
                </div>
              ))}
            </dl>
            <div style={{ fontSize: 11, opacity: 0.45, marginTop: 16 }}>ID: {listId}</div>
          </>
        )}
      </div>
    </div>
  );
}
