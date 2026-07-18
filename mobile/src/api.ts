// Thin client for the jobContext cloud API. Auth is a personal access token
// (cloud dashboard → API Keys tab) stored in the device keychain — no OAuth
// dance, no refresh tokens to go stale while the app sits unopened.
import * as SecureStore from 'expo-secure-store'

const URL_KEY = 'jc_base_url'
const PAT_KEY = 'jc_pat'
export const DEFAULT_URL = 'https://app.jobcontext.ai'

export async function getConfig(): Promise<{ url: string; pat: string }> {
  const [url, pat] = await Promise.all([
    SecureStore.getItemAsync(URL_KEY),
    SecureStore.getItemAsync(PAT_KEY),
  ])
  return { url: (url || DEFAULT_URL).replace(/\/$/, ''), pat: pat || '' }
}

export async function setConfig(url: string, pat: string): Promise<void> {
  await SecureStore.setItemAsync(URL_KEY, url.trim().replace(/\/$/, '') || DEFAULT_URL)
  if (pat.trim()) await SecureStore.setItemAsync(PAT_KEY, pat.trim())
}

export async function clearPat(): Promise<void> {
  await SecureStore.deleteItemAsync(PAT_KEY)
}

export async function isConnected(): Promise<boolean> {
  const { pat } = await getConfig()
  return Boolean(pat)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const { url, pat } = await getConfig()
  if (!pat) throw new Error('Not connected — add your API key in Settings.')
  const bearer = pat
  // Time-bound every call: an unbounded fetch leaves UI states (e.g. the
  // capture banner's "Saving…") hanging forever on a bad connection.
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 30_000)
  let res: Response
  try {
    res = await fetch(`${url}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${bearer}`,
        ...(init?.headers || {}),
      },
    })
  } catch (e: any) {
    if (e?.name === 'AbortError' || /abort/i.test(String(e?.message))) {
      throw new Error('Request timed out — check your connection and try again.')
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as any))
    throw new Error(body?.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

export type InboxEvent = {
  id: number
  ts: string
  type: string
  title: string
  subtitle?: string
  company?: string
  role?: string
}

export const fetchEvents = () => api<{ events: InboxEvent[] }>('/api/events')
export const captureUrl = (url: string, text = '') =>
  api<{ status: string; detail: string }>('/api/capture', {
    method: 'POST',
    body: JSON.stringify({ url, text }),
  })
export const registerPush = (token: string, platform: string) =>
  api('/api/push/register', { method: 'POST', body: JSON.stringify({ token, platform }) })
