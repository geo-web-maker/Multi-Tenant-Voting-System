import { useCallback, useEffect, useState } from 'react';
import api from './api';

// The nomination-form card used to pop in only after the whole page had rendered, because the
// config was first requested when the (lazy-loaded) Apply page mounted. Now:
//   1. the request starts at app start-up (prefetchNominationForm, called from App.jsx),
//   2. the last answer is remembered for the session, so revisits render the card instantly,
//   3. the Apply page shows a same-height placeholder while the very first answer is in flight.
const CACHE_KEY = `nomination-form:${typeof window !== 'undefined' ? window.location.hostname : ''}`;

let cached = null; // last good response (memory)
let inflight = null; // de-dupes the prefetch + the hook's own first load

function readStored() {
  if (cached) return cached;
  try {
    const raw = window.sessionStorage.getItem(CACHE_KEY);
    if (raw) cached = JSON.parse(raw);
  } catch { /* storage unavailable: fine, we just fetch */ }
  return cached;
}

function fetchNominationForm() {
  if (inflight) return inflight;
  inflight = api.get('/nomination-form')
    .then((res) => {
      cached = res.data || { enabled: false };
      try { window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(cached)); } catch { /* ignore */ }
      return cached;
    })
    .catch(() => ({ enabled: false })) // a failed fetch hides the card, as before (the cache is left untouched)
    .finally(() => { inflight = null; });
  return inflight;
}

export function prefetchNominationForm() {
  fetchNominationForm();
}

export function useNominationForm(pollMs = 20000) {
  const seed = readStored();
  const [data, setData] = useState(seed || { enabled: false });
  const [loading, setLoading] = useState(!seed);
  const load = useCallback(async () => {
    try { setData(await fetchNominationForm()); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!pollMs) return undefined;
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [pollMs, load]);
  return { ...(data || { enabled: false }), loading, refresh: load };
}
