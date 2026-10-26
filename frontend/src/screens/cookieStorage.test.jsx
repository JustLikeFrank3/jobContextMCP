// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const { apiFetch, apiSend } = vi.hoisted(() => ({ apiFetch: vi.fn(), apiSend: vi.fn() }))
vi.mock('../auth/api.js', async (original) => ({ ...await original(), apiFetch, apiSend }))
import Evals from './Evals.jsx'

const DRAFT_KEY = 'jc-evals-golden-draft'
let root, host

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  sessionStorage.clear()
  apiFetch.mockReset().mockResolvedValue({})
  apiSend.mockReset().mockResolvedValue({ entry: { id: 'synthetic-entry' } })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.restoreAllMocks()
  localStorage.clear()
  sessionStorage.clear()
})

function input(placeholder) {
  return host.querySelector(`[placeholder="${placeholder}"]`)
}

async function fill(placeholder, value) {
  const node = input(placeholder)
  const prototype = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, value)
    node.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function save() {
  const button = [...host.querySelectorAll('button')].find(node => node.textContent === 'Add entry')
  await act(async () => button.click())
}

test('viewing Evals alone creates no cookie, localStorage, or sessionStorage', async () => {
  await act(async () => root.render(<Evals />))
  expect(Object.keys(localStorage)).toEqual([])
  expect(Object.keys(sessionStorage)).toEqual([])
  expect(document.cookie).toBe('')
  expect(apiFetch).toHaveBeenCalledWith('/dashboard/evals/data')
  expect(apiSend).not.toHaveBeenCalled()
})

test('only the named session draft preserves inputs across remount and failed save, clearing on confirmed save', async () => {
  await act(async () => root.render(<Evals />))
  await fill('Company', 'Synthetic Company')
  await fill('Role title', 'Synthetic Role')
  await fill('Paste the full job description here', 'Synthetic job description')
  const draft = { company: 'Synthetic Company', role: 'Synthetic Role', jd: 'Synthetic job description', kind: 'resume' }
  expect(Object.keys(sessionStorage)).toEqual([DRAFT_KEY])
  expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY))).toEqual(draft)
  expect(Object.keys(localStorage)).toEqual([])
  expect(document.cookie).toBe('')

  await act(async () => root.unmount())
  root = createRoot(host)
  await act(async () => root.render(<Evals />))
  expect(input('Company').value).toBe(draft.company)
  expect(input('Role title').value).toBe(draft.role)
  expect(input('Paste the full job description here').value).toBe(draft.jd)

  apiSend.mockRejectedValueOnce(new Error('Synthetic interrupted save'))
  await save()
  expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY))).toEqual(draft)
  expect(host.textContent).toContain('Synthetic interrupted save')
  apiSend.mockResolvedValueOnce({})
  await save()
  expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY))).toEqual(draft)
  expect(host.textContent).toContain('save not confirmed by the server')

  apiSend.mockResolvedValueOnce({ entry: { id: 'synthetic-entry' } })
  await save()
  expect(apiSend).toHaveBeenLastCalledWith('/dashboard/evals/golden', {
    body: { company: draft.company, role: draft.role, jd_text: draft.jd, output_kind: 'resume' },
  })
  expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull()
  expect(Object.keys(localStorage)).toEqual([])
  expect(input('Company').value).toBe('')
})

test('blocked browser storage does not prevent editing and explicitly saving the form', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('Storage blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Storage blocked') })
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new DOMException('Storage blocked') })
  await act(async () => root.render(<Evals />))
  await fill('Company', 'Synthetic Company')
  await fill('Role title', 'Synthetic Role')
  await fill('Paste the full job description here', 'Synthetic job description')
  await save()
  expect(apiSend).toHaveBeenCalledTimes(1)
  expect(input('Company').value).toBe('')
})

test('changing only output type persists the selection and restores it after remount', async () => {
  await act(async () => root.render(<Evals />))
  await fill('Company', 'Synthetic Company')
  const outputType = [...host.querySelectorAll('select')].find(node =>
    [...node.options].some(option => option.value === 'cover_letter'))
  await act(async () => {
    outputType.value = 'cover_letter'
    outputType.dispatchEvent(new Event('change', { bubbles: true }))
  })
  expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY)).kind).toBe('cover_letter')
  await act(async () => root.unmount())
  root = createRoot(host)
  await act(async () => root.render(<Evals />))
  const restored = [...host.querySelectorAll('select')].find(node =>
    [...node.options].some(option => option.value === 'cover_letter'))
  expect(restored.value).toBe('cover_letter')
})
