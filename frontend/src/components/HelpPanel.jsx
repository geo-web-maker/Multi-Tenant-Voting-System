import React from 'react';
import VoterRegisterSearch from './VoterRegisterSearch';
import { useHelpMenu } from '../context/HelpMenuContext';

const modalOverlayStyle = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(15, 23, 42, 0.85)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 3000, backdropFilter: 'blur(4px)' };
const modalContentStyle = {
  backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', padding: '32px', borderRadius: '20px',
  width: '92%', maxWidth: '760px', maxHeight: '85vh', overflowY: 'auto',
  boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', border: '1px solid var(--border-color)'
};

/**
 * Renders the expanded Help panel (when open) and the Voter Register
 * modal. Has no trigger of its own — mount once near the root, alongside
 * whichever <HelpTrigger /> variants are appropriate for the current page.
 * Anchors itself above the tallest currently-reported bottom bar via the
 * --bottom-bar-height CSS var (see useReportedHeight), so it never needs
 * to know which page it's on.
 */
export default function HelpPanel({ supportPdfUrl, supportPhone, onShowGuide }) {
  const { open, close, showRegister, openRegister, closeRegister } = useHelpMenu();

  const items = [
    { icon: '📖', label: 'Sample Ballot Paper', onClick: () => { onShowGuide(); close(); } },
    { icon: '🔍', label: 'Check Voter Register', onClick: openRegister },
    ...(supportPdfUrl ? [{ icon: '📄', label: 'Official Register (PDF)', href: supportPdfUrl }] : []),
    {
      icon: '💬', label: 'Contact Support', color: '#25D366',
      href: supportPhone ? `https://wa.me/${supportPhone}?text=Hello%20Admin,%20I%20am%20having%20issues%20with%20the%20Election%20Portal.` : undefined
    },
  ];

  return (
    <>
      {open && (
        <div style={menuPanelStyle}>
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

      {showRegister && (
        <div style={modalOverlayStyle} onClick={closeRegister}>
          <div style={modalContentStyle} onClick={e => e.stopPropagation()}>
            <VoterRegisterSearch />
            <button onClick={closeRegister} style={closeBtnStyle}>Close</button>
          </div>
        </div>
      )}
    </>
  );
}

const menuPanelStyle = {
  position: 'fixed',
  bottom: 'calc(var(--bottom-bar-height, 0px) + 84px)',
  right: '24px', zIndex: 2600,
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
