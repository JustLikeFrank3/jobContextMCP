import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { AuthProvider } from './auth/AuthContext.jsx'
import WebMcpBridge from './webmcp/WebMcpBridge.jsx'
import './styles/global.css'

// basename matches the FastAPI mount prefix so client-side routes resolve as
// /app/, /app/pipeline, etc. when served in production.
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename="/app">
      <AuthProvider>
        {/* Sits beside App, not inside a route: WebMCP tools stay registered
            across client-side navigation for the whole authed session. */}
        <WebMcpBridge />
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
