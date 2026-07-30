import { describe, it, expect } from 'vitest'
import { workspaceStatusCard } from './workspaceStatus.js'

describe('workspaceStatusCard', () => {
  it('hosted mode is always the cloud workspace card', () => {
    const card = workspaceStatusCard(false, null)
    expect(card.label).toBe('CLOUD WORKSPACE')
    expect(card.warn).toBe(false)
  })

  it('desktop with sync status not yet loaded stays local', () => {
    const card = workspaceStatusCard(true, null)
    expect(card.label).toBe('LOCAL · SQLITE')
    expect(card.detail).toMatch(/Nothing leaves the device/)
    expect(card.warn).toBe(false)
  })

  it('desktop with sync unconfigured stays local', () => {
    const card = workspaceStatusCard(true, { configured: false })
    expect(card.label).toBe('LOCAL · SQLITE')
  })

  it('desktop with sync configured must NOT claim data stays local', () => {
    const card = workspaceStatusCard(true, {
      configured: true,
      url: 'https://app.jobcontext.ai',
      last: { status: 'ok', finished: '2026-07-30T12:00:00+00:00' },
    })
    expect(card.label).toBe('LOCAL · SYNCED')
    expect(card.detail).toContain('app.jobcontext.ai')
    expect(card.detail).toMatch(/last sync/)
    expect(card.detail).not.toMatch(/Nothing leaves the device/)
    expect(card.warn).toBe(false)
  })

  it('configured but never synced yet omits the last-sync suffix', () => {
    const card = workspaceStatusCard(true, { configured: true, url: 'https://app.jobcontext.ai', last: null })
    expect(card.label).toBe('LOCAL · SYNCED')
    expect(card.detail).not.toMatch(/last sync/)
  })

  it('a failing sync warns without opening Settings', () => {
    const card = workspaceStatusCard(true, {
      configured: true,
      url: 'https://app.jobcontext.ai',
      last: { status: 'error', finished: '2026-07-30T12:00:00+00:00' },
    })
    expect(card.label).toBe('LOCAL · SYNC FAILING')
    expect(card.warn).toBe(true)
    expect(card.detail).toMatch(/Settings/)
  })

  it('unparseable url and bad timestamps degrade gracefully', () => {
    const card = workspaceStatusCard(true, {
      configured: true,
      url: 'not a url',
      last: { status: 'ok', finished: 'garbage' },
    })
    expect(card.detail).toContain('not a url')
    expect(card.detail).not.toMatch(/last sync/)
  })
})
