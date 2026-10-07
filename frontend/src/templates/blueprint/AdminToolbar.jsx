// AdminHeader in the Blueprint template (BP-T7a, E4): a toolbar row above the console shell.
// Same props, same buttons, same handlers as the default AdminHeader; no tab-name <h1> (the header crumb shows that).
import { useEffect } from 'react';
import { setChrome } from '../../templateChrome';

export default function AdminToolbar({ title, subtitle, lastSynced, onRefresh, refreshing = false, actions = null, onLogout }) {
  // Lets the sidebar offer "Session -> Log out" with the very same handler (E4).
  useEffect(() => {
    setChrome({ onLogout: onLogout || null });
    return () => setChrome({ onLogout: null });
  }, [onLogout]);

  return (
    <div className="bp-toolbar no-print admin-header">
      <div className="bp-tt">
        <h2>{title}</h2>
        <span className="bp-mu">
          {subtitle}
          {subtitle && lastSynced ? ' · ' : ''}
          {lastSynced ? `Sync: ${lastSynced.toLocaleTimeString()}` : ''}
        </span>
      </div>
      <div className="bp-tact">
        {actions}
        {onRefresh && (
          <button type="button" className="bp-btn bp-ghost bp-sm" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? 'Syncing…' : 'Refresh'}
          </button>
        )}
        <button type="button" className="bp-btn bp-danger bp-sm" onClick={onLogout}>Logout</button>
      </div>
    </div>
  );
}
