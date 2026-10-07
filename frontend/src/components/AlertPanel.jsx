import React from 'react';
import { alertLabel, alertLevel, overallAlertState } from '../alertState';
import { getTemplate } from '../template';

const PILL_TONE = { healthy: 'ok', warning: 'warn', critical: 'neg' }; // Blueprint pill tone per overall state
const COLORS = { healthy: 'var(--success, #2e9e5b)', warning: 'var(--warning, #d98e04)', critical: 'var(--danger)' };

// Read-only view of the live alert state. `alerts` is undefined on an older backend: render nothing then.
export default function AlertPanel({ alerts }) {
  if (!Array.isArray(alerts)) return null;
  const state = overallAlertState(alerts);
  const bp = getTemplate(); // render-time: null => the standard UI
  return (
    <div style={bp ? { minWidth: 0 } : box} className={bp ? bp.cls.card : 'card-pad'} data-testid="alert-panel">
      <h3 style={h3}>Alerts</h3>
      <p style={{ margin: 0 }}>
        {bp ? <bp.Pill tone={PILL_TONE[state]}>{alertLabel(state)}</bp.Pill> : (
          <>
            <i style={{ ...dot, background: COLORS[state] }} />
            <strong>{alertLabel(state)}</strong>
          </>
        )}
      </p>
      {alerts.length === 0 ? (
        <p style={muted}>No alert thresholds are currently exceeded.</p>
      ) : (
        <ul style={bp ? { margin: '8px 0 0', padding: 0, listStyle: 'none' } : { margin: '8px 0 0', paddingLeft: 18 }}>
          {alerts.map((a) => (
            <li key={a.kind} style={{ fontSize: 13 }} className={bp ? (alertLevel(a.level) === 'critical' ? bp.cls.alt : bp.cls.warnBan) : undefined}>
              <strong>{alertLabel(alertLevel(a.level))}</strong>: {a.metric} is {a.value} (threshold {a.threshold})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)', minWidth: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: '6px 0 0' };
const dot = { display: 'inline-block', width: 10, height: 10, borderRadius: '50%', marginRight: 8 };
