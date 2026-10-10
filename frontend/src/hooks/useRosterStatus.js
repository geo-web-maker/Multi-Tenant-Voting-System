import { useEffect, useState } from 'react';
import { fetchRosterStatus } from '../studentEdit';
import { startPolling } from './usePolling';

/** { phase: 'pre_freeze' | 'voting_frozen' | 'closed', frozen, contact_change_required, freeze_at } or null while loading. */
export default function useRosterStatus(pollMs = 60000) {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => fetchRosterStatus().then((s) => live && setStatus(s)).catch(() => {});
    load();
    const stop = startPolling(load, pollMs);
    return () => { live = false; stop(); };
  }, [pollMs]);
  return status;
}

export const FROZEN_NOTE =
  'Roster frozen: voters cannot be added, removed or imported. Phone and registration-number changes need a commissioner’s approval.';
