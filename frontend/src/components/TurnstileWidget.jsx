import React, { useEffect, useRef, useState } from 'react';

import { TURNSTILE_SITE_KEY as SITE_KEY } from '../supportLink';
let scriptPromise;
function loadScript() {
  if (window.turnstile) return Promise.resolve();
  scriptPromise ||= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    s.async = true; s.onload = resolve;
    // Forget the failed attempt (promise + tag) so the Retry button can really try again.
    s.onerror = () => { scriptPromise = undefined; s.remove(); reject(new Error('turnstile script blocked')); };
    document.head.appendChild(s);
  });
  return scriptPromise;
}

/**
 * Cloudflare Turnstile. Tokens are single-use: bump `resetKey` after every attempt to get a fresh one.
 * If the check cannot load (blocked script, data-saver browser, bad network) or errors, the voter sees
 * a message with a Retry button instead of a silently disabled form. `onStatus` (optional) reports
 * 'loading' | 'ready' | 'failed' so a parent can show its own diagnostics.
 */
export default function TurnstileWidget({ onToken, resetKey = 0, onStatus }) {
  const ref = useRef(null);
  const idRef = useRef(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const status = (s) => { if (onStatus) onStatus(s); };

  useEffect(() => {
    if (!SITE_KEY) return undefined;
    let cancelled = false;
    onToken('');
    setFailed(false);
    status('loading');
    const fail = () => { if (!cancelled) { onToken(''); setFailed(true); status('failed'); } };
    loadScript().then(() => {
      if (cancelled || !ref.current) return;
      if (idRef.current != null) window.turnstile.remove(idRef.current);
      idRef.current = window.turnstile.render(ref.current, {
        sitekey: SITE_KEY, theme: 'auto',
        callback: (t) => { onToken(t); status('ready'); },
        'expired-callback': () => onToken(''),
        'error-callback': fail,
      });
    }).catch(fail);
    return () => { cancelled = true; if (idRef.current != null && window.turnstile) window.turnstile.remove(idRef.current); idRef.current = null; };
  }, [resetKey, attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!SITE_KEY) return null;
  return (
    <div style={{ margin: '12px 0' }}>
      <div ref={ref} style={{ display: failed ? 'none' : 'flex', justifyContent: 'center' }} />
      {failed && (
        <div role="alert" style={{ textAlign: 'center', fontSize: 13 }}>
          <p style={{ margin: '0 0 8px' }}>The security check could not load. Check your connection, turn off data saver or an ad blocker for this site, or switch network, then try again.</p>
          <button type="button" onClick={() => setAttempt((n) => n + 1)}
            style={{ padding: '8px 16px', borderRadius: 8, border: '1px solid currentColor', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: 13 }}>
            Retry security check
          </button>
        </div>
      )}
    </div>
  );
}
