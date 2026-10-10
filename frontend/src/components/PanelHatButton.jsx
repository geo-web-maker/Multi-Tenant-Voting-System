import React, { useEffect, useState } from 'react';
import api from '../api';
import { switchHat } from '../hatSwitch';
import { useToast } from './UIFeedback';

// "Switch to Vetting Panel" for IT admin, overseer and financial controller (the commissioner screen
// has its own copy because it also shows the chair's tie hint). Renders nothing unless the superadmin
// has linked this person to the panel; the answer is only ever about the caller.
export default function PanelHatButton({ onStatus }) {
  const toast = useToast();
  const [linked, setLinked] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await api.get('/admin/panel-link');
        if (!live) return;
        setLinked(Boolean(res?.data?.panel_linked));
        if (onStatus) onStatus(res?.data || null);
      } catch { /* no button if the check fails */ }
    })();
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- check once per mount
  }, []);

  if (!linked) return null;
  const go = async () => {
    setBusy(true);
    try { await switchHat(); } catch (e) {
      toast(e.response?.data?.detail || 'Could not switch to the Vetting Panel.', { kind: 'error' });
      setBusy(false);
    }
  };
  return (
    <button className="vp-switch" onClick={go} disabled={busy} style={{ ...btn, opacity: busy ? 0.6 : 1 }}>
      {busy ? 'Switching…' : 'Switch to Vetting Panel'}
    </button>
  );
}

const btn = { padding: '8px 14px', borderRadius: '8px', border: '1px solid var(--border-color)', backgroundColor: 'var(--card-bg)', color: 'var(--text-color)', cursor: 'pointer', fontSize: '13px', fontWeight: '600' };
