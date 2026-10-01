import React from 'react';
import api, { getErrorMessage } from '../api';
import { stashViewAsHandoff } from '../session';
import { useToast } from './UIFeedback';

/**
 * Superadmin "View" button: opens a READ-ONLY copy of another admin's dashboard in a new tab, so you
 * can troubleshoot or guide them. Nothing done in that tab can change data (enforced by the server).
 */
export default function ViewAsButton({ studentId, role }) {
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);

  const open = async () => {
    // Open the tab synchronously (inside the click) so popup blockers allow it, then point it at the session.
    const win = window.open('', '_blank');
    setBusy(true);
    try {
      const res = await api.post('/superadmin/view-as', { student_id: studentId, role });
      const nonce = stashViewAsHandoff(res.data);
      const url = `${window.location.origin}/?view_as=${nonce}`;
      if (win) win.location.href = url; else window.open(url, '_blank');
    } catch (e) {
      if (win) win.close();
      toast(getErrorMessage(e, 'Could not open the read-only view.'), { kind: 'error' });
    } finally { setBusy(false); }
  };

  return (
    <button type="button" onClick={open} disabled={busy} title="Open a read-only view of this admin's interface in a new tab"
      style={{ padding: '4px 10px', background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-color)',
               borderRadius: '6px', cursor: 'pointer', fontSize: '12px', opacity: busy ? 0.6 : 1 }}>
      {busy ? 'Opening…' : 'View as'}
    </button>
  );
}
