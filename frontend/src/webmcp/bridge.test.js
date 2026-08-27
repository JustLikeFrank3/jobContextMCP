import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./mcpClient.js', () => ({
  listTools: vi.fn(),
  callTool: vi.fn(),
}))

import { listTools, callTool } from './mcpClient.js'
import {
  getModelContext,
  injectOriginTrialToken,
  toWebMcpTool,
  registerJobContextTools,
} from './bridge.js'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getModelContext', () => {
  it('prefers document.modelContext (current spec)', () => {
    const docMc = {}
    const navMc = {}
    const scope = { document: { modelContext: docMc }, navigator: { modelContext: navMc } }
    expect(getModelContext(scope)).toBe(docMc)
  })

  it('falls back to the deprecated navigator alias', () => {
    const navMc = {}
    const scope = { document: {}, navigator: { modelContext: navMc } }
    expect(getModelContext(scope)).toBe(navMc)
  })

  it('returns null when WebMCP is unavailable', () => {
    expect(getModelContext({ document: {}, navigator: {} })).toBeNull()
    expect(getModelContext({})).toBeNull()
  })
})

describe('injectOriginTrialToken', () => {
  it('appends an origin-trial meta tag to head', () => {
    const appended = []
    const doc = {
      createElement: () => ({}),
      head: { appendChild: (el) => appended.push(el) },
    }
    const meta = injectOriginTrialToken('TOKEN123', doc)
    expect(meta.httpEquiv).toBe('origin-trial')
    expect(meta.content).toBe('TOKEN123')
    expect(appended).toEqual([meta])
  })
})

describe('toWebMcpTool', () => {
  const serverTool = {
    name: 'applications',
    description: 'Pipeline facade',
    inputSchema: { type: 'object', properties: { action: { type: 'string' } } },
  }

  it('carries name, description, and the server inputSchema verbatim', () => {
    const tool = toWebMcpTool(serverTool)
    expect(tool.name).toBe('applications')
    expect(tool.description).toBe('Pipeline facade')
    expect(tool.inputSchema).toBe(serverTool.inputSchema)
  })

  it('execute proxies to tools/call and passes a content result through', async () => {
    const result = { content: [{ type: 'text', text: 'ok' }] }
    callTool.mockResolvedValue(result)
    const out = await toWebMcpTool(serverTool).execute({ action: 'status' })
    expect(callTool).toHaveBeenCalledWith('applications', { action: 'status' })
    expect(out).toBe(result)
  })

  it('execute wraps a content-less result as text', async () => {
    callTool.mockResolvedValue({ weird: true })
    const out = await toWebMcpTool(serverTool).execute()
    expect(out.content[0].type).toBe('text')
    expect(out.content[0].text).toContain('weird')
  })

  it('defaults a missing schema to an empty object schema', () => {
    const tool = toWebMcpTool({ name: 'bare' })
    expect(tool.inputSchema).toEqual({ type: 'object', properties: {} })
    expect(tool.description).toBe('')
  })
})

describe('registerJobContextTools', () => {
  function fakeModelContext() {
    return {
      registered: [],
      registerTool(def, opts) {
        this.registered.push({ def, opts })
      },
      unregisterTool: vi.fn(),
    }
  }

  it('registers every server tool with an abort signal', async () => {
    listTools.mockResolvedValue([{ name: 'a' }, { name: 'b' }])
    const mc = fakeModelContext()
    const reg = await registerJobContextTools(mc)
    expect(reg.names).toEqual(['a', 'b'])
    expect(mc.registered).toHaveLength(2)
    for (const { opts } of mc.registered) {
      expect(opts.signal).toBeInstanceOf(AbortSignal)
      expect(opts.signal.aborted).toBe(false)
    }
  })

  it('one failed registration does not stop the rest', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    listTools.mockResolvedValue([{ name: 'bad' }, { name: 'good' }])
    const mc = fakeModelContext()
    mc.registerTool = vi.fn((def, opts) => {
      if (def.name === 'bad') throw new Error('nope')
      mc.registered.push({ def, opts })
    })
    const reg = await registerJobContextTools(mc)
    expect(reg.names).toEqual(['good'])
  })

  it('unregister aborts the signal and falls back to unregisterTool', async () => {
    listTools.mockResolvedValue([{ name: 'a' }])
    const mc = fakeModelContext()
    const reg = await registerJobContextTools(mc)
    reg.unregister()
    expect(mc.registered[0].opts.signal.aborted).toBe(true)
    expect(mc.unregisterTool).toHaveBeenCalledWith('a')
  })

  it('unregister survives a modelContext without unregisterTool', async () => {
    listTools.mockResolvedValue([{ name: 'a' }])
    const mc = fakeModelContext()
    delete mc.unregisterTool
    const reg = await registerJobContextTools(mc)
    expect(() => reg.unregister()).not.toThrow()
  })
})
