// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const request = vi.fn()
vi.mock('./conference/api.js', async importOriginal => ({ ...await importOriginal(), request: (...args) => request(...args) }))
const { default: ConferenceDemo } = await import('./ConferenceDemo.jsx')
let root, host
const job = { job_id: 7, company: 'Acme', role: 'Engineer', status: 'pending' }
const run = { id: 31, kind: 'badge_materials', inputs: { job_id: 7, material: 'both' }, status: 'succeeded', artifacts: { resume: 'made', cover_letter: 'made' } }
const button = text => [...host.querySelectorAll('button')].find(b => b.textContent === text)
const click = async text => act(async () => button(text).click())

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  window.history.replaceState(null, '', '/app/conference-demo')
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  request.mockReset()
  request.mockImplementation(async (path, body) => {
    if (path === '/api/work?limit=50') return { items: [] }
    if (path === '/api/work/31') return run
    if (path.startsWith('/api/badge/search?')) return { count: 1, results: [job] }
    if (path.startsWith('/api/badge/jobs?')) return { count: 1, search_id: 'stored-search', results: [{ number: 2, company: 'Acme', role: 'Engineer' }] }
    if (path === '/api/badge/jobs/queue') return { ...job, status: 'queued' }
    if (path === '/api/badge/materials' && body) return { work_id: 31, status: 'queued' }
    if (path === '/api/badge/work/31') return { work_id: 31, status: 'succeeded', made: ['resume', 'cover_letter'], detail: '' }
    throw new Error(`Unexpected request ${path}`)
  })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers() })
const render = async () => act(async () => root.render(<MemoryRouter><ConferenceDemo /></MemoryRouter>))
async function change(element, value) {
  await act(async () => {
    const prototype = element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
    element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
  })
}
async function search(source = 'pipeline') {
  if (source !== 'pipeline') await change(host.querySelector('select'), source)
  await change(host.querySelector('input'), 'Acme')
  await act(async () => host.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
}

test('existing pipeline → select → both documents → existing Materials, without another job', async () => {
  await render(); await search(); await click('Select'); await click('Generate documents')
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both' })
  expect(request.mock.calls.some(([path]) => path === '/api/badge/jobs/queue')).toBe(false)
  expect(host.textContent).toContain('Completed')
  expect(window.location.search).toBe('?work=31')
  expect(host.querySelector('a[href="/materials"]')).not.toBeNull()
})

test('open position is explicitly queued before generation', async () => {
  await render(); await search('open'); await click('Add & select')
  expect(request).toHaveBeenCalledWith('/api/badge/jobs/queue', { search_id: 'stored-search', number: 2 })
  await click('Generate documents')
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both' })
})

test('directory-only results cannot generate', async () => {
  request.mockImplementation(async path => path.startsWith('/api/badge/search') ? { count: 1, results: [{ ...job, job_id: 0 }] } : { items: [] })
  await render(); await search()
  expect(host.textContent).toContain('Employer only')
  expect(button('Select')).toBeUndefined()
  expect(button('Generate documents')).toBeUndefined()
})

test('partial completion names the missing document and preserves Materials access', async () => {
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/badge/work/31' ? { status: 'succeeded', made: ['resume'] } : impl(path, body))
  await render(); await search(); await click('Select'); await click('Generate documents')
  expect(host.textContent).toContain('Partially completed')
  expect(host.textContent).toContain('Not created: cover letter')
})

test('failed generation is never presented as completed', async () => {
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/badge/work/31' ? { status: 'failed', made: [], detail: 'Provider unavailable' } : impl(path, body))
  await render(); await search(); await click('Select'); await click('Generate documents')
  expect(host.textContent).toContain('Generation failed. Provider unavailable')
  expect(host.textContent).not.toContain('Completed')
})

test('lost POST response blocks another generation until recent runs are checked', async () => {
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/badge/materials' ? Promise.reject(new TypeError('Network lost')) : impl(path, body))
  await render(); await search(); await click('Select'); await click('Generate documents')
  expect(button('Generate documents').disabled).toBe(true)
  expect(button('I checked recent runs and Materials').disabled).toBe(true)
  await click('Refresh recent generations')
  await click('I checked recent runs and Materials')
  expect(button('Generate documents').disabled).toBe(false)
  expect(request.mock.calls.filter(([path]) => path === '/api/badge/materials')).toHaveLength(1)
})

test('polling network failure pauses; Check status retries GET without generating again', async () => {
  const impl = request.getMockImplementation()
  let fail = true
  request.mockImplementation((path, body) => path === '/api/badge/work/31' && fail ? Promise.reject(new TypeError('Offline')) : impl(path, body))
  await render(); await search(); await click('Select'); await click('Generate documents')
  expect(host.textContent).toContain('Status check paused')
  fail = false
  await click('Check status')
  expect(host.textContent).toContain('Completed')
  expect(request.mock.calls.filter(([path]) => path === '/api/badge/materials')).toHaveLength(1)
})

test('URL work handle resumes after refresh without any POST', async () => {
  window.history.replaceState(null, '', '/app/conference-demo?work=31')
  await render()
  expect(host.textContent).toContain('Generation #31')
  expect(host.textContent).toContain('Completed')
  expect(request.mock.calls.every(([, body]) => body === undefined)).toBe(true)
})

test('recent active work can be resumed and prevents duplicate generation', async () => {
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/work?limit=50' ? { items: [{ ...run, status: 'running' }, { id: 99, kind: 'capture_url' }] } : impl(path, body))
  await render(); await search(); await click('Select')
  expect(button('Generate documents').disabled).toBe(true)
  expect(button('View status #99')).toBeUndefined()
  await click('View status #31')
  expect(host.textContent).toContain('Generation #31')
})

test('expired session retains selected job and offers reauthentication', async () => {
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/badge/materials' ? Promise.reject({ status: 401 }) : impl(path, body))
  await render(); await search(); await click('Select'); await click('Generate documents')
  expect(host.textContent).toContain('Session expired')
  expect(host.textContent).toContain('Selected: Acme')
  expect(host.querySelector('a[target="_blank"]').getAttribute('href')).toContain('/dashboard/login?next=')
})

test('expired discovery results never select or generate a job', async () => {
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/badge/jobs/queue' ? Promise.reject({ status: 410 }) : impl(path, body))
  await render(); await search('open'); await click('Add & select')
  expect(host.textContent).toContain('results expired')
  expect(button('Generate documents')).toBeUndefined()
})

test('offline controls stop mutations and show saved-example recovery', async () => {
  await render(); await search(); await click('Select')
  await act(async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    window.dispatchEvent(new Event('offline'))
  })
  expect(button('Generate documents').disabled).toBe(true)
  expect(host.textContent).toContain('example PDFs saved on your device')
  await act(async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    window.dispatchEvent(new Event('online'))
  })
  expect(button('Generate documents').disabled).toBe(false)
})

test('double click sends a single generation request', async () => {
  await render(); await search(); await click('Select')
  await act(async () => { button('Generate documents').click(); button('Generate documents').click() })
  expect(request.mock.calls.filter(([path]) => path === '/api/badge/materials')).toHaveLength(1)
})
