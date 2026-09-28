import React from 'react';

/**
 * SVG loading spinner that matches the site's look (brand navy in light mode,
 * brand gold in dark mode; see the `.loading-spinner` rules in index.css).
 *
 *   <Spinner size={20} />                       just the ring
 *   <LoadingBlock text="Loading results…" />    ring + label, centred (sections/panels)
 *   <LoadingBlock text="Searching…" inline />   ring + label on one line (small hints)
 *
 * `color` overrides the arc colour (any CSS colour), e.g. for a dark backdrop.
 */
export function Spinner({ size = 24, color, label, style, className = '' }) {
  return (
    <svg
      className={`loading-spinner ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 50 50"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : 'true'}
      focusable="false"
      style={{
        display: 'inline-block', flexShrink: 0, maxWidth: 'none', maxHeight: 'none',
        ...(color ? { '--spinner-color': color } : null), ...style,
      }}
    >
      <circle className="loading-spinner-track" cx="25" cy="25" r="20" fill="none" strokeWidth="5" />
      <circle
        className="loading-spinner-arc" cx="25" cy="25" r="20" fill="none"
        strokeWidth="5" strokeLinecap="round" strokeDasharray="31.4 125.6"
      />
    </svg>
  );
}

export function LoadingBlock({ text = 'Loading…', size, inline = false, color, style }) {
  const s = size || (inline ? 14 : 28);
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: inline ? 'inline-flex' : 'flex',
        flexDirection: inline ? 'row' : 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: inline ? 8 : 10,
        padding: inline ? 0 : '16px 0',
        fontSize: inline ? 12 : 13,
        opacity: 0.75,
        ...style,
      }}
    >
      <Spinner size={s} color={color} />
      {text ? <span>{text}</span> : null}
    </div>
  );
}

export default Spinner;
