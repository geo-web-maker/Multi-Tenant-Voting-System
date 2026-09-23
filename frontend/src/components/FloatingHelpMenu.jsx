import React, { useState } from 'react';
import VoterRegisterSearch from './VoterRegisterSearch';
import { Icon } from './icons.jsx';
import { buildSupportLink } from '../supportLink';

const modalOverlayStyle = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.85)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 3000, backdropFilter: 'blur(4px)' };
const modalContentStyle = {
  backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', padding: '32px', borderRadius: '20px',
  width: '92%', maxWidth: '760px', maxHeight: '85vh', overflowY: 'auto',
  boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', border: '1px solid var(--border-color)'
};

export default function FloatingHelpMenu({ supportPdfUrl, supportPhone, orgName = '', onShowGuide, showSampleBallot = true }) {
  const [open, setOpen] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const items = [
    // Once voting is no longer live (phase closed or election closed), the
    // ballot preview stops being offered — it's a "here's what you'll see
    // when you vote" guide, and showing it after voting has ended just
    // advertises something that's no longer possible.
    ...(showSampleBallot ? [{ label: 'Sample Ballot Paper', onClick: () => { onShowGuide(); setOpen(false); } }] : []),
    { label: 'Check Voter Register', onClick: () => { setShowRegister(true); setOpen(false); } },
    ...(supportPdfUrl ? [{ label: 'Official Register (PDF)', href: supportPdfUrl }] : []),
    {
      label: 'Contact Support', color: '#25D366',
      href: buildSupportLink(supportPhone, orgName, '', 'describe your problem here (never send your code)')
    },
  ];

  return (
    <>
      {open && (
        <div style={menuPanelStyle}>
          <div style={{ padding: '8px 12px', fontSize: '12px', opacity: 0.8, lineHeight: 1.5, maxWidth: '260px' }}>
            <b>Code not arriving?</b> Keep your phone on and wait for the countdown before tapping Resend — the same code is sent again while it is valid.
            If you see “try again in…”, the wait ends by itself; nothing needs to be reset. Nobody can send or read out your code.
          </div>
          {items.map((it, i) => it.href ? (
            <a key={i} href={it.href} target="_blank" rel="noopener noreferrer" style={{ ...menuItemStyle, color: it.color || 'var(--text-color)' }}>
              {it.label}
            </a>
          ) : (
            <button key={i} onClick={it.onClick} style={menuItemStyle}>
              {it.label}
            </button>
          ))}
        </div>
      )}

      <button onClick={() => setOpen(o => !o)} style={fabStyle()} aria-label="Help">
        {open ? <Icon name="close" /> : '?'} <span style={fabLabelStyle}>{open ? 'Close' : 'Help'}</span>
      </button>

      {showRegister && (
        <div style={modalOverlayStyle} onClick={() => setShowRegister(false)}>
          <div style={modalContentStyle} onClick={e => e.stopPropagation()}>
            <VoterRegisterSearch />
            <button onClick={() => setShowRegister(false)} style={closeBtnStyle}>Close</button>
          </div>
        </div>
      )}
    </>
  );
}

const fabStyle = () => ({
  position: 'fixed', bottom: '24px', right: '24px', zIndex: 2600,
  display: 'flex', alignItems: 'center', gap: '8px',
  padding: '14px 20px', borderRadius: '30px',
  backgroundColor: 'var(--brand-primary, #003366)', color: 'white',
  border: '2px solid var(--brand-accent, #f1c40f)',
  fontSize: '16px', fontWeight: 'bold', cursor: 'pointer',
  boxShadow: '0 8px 20px rgba(0,0,0,0.35)', transition: 'transform 0.15s',
});

const fabLabelStyle = { fontSize: '14px' };

const menuPanelStyle = {
  position: 'fixed', bottom: '84px', right: '24px', zIndex: 2600,
  backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', borderRadius: '16px',
  padding: '10px', boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
  border: '1px solid var(--border-color)',
  display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '240px'
};

const menuItemStyle = {
  display: 'flex', alignItems: 'center', gap: '10px',
  background: 'none', border: 'none', textAlign: 'left', padding: '10px 12px',
  borderRadius: '10px', cursor: 'pointer', fontSize: '14px', fontWeight: 600,
  color: 'inherit', textDecoration: 'none'
};

const closeBtnStyle = {
  width: '100%', marginTop: '20px', padding: '12px', borderRadius: '30px',
  border: '1px solid var(--border-color)', background: 'none', color: 'var(--text-color)',
  cursor: 'pointer', fontWeight: 'bold'
};
