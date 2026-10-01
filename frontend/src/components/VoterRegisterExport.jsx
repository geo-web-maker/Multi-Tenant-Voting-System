import React, { useEffect, useRef, useState } from 'react';
import { useToast, useConfirm } from './UIFeedback';
import { fetchExportPermission, downloadRegister, exportErrorMessage } from '../registerExport';

export default function VoterRegisterExport() {
  const toast = useToast();
  const confirm = useConfirm();
  const [perm, setPerm] = useState(null);          // null = unknown (render nothing), else {mode}
  const [format, setFormat] = useState('xlsx');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);                       // a state flag alone does not stop a fast double tap

  const loadPerm = () => fetchExportPermission().then(setPerm).catch(() => setPerm({ mode: 'none' }));
  useEffect(() => { loadPerm(); }, []);

  if (!perm || perm.mode === 'none') return null;   // "they don't have the option": nothing is shown at all

  const full = perm.mode === 'full';
  const onExport = async () => {
    if (lock.current) return;
    lock.current = true;
    setError('');
    try {
      if (full && !(await confirm(
        'This file contains COMPLETE phone numbers for every voter. Store it securely and do not share it. Continue?'))) return;
      setBusy(true);
      const r = await downloadRegister(format);
      toast(`Exported ${Number.isFinite(r.rows) ? r.rows + ' voters' : 'register'} (${r.mode || perm.mode}).`, { kind: 'success' });
    } catch (e) {
      setError(await exportErrorMessage(e));
      if (e?.response?.status === 403) loadPerm();     // permission changed while the page was open: the button disappears
    } finally {
      setBusy(false);
      lock.current = false;
    }
  };

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 14 }}>
        Format
        <select data-track="export-register-format" value={format} disabled={busy}
          onChange={(e) => setFormat(e.target.value)} style={{ minHeight: 44, fontSize: 16 }}>
          <option value="xlsx">Excel (.xlsx)</option>
          <option value="csv">CSV (.csv)</option>
        </select>
      </label>
      <button type="button" data-track="export-register" onClick={onExport} disabled={busy} aria-busy={busy}
        style={{ minHeight: 44, padding: '0 16px', borderRadius: 8, fontWeight: 700, border: 0,
                 background: full ? '#b45309' : 'var(--brand-primary)', color: '#fff',
                 cursor: busy ? 'wait' : 'pointer' }}>
        {busy ? 'Preparing…' : full ? 'Export register (full details)' : 'Export register (phones hidden)'}
      </button>
      {format === 'csv' && (
        <small style={{ opacity: 0.75, flexBasis: '100%' }}>
          Opening a CSV in Excel can turn long phone numbers into 2.5E+11. Choose Excel (.xlsx) to keep them exact.
        </small>
      )}
      {error && <p role="alert" style={{ color: 'var(--danger, #c0392b)', margin: 0, flexBasis: '100%' }}>{error}</p>}
    </div>
  );
}
