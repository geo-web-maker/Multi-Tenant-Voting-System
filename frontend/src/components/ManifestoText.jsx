import React, { useState } from 'react';

// Long manifestos used to stretch the review card to any height (and a pasted URL or
// unbroken string could push it wider than the screen). Show the first few lines and let
// the reviewer expand in place; newlines are kept and long words wrap.
const COLLAPSE_OVER = 320; // characters

export default function ManifestoText({ text, style }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const long = text.length > COLLAPSE_OVER;
  const clamped = long && !expanded;

  return (
    <div style={{ margin: '10px 0 0' }}>
      <p
        style={{
          margin: 0, fontSize: '13px', opacity: 0.85, lineHeight: '1.6',
          whiteSpace: 'pre-line', overflowWrap: 'anywhere', ...style,
          ...(clamped && { display: '-webkit-box', WebkitLineClamp: 5, WebkitBoxOrient: 'vertical', overflow: 'hidden' }),
        }}
      >
        {text}
      </p>
      {long && (
        <button
          type="button" onClick={() => setExpanded(v => !v)}
          style={{ background: 'none', border: 'none', padding: '4px 0 0', minHeight: 0, cursor: 'pointer', fontSize: '12px', color: 'var(--info)', fontWeight: 600 }}
        >
          {expanded ? 'Show less' : `Read full manifesto (${text.trim().split(/\s+/).filter(Boolean).length} words)`}
        </button>
      )}
    </div>
  );
}
