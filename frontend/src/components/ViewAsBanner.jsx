import React from 'react';
import { getViewAs, clearAdminSession } from '../session';
import { ADMIN_TOKEN_KEY } from '../api';

const LABELS = { it_admin: 'IT Admin', commission: 'Commissioner', financial_controller: 'Financial Controller', overseer: 'Overseer' };

function minutesLeft() {
  try {
    const p = sessionStorage.getItem(ADMIN_TOKEN_KEY).split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const exp = JSON.parse(atob(p + '='.repeat((4 - (p.length % 4)) % 4))).exp;
    return Math.max(0, Math.ceil((exp * 1000 - Date.now()) / 60000));
  } catch { return null; }
}

/** Sticky bar shown only in a superadmin's "View as" tab. */
export default function ViewAsBanner() {
  const [, tick] = React.useState(0);
  React.useEffect(() => { const t = setInterval(() => tick(n => n + 1), 5000); return () => clearInterval(t); }, []);
  const v = getViewAs();
  if (!v) return null;
  const left = minutesLeft();
  const close = () => { clearAdminSession(); window.close(); window.location.replace('/'); };
  return (
    <div role="status" style={{ position: 'sticky', top: 0, zIndex: 10000, display: 'flex', gap: 12, alignItems: 'center',
      justifyContent: 'space-between', flexWrap: 'wrap', padding: '8px 14px', background: '#f39c12', color: '#1a1a1a', fontSize: 13, fontWeight: 600 }}>
      <span>
        Read-only view of {v.name} ({LABELS[v.role] || v.role}). Nothing you do here can change data.
        {left !== null && ` Ends in ${left} min.`}
      </span>
      <button onClick={close} style={{ padding: '4px 12px', border: '1px solid #1a1a1a', background: 'transparent', borderRadius: 6, cursor: 'pointer', fontWeight: 700 }}>
        Close view
      </button>
    </div>
  );
}
