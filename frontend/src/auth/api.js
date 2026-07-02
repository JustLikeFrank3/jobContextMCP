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
  constructor(status, message, body) {
    super(message || `API error ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
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

/**
 * Send a mutating request (POST by default) with a JSON body.
 *
 * Mirrors apiFetch's auth handling: forwards the session cookie, redirects on
 * 401, and throws ApiError on non-2xx. On error it captures the response body
 * (when present) on err.body so callers can surface why an action failed
 * (e.g. an LLM rate-limit message from a generate endpoint).
 *
 * Returns parsed JSON, or { ok: true, raw } when the body is not JSON.
 */
export async function apiSend(path, { method = 'POST', body, headers } = {}) {
  const hasBody = body !== undefined
  const res = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
      ...(headers || {}),
    },
    ...(hasBody ? { body: JSON.stringify(body) } : {}),
  })

  if (res.status === 401) {
    redirectToLogin()
    throw new ApiError(401, 'Authentication required')
  }

  const text = await res.text()
  if (!res.ok) {
    throw new ApiError(res.status, `Request failed (${res.status})`, text)
  }
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { ok: true, raw: text }
  }
}

/** Convenience wrapper: POST a JSON body and return the parsed response. */
export function apiPost(path, body) {
  return apiSend(path, { method: 'POST', body })
}