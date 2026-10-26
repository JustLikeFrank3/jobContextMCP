// @vitest-environment jsdom
import { afterEach, expect, test, vi } from 'vitest'
import { errorText, request } from './api.js'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

test('requests use same-origin cookies, not browser-managed credentials', async () => {
  const fetch = vi.fn(async () => ({ status: 200, ok: true, text: async () => '{"work_id":2}' }))
  vi.stubGlobal('fetch', fetch)
  await request('/api/badge/materials', { job_id: 1, material: 'both' })
  const [path, options] = fetch.mock.calls[0]
  expect(path).toBe('/api/badge/materials')
  expect(options.credentials).toBe('same-origin')
  expect(options.headers.Authorization).toBeUndefined()
  expect(JSON.parse(options.body)).toEqual({ job_id: 1, material: 'both' })
  expect(options.signal).toBeInstanceOf(AbortSignal)
})

test('a hung mutation times out without an automatic retry', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((_, { signal }) => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
  vi.stubGlobal('fetch', fetch)
  const result = request('/api/badge/materials', { job_id: 1 }).catch(e => e)
  await vi.advanceTimersByTimeAsync(35000)
  expect((await result).name).toBe('AbortError')
  expect(fetch).toHaveBeenCalledTimes(1)
})

test('a hung status GET times out after 35 seconds without generating or retrying', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((_, { signal }) => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
  vi.stubGlobal('fetch', fetch)
  const result = request('/api/badge/work/31').catch(e => e)
  await vi.advanceTimersByTimeAsync(34999)
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(false)
  await vi.advanceTimersByTimeAsync(1)
  expect((await result).name).toBe('AbortError')
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0][1].method).toBe('GET')
  expect(fetch.mock.calls[0][1].body).toBeUndefined()
})

test.each([401, 403, 404, 410, 429, 503, 502])('HTTP %s stays an error with actionable guidance', async status => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ status, ok: false, text: async () => '{}' })))
  await expect(request('/api/badge/ping')).rejects.toMatchObject({ status })
  expect(errorText({ status }).length).toBeGreaterThan(30)
})
