import React from 'react';
import { EXPORT_MODES, MODE_LABEL, MODE_HELP } from '../registerExport';

export default function ExportModeControl({ name, mode, onChange, disabled }) {
  return (
    <div role="group" aria-label={`Voter register export for ${name}`} style={{ display: 'grid', gap: 6 }}>
      <b style={{ fontSize: 13 }}>Voter register export</b>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {EXPORT_MODES.map((m) => (
          <button key={m} type="button" data-track={`export-mode-${m}`} disabled={disabled}
            aria-pressed={mode === m} onClick={() => mode !== m && onChange(m)}
            style={{ minHeight: 44, padding: '0 14px', borderRadius: 8, fontWeight: 700, fontSize: 14,
                     border: '1px solid var(--border-color)', cursor: disabled ? 'not-allowed' : 'pointer',
                     background: mode === m ? 'var(--brand-primary)' : 'var(--card-bg)',
                     color: mode === m ? 'var(--brand-on-primary, white)' : 'var(--text-color)' }}>
            {MODE_LABEL[m]}
          </button>
        ))}
      </div>
      <small style={{ opacity: 0.75 }}>{MODE_HELP[mode] || MODE_HELP.none}</small>
    </div>
  );
}
