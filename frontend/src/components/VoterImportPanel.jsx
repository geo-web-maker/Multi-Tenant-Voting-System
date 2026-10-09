import React, { useRef, useState } from 'react';
import { useToast } from './UIFeedback';
import VoterImportReview from './VoterImportReview';
import { FROZEN_NOTE } from '../hooks/useRosterStatus';
import { patchIdText } from '../idText';

/**
 * Entry point for the roster update from a CSV / TSV / Excel file.
 * Picking a file opens VoterImportReview (match columns -> review the diff -> confirm); nothing is
 * written until it is confirmed there. `onImported` lets the host refresh its voter list afterwards.
 * Hidden-by-note once the roster is frozen (the backend refuses imports then as well).
 */
export default function VoterImportPanel({ frozen = false, onImported }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const inputRef = useRef(null);

  const pick = (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = '';                       // allow re-picking the same file
    if (f) setFile(f);
  };

  const done = (r) => {
    const parts = [`${r.added} added`, `${r.updated} updated`];
    if (r.skipped_changes) parts.push(`${r.skipped_changes} left unchanged`);
    if (r.removed) parts.push(`${r.removed} removed`);
    if (r.blocked_removals) parts.push(`${r.blocked_removals} protected voter(s) kept`);
    if (r.staff_changes_skipped) parts.push(`${r.staff_changes_skipped} admin/commissioner change(s) need a superadmin`);
    toast(`Voter update applied: ${parts.join(', ')}.`, { kind: 'success', duration: 7000 });
    setFile(null);
    if (r.id_label) patchIdText({ id_label: r.id_label });   // the label chosen during the import
    if (onImported) onImported(r);
  };

  return (
    <div style={box}>
      <div style={{ flex: '1 1 260px' }}>
        <h4 style={{ margin: 0 }}>Update voters from a file (CSV or Excel)</h4>
        <p style={{ margin: '4px 0 0', fontSize: 12, opacity: 0.7 }}>
          {frozen
            ? FROZEN_NOTE
            : 'You will match the columns and review every change before anything is saved.'}
        </p>
      </div>
      {!frozen && (
        <input ref={inputRef} type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm"
          aria-label="Choose a voter file" onChange={pick} />
      )}
      {file && !frozen && <VoterImportReview file={file} onClose={() => setFile(null)} onDone={done} />}
    </div>
  );
}

const box = {
  display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
  padding: 16, marginBottom: 14, borderRadius: 10,
  border: '1px solid var(--border-color)', background: 'var(--card-bg, transparent)',
};
