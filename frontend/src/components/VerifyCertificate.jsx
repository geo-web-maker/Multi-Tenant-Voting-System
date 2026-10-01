import React, { useEffect, useState } from 'react';
import api from '../api';
import { properName, properTitle } from '../displayText';
import { LoadingBlock } from './Spinner.jsx';

/**
 * Public page a certificate's QR code opens (/verify/<certificate_id>).
 * Reads GET /verify/{id}, which checks the `certificates` collection only.
 */
export default function VerifyCertificate({ certificateId }) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    api.get(`/verify/${encodeURIComponent(certificateId)}`)
      .then(res => setState({ data: res.data }))
      .catch(e => setState({ notFound: e?.response?.status === 404, failed: e?.response?.status !== 404 }));
  }, [certificateId]);

  const { loading, data, notFound, failed } = state;
  const valid = data?.verified;
  const revoked = data && !data.verified;
  const color = valid ? '#2ecc71' : '#e74c3c';

  return (
    <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 20, background: 'var(--bg-color)' }}>
      <div style={{ width: '100%', maxWidth: 460, background: 'var(--card-bg)', border: '1px solid var(--border-color)', borderRadius: 16, padding: 28, textAlign: 'center', color: 'var(--text-color)' }}>
        <div style={{ fontSize: 12, letterSpacing: 1, textTransform: 'uppercase', opacity: 0.55, marginBottom: 12 }}>Certificate verification</div>
        {loading && <LoadingBlock text="Checking our records…" />}
        {failed && <p style={{ color: '#e74c3c' }}>Could not reach the server. Please try again.</p>}
        {(notFound || revoked || valid) && (
          <>
            <div style={{ fontSize: 22, fontWeight: 800, color, marginBottom: 6 }}>
              {valid ? 'Valid certificate' : revoked ? 'No longer valid' : 'Certificate not found'}
            </div>
            <p style={{ fontSize: 13, opacity: 0.65, margin: '0 0 16px' }}>
              {valid && 'This certificate matches our records.'}
              {revoked && 'This certificate was issued but has since been revoked (the candidacy was withdrawn).'}
              {notFound && 'No certificate with this ID exists. It may be forged or mistyped.'}
            </p>
            {valid && (
              <dl style={{ margin: 0, textAlign: 'left', fontSize: 14 }}>
                {[['Candidate', properName(data.candidate_name)], ['Position', properTitle(data.position_title)], ['Organisation', data.org_name],
                  ['Issued', data.issued_at ? new Date(data.issued_at).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) : '']].map(([l, v]) => (
                  <div key={l} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-color)' }}>
                    <dt style={{ opacity: 0.6 }}>{l}</dt><dd style={{ margin: 0, fontWeight: 600, textAlign: 'right' }}>{v}</dd>
                  </div>
                ))}
              </dl>
            )}
            <div style={{ fontSize: 11, opacity: 0.45, marginTop: 16 }}>ID: {certificateId}</div>
          </>
        )}
      </div>
    </div>
  );
}
