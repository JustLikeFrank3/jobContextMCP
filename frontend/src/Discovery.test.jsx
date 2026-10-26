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
  expect(host.querySelector('form button').getAttribute('type')).toBe('submit')
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

test('review displays both signup programs and their separate answers', async () => {
  window.history.replaceState({}, '', '/discovery/review')
  const participant = {id:1,name:'Pat',contact:'pat@example.com',program:'interview',programs:['interview','beta'],status:'screened',segment:'coach',channel:'referral',consent:{},screener:{program_signups:{interview:{channel:'referral',created_at:'2026-09-07',screener:{best_window:'Monday',incentive_preference:'gift_card'}},beta:{channel:'network_free',created_at:'2026-09-08',screener:{best_window:'Next week',current_tools:['Notes']}}}}}
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({ledger:{participants:[participant],sessions:[],incentives:[]},report:{numbers:{},errors:[],warnings:[]}})}))
  await act(async()=>root.render(<Discovery />))
  expect(host.textContent).toContain('interview + beta')
  expect(host.textContent).toContain('Testing availability')
  expect(host.textContent).toContain('Next week')
  expect(host.textContent).toContain('Monday')
  expect(host.textContent).not.toContain('[object Object]')
  expect(host.querySelector('.discovery-actions form button').getAttribute('type')).toBe('submit')
})

test('review filter values use explicit alphabetical ordering without changing participant order', async () => {
  window.history.replaceState({}, '', '/discovery/review')
  const participants = [
    { id: 2, name: 'Second', contact: '', status: 'screened', segment: 'coach', channel: 'referral', consent: {} },
    { id: 10, name: 'Tenth', contact: '', status: 'consented', segment: 'career change', channel: 'other', consent: {} },
    { id: 1, name: 'First', contact: '', status: 'screened', segment: 'coach', channel: 'discord', consent: {} },
  ]
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    ledger: { participants, sessions: [], incentives: [] }, report: { numbers: {}, errors: [], warnings: [] },
  }) }))
  await act(async () => root.render(<Discovery />))
  const filters = host.querySelectorAll('.discovery-grid select')
  expect([...filters[0].options].map(option => option.text)).toEqual(['All', 'consented', 'screened'])
  expect([...filters[1].options].map(option => option.text)).toEqual(['All', 'career change', 'coach'])
  expect([...filters[2].options].map(option => option.text)).toEqual(['All', 'discord', 'other', 'referral'])
  expect([...host.querySelectorAll('summary strong')].map(node => node.textContent)).toEqual(['Tenth', 'Second', 'First'])
  expect(host.querySelector('button').getAttribute('type')).toBe('button')
})
