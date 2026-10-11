import React, { useEffect, useRef, useState } from 'react';
import { properName, properTitle } from '../displayText';
import { sealAccent, sealInk } from '../documentTemplates';
import { OrgSeal } from './FormalCertificate';
import { PAGE_W, PAGE_H, fmtStamp } from '../candidateListPages';
import { CL } from '../candidateListColors';

// One A4 portrait page of the Official List of Candidates, in the organisation's certificate style
// ("classic" gold double border, or "formal" digital seal). Drawn on a fixed 794 x 1123 sheet and scaled to the
// screen; printing uses it at full size. Every page carries the footer (QR, list id, issue time), so a single
// torn-out or photocopied page can still be checked on its own.
const SERIF = 'Georgia, "Times New Roman", Times, serif';
const TIMES = '"Times New Roman", Times, serif';

const shortDate = (d) => {
  try { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); } catch { return ''; }
};

// Screen: scaled to the column. Print: full size, one sheet per page (see PRINT_CSS).
export function ScaledPage({ children, isLast }) {
  const ref = useRef(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () => setScale(Math.min(1, el.clientWidth / PAGE_W) || 1);
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} className={`cl-fit${isLast ? ' cl-last' : ''}`} style={{ width: '100%', maxWidth: PAGE_W, height: PAGE_H * scale, margin: '0 auto 16px', overflow: 'hidden' }}>
      <div className="cl-fit-in" style={{ width: PAGE_W, height: PAGE_H, transform: `scale(${scale})`, transformOrigin: 'top left' }}>{children}</div>
    </div>
  );
}

function Superseded({ at }) {
  return (
    <>
      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', overflow: 'hidden' }}>
        <div style={{ fontSize: 110, fontWeight: 900, letterSpacing: 8, color: 'rgba(180,30,30,0.14)', transform: 'rotate(-28deg)', whiteSpace: 'nowrap' }}>SUPERSEDED</div>
      </div>
      <div style={{ position: 'absolute', top: 6, left: 0, right: 0, textAlign: 'center', fontSize: 12, fontWeight: 700, color: CL.red }}>
        Superseded on {fmtStamp(at)}. A newer list has been issued.
      </div>
    </>
  );
}

function Header({ template, list, branding, first, page, total, ink, accent }) {
  const formal = template === 'formal';
  const font = formal ? SERIF : TIMES;
  const org = list.org_name || branding.org_name || '';
  const stamp = `as at ${fmtStamp(list.issued_at)}`;
  if (!first) {
    return (
      <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px solid ${accent}`, paddingBottom: 8, fontFamily: font, fontSize: 13, color: ink }}>
        <span style={{ fontWeight: 700 }}>Official List of Candidates</span>
        <span>{org} · {stamp}</span>
        <span>Page {page} of {total}</span>
      </div>
    );
  }
  const logo = (src, alt) => (src ? <img src={src} alt={alt} style={{ height: 56, width: 'auto', maxWidth: 110, objectFit: 'contain' }} /> : <div style={{ width: 56 }} />);
  return (
    <div style={{ width: '100%', textAlign: 'center', fontFamily: font, color: ink }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        {logo(branding.university_logo_url, 'University logo')}
        <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
          <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: 3, textTransform: 'uppercase' }}>{org}</div>
          {branding.university_name ? <div style={{ marginTop: 2, fontSize: 12, letterSpacing: 2, textTransform: 'uppercase', opacity: 0.75 }}>{branding.university_name}</div> : null}
        </div>
        {logo(branding.logo_url, 'Organisation logo')}
      </div>
      <div style={{ marginTop: 14, fontSize: formal ? 38 : 40, fontWeight: 700, lineHeight: 1.05 }}>Official List of Candidates</div>
      <div style={{ marginTop: 6, fontSize: 14, fontStyle: formal ? 'normal' : 'italic' }}>{stamp} · Page {page} of {total}</div>
      <div style={{ margin: '10px auto 0', width: 150, height: 2, background: accent }} />
    </div>
  );
}

function Names({ items, formal, ink, accent }) {
  return (
    <div style={{ marginTop: 22, fontFamily: formal ? SERIF : TIMES, color: CL.text }}>
      {items.map((it) => (
        <div key={`${it.position}-${it.startIndex}`} style={{ marginBottom: 14, textAlign: formal ? 'left' : 'center' }}>
          <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: 2, textTransform: 'uppercase', color: formal ? ink : accent, borderBottom: formal ? `1px solid ${accent}` : 'none', paddingBottom: formal ? 3 : 0 }}>
            {properTitle(it.position)}{it.continued ? ' (continued)' : ''}
          </div>
          {it.names.map((n, i) => (
            <div key={n + i} style={{ fontSize: 18, lineHeight: 1.45, paddingLeft: formal ? 10 : 0, overflowWrap: 'anywhere' }}>
              {formal ? `${it.startIndex + i + 1}. ` : ''}{properName(n)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function Footer({ template, list, verifyUrl, qrDataUrl, ink, accent, org }) {
  const formal = template === 'formal';
  const host = String(verifyUrl).replace(/^https?:\/\//, '');
  return (
    <div style={{ marginTop: 'auto', width: '100%', borderTop: `1px solid ${accent}`, paddingTop: 12, display: 'flex', alignItems: 'center', gap: 14, fontFamily: formal ? SERIF : TIMES, color: CL.text }}>
      <div style={{ width: 128, height: 128, flex: 'none', border: `1px solid ${formal ? ink : accent}`, display: 'flex', alignItems: 'center', justifyContent: 'center', background: CL.white }}>
        {qrDataUrl ? <img src={qrDataUrl} alt="Verification QR code" style={{ width: 120, height: 120 }} /> : null}
      </div>
      <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, lineHeight: 1.45, overflowWrap: 'anywhere' }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: formal ? ink : CL.text }}>Digitally issued and verifiable</div>
        <div>List ID: {list.list_id}</div>
        <div>Issued: {fmtStamp(list.issued_at)}</div>
        <div>Verify: {host}</div>
        <div style={{ fontStyle: 'italic', opacity: 0.8, marginTop: 2 }}>Scan to confirm this list is current. If a candidate is removed or withdrawn, it shows as superseded.</div>
      </div>
      {formal ? <OrgSeal orgName={org} issued={shortDate(list.issued_at)} ink={ink} accent={accent} size={104} /> : null}
    </div>
  );
}

export function CandidateListPage({ list, branding = {}, items, page, total, verifyUrl, qrDataUrl }) {
  const template = list.document_template === 'formal' ? 'formal' : 'classic';
  const formal = template === 'formal';
  const ink = formal ? sealInk(branding.primary_color) : CL.text;
  const accent = sealAccent(branding.accent_color);
  const org = list.org_name || branding.org_name || '';
  const inner = {
    height: '100%', boxSizing: 'border-box', padding: formal ? '26px 44px 20px' : '30px 46px 22px',
    display: 'flex', flexDirection: 'column',
  };
  const body = (
    <>
      <Header template={template} list={list} branding={branding} first={page === 1} page={page} total={total} ink={ink} accent={accent} />
      <Names items={items} formal={formal} ink={ink} accent={accent} />
      <Footer template={template} list={list} verifyUrl={verifyUrl} qrDataUrl={qrDataUrl} ink={ink} accent={accent} org={org} />
    </>
  );
  return (
    <div className="cl-page" style={{ width: PAGE_W, height: PAGE_H, boxSizing: 'border-box', padding: 26, background: CL.white, position: 'relative', color: CL.text }}>
      {formal ? (
        <div style={{ height: '100%', boxSizing: 'border-box', border: `1px solid ${ink}`, padding: 6 }}>
          <div style={{ ...inner, border: `5px solid ${ink}` }}>{body}</div>
        </div>
      ) : (
        <div style={{ ...inner, border: `4px double ${accent}`, padding: '30px 46px 22px' }}>{body}</div>
      )}
      {list.current === false ? <Superseded at={list.superseded_at} /> : null}
    </div>
  );
}
