// Thin client for the jobContext cloud API. Auth is a personal access token
// (cloud dashboard → API Keys) stored in the device keychain.
import * as SecureStore from 'expo-secure-store'
import { getAccessToken } from './auth'

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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const { url, pat } = await getConfig()
  // Entra sign-in first (silently refreshed); PAT is the advanced fallback.
  const bearer = (await getAccessToken(url)) || pat
  if (!bearer) throw new Error('Not signed in — use Settings.')
  const res = await fetch(`${url}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${bearer}`,
      ...(init?.headers || {}),
    },
  })
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
export const captureUrl = (url: string) =>
  api<{ status: string; detail: string }>('/api/capture', {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
export const registerPush = (token: string, platform: string) =>
  api('/api/push/register', { method: 'POST', body: JSON.stringify({ token, platform }) })
