import React from 'react';
import api from './api';
import usePolling from './hooks/usePolling';

/**
 * Mobile Money payment details for this election: public read (GET /payment-info), set by the
 * superadmin (PUT /superadmin/payment-info). Both values are empty until someone sets them.
 */

const EMPTY = { number: '', name: '' };

export function usePaymentInfo(pollMs = 0) {
  const [info, setInfo] = React.useState(EMPTY);
  const load = React.useCallback(async () => {
    const res = await api.get('/payment-info');
    setInfo({ number: res.data?.mobile_money_number || '', name: res.data?.mobile_money_name || '' });
  }, []);
  React.useEffect(() => { load().catch(() => {}); }, [load]);
  // A number that changes while someone is mid-application must not leave them paying the old one.
  usePolling(load, pollMs, pollMs > 0);
  return info;
}

// Stored as digits with the country code ("256772123456"); people dial and copy the local form.
export const momoLocalDigits = n => (/^256\d{9}$/.test(n || '') ? `0${n.slice(3)}` : (n || ''));
export const momoDisplay = n => {
  const m = /^256(\d{3})(\d{3})(\d{3})$/.exec(n || '');
  return m ? `0${m[1]} ${m[2]} ${m[3]}` : (n ? `+${n}` : '');
};
