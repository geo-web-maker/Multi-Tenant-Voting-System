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
import { properName, properTitle } from '../displayText';
import { faceCropUrl } from '../cloudinaryImage';
import { LoadingBlock } from './Spinner.jsx';
import { applicationVersions } from '../applicationVersions';

export const PrintStyles = () => (
  <style>{`
    @media print {
      * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      .no-print { display: none !important; }
      body { background: #fff; }
      .csp-outer { padding: 0 !important; background: #fff !important; }
      .csp-doc-card { max-width: none !important; padding: 0 !important; border: none !important; border-radius: 0 !important; background: transparent !important; }
      .csp-print-sheet { border: none !important; border-radius: 0 !important; padding: 0 !important; }
      .csp-page + .csp-page { break-before: page; page-break-before: always; margin-top: 0 !important; padding-top: 0 !important; border-top: none !important; }
      .csp-page { break-inside: avoid; page-break-inside: avoid; }
      /* Page breaks are ignored inside flex / fixed-height / scrolling ancestors, so flatten them for print. */
      html, body, #root { height: auto !important; min-height: 0 !important; overflow: visible !important; background: #fff !important; }
      .csp-outer, .csp-doc-card { display: block !important; min-height: 0 !important; height: auto !important; overflow: visible !important; }
      .csp-print-sheet { display: block !important; background: #fff !important; }
      @page { margin: 12mm; }
    }
    @media screen and (max-width: 560px) {
      .csp-outer { padding: 10px !important; }
      .csp-card { padding: 16px !important; border-radius: 12px !important; }
      /* logos share the first row (one left, one right); the text drops to its own full-width row */
      .csp-hd, .csp-dh { flex-wrap: wrap !important; row-gap: 8px !important; }
      .csp-hd-l, .csp-dh-l { order: 1; width: auto !important; }
      .csp-hd-r, .csp-dh-r { order: 2; width: auto !important; }
      .csp-hd-t, .csp-dh-t { order: 3; flex: 1 1 100% !important; padding: 0 !important; }
      .csp-dh img { width: 60px !important; }
      .csp-cert-box { padding: 22px 16px !important; }
    }
    /* index.css forces h1/h2/h3/p/span to var(--text-color) on screen; in OS dark
       mode that is near-white, which vanishes on the white sheet. Pin the sheet
       to light-mode values so documents look the same as the printed PDF. */
    .csp-print-sheet {
      color-scheme: light;
      --text-color: #1e293b;
      --text-muted: #64748b;
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
      if (res.data.branding) setBranding(res.data.branding);
      setError('');
    } catch (e) {
      if (!silent) setError(e?.response?.data?.detail || 'This status link could not be found.');
    }
  };

  useEffect(() => {
    api.get('/superadmin/branding').then(res => setBranding(b => (b.org_name ? b : (res.data || {})))).catch(() => {});
    fetchStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Results band updates live during voting without a manual refresh (§4.2).
  usePolling(() => fetchStatus({ silent: true }), 20000);

  const candidacy = candidacies?.[selected] || null;
  const who = candidacies?.find(c => c.application_snapshot)?.application_snapshot || null;

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
    <div style={outerWrap} className="csp-outer">
      <PrintStyles />
      <div style={container} className="csp-card">
        <div style={{ ...header, flexWrap: 'nowrap', gap: 14, marginBottom: 22 }} className="no-print csp-hd">
          <div style={{ width: 64, flexShrink: 0 }} className="csp-hd-l">
            {branding.university_logo_url && <img src={branding.university_logo_url} alt="" style={logoImg} />}
          </div>
          <div style={{ minWidth: 0, flex: 1, textAlign: 'center' }} className="csp-hd-t">
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>Candidate Status</h2>
            <span style={sub}>{branding.org_name || 'Election'} · {branding.university_name || ''}</span>
            {who && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-color)' }}>{properName(who.full_name)}</div>
                {who.student_id && <div style={{ ...sub, marginTop: 2 }}>Registration number: {regNo(who.student_id)}</div>}
              </div>
            )}
          </div>
          <div style={{ width: 64, flexShrink: 0, textAlign: 'right' }} className="csp-hd-r">
            {branding.logo_url && <img src={branding.logo_url} alt="" style={{ ...logoImg, marginLeft: 'auto' }} />}
          </div>
        </div>

        {error && (
          <div style={{ ...infoBox, borderColor: '#e74c3c40' }}>
            <p style={{ margin: 0, color: 'var(--bp-no, #e74c3c)', fontSize: '13px' }}><Icon name="warning" /> {error}</p>
          </div>
        )}

        {!error && candidacies === null && (
          <div style={emptyState}><LoadingBlock text="Loading your application status…" /></div>
        )}

        {!error && candidacies && candidacies.length === 0 && (
          <div style={emptyState}><p style={{ opacity: 0.5 }}>No applications found for this link.</p></div>
        )}

        {!error && candidacies && candidacies.length > 0 && (
          <>
            {/* One pill per position, coloured by status; with several positions it also acts as the picker (§4.2). */}
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }} className="no-print">
              {candidacies.map((c, i) => {
                const col = statusColor(c.status);
                const active = i === selected;
                return (
                  <button
                    key={i}
                    onClick={() => setSelected(i)}
                    title={statusLabel(c.status)}
                    style={{
                      ...pillBtn, display: 'inline-flex', alignItems: 'center', gap: 8,
                      borderColor: `color-mix(in srgb, ${col} ${active ? 100 : 45}%, transparent)`,
                      background: `color-mix(in srgb, ${col} ${active ? 18 : 10}%, var(--bg-color))`,
                      fontWeight: active ? 600 : 400,
                      boxShadow: active ? `0 0 0 1px ${col}` : 'none',
                    }}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: col, flexShrink: 0 }} />
                    {properTitle(c.position_title)}
                    <span style={{ fontSize: 10, letterSpacing: 0.5, textTransform: 'uppercase', color: col, fontWeight: 700 }}>
                      {statusLabel(c.status)}
                    </span>
                  </button>
                );
              })}
            </div>

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
          <b style={{ color: 'var(--text-color)', fontSize: '15px' }}>{properTitle(candidacy.position_title)}</b>
          <span style={statusBadge(candidacy.status)}>{statusLabel(candidacy.status)}</span>
        </div>
        {snap ? (
          <>
            <p style={{ margin: '8px 0 0', fontSize: '13px', opacity: 0.7 }}>{properName(snap.full_name)}</p>
            <p style={{ margin: '4px 0', fontSize: '12px', opacity: 0.55 }}>
              Submitted {formatDate(snap.submitted_at)}
            </p>
            {applicationVersions(snap, candidacy.edits).length > 1 && (
              <p style={{ margin: '4px 0', fontSize: '12px' }}>
                <span style={editedMark}>EDITED</span>{' '}
                <span style={{ opacity: 0.6 }}>corrected {formatDate(candidacy.edits[candidacy.edits.length - 1].at)} — the printout includes the original</span>
              </p>
            )}
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
          <Icon name="success" /> Your nomination for <strong>{properTitle(candidacy.position_title)}</strong> was approved.
        </p>
        <button style={{ ...ghostBtn, marginTop: '12px' }} onClick={onPrintCertificate}>View / print certificate</button>
      </div>
    );
  }
  if (candidacy.denial_snapshot) {
    return (
      <div style={appCard}>
        <p style={{ margin: 0, fontSize: '14px', color: 'var(--bp-no, #e74c3c)' }}>
          <Icon name="error" /> Your application for <strong>{properTitle(candidacy.position_title)}</strong> was not approved.
        </p>
        {candidacy.denial_snapshot.reason && (
          <p style={{ margin: '10px 0 0', fontSize: '13px', lineHeight: 1.5 }}>
            <strong>Denied by the Financial Controller:</strong> {candidacy.denial_snapshot.reason}
            <br />
            <span style={{ opacity: 0.7 }}>If you think this is a mistake, please contact the Finance office to have it fixed.</span>
          </p>
        )}
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

// Header layout follows FinalReport.jsx (university logo left, organisation logo
// right, text centred) but with the organisation name on top. The two variants
// use different typefaces: sans-serif for forms/notices, serif for the certificate.
function DocHeader({ branding, title, variant = 'form', marginBottom = 30 }) {
  const cert = variant === 'certificate';
  const font = cert ? 'Georgia, "Times New Roman", Times, serif' : 'inherit';
  const logoW = cert ? { uni: 96, org: 84 } : { uni: 80, org: 70 };
  return (
    <div style={{ marginBottom, fontFamily: font }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }} className="csp-dh">
        <div style={{ width: 110, textAlign: 'left', flexShrink: 0 }} className="csp-dh-l">
          {branding.university_logo_url && <img src={branding.university_logo_url} alt="University logo" style={{ width: logoW.uni, height: 'auto' }} />}
        </div>
        <div style={{ textAlign: 'center', flex: 1, padding: '0 10px', minWidth: 0, overflowWrap: 'anywhere' }} className="csp-dh-t">
          <div style={cert
            ? { fontSize: 'clamp(20px, 6.5vw, 30px)', fontWeight: 700, letterSpacing: 2, lineHeight: 1.2, color: '#7a5c00' }
            : { fontSize: 'clamp(16px, 5vw, 22px)', fontWeight: 900, textTransform: 'uppercase', color: '#1e293b' }}>
            {branding.org_name}
          </div>
          <div style={cert
            ? { margin: '8px 0 0', fontSize: 12, textTransform: 'uppercase', letterSpacing: 4, color: 'var(--bp-mu, #64748b)' }
            : { margin: '2px 0', fontSize: 16, fontWeight: 600, color: '#334155' }}>
            {branding.university_name}
          </div>
          {title && <div style={{ margin: '5px 0', fontSize: 16, fontWeight: 500, color: '#475569' }}>{title}</div>}
        </div>
        <div style={{ width: 110, textAlign: 'right', flexShrink: 0 }} className="csp-dh-r">
          {branding.logo_url && <img src={branding.logo_url} alt="Organisation logo" style={{ width: logoW.org, height: 'auto' }} />}
        </div>
      </div>
      {cert && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '18px auto 0', maxWidth: 360 }}>
          <div style={{ flex: 1, borderTop: '1px solid #b8860b' }} />
          <div style={{ color: '#b8860b', fontSize: 14, lineHeight: 1 }}>&#10086;</div>
          <div style={{ flex: 1, borderTop: '1px solid #b8860b' }} />
        </div>
      )}
    </div>
  );
}

// Wraps every printable document in the same chrome as the portal itself
// (themed page, bordered card, "Candidate Status" header), so opening a document
// feels like another view of the portal rather than a separate page. The white
// "paper" inside is what actually prints; everything else is .no-print.
// Chrome (and most browsers) use document.title as the default file name for
// "Save as PDF", so it is set while a document is open, for both the button and
// Ctrl+P, and restored when the document is closed.
function docFileName(kind, name, position) {
  const clean = (t) => String(t || '').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim();
  return [kind, properName(clean(name)), properTitle(clean(position))].filter(Boolean).join(' - ');
}

function DocShell({ children, maxWidth = 760, onClose, branding = {}, label = '', fileName = '' }) {
  useEffect(() => {
    if (!fileName) return undefined;
    const prev = document.title;
    document.title = fileName;
    return () => { document.title = prev; };
  }, [fileName]);
  return (
    <div style={outerWrap} className="csp-outer">
      <div style={{ ...container, maxWidth: maxWidth + 62 }} className="csp-doc-card csp-card">
        <div style={header} className="no-print">
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, color: 'var(--text-color)' }}>Candidate Status</h2>
            <span style={sub}>{branding.org_name || 'Election'} · {branding.university_name || ''}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onClose} style={ghostBtn}>← Back</button>
            <button onClick={() => window.print()} style={primaryBtn}>Print / Save as PDF</button>
          </div>
        </div>
        {label && (
          <div className="no-print" style={{ fontSize: 12, opacity: 0.6, marginBottom: 12, color: 'var(--text-color)' }}>
            {label} · this is how it will print
          </div>
        )}
        <div className="csp-print-sheet" style={{ background: '#fff', border: '1px solid var(--border-color)', borderRadius: 8, padding: 'clamp(16px, 5vw, 40px)', color: '#1e293b', fontFamily: '-apple-system, "Segoe UI", Arial, sans-serif' }}>
          {children}
        </div>
      </div>
    </div>
  );
}

function ApplicationPage({ version, position, branding, hasEdits }) {
  const isOriginal = version.kind === 'original';
  const stamp = isOriginal && hasEdits
    ? { text: 'ORIGINAL', color: '#64748b' }
    : !isOriginal ? { text: 'EDITED', color: '#b45309' } : null;
  const title = version.position_title || position;
  return (
    <div className="csp-page" style={{ position: 'relative' }}>
      {stamp && (
        <div style={{ position: 'absolute', top: 0, right: 0, border: `2px solid ${stamp.color}`, color: stamp.color, borderRadius: 4, padding: '2px 10px', fontSize: 12, fontWeight: 800, letterSpacing: 2, transform: 'rotate(4deg)' }}>
          {stamp.text}
        </div>
      )}
      <DocHeader branding={branding} title="Candidate Application Record" marginBottom={24} />

      {!isOriginal && (
        <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#92400e', marginBottom: 16 }}>
          <strong>Edited {formatDate(version.edited_at)}</strong> — corrected: {version.changedFields.join(', ')}.
          {' '}The application as it was before this correction is on the following page.
        </div>
      )}
      {isOriginal && hasEdits && (
        <div style={{ background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#475569', marginBottom: 16 }}>
          <strong>Original submission</strong> — kept for the record. It was later corrected; see the edited page.
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '2px solid #3b82f6', paddingBottom: 10, marginBottom: 24, fontSize: 12 }}>
        <div>
          <p style={{ margin: '2px 0' }}><strong>Position applied for:</strong> {properTitle(title)}</p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <p style={{ margin: '2px 0' }}><strong>Submitted:</strong> {formatDate(version.submitted_at)}</p>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 24, alignItems: 'flex-start' }}>
        {version.image_url && <img src={faceCropUrl(version.image_url, 96, 96)} alt="" style={{ width: 96, height: 96, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0' }} />}
        <dl style={{ flex: 1, margin: 0 }}>
          <dt style={{ fontSize: 10, textTransform: 'uppercase', color: '#64748b' }}>Full name</dt>
          <dd style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{properName(version.full_name)}</dd>
          <dt style={{ fontSize: 10, textTransform: 'uppercase', color: '#64748b', marginTop: 8 }}>Registration number</dt>
          <dd style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{regNo(version.student_id)}</dd>
        </dl>
      </div>

      <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, color: '#3b82f6', borderBottom: '1px solid #e2e8f0', paddingBottom: 6, margin: '24px 0 10px' }}>Manifesto</div>
      <div style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: '#334155' }}>{version.manifesto}</div>

      <div style={{ marginTop: 36, paddingTop: 14, borderTop: '1px dashed #cbd5e1', fontSize: 10, color: '#94a3b8', textAlign: 'center', lineHeight: 1.5 }}>
        {isOriginal
          ? 'This page is a record of the application exactly as submitted on the date above.'
          : 'This page shows the application after the correction dated above. Earlier versions are kept on their own pages.'}
        <br />Generated by {branding.org_name}.
      </div>
    </div>
  );
}

// Original submission snapshot + any later corrections, newest first, one printed page each.
// Also used by the superadmin dashboard (which builds `edits` from the application's own history).
export function ApplicationSnapshotDoc({ candidacy, branding, onClose }) {
  const snap = candidacy.application_snapshot || {};
  const versions = applicationVersions(candidacy.application_snapshot, candidacy.edits);
  const hasEdits = versions.length > 1;
  const current = versions[0] || snap;
  return (
    <DocShell onClose={onClose} branding={branding} label={hasEdits ? `Candidate Application Record · ${versions.length} pages (edited + original)` : 'Candidate Application Record'} fileName={docFileName('Application', current.full_name, current.position_title || candidacy.position_title)}>
      {versions.map((v, i) => (
        <ApplicationPage key={i} version={v} position={candidacy.position_title} branding={branding} hasEdits={hasEdits} />
      ))}
    </DocShell>
  );
}

function CertificateDoc({ candidacy, branding: liveBranding, onClose }) {
  // Prefer the frozen values stored on the certificate row over live branding.
  const cert = candidacy.certificate || {};
  const branding = { ...liveBranding, org_name: cert.org_name || liveBranding.org_name };
  const nomineeName = cert.candidate_name || candidacy.application_snapshot?.full_name || '';
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
    <DocShell maxWidth={800} onClose={onClose} branding={branding} label="Certificate of Nomination" fileName={docFileName('Certificate of Nomination', nomineeName, candidacy.position_title)}>
      <div style={{ border: '3px double #b8860b', padding: '44px 48px', position: 'relative' }} className="csp-cert-box">
        <DocHeader branding={branding} title="" variant="certificate" marginBottom={6} />

        <div style={{ textAlign: 'center', fontFamily: 'Times New Roman, Times, serif', fontSize: 30, fontWeight: 700, letterSpacing: 3, color: '#b8860b', margin: '22px 0 4px' }}>
          Certificate of Nomination
        </div>
        <div style={{ textAlign: 'center', fontSize: 12, textTransform: 'uppercase', letterSpacing: 2, color: '#94a3b8', marginBottom: 30 }}>
          Duly vetted and cleared to contest
        </div>

        <div style={{ fontFamily: 'Times New Roman, Times, serif', fontSize: 16, lineHeight: 2, textAlign: 'center', margin: '0 10px 30px' }}>
          This is to certify that<br />
          <span style={{ fontSize: 22, fontWeight: 700, borderBottom: '1px solid #1e293b', paddingBottom: 2 }}>
            {properName(nomineeName)}
          </span><br />
          has been reviewed and duly nominated as a candidate for the position of<br />
          <span style={{ fontWeight: 700 }}>{properTitle(candidacy.position_title)}</span><br />
          in the {branding.org_name} election.
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 44 }}>
          <div style={{ textAlign: 'center' }}>
            {qrDataUrl && <img src={qrDataUrl} alt="Verification QR code" style={{ width: 84, height: 84 }} />}
            <div style={{ fontSize: 9, color: '#94a3b8', marginTop: 4, letterSpacing: 1 }}>ID: {candidacy.certificate_id}</div>
            <div style={{ fontSize: 9, color: '#94a3b8', overflowWrap: 'anywhere' }}>Verify at {verifyUrl}</div>
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
    <DocShell maxWidth={600} onClose={onClose} branding={branding} label="Application Decision Notice" fileName={docFileName('Decision Notice', d.full_name, candidacy.position_title)}>
      <DocHeader branding={branding} title="Application Decision Notice" marginBottom={24} />
      <dl style={{ margin: 0 }}>
        <Row label="Applicant" value={properName(d.full_name)} />
        <Row label="Position applied for" value={properTitle(d.position_title)} />
        <Row label="Decision" value="Not approved" />
        {d.reason && <Row label="Denied by" value="Financial Controller" />}
        {d.reason && <Row label="Reason" value={d.reason} />}
        <Row label="Decision date" value={formatDate(d.decided_at)} />
      </dl>
      {d.reason && (
        <p style={{ fontSize: 13, lineHeight: 1.6, color: '#334155', margin: '16px 0 0' }}>
          If you believe this is an error, please contact the Finance office.
        </p>
      )}
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

function statusColor(status) {
  return { pending: 'var(--warning)', approved: 'var(--success)', denied: 'var(--danger)' }[status] || '#95a5a6';
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
// White tile so dark / transparent logos stay visible on the dark theme too.
const logoImg    = { maxWidth: 64, maxHeight: 64, objectFit: 'contain', display: 'block', background: '#fff', padding: 4, borderRadius: 8, boxSizing: 'border-box' };
const sub        = { fontSize: '12px', opacity: 0.6 };
const appCard    = { border: '1px solid var(--border-color)', borderRadius: '12px', padding: '16px', marginBottom: '12px', backgroundColor: 'var(--bg-color)' };
const infoBox    = { padding: '12px 16px', backgroundColor: 'color-mix(in srgb, var(--info) 10%, transparent)', borderRadius: '8px', border: '1px solid color-mix(in srgb, var(--info) 30%, transparent)' };
const emptyState = { textAlign: 'center', padding: '60px 20px', color: 'var(--text-color)' };
const ghostBtn   = { padding: '9px 14px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' };
const primaryBtn = { padding: '9px 14px', background: 'var(--info)', border: '1px solid var(--info)', color: 'var(--bp-ai, #fff)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 };
const pillBtn    = { padding: '8px 14px', borderRadius: '999px', border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', cursor: 'pointer', fontSize: '13px' };

const editedMark = { display: 'inline-block', border: '1px solid #b45309', color: '#b45309', borderRadius: 4, padding: '0 6px', fontSize: 10, fontWeight: 800, letterSpacing: 1 };
