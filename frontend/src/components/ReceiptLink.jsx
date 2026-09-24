import React, { useEffect, useState } from 'react';
import { Icon } from './icons.jsx';

// "View Receipt" that opens the image inside the app (a lightbox) instead of a new tab.
// If the image can't be loaded (deleted upload, bad URL, blocked network) the viewer says so
// and shows the stored link, so the problem is visible instead of a blank tab.
export default function ReceiptLink({ url, label = 'View Receipt', style }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState('loading'); // loading | ok | error

  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  if (!url) return null;

  const show = () => { setState('loading'); setOpen(true); };

  return (
    <>
      <button
        type="button"
        onClick={show}
        style={{
          background: 'none', border: 'none', padding: 0, minHeight: 0, cursor: 'pointer',
          fontSize: '12px', color: 'var(--info)', textDecoration: 'underline', ...style,
        }}
      >
        {label}
      </button>

      {open && (
        <div
          role="dialog" aria-modal="true" aria-label="Payment receipt"
          onClick={() => setOpen(false)}
          style={{
            position: 'fixed', inset: 0, zIndex: 10000, backgroundColor: 'rgba(0,0,0,0.8)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', borderRadius: '14px',
              padding: '14px', width: '100%', maxWidth: '640px', maxHeight: '92vh',
              display: 'flex', flexDirection: 'column', gap: '10px', boxSizing: 'border-box',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
              <strong style={{ fontSize: '14px' }}>Payment receipt</strong>
              <button
                type="button" onClick={() => setOpen(false)} aria-label="Close"
                style={{ border: 'none', background: 'none', cursor: 'pointer', padding: '4px', color: 'var(--text-color)' }}
              >
                <Icon name="close" size="1.4em" />
              </button>
            </div>

            <div style={{ overflow: 'auto', flex: 1, textAlign: 'center', minHeight: '120px' }}>
              {state === 'loading' && <p style={{ opacity: 0.6, fontSize: '13px' }}><Icon name="loading" /> Loading receipt…</p>}
              {state === 'error' ? (
                <div style={{ padding: '16px 8px', fontSize: '13px' }}>
                  <p style={{ margin: '0 0 8px' }}><Icon name="warning" /> This receipt image couldn&apos;t be loaded.</p>
                  <p style={{ margin: 0, opacity: 0.7, wordBreak: 'break-all' }}>{url}</p>
                </div>
              ) : (
                <img
                  src={url} alt="Payment receipt"
                  onLoad={() => setState('ok')} onError={() => setState('error')}
                  style={{ maxWidth: '100%', maxHeight: '74vh', borderRadius: '8px', display: state === 'ok' ? 'inline-block' : 'none' }}
                />
              )}
            </div>

            <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '12px', color: 'var(--info)', textAlign: 'center' }}>
              Open original in a new tab
            </a>
          </div>
        </div>
      )}
    </>
  );
}
