// Blueprint boot splash (BP-T2). App.jsx keeps the stages, copy and dot colours; this only changes the look.
// The spinner ring of the default splash is replaced by the stamp (logo image or initials).
import { Stamp } from './primitives';

export default function BootSplash({ orgName, logoUrl, exiting, text, label, dot }) {
  const wrap = {
    position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'var(--bp-bg)', boxSizing: 'border-box', transition: 'opacity 0.35s ease, transform 0.35s ease',
    ...(exiting ? { opacity: 0, transform: 'scale(1.02)', pointerEvents: 'none' } : { opacity: 1, transform: 'scale(1)' }),
  };
  return (
    <div style={wrap}>
      <div className="bp-card bp-boot" style={{ width: '100%', maxWidth: '384px', textAlign: 'center' }}>
        <Stamp name={orgName} logoUrl={logoUrl} className="bp-boot-stamp" />
        <h1>{orgName || 'Election Portal'}</h1>
        <p className="bp-mu" aria-live="polite">{text}</p>
        <div className="bp-mono" role="status" style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '.1em' }}>
          <span className="bp-dot" style={{ background: dot }} />
          {label}
        </div>
      </div>
    </div>
  );
}
