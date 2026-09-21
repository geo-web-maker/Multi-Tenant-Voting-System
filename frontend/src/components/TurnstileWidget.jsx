import React, { useEffect, useRef } from 'react';

import { TURNSTILE_SITE_KEY as SITE_KEY } from '../supportLink';
let scriptPromise;
function loadScript() {
  if (window.turnstile) return Promise.resolve();
  scriptPromise ||= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    s.async = true; s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
  return scriptPromise;
}

/** Cloudflare Turnstile. Tokens are single-use: bump `resetKey` after every attempt to get a fresh one. */
export default function TurnstileWidget({ onToken, resetKey = 0 }) {
  const ref = useRef(null);
  const idRef = useRef(null);
  useEffect(() => {
    if (!SITE_KEY) return undefined;
    let cancelled = false;
    onToken('');
    loadScript().then(() => {
      if (cancelled || !ref.current) return;
      if (idRef.current != null) window.turnstile.remove(idRef.current);
      idRef.current = window.turnstile.render(ref.current, {
        sitekey: SITE_KEY, theme: 'auto',
        callback: (t) => onToken(t), 'expired-callback': () => onToken(''), 'error-callback': () => onToken(''),
      });
    }).catch(() => onToken(''));
    return () => { cancelled = true; if (idRef.current != null && window.turnstile) window.turnstile.remove(idRef.current); idRef.current = null; };
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!SITE_KEY) return null;
  return <div ref={ref} style={{ display: 'flex', justifyContent: 'center', margin: '12px 0' }} />;
}
