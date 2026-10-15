import React, { useEffect, useRef, useState } from 'react';

import { TURNSTILE_SITE_KEY as SITE_KEY } from '../supportLink';
import { getTemplate } from '../template';
import { reportClientProblem } from '../clientReport';
const STUCK_MS = 20000;   // no token this long after the widget rendered: slow or odd network, nothing errors
const retryStyle = { minHeight: 44, padding: '10px 16px', borderRadius: 10, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', cursor: 'pointer', fontSize: 14, fontWeight: 600 };
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
 * 'loading' | 'ready' | 'failed' so a parent can show its own diagnostics. Failures are reported to the server
 * (clientReport.js, no personal data) unless `report={false}` (the superadmin test).
 */
export default function TurnstileWidget({ onToken, resetKey = 0, onStatus, report = true }) {
  const ref = useRef(null);
  const idRef = useRef(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const status = (s) => { if (onStatus) onStatus(s); };

  useEffect(() => {
    if (!SITE_KEY) return undefined;
    let cancelled = false;
    onToken('');
    status('loading');
    const note = (kind, code) => { if (report) reportClientProblem(kind, { code }); };
    let stuckTimer = null;
    const fail = () => { if (!cancelled) { clearTimeout(stuckTimer); onToken(''); setFailed(true); status('failed'); } };
    loadScript().then(() => {
      if (cancelled || !ref.current) return;
      if (idRef.current != null) window.turnstile.remove(idRef.current);
      stuckTimer = setTimeout(() => note('captcha_stuck', 'no_token_20s'), STUCK_MS);
      idRef.current = window.turnstile.render(ref.current, {
        sitekey: SITE_KEY, theme: 'auto',
        callback: (t) => { clearTimeout(stuckTimer); setFailed(false); onToken(t); status('ready'); },
        'expired-callback': () => onToken(''),
        'error-callback': (code) => { if (!cancelled) note('captcha_error', code); fail(); },
      });
    }).catch(() => { if (!cancelled) note('captcha_script_failed', 'script_blocked'); fail(); });
    return () => { cancelled = true; clearTimeout(stuckTimer); if (idRef.current != null && window.turnstile) window.turnstile.remove(idRef.current); idRef.current = null; };
  }, [resetKey, attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!SITE_KEY) return null;
  // Same pattern as LoginErrorActions: Blueprint gets its button class, the default look keeps a tokenised inline style.
  const bp = getTemplate();
  const retryLook = bp ? { className: bp.cls.ghost } : { style: retryStyle };
  return (
    <div style={{ margin: '12px 0' }}>
      <div ref={ref} style={{ display: failed ? 'none' : 'flex', justifyContent: 'center' }} />
      {failed && (
        <div role="alert" style={{ textAlign: 'center', fontSize: 13 }}>
          <p style={{ margin: '0 0 8px' }}>The security check could not load. Check your connection, turn off data saver or an ad blocker for this site, or switch network, then try again.</p>
          <button type="button" onClick={() => { setFailed(false); setAttempt((n) => n + 1); }} {...retryLook}>
            Retry security check
          </button>
        </div>
      )}
    </div>
  );
}
