import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { UIFeedbackProvider } from './components/UIFeedback.jsx'
import ViewAsBanner from './components/ViewAsBanner.jsx'
import { consumeViewAsHandoff } from './session.js'

// Must run before <App/> reads the session: a superadmin's "View as" tab starts here.
consumeViewAsHandoff()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <UIFeedbackProvider>
      <ViewAsBanner />
      <App />
    </UIFeedbackProvider>
  </StrictMode>,
)
