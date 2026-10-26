import { apiSend } from '../../auth/api.js'

// Use the dashboard's HttpOnly session, never a badge key in browser storage.
// A timeout only stops waiting. It MUST NOT trigger a second mutation.
export async function request(path, body) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 35000)
  try {
    return await apiSend(path, {
      method: body === undefined ? 'GET' : 'POST', body, signal: controller.signal,
    })
  } finally {
    clearTimeout(timeout)
  }
}

export function errorText(error) {
  if (error?.status === 401) return 'Session expired. Sign in again in another tab, then check status before generating again.'
  if (error?.status === 403) return 'Access denied. Use your normal dashboard sign-in.'
  if (error?.status === 404) return 'This endpoint or work item is unavailable. Check the environment, or use Pipeline and Materials.'
  if (error?.status === 410) return 'These search results expired. Search again before selecting a job.'
  if (error?.status === 429) return 'The service limit was reached. Use an existing pipeline job or saved example, and try later.'
  if (error?.status === 503) return 'The service is temporarily unavailable or not configured. Use an existing pipeline job or saved example.'
  return 'The request could not be confirmed. Check your connection, then check recent generations before trying again.'
}

export const terminal = status => ['succeeded', 'failed', 'cancelled'].includes(status)
export const madeFrom = item => ['resume', 'cover_letter'].filter(k => item.artifacts?.[k])
export const wantedFor = material => material === 'both' ? ['resume', 'cover_letter'] : [material || 'resume']

export function recentGenerations(data) {
  return (data?.items || []).filter(item => item.kind === 'badge_materials')
}
