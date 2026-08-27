import React, { useState } from 'react';
import VoterRegisterSearch from './VoterRegisterSearch';

const modalOverlayStyle = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.85)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 3000, backdropFilter: 'blur(4px)' };
const modalContentStyle = {
  backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', padding: '32px', borderRadius: '20px',
  width: '92%', maxWidth: '760px', maxHeight: '85vh', overflowY: 'auto',
  boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', border: '1px solid var(--border-color)'
};

export default function FloatingHelpMenu({ supportPdfUrl, supportPhone, onShowGuide, bottomOffset = 24 }) {
  const [open, setOpen] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const items = [
    { icon: '📖', label: 'Sample Ballot Paper', onClick: () => { onShowGuide(); setOpen(false); } },
    { icon: '🔍', label: 'Check Voter Register', onClick: () => { setShowRegister(true); setOpen(false); } },
    ...(supportPdfUrl ? [{ icon: '📄', label: 'Official Register (PDF)', href: supportPdfUrl }] : []),
    {
      icon: '💬', label: 'Contact Support', color: '#25D366',
      href: supportPhone ? `https://wa.me/${supportPhone}?text=Hello%20Admin,%20I%20am%20having%20issues%20with%20the%20Election%20Portal.` : undefined
    },
  ];

  return (
    <>
      {open && (
        <div style={menuPanelStyle(bottomOffset)}>
          {items.map((it, i) => it.href ? (
            <a key={i} href={it.href} target="_blank" rel="noopener noreferrer" style={{ ...menuItemStyle, color: it.color || 'var(--text-color)' }}>
              <span>{it.icon}</span> {it.label}
            </a>
          ) : (
            <button key={i} onClick={it.onClick} style={menuItemStyle}>
              <span>{it.icon}</span> {it.label}
            </button>
          ))}
        </div>
      )}

      <button onClick={() => setOpen(o => !o)} style={fabStyle(open, bottomOffset)} aria-label="Help">
        <span style={fabLabelStyle}>{open ? '✕' : '?'}</span> <span style={fabLabelStyle}>{open ? 'Close' : 'Help'}</span>
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

const fabStyle = (open, bottomOffset = 24) => ({
  position: 'fixed', bottom: `${bottomOffset}px`, right: '24px', zIndex: 2600,
  display: 'flex', alignItems: 'center', gap: '8px',
  padding: '14px 20px', borderRadius: '30px',
  backgroundColor: 'var(--brand-primary, #003366)',
  color: '#ffffff',
  border: '2px solid var(--brand-accent, #f1c40f)',
  fontSize: '16px', fontWeight: 'bold', cursor: 'pointer',
  boxShadow: '0 8px 20px rgba(0,0,0,0.35)', transition: 'bottom 0.2s ease, transform 0.15s',
});

// Explicit color object, spread last so nothing else in the cascade can
// override it — the FAB background is always dark navy regardless of
// light/dark theme, so its text must always stay white.
const fabLabelStyle = { fontSize: '14px', color: '#ffffff' };

const menuPanelStyle = (bottomOffset = 24) => ({
  position: 'fixed', bottom: `${bottomOffset + 60}px`, right: '24px', zIndex: 2600,
  backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', borderRadius: '16px',
  padding: '10px', boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
  border: '1px solid var(--border-color)',
  display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '240px'
});

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
