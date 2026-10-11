import React, { useEffect, useId, useRef, useState } from 'react';
import { properName, properTitle } from '../displayText';
import { sealAccent, sealInk } from '../documentTemplates';

// "Formal digital seal" certificate. Drawn on a fixed 960 x 679 sheet (A4 landscape proportions) and scaled to fit
// the screen; printing uses the sheet at full size (see PrintStyles in CandidateStatusPortal.jsx).
export const FORMAL_W = 960;
export const FORMAL_H = 679;
const SERIF = 'Georgia, "Times New Roman", Times, serif';

export function FitSheet({ width, height, children }) {
  const ref = useRef(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () => setScale(Math.min(1, el.clientWidth / width) || 1);
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);
  return (
    <div ref={ref} className="csp-fit" style={{ width: '100%', height: height * scale, overflow: 'hidden', '--fit-h': `${height}px` }}>
      <div className="csp-fit-in" style={{ width, height, transform: `scale(${scale})`, transformOrigin: 'top left' }}>{children}</div>
    </div>
  );
}

// A plain ring with the organisation name written around it. Short names repeat to fill the ring; long ones shrink.
export function OrgSeal({ orgName, issued, ink, accent, size = 150 }) {
  const rid = `seal-ring-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const base = String(orgName || '').trim().toUpperCase().slice(0, 64) || 'ORGANISATION';
  const unit = `${base} • `;
  const reps = unit.length * 7.2 <= 172 ? Math.max(1, Math.floor(312 / (unit.length * 7.2))) : 1;
  const text = unit.repeat(reps);
  const fs = reps > 1 ? 10 : Math.max(5.5, Math.min(10, 312 / (text.length * 0.72)));
  const mid = { textAnchor: 'middle', fontFamily: SERIF, fontWeight: 700, fill: ink, letterSpacing: 1 };
  return (
    <svg width={size} height={size} viewBox="0 0 140 140" role="img" aria-label={`Digitally issued seal, ${base}`} style={{ flex: 'none' }}>
      <circle cx="70" cy="70" r="67" fill="none" stroke={accent} strokeWidth="2" />
      <circle cx="70" cy="70" r="63" fill="none" stroke={accent} strokeWidth="1" />
      <circle cx="70" cy="70" r="40" fill="none" stroke={accent} strokeWidth="1" />
      <path id={rid} d="M 19,70 A 51,51 0 0,1 121,70 A 51,51 0 0,1 19,70" fill="none" />
      <text fill={ink} fontFamily={SERIF} fontWeight="700" fontSize={fs} letterSpacing="1">
        <textPath href={`#${rid}`} textLength="312" lengthAdjust="spacing">{text}</textPath>
      </text>
      <text x="70" y="62" fontSize="9" {...mid}>DIGITALLY</text>
      <text x="70" y="74" fontSize="9" {...mid}>ISSUED</text>
      <text x="70" y="88" fontSize="8" {...mid} fontWeight={500} letterSpacing={0}>{issued}</text>
    </svg>
  );
}

const shortDate = (d) => {
  try { return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); } catch { return ''; }
};

export function FormalCertificateSheet({ name, position, branding = {}, certificateId, issuedAt, issuedLabel = '', verifyUrl = '', qrDataUrl = '' }) {
  const ink = sealInk(branding.primary_color);
  const accent = sealAccent(branding.accent_color);
  const nominee = properName(name);
  const office = properTitle(position);
  const nameSize = nominee.length > 40 ? 28 : nominee.length > 28 ? 34 : 42;
  const officeSize = office.length > 48 ? 20 : office.length > 32 ? 24 : 28;
  const verifyHost = String(verifyUrl).replace(/^https?:\/\//, '').replace(/\/verify\/.*$/, '/verify');
  const orgName = branding.org_name || '';
  const logo = (src, alt) => (src ? <img src={src} alt={alt} style={{ height: 64, width: 'auto', maxWidth: 120, objectFit: 'contain' }} /> : <div style={{ width: 64 }} />);
  return (
    <div style={{ width: FORMAL_W, height: FORMAL_H, boxSizing: 'border-box', padding: 28, background: 'white', fontFamily: SERIF, color: ink, position: 'relative' }}>
      <div style={{ height: '100%', boxSizing: 'border-box', border: `1px solid ${ink}`, padding: 7 }}>
        <div style={{ height: '100%', boxSizing: 'border-box', border: `6px solid ${ink}`, padding: '18px 48px 14px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
          <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
            {logo(branding.university_logo_url, 'University logo')}
            <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
              <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: 4, textTransform: 'uppercase' }}>{orgName}</div>
              {branding.university_name ? <div style={{ marginTop: 2, fontSize: 13, letterSpacing: 2, textTransform: 'uppercase', opacity: 0.75 }}>{branding.university_name}</div> : null}
            </div>
            {logo(branding.logo_url, 'Organisation logo')}
          </div>
          <div style={{ marginTop: 14, fontSize: 46, fontWeight: 700, lineHeight: 1 }}>Certificate of Nomination</div>
          <div style={{ marginTop: 10, width: 170, height: 2, background: accent }} />
          <div style={{ marginTop: 16, fontSize: 20 }}>This certifies that</div>
          <div style={{ marginTop: 4, fontSize: nameSize, fontWeight: 700, fontStyle: 'italic', lineHeight: 1.15, overflowWrap: 'anywhere' }}>{nominee}</div>
          <div style={{ marginTop: 8, fontSize: 20, lineHeight: 1.5 }}>has been duly vetted and cleared to contest for the office of</div>
          <div style={{ marginTop: 2, fontSize: officeSize, fontWeight: 700, lineHeight: 1.2, overflowWrap: 'anywhere' }}>{office}</div>
          <div style={{ marginTop: 4, fontSize: 17 }}>in the {orgName} election.</div>
          <div style={{ marginTop: 'auto', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
            <div style={{ width: 270, display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left', fontSize: 14, lineHeight: 1.4 }}>
              <div style={{ width: 92, height: 92, flex: 'none', border: `1px solid ${ink}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {qrDataUrl ? <img src={qrDataUrl} alt="Verification QR code" style={{ width: 84, height: 84 }} /> : null}
              </div>
              <div>Scan to verify<br />this certificate</div>
            </div>
            <OrgSeal orgName={orgName} issued={shortDate(issuedAt)} ink={ink} accent={accent} />
            <div style={{ width: 270, textAlign: 'right', fontSize: 14, lineHeight: 1.5, overflowWrap: 'anywhere' }}>
              ID: {certificateId}<br />
              Issued {issuedLabel}<br />
              {verifyHost}
            </div>
          </div>
          <div style={{ marginTop: 8, fontSize: 11, opacity: 0.7 }}>
            Digitally issued by {orgName}. Authenticity is checked live on the verification page; a revoked certificate shows as invalid.
          </div>
        </div>
      </div>
    </div>
  );
}
