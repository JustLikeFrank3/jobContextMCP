// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const { apiFetch, apiPost, apiSend } = vi.hoisted(() => ({
  apiFetch: vi.fn(), apiPost: vi.fn(), apiSend: vi.fn(),
}))
vi.mock('../auth/api.js', async (original) => ({
  ...await original(), apiFetch, apiPost, apiSend,
}))
vi.mock('../shell/useDesktopMode.js', () => ({ default: () => true }))

import Evals from './Evals.jsx'
import Chat from './Chat.jsx'
import DataSection from './settings/DataSection.jsx'
import McpClientsSection from './settings/McpClientsSection.jsx'
import OuraSection from './settings/OuraSection.jsx'

let root, host, scrollToDescriptor
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  apiFetch.mockReset().mockResolvedValue({})
  apiPost.mockReset().mockResolvedValue({})
  apiSend.mockReset().mockResolvedValue({})
  scrollToDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  if (scrollToDescriptor) Object.defineProperty(HTMLElement.prototype, 'scrollTo', scrollToDescriptor)
  else delete HTMLElement.prototype.scrollTo
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function button(label) {
  return [...host.querySelectorAll('button')].find(node => node.textContent === label)
}

function inputValue(input, value) {
  const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

test('triage awaits failed rulings, rolls back selection, and reports note-save errors', async () => {
  apiFetch.mockResolvedValue({
    rows: [{ gd_id: 'gd1', mean: 4, flags: 1 }],
    claims: [{ key: 'claim1', gd_id: 'gd1', claim: 'Synthetic claim', ruling: 'A', note: 'Existing note' }],
  })
  apiSend.mockRejectedValue(new Error('Unable to save this ruling'))
  await act(async () => root.render(<Evals />))
  await act(async () => button('B').click())
  expect(apiSend).toHaveBeenCalledWith('/dashboard/evals/triage', {
    body: { gd_id: 'gd1', claim: 'Synthetic claim', ruling: 'B', note: 'Existing note' },
  })
  expect(button('A').style.background).toContain('--danger')
  expect(button('B').style.background).toContain('--well')
  expect(host.textContent).toContain('Unable to save this ruling')
  const note = host.querySelector('input[placeholder^="Note"]')
  await act(async () => inputValue(note, 'Keep this unsaved note'))
  await act(async () => note.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
  expect(apiSend.mock.calls.at(-1)[1].body).toMatchObject({ ruling: 'A', note: 'Keep this unsaved note' })
  expect(note.value).toBe('Keep this unsaved note')
  expect(host.textContent).not.toContain('saving…')
})

test('workspace import reports failure, allows same-file retry, and shows confirmed success', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error('Import unavailable'))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ backup: '/backup/synthetic' }) })
  vi.stubGlobal('fetch', fetch)
  await act(async () => root.render(<DataSection isDesktop />))
  const file = new File(['synthetic zip'], 'workspace.zip', { type: 'application/zip' })
  const input = host.querySelector('input[type="file"]')
  Object.defineProperty(input, 'files', { configurable: true, value: [file] })
  await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
  expect(host.textContent).toContain('Import unavailable')
  expect(input.value).toBe('')
  expect(button('Import from zip…').disabled).toBe(false)
  await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls[1][1].body).toBe(file)
  expect(host.textContent).toContain('Import complete — previous data saved to /backup/synthetic')
})

test('Oura Enter submission awaits error handling and can retry without losing the token', async () => {
  apiPost.mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce({})
  const reload = vi.fn()
  await act(async () => root.render(<OuraSection data={{}} reload={reload} isDesktop />))
  const input = host.querySelector('input[type="password"]')
  await act(async () => inputValue(input, 'synthetic-test-token'))
  const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
  await act(async () => input.dispatchEvent(enter))
  expect(enter.defaultPrevented).toBe(true)
  expect(host.textContent).toContain('Could not connect. Check the token and try again.')
  expect(input.value).toBe('synthetic-test-token')
  expect(button('Connect').disabled).toBe(false)
  await act(async () => button('Connect').click())
  expect(apiPost).toHaveBeenLastCalledWith('/api/dashboard/oura/pat', { token: 'synthetic-test-token' })
  expect(reload).toHaveBeenCalledTimes(1)
  expect(input.value).toBe('')
})

test('MCP client status stays distinct while both disconnected states share the muted tone', async () => {
  apiFetch.mockResolvedValue({ clients: [
    { id: 'a', label: 'Connected client', installed: true, connected: true },
    { id: 'b', label: 'Detected client', installed: true, connected: false },
    { id: 'c', label: 'Missing client', installed: false, connected: false },
  ] })
  await act(async () => root.render(<McpClientsSection />))
  const badges = [...host.querySelectorAll('span')].filter(node => ['connected', 'detected', 'not detected'].includes(node.textContent))
  expect(badges.map(node => node.textContent)).toEqual(['connected', 'detected', 'not detected'])
  expect(badges[1].style.color).toBe(badges[2].style.color)
  expect(badges[0].style.color).not.toBe(badges[1].style.color)
})

function renderChat(state) {
  return root.render(<MemoryRouter initialEntries={[{ pathname: '/chat', state }]}><Chat /></MemoryRouter>)
}

test('seeded chat session-creation failure is handled and shown without streaming', async () => {
  apiPost.mockRejectedValue(new Error('Session creation unavailable'))
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await act(async () => renderChat({ seed: 'Help me prepare' }))
  expect(host.querySelector('[role="alert"]').textContent).toContain('Could not start the suggested chat')
  expect(apiPost).toHaveBeenCalledTimes(1)
  expect(fetch).not.toHaveBeenCalled()
})

test('manual chat session-creation failure retains the unsent draft and prevents duplicate requests', async () => {
  let reject
  apiPost.mockImplementation(() => new Promise((resolve, fail) => { reject = fail }))
  await act(async () => renderChat())
  const input = host.querySelector('textarea')
  await act(async () => inputValue(input, 'My unsent question'))
  await act(async () => button('Send').click())
  expect(button('Send').disabled).toBe(true)
  await act(async () => button('Send').click())
  expect(apiPost).toHaveBeenCalledTimes(1)
  await act(async () => reject(new Error('Unavailable')))
  expect(input.value).toBe('My unsent question')
  expect(host.querySelector('[role="alert"]').textContent).toContain('Your message was not sent')
  expect(button('Send').disabled).toBe(false)
})

test('a delayed chat failure does not overwrite a newer composer draft', async () => {
  let reject
  apiPost.mockImplementation(() => new Promise((resolve, fail) => { reject = fail }))
  await act(async () => renderChat())
  const input = host.querySelector('textarea')
  await act(async () => inputValue(input, 'First question'))
  await act(async () => button('Send').click())
  await act(async () => inputValue(input, 'Newer draft'))
  await act(async () => reject(new Error('Unavailable')))
  expect(input.value).toBe('Newer draft')
  expect(host.querySelector('[role="alert"]').textContent).toContain('Your message was not sent')
})

test('chat session selection and tool disclosure are native focusable buttons', async () => {
  apiFetch.mockImplementation(async path => {
    if (path === '/api/chat/sessions') return { sessions: [{ id: 7, title: 'Earlier chat' }] }
    if (path === '/api/chat/sessions/7/messages') return { messages: [{ id: 1, role: 'tool', tool_name: 'list_jobs', content: 'Synthetic result' }] }
    return {}
  })
  await act(async () => renderChat())
  const session = button('Earlier chat')
  expect(session.type).toBe('button')
  expect(session.tabIndex).toBe(0)
  await act(async () => session.click())
  expect(session.getAttribute('aria-pressed')).toBe('true')
  expect(apiFetch).toHaveBeenCalledWith('/api/chat/sessions/7/messages')
  const chip = [...host.querySelectorAll('button')].find(node => node.textContent.includes('list_jobs'))
  expect(chip.type).toBe('button')
  expect(chip.tabIndex).toBe(0)
  expect(chip.getAttribute('aria-expanded')).toBe('false')
  await act(async () => chip.click())
  expect(chip.getAttribute('aria-expanded')).toBe('true')
  expect(host.querySelector('pre').textContent).toBe('Synthetic result')
  await act(async () => chip.click())
  expect(host.querySelector('pre')).toBeNull()
})
