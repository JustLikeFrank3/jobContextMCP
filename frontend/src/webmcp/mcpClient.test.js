import { describe, it, expect } from 'vitest'
import { extractResponse, mcpRequest, listTools, callTool, McpError } from './mcpClient.js'

// ── extractResponse ──────────────────────────────────────────────────────────

describe('extractResponse', () => {
  it('parses a plain JSON response', () => {
    const msg = extractResponse('application/json', '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}', 1)
    expect(msg.result.ok).toBe(true)
  })

  it('pulls the matching message out of an SSE body', () => {
    const body = 'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n\n'
    const msg = extractResponse('text/event-stream', body, 7)
    expect(msg.result.tools).toEqual([])
  })

  it('handles CRLF line endings', () => {
    const body = 'data: {"jsonrpc":"2.0","id":3,"result":{}}\r\n\r\n'
    expect(extractResponse('text/event-stream; charset=utf-8', body, 3).id).toBe(3)
  })

  it('skips notifications and non-matching ids before the response', () => {
    const body = [
      'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}',
      '',
      ': keepalive comment',
      '',
      'data: {"jsonrpc":"2.0","id":9,"result":{"content":[]}}',
      '',
    ].join('\n')
    const msg = extractResponse('text/event-stream', body, 9)
    expect(msg.result.content).toEqual([])
  })

  it('joins multi-line data fields per the SSE spec', () => {
    const body = 'data: {"jsonrpc":"2.0","id":2,\ndata: "result":{"a":1}}\n\n'
    expect(extractResponse('text/event-stream', body, 2).result.a).toBe(1)
  })

  it('throws when no message matches the request id', () => {
    const body = 'data: {"jsonrpc":"2.0","id":999,"result":{}}\n\n'
    expect(() => extractResponse('text/event-stream', body, 1)).toThrow(McpError)
  })
})

// ── fetch-level behavior (mock fetchImpl echoes the request id) ──────────────

function jsonFetch(makeResult, { status = 200, capture } = {}) {
  return async (url, options) => {
    if (capture) capture.push({ url, options })
    const req = JSON.parse(options.body)
    const payload = makeResult(req)
    return {
      status,
      ok: status >= 200 && status < 300,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ jsonrpc: '2.0', id: req.id, ...payload }),
    }
  }
}

describe('mcpRequest', () => {
  it('POSTs a same-origin JSON-RPC request with both Accept types', async () => {
    const capture = []
    await mcpRequest('tools/list', {}, { fetchImpl: jsonFetch(() => ({ result: {} }), { capture }) })
    const { url, options } = capture[0]
    expect(url).toBe('/mcp')
    expect(options.method).toBe('POST')
    expect(options.credentials).toBe('same-origin')
    expect(options.headers.Accept).toContain('application/json')
    expect(options.headers.Accept).toContain('text/event-stream')
    const body = JSON.parse(options.body)
    expect(body.method).toBe('tools/list')
    expect(body.jsonrpc).toBe('2.0')
  })

  it('returns the result of a successful call', async () => {
    const result = await mcpRequest('tools/call', { name: 'x' }, {
      fetchImpl: jsonFetch(() => ({ result: { content: [{ type: 'text', text: 'hi' }] } })),
    })
    expect(result.content[0].text).toBe('hi')
  })

  it('throws a person-readable error on 401', async () => {
    const fetchImpl = async () => ({ status: 401, ok: false, headers: { get: () => '' }, text: async () => '' })
    await expect(mcpRequest('tools/list', {}, { fetchImpl })).rejects.toThrow(/sign in/)
  })

  it('throws on a JSON-RPC error response', async () => {
    const fetchImpl = jsonFetch(() => ({ error: { code: -32602, message: 'bad params' } }))
    await expect(mcpRequest('tools/call', {}, { fetchImpl })).rejects.toThrow(/bad params/)
  })

  it('throws on non-2xx transport status', async () => {
    const fetchImpl = async () => ({ status: 503, ok: false, headers: { get: () => '' }, text: async () => '' })
    await expect(mcpRequest('tools/list', {}, { fetchImpl })).rejects.toThrow(/503/)
  })
})

describe('listTools', () => {
  it('follows nextCursor pagination to collect every page', async () => {
    const fetchImpl = jsonFetch((req) =>
      req.params.cursor
        ? { result: { tools: [{ name: 'b' }] } }
        : { result: { tools: [{ name: 'a' }], nextCursor: 'page2' } })
    const tools = await listTools({ fetchImpl })
    expect(tools.map((t) => t.name)).toEqual(['a', 'b'])
  })
})

describe('callTool', () => {
  it('sends name and arguments under tools/call', async () => {
    const capture = []
    await callTool('applications', { action: 'status' }, {
      fetchImpl: jsonFetch(() => ({ result: { content: [] } }), { capture }),
    })
    const body = JSON.parse(capture[0].options.body)
    expect(body.method).toBe('tools/call')
    expect(body.params).toEqual({ name: 'applications', arguments: { action: 'status' } })
  })
})
