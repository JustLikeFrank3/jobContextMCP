import { useEffect } from 'react'
import { useAuth } from '../auth/AuthContext.jsx'
import { getModelContext, injectOriginTrialToken, registerJobContextTools } from './bridge.js'

/**
 * Invisible mount point for the WebMCP bridge.
 *
 * Tools register only once the session probe succeeds ('authed') — register
 * earlier and an in-browser agent sees a tool surface whose every call 401s,
 * so it falls back to screen-scraping a login splash. Unregisters on unmount
 * and re-runs if auth status changes.
 */
export default function WebMcpBridge() {
  const { status } = useAuth()

  useEffect(() => {
    if (status !== 'authed') return undefined

    const token = import.meta.env.VITE_WEBMCP_OT_TOKEN
    if (token) injectOriginTrialToken(token)

    const modelContext = getModelContext()
    if (!modelContext) return undefined

    let cancelled = false
    let registration = null
    registerJobContextTools(modelContext)
      .then((reg) => {
        if (cancelled) reg.unregister()
        else registration = reg
      })
      .catch((err) => {
        // Non-fatal: the dashboard works without WebMCP; agents just lose tools.
        console.warn('[webmcp] tool registration failed:', err)
      })

    return () => {
      cancelled = true
      if (registration) registration.unregister()
    }
  }, [status])

  return null
}
