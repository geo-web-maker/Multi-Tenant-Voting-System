import React from 'react';
import VoterRegisterSearch from './VoterRegisterSearch';
import ElectionTimeline from './ElectionTimeline';
import FeeSchedule from './FeeSchedule';
import { useHelpMenu } from '../context/HelpMenuContext';
import { buildSupportLink } from '../supportLink';

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
export default function HelpPanel({ supportPhone, supportContacts = [], orgName = '', onShowGuide }) {
  const { open, close, showRegister, openRegister, closeRegister, showTimeline, openTimeline, closeTimeline, showFees, openFees, closeFees } = useHelpMenu();
  // Which reason's contact submenu is open (null = showing the main list). Reset whenever the
  // main panel closes so re-opening Help never lands on a stale submenu.
  const [subReason, setSubReason] = React.useState(null);
  React.useEffect(() => { if (!open) setSubReason(null); }, [open]);

  const items = [
    { label: 'Sample Ballot Paper', onClick: () => { onShowGuide(); close(); } },
    { label: 'Check Voter Register', onClick: openRegister },
    { label: 'Election Timeline', onClick: openTimeline },
    { label: 'Nomination Fees', onClick: openFees },
    // General number first, then one entry per configured reason (Branding → Support contacts).
    // A reason with exactly one contact behind it is a direct link; more than one opens a small
    // submenu (below) listing each contact by name so the voter picks who to message.
    ...(supportPhone ? [{
      label: 'Contact Support', color: '#25D366',
      href: buildSupportLink(supportPhone, orgName, '', 'describe your problem here (never send your code)'),
    }] : []),
    ...supportContacts.filter(g => g?.reason && (g?.contacts || []).some(c => c?.link)).map(g => {
      const contacts = (g.contacts || []).filter(c => c?.link);
      return contacts.length === 1
        ? { label: g.reason, color: '#25D366', href: buildSupportLink(contacts[0].link, orgName, '', `${g.reason} (never send your code)`) }
        : { label: g.reason, color: '#25D366', onClick: () => setSubReason(g) };
    }),
  ].filter(it => it.onClick || it.href);

  const subContacts = subReason ? (subReason.contacts || []).filter(c => c?.link) : [];

  return (
    <>
      {open && (
        <div style={menuPanelStyle} className="panel-fade-in">
          {subReason ? (
            <>
              <button onClick={() => setSubReason(null)} style={{ ...menuItemStyle, opacity: 0.7 }}>← Back</button>
              <div style={{ padding: '4px 12px 8px', fontSize: '12px', opacity: 0.7 }}>{subReason.reason}</div>
              {subContacts.map((c, i) => (
                <a
                  key={i}
                  href={buildSupportLink(c.link, orgName, '', `${subReason.reason} (never send your code)`)}
                  target="_blank" rel="noopener noreferrer"
                  style={{ ...menuItemStyle, color: '#25D366' }}
                >
                  {c.name || `Contact ${i + 1}`}
                </a>
              ))}
            </>
          ) : (
            <>
              <div style={{ padding: '8px 12px', fontSize: '12px', opacity: 0.8, lineHeight: 1.5, maxWidth: '260px' }}>
                <b>Code not arriving?</b> Keep your phone on and wait for the countdown before tapping Resend. The same code is sent again while it is valid.
                Still stuck, or need a detail changed? Use Contact Support below. Never send your code.
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
            </>
          )}
        </div>
      )}

      {showRegister && (
        <div style={modalOverlayStyle} className="overlay-fade-in" onClick={closeRegister}>
          <div style={modalContentStyle} className="panel-fade-in" onClick={e => e.stopPropagation()}>
            <VoterRegisterSearch />
            <button onClick={closeRegister} style={closeBtnStyle}>Close</button>
          </div>
        </div>
      )}

      {showTimeline && (
        <div style={modalOverlayStyle} className="overlay-fade-in" onClick={closeTimeline}>
          <div style={modalContentStyle} className="panel-fade-in" onClick={e => e.stopPropagation()}>
            <ElectionTimeline />
            <button onClick={closeTimeline} style={closeBtnStyle}>Close</button>
          </div>
        </div>
      )}

      {showFees && (
        <div style={modalOverlayStyle} className="overlay-fade-in" onClick={closeFees}>
          <div style={modalContentStyle} className="panel-fade-in" onClick={e => e.stopPropagation()}>
            <FeeSchedule />
            <button onClick={closeFees} style={closeBtnStyle}>Close</button>
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
