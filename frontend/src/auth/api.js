// Centralized API client for the dashboard SPA.
//
// Every data call goes through apiFetch so authentication is handled in one
// place: the session is a same-origin cookie (jc_session) set by the Entra
// OAuth flow, so we never attach a token manually — we just forward cookies and
// react to a 401 by sending the browser to the login flow.

const LOGIN_PATH = '/dashboard/login'

/** Build the login URL, returning the user to `next` (defaults to current path). */
export function loginUrl(next) {
  const target =
    next ||
    (typeof window !== 'undefined'
      ? window.location.pathname + window.location.search
      : '/app')
  return `${LOGIN_PATH}?next=${encodeURIComponent(target)}`
}

/** Send the browser to the login flow. A full navigation, not a client route. */
export function redirectToLogin(next) {
  if (typeof window !== 'undefined') {
    window.location.assign(loginUrl(next))
  }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message || `API error ${status}`)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Fetch JSON from the backend with credentials.
 *
 * - Forwards the session cookie (credentials: 'same-origin').
 * - On 401 it triggers a login redirect and throws ApiError(401), so callers
 *   don't render stale/empty state while the browser navigates away.
 * - Non-2xx throws ApiError(status); 2xx returns parsed JSON (or null on 204).
 */
export async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: { Accept: 'application/json', ...(options.headers || {}) },
  })

  if (res.status === 401) {
    redirectToLogin()
    throw new ApiError(401, 'Authentication required')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `Request failed (${res.status})`)
  }

  const text = await res.text()
  return text ? JSON.parse(text) : null
}
