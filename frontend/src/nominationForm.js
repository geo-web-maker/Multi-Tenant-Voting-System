import { useCallback, useEffect, useState } from 'react';
import api from './api';

export function useNominationForm(pollMs = 20000) {
  const [data, setData] = useState({ enabled: false });
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try { setData((await api.get('/nomination-form')).data || { enabled: false }); }
    catch { setData({ enabled: false }); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!pollMs) return undefined;
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);
  return { ...(data || { enabled: false }), loading, refresh: load };
}
