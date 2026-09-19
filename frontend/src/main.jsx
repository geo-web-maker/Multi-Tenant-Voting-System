import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { UIFeedbackProvider } from './components/UIFeedback.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <UIFeedbackProvider>
      <App />
    </UIFeedbackProvider>
  </StrictMode>,
)
