// Blueprint look of PhaseBanner (BP-T3). PhaseBanner keeps derivePhase, the countdown clock and all copy;
// this only renders. Keeps role="status", data-phase, the single banner and the Apply-now button (data-track).
import { PHASE_VARIANT } from './labels.js';

export default function PhaseBannerView({ state, title, rows, left, countdownLabel, onApply, style }) {
  return (
    <div
      role="status"
      className={`bp-ban${PHASE_VARIANT[state] ?? ''} no-print`}
      data-phase={state}
      style={{ fontSize: 16, lineHeight: 1.35, textAlign: 'center', ...style }}
    >
      <div className="bp-ban-title">{title}</div>
      {rows.length > 0 && (
        <div className="bp-ban-rows">
          {rows.map(([label, value]) => (
            <div key={label}>
              <div className="bp-ban-k">{label}</div>
              <div className="bp-ban-v">{value}</div>
            </div>
          ))}
        </div>
      )}
      {left && (
        <div className="bp-cd">
          <div className="bp-ban-k">{countdownLabel}</div>
          <div className="bp-big bp-num">{left}</div>
        </div>
      )}
      {state === 'apply_open' && (
        <button type="button" data-track="phase-apply-now" className="bp-btn" onClick={onApply} style={{ fontSize: 16 }}>
          Apply now
        </button>
      )}
    </div>
  );
}
