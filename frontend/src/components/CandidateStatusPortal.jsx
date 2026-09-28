import React, { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import api from '../api';
import TabBar from './TabBar';
import { Icon } from './icons.jsx';
import { ScrollList } from './UIFeedback';
import usePolling from '../hooks/usePolling';
import { usePersistedTab } from '../session';
import { regNo } from '../regNo';
import ManifestoText from './ManifestoText';

const PrintStyles = () => (
  <style>{`
    @media print {
      .no-print { display: none !important; }
      body { background: #fff; }
      .csp-print-sheet { box-shadow: none !important; margin: 0 !important; }
    }
  `}</style>
);

function formatDate(d) {
  if (!d) return '';
  try { return new Date(d).toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }); } catch { return String(d); }
}

/**
 * Read-only, token-linked candidate portal (candidate-portal-spec §4.2).
 * Modeled on OverseerDashboard's layout (AdminHeader-style header, TabBar,
 * ScrollList) rather than custom chrome — same "here's information, nothing
 * to act on" pattern, minus any login/session: everything here comes from
 * the token in the URL, not an admin session.
 */
export default function CandidateStatusPortal({ token }) {
  const [branding, setBranding] = useState({});
  const [candidacies, setCandidacies] = useState(null); // null = loading
  const [error, setError] = useState('');
  const [publicResultsLive, setPublicResultsLive] = useState(false);
  const [selected, setSelected] = useState(0);
  const [tab, setTab] = usePersistedTab('candidate-status', 'application');
  const [printing, setPrinting] = useState(null); // 'application' | 'certificate' | 'denial' | null

  const fetchStatus = async ({ silent = false } = {}) => {
    try {
      const res = await api.get(`/candidates/status/${encodeURIComponent(token)}`);
      setCandidacies(res.data.candidacies || []);
      setPublicResultsLive(!!res.data.public_results_live);
      setError('');
    } catch (e) {
      if (!silent) setError(e?.response?.data?.detail || 'This status link could not be found.');
    }
  };

  useEffect(() => {
    api.get('/superadmin/branding').then(res => setBranding(res.data || {})).catch(() => {});
    fetchStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Results band updates live during voting without a manual refresh (§4.2).
  usePolling(() => fetchStatus({ silent: true }), 20000);

  const candidacy = candidacies?.[selected] || null;

  // When results are public from the start, they're already on display for everyone,
  // so this page doesn't repeat them in its own tab.
  const tabs = [
    { id: 'application', label: 'Application' },
    { id: 'vetting', label: 'Vetting' },
    { id: 'documents', label: 'Documents' },
    ...(publicResultsLive ? [] : [{ id: 'results', label: 'Results' }]),
  ];
  const activeTab = tabs.some(t => t.id === tab) ? tab : 'application';

  if (printing) {
    return (
      <>
        <PrintStyles />
        <PrintableDoc kind={printing} candidacy={candidacy} branding={branding} onClose={() => setPrinting(null)} />
      </>
    );
  }

  return (
    <div style={outerWrap}>
      <PrintStyles />
      <div style={container}>
        <div style={header} className="no-print">
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>Candidate Status</h2>
            <span style={sub}>{branding.org_name || 'Election'} · {branding.university_name || ''}</span>
          </div>
        </div>

        {error && (
          <div style={{ ...infoBox, borderColor: '#e74c3c40' }}>
            <p style={{ margin: 0, color: '#e74c3c', fontSize: '13px' }}><Icon name="warning" /> {error}</p>
          </div>
        )}

        {!error && candidacies === null && (
          <div style={emptyState}><p style={{ opacity: 0.5 }}>Loading your application status…</p></div>
        )}

        {!error && candidacies && candidacies.length === 0 && (
          <div style={emptyState}><p style={{ opacity: 0.5 }}>No applications found for this link.</p></div>
        )}

        {!error && candidacies && candidacies.length > 0 && (
          <>
            {/* §4.2: more than one position applied for → a simple picker above the tabs. */}
            {candidacies.length > 1 && (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }} className="no-print">
                {candidacies.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => setSelected(i)}
                    style={{ ...pillBtn, ...(i === selected ? pillBtnActive : {}) }}
                  >
                    {c.position_title}
                  </button>
                ))}
              </div>
            )}

            <div className="no-print">
              <TabBar tabs={tabs} activeTab={activeTab} onChange={setTab} />
              <div style={{ marginBottom: '20px' }} />
            </div>

            {candidacy.status === 'removed' && (activeTab === 'vetting' || activeTab === 'documents') && (
              <div style={{ ...infoBox, marginBottom: '16px' }}>
                <p style={{ margin: 0, fontSize: '13px' }}>
                  This candidacy was withdrawn after approval.
                </p>
              </div>
            )}

            {activeTab === 'application' && (
              <ApplicationTab candidacy={candidacy} onPrint={() => setPrinting('application')} />
            )}

            {activeTab === 'vetting' && (
              <VettingTab candidacy={candidacy} onPrintCertificate={() => setPrinting('certificate')} onPrintDenial={() => setPrinting('denial')} />
            )}

            {activeTab === 'documents' && (
              <DocumentsTab
                candidacy={candidacy}
                onPrintApplication={() => setPrinting('application')}
                onPrintCertificate={() => setPrinting('certificate')}
                onPrintDenial={() => setPrinting('denial')}
              />
            )}

            {activeTab === 'results' && <ResultsTab candidacy={candidacy} />}
          </>
        )}
      </div>
    </div>
  );
}

// ── Tabs ──

function ApplicationTab({ candidacy, onPrint }) {
  const snap = candidacy.application_snapshot;
  return (
    <div>
      <div style={appCard}>
        <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
          <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>{candidacy.position_title}</b>
          <span style={statusBadge(candidacy.status)}>{statusLabel(candidacy.status)}</span>
        </div>
        {snap ? (
          <>
            <p style={{ margin: '8px 0 0', fontSize: '13px', opacity: 0.7 }}>{snap.full_name}</p>
            <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.55 }}>
              Submitted {formatDate(snap.submitted_at)}
            </p>
            <ManifestoText text={snap.manifesto} />
          </>
        ) : (
          <p style={{ opacity: 0.5, fontSize: '13px', marginTop: '8px' }}>Application details are not available yet.</p>
        )}
      </div>
      {snap && (
        <button style={ghostBtn} onClick={onPrint}>View / print application</button>
      )}
    </div>
  );
}

function VettingTab({ candidacy, onPrintCertificate, onPrintDenial }) {
  if (candidacy.status === 'pending') {
    return <div style={emptyState}><p style={{ opacity: 0.5 }}>Your application is still under review.</p></div>;
  }
  // Exactly one of the two fixed documents, never both, never a live label
  // standing in for either (§4.2).
  if (candidacy.certificate_id) {
    return (
      <div style={appCard}>
        <p style={{ margin: 0, fontSize: '14px', color: 'var(--success)' }}>
          <Icon name="success" /> Your nomination for <strong>{candidacy.position_title}</strong> was approved.
        </p>
        <button style={{ ...ghostBtn, marginTop: '12px' }} onClick={onPrintCertificate}>View / print certificate</button>
      </div>
    );
  }
  if (candidacy.denial_snapshot) {
    return (
      <div style={appCard}>
        <p style={{ margin: 0, fontSize: '14px', color: '#e74c3c' }}>
          <Icon name="error" /> Your application for <strong>{candidacy.position_title}</strong> was not approved.
        </p>
        <button style={{ ...ghostBtn, marginTop: '12px' }} onClick={onPrintDenial}>View / print decision notice</button>
      </div>
    );
  }
  if (candidacy.status === 'removed') {
    return <div style={emptyState}><p style={{ opacity: 0.5 }}>This candidacy was withdrawn after approval.</p></div>;
  }
  return <div style={emptyState}><p style={{ opacity: 0.5 }}>Nothing to show yet.</p></div>;
}

function DocumentsTab({ candidacy, onPrintApplication, onPrintCertificate, onPrintDenial }) {
  const rows = [];
  if (candidacy.application_snapshot) {
    rows.push({ label: 'Application record', onClick: onPrintApplication });
  }
  if (candidacy.certificate_id) {
    rows.push({ label: 'Certificate of Nomination', onClick: onPrintCertificate });
  }
  if (candidacy.denial_snapshot) {
    rows.push({ label: 'Application Decision Notice', onClick: onPrintDenial });
  }
  if (rows.length === 0) {
    return <div style={emptyState}><p style={{ opacity: 0.5 }}>No documents available yet.</p></div>;
  }
  return (
    <ScrollList>
      {rows.map((r, i) => (
        <div key={i} style={{ ...appCard, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '14px', color: 'var(--text-color)' }}>{r.label}</span>
          <button style={ghostBtn} onClick={r.onClick}>View / print</button>
        </div>
      ))}
    </ScrollList>
  );
}

function ResultsTab({ candidacy }) {
  const r = candidacy.results;
  if (!r) {
    return <div style={emptyState}><p style={{ opacity: 0.5 }}>Results are not open yet.</p></div>;
  }
  return (
    <div style={appCard}>
      <p style={{ margin: 0, fontSize: '15px', color: 'var(--text-color)' }}>
        <strong>{r.trend === 'leading' ? 'Leading' : r.trend === 'tied' ? 'Tied' : 'Trailing'}</strong>
        {' — '}rank {r.rank} of {r.of}
      </p>
      <p style={{ margin: '6px 0 0', fontSize: '11px', opacity: 0.5 }}>
        Live figures — no vote counts or opponent names are shown here.
      </p>
    </div>
  );
}

// ── Printable documents (§3.5 / §4.2) ──
// Each mirrors the printed-sample templates: plain @media print + a
// window.print() button, same pattern FinalReport.jsx already uses.
// Renders frozen *_snapshot / certificate fields only — never live
// application data — so a later correction never changes what was already
// "printed".

function PrintableDoc({ kind, candidacy, branding, onClose }) {
  if (kind === 'application') return <ApplicationSnapshotDoc candidacy={candidacy} branding={branding} onClose={onClose} />;
  if (kind === 'certificate') return <CertificateDoc candidacy={candidacy} branding={branding} onClose={onClose} />;
  if (kind === 'denial') return <DenialNoticeDoc candidacy={candidacy} branding={branding} onClose={onClose} />;
  return null;
}

function DocShell({ children, maxWidth = 760, onClose }) {
  return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9' }}>
      <div style={{ maxWidth, margin: '16px auto 0', padding: '0 4px', display: 'flex', justifyContent: 'space-between' }} className="no-print">
        <button onClick={onClose} style={{ background: 'none', border: '1px solid #cbd5e1', color: '#475569', padding: '10px 18px', borderRadius: '6px', fontSize: '14px', cursor: 'pointer' }}>← Back</button>
        <button onClick={() => window.print()} style={{ background: '#3b82f6', color: '#fff', border: 'none', padding: '10px 18px', borderRadius: '6px', fontSize: '14px', cursor: 'pointer' }}>Print / Save as PDF</button>
      </div>
      <div className="csp-print-sheet" style={{ maxWidth, margin: '16px auto 40px', background: '#fff', boxShadow: '0 1px 6px rgba(0,0,0,0.15)', padding: 40, color: '#1e293b', fontFamily: '-apple-system, "Segoe UI", Arial, sans-serif' }}>
        {children}
      </div>
    </div>
  );
}

function ApplicationSnapshotDoc({ candidacy, branding, onClose }) {
  const snap = candidacy.application_snapshot || {};
  return (
    <DocShell onClose={onClose}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ width: 90 }}>{branding.university_logo_url && <img src={branding.university_logo_url} alt="" style={{ width: '100%' }} />}</div>
        <div style={{ textAlign: 'center', flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 20, textTransform: 'uppercase', fontWeight: 900 }}>{branding.university_name}</h1>
          <h2 style={{ margin: '2px 0', fontSize: 16 }}>{branding.org_name}</h2>
          <h3 style={{ margin: '6px 0 0', fontSize: 13, fontWeight: 500, color: '#475569' }}>Candidate Application Record</h3>
        </div>
        <div style={{ width: 90, textAlign: 'right' }}>{branding.logo_url && <img src={branding.logo_url} alt="" style={{ width: '100%' }} />}</div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '2px solid #3b82f6', paddingBottom: 10, marginBottom: 24, fontSize: 12 }}>
        <div>
          <p style={{ margin: '2px 0' }}><strong>Position applied for:</strong> {candidacy.position_title}</p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <p style={{ margin: '2px 0' }}><strong>Submitted:</strong> {formatDate(snap.submitted_at)}</p>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 24, alignItems: 'flex-start' }}>
        {snap.image_url && <img src={snap.image_url} alt="" style={{ width: 96, height: 96, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0' }} />}
        <dl style={{ flex: 1, margin: 0 }}>
          <dt style={{ fontSize: 10, textTransform: 'uppercase', color: '#64748b' }}>Full name</dt>
          <dd style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{snap.full_name}</dd>
          <dt style={{ fontSize: 10, textTransform: 'uppercase', color: '#64748b', marginTop: 8 }}>Registration number</dt>
          <dd style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{regNo(snap.student_id)}</dd>
        </dl>
      </div>

      <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, color: '#3b82f6', borderBottom: '1px solid #e2e8f0', paddingBottom: 6, margin: '24px 0 10px' }}>Manifesto</div>
      <div style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: '#334155' }}>{snap.manifesto}</div>

      <div style={{ marginTop: 36, paddingTop: 14, borderTop: '1px dashed #cbd5e1', fontSize: 10, color: '#94a3b8', textAlign: 'center', lineHeight: 1.5 }}>
        This document is a record of the application exactly as submitted on the date above.
        It does not reflect any correction made to the applicant's record afterwards.<br />
        Generated by {branding.org_name}.
      </div>
    </DocShell>
  );
}

function CertificateDoc({ candidacy, branding, onClose }) {
  const [qrDataUrl, setQrDataUrl] = useState('');
  // Opens the public /verify page in this app, which reads the backend endpoint.
  const verifyUrl = `${window.location.origin}/verify/${candidacy.certificate_id}`;

  useEffect(() => {
    // Client-side only — no network call to render this, unlike the
    // third-party QR image service FinalReport.jsx deliberately dropped.
    // This one points at a real backend endpoint that checks a database row.
    QRCode.toDataURL(verifyUrl, { width: 84, margin: 0 })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(''));
  }, [verifyUrl]);

  return (
    <DocShell maxWidth={800} onClose={onClose}>
      <div style={{ border: '3px double #b8860b', padding: '44px 48px', position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <div style={{ width: 74 }}>{branding.university_logo_url && <img src={branding.university_logo_url} alt="" style={{ width: '100%' }} />}</div>
          <div style={{ textAlign: 'center', flex: 1 }}>
            <h1 style={{ margin: 0, fontSize: 15, textTransform: 'uppercase', fontWeight: 800, color: '#64748b', letterSpacing: 1 }}>{branding.university_name}</h1>
            <h2 style={{ margin: '2px 0', fontSize: 20, fontWeight: 900 }}>{branding.org_name}</h2>
          </div>
          <div style={{ width: 74, textAlign: 'right' }}>{branding.logo_url && <img src={branding.logo_url} alt="" style={{ width: '100%' }} />}</div>
        </div>

        <div style={{ textAlign: 'center', fontFamily: 'Times New Roman, Times, serif', fontSize: 30, fontWeight: 700, letterSpacing: 3, color: '#b8860b', margin: '22px 0 4px' }}>
          Certificate of Nomination
        </div>
        <div style={{ textAlign: 'center', fontSize: 12, textTransform: 'uppercase', letterSpacing: 2, color: '#94a3b8', marginBottom: 30 }}>
          Duly vetted and cleared to contest
        </div>

        <div style={{ fontFamily: 'Times New Roman, Times, serif', fontSize: 16, lineHeight: 2, textAlign: 'center', margin: '0 10px 30px' }}>
          This is to certify that<br />
          <span style={{ fontSize: 22, fontWeight: 700, borderBottom: '1px solid #1e293b', paddingBottom: 2 }}>
            {candidacy.application_snapshot?.full_name}
          </span><br />
          has been reviewed and duly nominated as a candidate for the position of<br />
          <span style={{ fontWeight: 700 }}>{candidacy.position_title}</span><br />
          in the {branding.org_name} election.
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 44 }}>
          <div style={{ textAlign: 'center' }}>
            {qrDataUrl && <img src={qrDataUrl} alt="Verification QR code" style={{ width: 84, height: 84 }} />}
            <div style={{ fontSize: 9, color: '#94a3b8', marginTop: 4, letterSpacing: 1 }}>ID: {candidacy.certificate_id}</div>
            <div style={{ fontSize: 9, color: '#94a3b8' }}>Verify at {verifyUrl}</div>
          </div>
        </div>

        <div style={{ marginTop: 40, paddingTop: 12, borderTop: '1px dashed #d6c58a', textAlign: 'center', fontSize: 10, color: '#a8a29e' }}>
          Generated by {branding.org_name} · Scan the code or visit the link above to confirm this certificate against our records
        </div>
      </div>
    </DocShell>
  );
}

function DenialNoticeDoc({ candidacy, branding, onClose }) {
  const d = candidacy.denial_snapshot || {};
  return (
    <DocShell maxWidth={600} onClose={onClose}>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 24 }}>{branding.org_name} · {branding.university_name}</div>
      <h1 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 24px' }}>Application Decision Notice</h1>
      <dl style={{ margin: 0 }}>
        <Row label="Applicant" value={d.full_name} />
        <Row label="Position applied for" value={d.position_title} />
        <Row label="Decision" value="Not approved" />
        <Row label="Decision date" value={formatDate(d.decided_at)} />
      </dl>
      <p style={{ fontSize: 13, lineHeight: 1.6, color: '#334155', margin: '24px 0 0' }}>
        This notice reflects the vetting decision as made on the date above and does not change afterwards.
      </p>
      <div style={{ marginTop: 30, fontSize: 10, color: '#94a3b8' }}>Generated by {branding.org_name}.</div>
    </DocShell>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f1f5f9', fontSize: 13 }}>
      <dt style={{ color: '#64748b' }}>{label}</dt>
      <dd style={{ margin: 0, fontWeight: 600, textAlign: 'right' }}>{value}</dd>
    </div>
  );
}

// ── Helpers ──

function statusLabel(status) {
  if (status === 'pending') return 'UNDER REVIEW';
  if (status === 'approved') return 'APPROVED';
  if (status === 'denied') return 'NOT APPROVED';
  if (status === 'removed') return 'WITHDRAWN';
  return String(status || '').toUpperCase();
}

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

// ── Styles ──
const outerWrap  = { width: '100%', minHeight: '100vh', display: 'flex', justifyContent: 'center', backgroundColor: 'var(--bg-color)', padding: '20px' };
const container  = { width: '100%', maxWidth: '760px', backgroundColor: 'var(--card-bg)', borderRadius: '16px', padding: '30px', border: '1px solid var(--border-color)' };
const header     = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' };
const sub        = { fontSize: '12px', opacity: 0.6 };
const appCard    = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
const infoBox    = { padding: '12px 16px', backgroundColor: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--info) 30%, transparent)' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
const ghostBtn   = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const pillBtn    = { padding: '8px 14px', borderRadius: '999px', border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', cursor: 'pointer', fontSize: '13px' };
const pillBtnActive = { borderColor: 'var(--info)', color: 'var(--info)', fontWeight: 600 };
