import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { UIFeedbackProvider } from './components/UIFeedback.jsx'
import ViewAsBanner from './components/ViewAsBanner.jsx'
import { consumeViewAsHandoff } from './session.js'
import { setTemplateImpl } from './template.js'

// After a redeploy, a tab (or cached index.html) can point at hashed chunks that no longer exist. Reload once to pick up
// the new build; the 10 s guard stops a reload loop if the failure is a real outage rather than a stale build.
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  try {
    const last = Number(sessionStorage.getItem('chunk_reload_at') || 0)
    if (Date.now() - last < 10000) return
    sessionStorage.setItem('chunk_reload_at', String(Date.now()))
  } catch { /* storage blocked: reload once anyway */ }
  window.location.reload()
})

async function start() {
  // Must run before <App/> reads the session: a superadmin's "View as" tab starts here.
  consumeViewAsHandoff()

  // Exact literal comparison: the bundler removes this whole branch (and the blueprint chunk) from default builds.
  // Registered before the first render so there is no flash of the wrong design; a failed load falls back to the standard UI.
  if (import.meta.env.VITE_UI_TEMPLATE === 'blueprint') {
    try {
      setTemplateImpl(await import('./templates/blueprint/index.js'))
    } catch (err) {
      console.error('Blueprint template failed to load — using the standard UI.', err)
    }
  }

  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <UIFeedbackProvider>
        <ViewAsBanner />
        <App />
      </UIFeedbackProvider>
    </StrictMode>,
  )
}
start()
