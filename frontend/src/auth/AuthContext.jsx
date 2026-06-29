import { createContext, useContext, useEffect, useState } from 'react'
import { Logo } from '../design-system'
import { apiFetch } from './api.js'

/**
 * Auth state for the SPA.
 *
 * status:
 *   'loading' — probing /api/dashboard/me
 *   'authed'  — session valid; user is populated
 *   'anon'    — no/expired session; apiFetch has already started a login redirect
 *   'error'   — server unreachable or unexpected failure
 */
const AuthContext = createContext({ status: 'loading', user: null })

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', user: null })

  useEffect(() => {
    let cancelled = false
    apiFetch('/api/dashboard/me')
      .then((me) => {
        if (!cancelled) setState({ status: 'authed', user: me })
      })
      .catch((err) => {
        if (cancelled) return
        // A 401 already kicked off the login redirect inside apiFetch; mark
        // anon so the tree renders a redirect splash, not stale content.
        setState({ status: err?.status === 401 ? 'anon' : 'error', user: null })
      })
    return () => {
      cancelled = true
    }
  }, [])

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}

/** Gate children behind a valid session. Shows a branded splash while resolving. */
export function ProtectedRoute({ children }) {
  const { status } = useAuth()
  if (status === 'authed') return children
  if (status === 'anon') return <AuthSplash label="Redirecting to sign in\u2026" />
  if (status === 'error') {
    return (
      <AuthSplash
        label="Couldn\u2019t reach the server. Refresh to try again."
        error
      />
    )
  }
  return <AuthSplash label="Loading your workspace\u2026" />
}

function AuthSplash({ label, error = false }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 18,
        background: 'var(--ink-900)',
        color: error ? 'var(--warn)' : 'var(--muted)',
        font: 'var(--fw-medium) var(--fs-sm)/1.4 var(--font-sans)',
        padding: 24,
        textAlign: 'center',
      }}
    >
      <Logo size={44} markOnly />
      <span>{label}</span>
    </div>
  )
}
