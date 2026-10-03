// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, test, expect, vi } from 'vitest'

const apiFetch = vi.fn()
vi.mock('../auth/api.js', () => ({ apiFetch: (...args) => apiFetch(...args) }))

const { default: ApiKeys } = await import('./ApiKeys.jsx')

let root, host
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  apiFetch.mockReset()
  apiFetch.mockImplementation(async (path, opts) => {
    if (opts?.method === 'POST') return { id: 7, token: 'jcmcp_new' }
    return { keys: [
      { id: 1, label: 'Universe badge', created_at: '', last_used_at: '', scope: 'badge' },
      { id: 2, label: 'Claude', created_at: '', last_used_at: '', scope: 'full' },
    ] }
  })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

function choose(select, value) {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set
  setter.call(select, value)
  select.dispatchEvent(new Event('change', { bubbles: true }))
}

test('the badge-only choice reaches the create request', async () => {
  await act(async () => root.render(<ApiKeys />))
  const select = host.querySelector('select[aria-label="Key scope"]')
  await act(async () => choose(select, 'badge'))
  expect(host.textContent).toContain('nothing else')
  const generate = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Generate key')
  await act(async () => generate.click())
  const [, post] = apiFetch.mock.calls.find(([, opts]) => opts?.method === 'POST')
  expect(JSON.parse(post.body)).toEqual({ label: '', scope: 'badge' })
  expect(host.textContent).toContain('jcmcp_new')
})

test('defaults to full access and labels each key with its scope', async () => {
  await act(async () => root.render(<ApiKeys />))
  expect(host.querySelector('select[aria-label="Key scope"]').value).toBe('full')
  expect(host.textContent).toContain('Badge only')
  expect(host.textContent).toContain('Full access')
})
