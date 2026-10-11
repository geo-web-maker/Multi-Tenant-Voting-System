import React from 'react'
import { getTemplate } from '../template.js'

// Shown when the first screen has been "loading" far longer than even a cold server needs. Most cases are a stale cached
// copy, a browser extension or ad blocker dropping requests, or a flaky network, so the steps are ordered cheapest first.
export async function reloadFresh() {
  try {
    if ('caches' in window) await Promise.all((await caches.keys()).map(k => caches.delete(k)))
    if ('serviceWorker' in navigator) await Promise.all((await navigator.serviceWorker.getRegistrations()).map(r => r.unregister()))
  } catch { /* best effort: still reload */ }
  window.location.reload()
}

const STEPS = [
  ['Tap ', 'Reload fresh', ' below.'],
  ['Open this page in a ', 'private / incognito window', ' (paste the link).'],
  ['Turn off ad blockers or privacy extensions for this site.'],
  ['Switch between Wi-Fi and mobile data.'],
]
const renderStep = (parts) => (parts.length === 3 ? <>{parts[0]}<strong>{parts[1]}</strong>{parts[2]}</> : parts[0])

export default function StuckHelp() {
  const [copied, setCopied] = React.useState(false)
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(window.location.href); setCopied(true) } catch { /* clipboard denied */ }
  }
  const steps = STEPS.map((p, i) => <li key={i}>{renderStep(p)}</li>)
  const label = copied ? 'Link copied' : 'Copy page link'

  // Blueprint Console look: same card, mono heading and pill buttons as its boot splash (tokens come from blueprint.css).
  if (getTemplate()) {
    return (
      <div role="alert" style={wrap}>
        <div className="bp-card" style={{ width: '100%', maxWidth: 420, margin: 0, textAlign: 'left' }}>
          <div className="bp-mono" style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.1em', marginBottom: 8 }}>TAKING LONGER THAN USUAL?</div>
          <ol className="bp-mu" style={{ margin: '0 0 12px', paddingLeft: 18, lineHeight: 1.5 }}>{steps}</ol>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" className="bp-btn bp-sm" onClick={reloadFresh}>Reload fresh</button>
            <button type="button" className="bp-btn bp-ghost bp-sm" onClick={copyLink}>{label}</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div role="alert" style={wrap}>
      <div style={card}>
        <strong style={{ display: 'block', marginBottom: 6 }}>Taking longer than usual?</strong>
        <ol style={{ margin: '0 0 10px', paddingLeft: 18, textAlign: 'left', lineHeight: 1.5 }}>{steps}</ol>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
          <button type="button" onClick={reloadFresh} style={btnPrimary}>Reload fresh</button>
          <button type="button" onClick={copyLink} style={btn}>{label}</button>
        </div>
      </div>
    </div>
  )
}

const wrap = { position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 10000, padding: 12, display: 'flex', justifyContent: 'center', boxSizing: 'border-box' }
const card = { width: '100%', maxWidth: 420, fontSize: 14, textAlign: 'center', background: 'var(--card-bg, #fff)', color: 'var(--text-color, #111827)', border: '1px solid var(--border-color, #e5e9f2)', borderRadius: 14, padding: '14px 16px', boxShadow: '0 8px 30px rgba(0,0,0,0.15)' }
const btn = { padding: '8px 14px', borderRadius: 8, border: '1px solid var(--border-color, #cbd5e1)', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: 14 }
const btnPrimary = { ...btn, background: 'var(--brand-primary, #2563eb)', borderColor: 'transparent', color: '#fff' }
