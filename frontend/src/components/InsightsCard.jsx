import React, { useMemo } from 'react';
import { buildInsights } from '../insights';

// D2c: plain-language highlights from the summary. Renders nothing-to-say text instead of empty or misleading lines.
export default function InsightsCard({ summary }) {
  const lines = useMemo(() => buildInsights(summary), [summary]);
  return (
    <div style={box} className="card-pad" data-testid="insights-card">
      <h3 style={h3}>What stands out</h3>
      {lines.length === 0 ? (
        <p style={muted}>Not enough activity in this period to highlight anything yet.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6, fontSize: 14 }}>
          {lines.map((l) => <li key={l}>{l}</li>)}
        </ul>
      )}
    </div>
  );
}

const box = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)', minWidth: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
