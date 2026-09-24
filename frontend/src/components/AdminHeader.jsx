import React, { useCallback, useState } from 'react';

/**
 * The one header every admin panel uses, so they all look and behave the same:
 *
 *   Title                                     [role actions…] [Refresh] [Logout]
 *   subtitle · Sync: HH:MM:SS
 *
 * - Sync shows when the screen last loaded data successfully (call markSynced() after a fetch).
 * - Refresh appears when the screen passes onRefresh.
 * - Logout is always last, always red.
 * - Role-specific buttons (Start/Stop election, Preview…) go in `actions`, left of Refresh.
 */
export function useLastSynced() {
  const [lastSynced, setLastSynced] = useState(() => new Date());
  const markSynced = useCallback(() => setLastSynced(new Date()), []);
  return [lastSynced, markSynced];
}

export default function AdminHeader({ title, subtitle, lastSynced, onRefresh, refreshing = false, actions = null, onLogout }) {
  return (
    <div style={wrap} className="no-print admin-header">
      <div style={{ minWidth: 0 }}>
        <h2 style={{ margin: 0, color: 'var(--text-color)' }}>{title}</h2>
        <span style={sub}>
          {subtitle}
          {subtitle && lastSynced ? ' · ' : ''}
          {lastSynced ? `Sync: ${lastSynced.toLocaleTimeString()}` : ''}
        </span>
      </div>
      <div style={right}>
        {actions}
        {onRefresh && (
          <button type="button" style={ghost} onClick={onRefresh} disabled={refreshing}>
            {refreshing ? 'Syncing…' : 'Refresh'}
          </button>
        )}
        <button type="button" style={logout} onClick={onLogout}>Logout</button>
      </div>
    </div>
  );
}

const wrap = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' };
const right = { display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' };
const sub = { fontSize: '12px', opacity: 0.6 };
const base = { padding: '9px 16px', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' };
const ghost = { ...base, background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)', fontWeight: 'normal', padding: '9px 14px' };
const logout = { ...base, color: '#fff', border: 'none', backgroundColor: '#e74c3c' };
