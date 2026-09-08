// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, test, expect, vi } from 'vitest'
import Discovery from './Discovery.jsx'
let root, host
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  window.history.replaceState({}, '', '/discovery?c=referral&program=beta')
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals() })

test('signup omits credentials, includes attribution, and shows only the thank-you', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ message: 'ok' }) }); vi.stubGlobal('fetch', fetch)
  await act(async () => root.render(<Discovery />))
  for (const [key, value] of Object.entries({ name:'Pat', email:'pat@example.com', segment_answer:'coach', current_tools:'Notes', ai_assistant:'Claude', best_window:'Friday 2pm Eastern' })) host.querySelector(`[name="${key}"]`).value = value
  expect(host.querySelector('[name="incentive_preference"]')).toBeNull()
  await act(async () => host.querySelector('form').dispatchEvent(new Event('submit', { bubbles:true, cancelable:true })))
  const [url, request] = fetch.mock.calls[0]
  expect(url).toBe('/api/discovery/signup'); expect(request.credentials).toBe('omit')
  expect(JSON.parse(request.body)).toMatchObject({ channel:'referral', program:'beta' })
  expect(host.textContent).toContain("Thanks for your interest in the jobContext beta.")
})

test('signup shows recoverable failure without discarding fields', async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'Please try again in ten minutes.'})}))
  await act(async () => root.render(<Discovery />))
  host.querySelector('[name="name"]').value='Pat'
  await act(async () => host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))
  expect(host.querySelector('[role="alert"]').textContent).toContain('ten minutes')
  expect(host.querySelector('[name="name"]').value).toBe('Pat')
})

test('review exposes consent error and blocks invalid snapshot', async () => {
  window.history.replaceState({}, '', '/discovery/review')
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({ledger:{participants:[],sessions:[],incentives:[]},report:{numbers:{customer_interviews_completed:0},errors:['session 1: completed interview without consent on file'],warnings:[]}})}))
  await act(async()=>root.render(<Discovery />))
  expect(host.querySelector('[role="alert"]').textContent).toContain('without consent')
  expect(host.querySelector('button').disabled).toBe(true)
})

 test.each(['/discovery/beta?c=network_free', '/discovery?program=beta&c=network_free'])('beta route %s is clearly distinct and preserves attribution', async path => {
  window.history.replaceState({}, '', path)
  await act(async () => root.render(<Discovery />))
  expect(host.querySelector('h1').textContent).toBe('Help test jobContext.')
  expect(document.title).toBe('jobContext: Beta signup')
  expect(host.querySelector('[name="best_window"]').required).toBe(false)
  expect(host.querySelector('[name="incentive_preference"]')).toBeNull()
  expect(host.querySelector('a').getAttribute('href')).toBe('/discovery?c=network_free')
  expect(host.querySelector('button').textContent).toBe('Join the beta list')
 })
 test('interview keeps scheduling and incentive choices with beta navigation', async () => {
  window.history.replaceState({}, '', '/discovery?c=referral')
  await act(async () => root.render(<Discovery />))
  expect(host.querySelector('h1').textContent).toBe('Help shape a better job search.')
  expect(host.querySelector('[name="best_window"]').required).toBe(true)
  expect(host.querySelector('[value="gift_card"]')).not.toBeNull()
  expect(host.querySelector('a').getAttribute('href')).toBe('/discovery/beta?c=referral')
 })
