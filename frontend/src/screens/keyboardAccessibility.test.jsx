// @vitest-environment jsdom
import React, { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import Posts from './Posts.jsx'
import ImportFlow from './posts/ImportFlow.jsx'
import Sidebar from '../shell/Sidebar.jsx'
import { Modal } from './pipeline/shared.jsx'
import { ToolbarSlotContext } from '../shell/toolbarSlot.jsx'

const { apiPost, reload } = vi.hoisted(() => ({ apiPost: vi.fn(), reload: vi.fn() }))
vi.mock('../auth/api.js', () => ({
  apiPost,
  apiFetch: vi.fn(),
  ApiError: class extends Error {},
}))
vi.mock('../shell/useDesktopMode.js', () => ({ default: () => false }))
vi.mock('./_shared.jsx', () => ({
  useApi: () => ({ data: { posts: [{ id: 'p1', text: 'A post', impressions: 12 }] }, reload }),
  Screen: ({ children }) => children,
  Badge: ({ children }) => children,
  fmtDate: (value) => value,
}))

let host, root
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  apiPost.mockReset()
  reload.mockReset()
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

function button(label, container = document.body) {
  return [...container.querySelectorAll('button')].find((node) => (
    node.textContent.trim() === label || node.getAttribute('aria-label') === label
  ))
}

function key(node, value, shiftKey = false) {
  const event = new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true })
  node.dispatchEvent(event)
  return event
}

function expectNativeButton(node) {
  // Native buttons supply Enter/Space activation in the browser. jsdom does
  // not synthesize those default actions, so assert the native contract rather
  // than emulate the missing browser action with a custom keyboard listener.
  expect(node).toBeDefined()
  expect(node.tagName).toBe('BUTTON')
  expect(node.type).toBe('button')
  expect(node.tabIndex).toBe(0)
}

function PostsWithToolbar() {
  const [node, setNode] = useState(null)
  return <ToolbarSlotContext.Provider value={{ setNode }}><header>{node}</header><Posts /></ToolbarSlotContext.Provider>
}

test('post actions are native buttons and metrics dialog supports Escape, Tab and focus restoration', async () => {
  await act(async () => root.render(<PostsWithToolbar />))
  expectNativeButton(button('↧ Import from LinkedIn'))
  const update = button('Update')
  expectNativeButton(update)
  update.focus()
  await act(async () => update.click())
  const dialog = document.querySelector('[role="dialog"][aria-label="Update metrics"]')
  expect(dialog.getAttribute('aria-modal')).toBe('true')
  const close = button('Close metrics')
  const save = button('Save metrics')
  expectNativeButton(close)
  expectNativeButton(save)
  expect(document.activeElement).toBe(close)
  await act(async () => key(close, 'Tab', true))
  expect(document.activeElement).toBe(save)
  await act(async () => key(save, 'Tab'))
  expect(document.activeElement).toBe(close)
  const input = dialog.querySelector('input')
  await act(async () => input.click())
  expect(document.querySelector('[role="dialog"]')).toBe(dialog)
  input.focus()
  expect(key(input, 'Enter').defaultPrevented).toBe(false)
  expect(key(input, ' ').defaultPrevented).toBe(false)
  await act(async () => key(input, 'Escape'))
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(document.activeElement).toBe(update)

  await act(async () => update.click())
  await act(async () => document.querySelector('[role="dialog"]').click())
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})

test('metrics save cannot fire again while a request is pending and closes on success', async () => {
  let resolve
  apiPost.mockReturnValue(new Promise((done) => { resolve = done }))
  await act(async () => root.render(<PostsWithToolbar />))
  await act(async () => button('Update').click())
  await act(async () => button('Save metrics').click())
  const saving = button('Saving…')
  expect(saving.disabled).toBe(true)
  await act(async () => saving.click())
  expect(apiPost).toHaveBeenCalledTimes(1)
  expect(apiPost).toHaveBeenCalledWith('/dashboard/posts/metrics', {
    post_id: 'p1', impressions: 12, reactions: 0, comments: 0,
  })
  await act(async () => resolve({ ok: true }))
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(reload).toHaveBeenCalledOnce()
})

function ImportHarness({ onDone, onCancel, initialStep = 1 }) {
  const [step, setStep] = useState(initialStep)
  return <ImportFlow step={step} setStep={setStep} onDone={onDone} onCancel={onCancel} />
}

test('CSV picker, sample, import, cancel and completion actions use native controls', async () => {
  const onDone = vi.fn(), onCancel = vi.fn()
  apiPost.mockResolvedValue({ logged: 4, with_metrics: 0 })
  await act(async () => root.render(<ImportHarness onDone={onDone} onCancel={onCancel} />))
  const file = host.querySelector('input[type="file"][aria-label="Choose CSV file"]')
  expect(file.tabIndex).toBe(0)
  expect(file.style.display).not.toBe('none')
  await act(async () => file.focus())
  expect(document.activeElement).toBe(file)
  expect(file.closest('label').style.outline).toContain('2px solid')
  expectNativeButton(button('Use sample Shares.csv'))
  await act(async () => button('Use sample Shares.csv').click())
  expectNativeButton(button('Cancel'))
  expectNativeButton(button('Import 4 posts →'))
  await act(async () => button('Cancel').click())
  expect(onCancel).toHaveBeenCalledOnce()
  await act(async () => button('Import 4 posts →').click())
  expect(apiPost).toHaveBeenCalledTimes(1)
  expectNativeButton(button('View in Posts'))
  expectNativeButton(button('Import another'))
  await act(async () => button('View in Posts').click())
  expect(onDone).toHaveBeenCalledOnce()
  await act(async () => button('Import another').click())
  expect(host.querySelector('input[type="file"]')).not.toBeNull()
})

test('invalid or pending imports cannot be submitted repeatedly', async () => {
  let resolve
  apiPost.mockReturnValue(new Promise((done) => { resolve = done }))
  await act(async () => root.render(<ImportHarness initialStep={2} />))
  const invalid = button('Import 0 posts →')
  expect(invalid.disabled).toBe(true)
  await act(async () => invalid.click())
  expect(apiPost).not.toHaveBeenCalled()
  await act(async () => root.render(<ImportHarness key="fresh" />))
  await act(async () => button('Use sample Shares.csv').click())
  await act(async () => button('Import 4 posts →').click())
  const pending = button('Importing…')
  expect(pending.disabled).toBe(true)
  await act(async () => pending.click())
  expect(apiPost).toHaveBeenCalledTimes(1)
  await act(async () => resolve({ logged: 4 }))
})

test('sidebar navigation and sign-out are focusable native buttons', async () => {
  const onSelect = vi.fn(), onSignOut = vi.fn()
  await act(async () => root.render(<Sidebar
    primary={[{ key: 'home', label: 'Home' }]} secondary={[{ key: 'chat', label: 'Chat' }]}
    active="home" isDesktop={false} onSelect={onSelect} onSignOut={onSignOut}
  />))
  for (const label of ['Home', 'Chat', 'Settings', 'Sign out']) expectNativeButton(button(label))
  expect(button('Home').getAttribute('aria-current')).toBe('page')
  button('Chat').focus()
  expect(document.activeElement).toBe(button('Chat'))
  await act(async () => button('Chat').click())
  expect(onSelect).toHaveBeenCalledWith('chat')
  await act(async () => button('Sign out').click())
  expect(onSignOut).toHaveBeenCalledOnce()
})

test('pipeline modal handles Escape and wraps focus without treating content clicks as backdrop clicks', async () => {
  const onClose = vi.fn()
  const opener = document.createElement('button')
  host.append(opener)
  opener.focus()
  await act(async () => root.render(<Modal title="Edit resume" onClose={onClose}>
    <input aria-label="Instructions" /><button type="button">Apply</button>
  </Modal>))
  const dialog = document.querySelector('[role="dialog"][aria-label="Edit resume"]')
  const close = button('Close dialog'), last = button('Apply')
  expect(document.activeElement).toBe(close)
  await act(async () => key(close, 'Tab', true))
  expect(document.activeElement).toBe(last)
  await act(async () => key(last, 'Tab'))
  expect(document.activeElement).toBe(close)
  const input = dialog.querySelector('input')
  await act(async () => input.click())
  expect(onClose).not.toHaveBeenCalled()
  await act(async () => key(input, 'Escape'))
  expect(onClose).toHaveBeenCalledTimes(1)
  await act(async () => dialog.click())
  expect(onClose).toHaveBeenCalledTimes(2)
})
