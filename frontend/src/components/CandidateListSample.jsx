import React, { useEffect, useMemo, useState } from 'react';
import QRCode from 'qrcode';
import { docFileName, resolveDocTemplate } from '../documentTemplates';
import { paginate } from '../candidateListPages';
import { sampleSections, SAMPLE_LIST_ID } from '../candidateListSample';
import { PRINT_CSS } from '../candidateListPrint';
import { CL } from '../candidateListColors';
import { CandidateListPage, ScaledPage } from './CandidateListSheet';

// Superadmin "Print sample list": the chosen style with made-up names, the organisation's current branding and a
// SAMPLE watermark. The id does not exist, so its QR leads nowhere real. Nothing is read from or written to the server.
const btn = { padding: '9px 16px', borderRadius: 8, border: 'none', cursor: 'pointer', fontWeight: 600, background: `var(--accent-color, ${CL.blue})`, color: CL.white };
const ghost = { ...btn, background: 'transparent', color: 'var(--text-color)', border: '1px solid var(--border-color)' };

export default function SampleCandidateListDoc({ branding = {}, longNames = false, onClose }) {
  const [qr, setQr] = useState('');
  const orgName = branding.org_name || 'Your Organisation Name';
  const template = resolveDocTemplate(branding.document_template);
  const verifyUrl = `${window.location.origin}/verify-list/${SAMPLE_LIST_ID}`;
  const sections = useMemo(() => sampleSections(longNames), [longNames]);
  const pages = useMemo(() => paginate(sections), [sections]);
  const list = useMemo(() => ({
    list_id: SAMPLE_LIST_ID, org_name: orgName, issued_at: new Date().toISOString(), document_template: template,
    current: true, sections, count: sections.reduce((n, s) => n + s.names.length, 0),
  }), [orgName, template, sections]);

  useEffect(() => {
    QRCode.toDataURL(verifyUrl, { width: 240, margin: 4, errorCorrectionLevel: 'M' }).then(setQr).catch(() => setQr(''));
  }, [verifyUrl]);

  useEffect(() => {
    const prev = document.title;
    document.title = docFileName('Official List of Candidates (Sample)', '', orgName);
    return () => { document.title = prev; };
  }, [orgName]);

  return (
    <div className="cl-sample" style={{ padding: 20, minHeight: '100vh', background: 'var(--bg-color)' }}>
      <style>{PRINT_CSS}</style>
      <div className="no-print" style={{ maxWidth: 794, margin: '0 auto 16px', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" style={ghost} onClick={onClose}>← Back</button>
        <button type="button" style={btn} onClick={() => window.print()}>Print / Save as PDF</button>
        <span style={{ fontSize: 12, opacity: 0.7, color: 'var(--text-color)' }}>
          Sample of the Official List of Candidates · {template === 'formal' ? 'Formal digital seal' : 'Classic'} style · A4 portrait · {pages.length} page{pages.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="cl-sheets">
        {pages.map((items, i) => (
          <ScaledPage key={i} isLast={i === pages.length - 1}>
            <CandidateListPage sample list={list} branding={branding} items={items} page={i + 1} total={pages.length}
              verifyUrl={verifyUrl} qrDataUrl={qr} />
          </ScaledPage>
        ))}
      </div>
    </div>
  );
}
