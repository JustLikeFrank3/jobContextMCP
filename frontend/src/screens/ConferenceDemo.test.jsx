// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const request = vi.fn()
const apiPost = vi.fn()
vi.mock('../auth/api.js', async importOriginal => ({ ...await importOriginal(), apiSend: (path, options) => apiPost(path, options.body) }))
vi.mock('./conference/api.js', async importOriginal => ({ ...await importOriginal(), request: (...args) => request(...args) }))
const { default: ConferenceDemo } = await import('./ConferenceDemo.jsx')
let root, host, savedJob
const job = { job_id: 7, company: 'Acme', role: 'Engineer', status: 'pending' }
const run = { id: 31, kind: 'badge_materials', inputs: { job_id: 7, material: 'both' }, status: 'succeeded', artifacts: { resume: 'made', cover_letter: 'made' } }
const button = text => [...host.querySelectorAll('button')].find(b => b.textContent === text)
const click = async text => act(async () => button(text).click())

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  window.history.replaceState(null, '', '/app/conference-demo')
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  savedJob = { id: 7, company: 'Acme', role: 'Engineer', resume_template: '', resume_style: '', cl_template: '', cl_style: '' }
  apiPost.mockReset()
  apiPost.mockImplementation(async (path, body) => {
    const prefix = path.endsWith('/select-cl-template') ? 'cl' : 'resume'
    savedJob = { ...savedJob, [`${prefix}_template`]: body.template, [`${prefix}_style`]: body.style }
    return { ok: true }
  })
  request.mockReset()
  request.mockImplementation(async (path, body) => {
    if (path === '/dashboard/pipeline/data') return { jobs: [savedJob], resume_templates: ['modern', 'executive', 'sidebar', 'portfolio'], cl_templates: ['modern', 'executive', 'sidebar', 'portfolio'], template_styles: ['navy', 'slate', 'forest', 'warm', 'classic'] }
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
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both', template: '', style: 'navy', cl_template: '', cl_style: 'navy' })
  expect(request.mock.calls.some(([path]) => path === '/api/badge/jobs/queue')).toBe(false)
  expect(host.textContent).toContain('Completed')
  expect(window.location.search).toBe('?work=31')
  expect(host.querySelector('a[href="/materials"]')).not.toBeNull()
})

test('open position is explicitly queued before generation', async () => {
  await render(); await search('open'); await click('Add & select')
  expect(request).toHaveBeenCalledWith('/api/badge/jobs/queue', { search_id: 'stored-search', number: 2 })
  await click('Generate documents')
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both', template: '', style: 'navy', cl_template: '', cl_style: 'navy' })
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

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('a late URL recovery cannot replace a newer selected generation', async () => {
  const recovery = deferred()
  const newer = { ...run, id: 32 }
  const impl = request.getMockImplementation()
  window.history.replaceState({ idx: 2, key: 'retained' }, '', '/app/conference-demo?work=31')
  request.mockImplementation((path, body) => {
    if (path === '/api/work/31') return recovery.promise
    if (path === '/api/work?limit=50') return { items: [newer] }
    return impl(path, body)
  })
  await render()
  await click('View status #32')
  await act(async () => recovery.resolve(run))
  expect(host.textContent).toContain('Generation #32')
  expect(host.textContent).not.toContain('Generation #31')
  expect(window.location.search).toBe('?work=32')
  expect(window.history.state).toEqual({ idx: 2, key: 'retained' })
})

test('a generation response after leaving cannot rewrite the new page URL', async () => {
  const submission = deferred()
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/api/badge/materials' ? submission.promise : impl(path, body))
  await render(); await search(); await click('Select')
  await click('Generate documents')
  await act(async () => root.render(<div>Materials screen</div>))
  window.history.replaceState({ idx: 3 }, '', '/app/materials')
  await act(async () => submission.resolve({ work_id: 31 }))
  expect(window.location.pathname + window.location.search).toBe('/app/materials')
  expect(window.history.state).toEqual({ idx: 3 })
  expect(request.mock.calls.filter(([path]) => path === '/api/badge/materials')).toHaveLength(1)
})

test('late initial history cannot overwrite a newer recovery list', async () => {
  const initialHistory = deferred()
  const impl = request.getMockImplementation()
  let historyCalls = 0
  request.mockImplementation((path, body) => {
    if (path === '/api/work?limit=50') return ++historyCalls === 1 ? initialHistory.promise : { items: [run] }
    return impl(path, body)
  })
  await render()
  await click('Refresh recent generations')
  await act(async () => initialHistory.resolve({ items: [] }))
  expect(button('View status #31')).toBeDefined()
  expect(host.textContent).not.toContain('No badge or conference generations')
})


test('existing template picker persists independent document choices and queues those exact choices', async () => {
  await render(); await search(); await click('Select'); await click('Choose templates')
  const modal = () => document.querySelector('[role="dialog"]')
  const modalButton = text => [...modal().querySelectorAll('button')].find(b => b.textContent === text)
  await change(modal().querySelectorAll('select')[0], 'executive')
  await change(modal().querySelectorAll('select')[1], 'forest')
  expect(modal().querySelector('iframe').getAttribute('src')).toBe('/dashboard/pipeline/preview-template/executive/forest')
  await act(async () => modalButton('Use this resume template').click())
  expect(apiPost).toHaveBeenCalledWith('/dashboard/pipeline/select-template', { job_id: 7, template: 'executive', style: 'forest' })
  await act(async () => modalButton('Cover Letter').click())
  await change(modal().querySelectorAll('select')[0], 'sidebar')
  await change(modal().querySelectorAll('select')[1], 'warm')
  await act(async () => modalButton('Use this cover letter template').click())
  await act(async () => modalButton('Close').click())
  expect(host.textContent).toContain('Resume layout: executive / forest. Cover letter layout: sidebar / warm.')
  await click('Choose templates')
  expect(modal().querySelectorAll('select')[0].value).toBe('executive')
  await act(async () => modalButton('Cover Letter').click())
  expect(modal().querySelectorAll('select')[0].value).toBe('sidebar')
  expect(modal().querySelectorAll('select')[1].value).toBe('warm')
  await act(async () => modalButton('Close').click())
  await click('Generate documents')
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both', template: 'executive', style: 'forest', cl_template: 'sidebar', cl_style: 'warm' })
  expect(host.textContent).toContain('Queued layouts: resume executive / forest; cover letter sidebar / warm.')
})

test('saved template choices are loaded for a selected job and not silently replaced on fetch failure', async () => {
  savedJob = { ...savedJob, resume_template: 'portfolio', resume_style: 'classic', cl_template: 'modern', cl_style: 'slate' }
  const impl = request.getMockImplementation()
  let fail = true
  request.mockImplementation((path, body) => path === '/dashboard/pipeline/data' && fail ? Promise.reject(new TypeError('Offline')) : impl(path, body))
  await render(); await search(); await click('Select')
  expect(button('Generate documents').disabled).toBe(true)
  fail = false
  await click('Load saved template choices')
  expect(host.textContent).toContain('Resume layout: portfolio / classic. Cover letter layout: modern / slate.')
  await click('Generate documents')
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both', template: 'portfolio', style: 'classic', cl_template: 'modern', cl_style: 'slate' })
})

test('closing the picker without saving does not alter queued choices', async () => {
  await render(); await search(); await click('Select'); await click('Choose templates')
  const modal = document.querySelector('[role="dialog"]')
  await change(modal.querySelectorAll('select')[0], 'sidebar')
  await act(async () => [...modal.querySelectorAll('button')].find(b => b.textContent === 'Close').click())
  expect(apiPost).not.toHaveBeenCalled()
  await click('Generate documents')
  expect(request).toHaveBeenCalledWith('/api/badge/materials', { job_id: 7, material: 'both', template: '', style: 'navy', cl_template: '', cl_style: 'navy' })
})


test('picker save timeout releases every close path without retrying the POST', async () => {
  await render(); await search(); await click('Select'); await click('Choose templates')
  apiPost.mockImplementation(() => new Promise(() => {}))
  vi.useFakeTimers()
  try {
    const dialog = () => document.querySelector('[role="dialog"]')
    const modalButton = text => [...dialog().querySelectorAll('button')].find(b => b.textContent === text)
    await act(async () => modalButton('Use this resume template').click())
    expect(modalButton('Close').disabled).toBe(true)
    await act(async () => dialog().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(dialog()).not.toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(35000) })
    expect(dialog().textContent).toContain('Saving could not be confirmed')
    expect(modalButton('Close').disabled).toBe(false)
    await act(async () => modalButton('Close').click())
    expect(dialog()).toBeNull()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(button('Generate documents').disabled).toBe(true)
  } finally { vi.useRealTimers() }
})

test('saved selection with a failed reload cannot silently generate using stale choices', async () => {
  await render(); await search(); await click('Select'); await click('Choose templates')
  const impl = request.getMockImplementation()
  request.mockImplementation((path, body) => path === '/dashboard/pipeline/data' ? Promise.reject(new TypeError('Lost response')) : impl(path, body))
  const dialog = document.querySelector('[role="dialog"]')
  await change(dialog.querySelectorAll('select')[0], 'executive')
  await act(async () => [...dialog.querySelectorAll('button')].find(b => b.textContent === 'Use this resume template').click())
  await act(async () => [...dialog.querySelectorAll('button')].find(b => b.textContent === 'Close').click())
  expect(button('Generate documents').disabled).toBe(true)
  request.mockImplementation(impl)
  await click('Load saved template choices')
  expect(host.textContent).toContain('Resume layout: executive / navy.')
  expect(button('Generate documents').disabled).toBe(false)
})
