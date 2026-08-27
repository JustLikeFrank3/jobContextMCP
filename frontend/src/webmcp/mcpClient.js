// Minimal MCP Streamable-HTTP client for the SPA's own /mcp endpoint.
//
// This only works because the server runs stateless (server.py,
// MCP_STATELESS_HTTP): every POST is a self-contained JSON-RPC exchange with
// no initialize handshake and no Mcp-Session-Id to carry between calls. If
// the server ever moves back to session mode this client needs the full
// initialize/initialized dance plus session-id plumbing — don't bolt that on
// here, revisit the design (see docs/webmcp.md).
//
// Auth rides the same jc_session cookie as every other dashboard call
// (credentials: 'same-origin'), so there is nothing to attach manually.

export class McpError extends Error {
  constructor(message, { status, code } = {}) {
    super(message)
    this.name = 'McpError'
    this.status = status
    this.code = code
  }
}

let _requestId = 0

/**
 * Pull the JSON-RPC response with the given id out of a Streamable-HTTP POST
 * response body. The transport answers either as plain JSON or as an SSE
 * stream (`text/event-stream`) whose events each carry one JSON message in
 * `data:` lines; notifications and unrelated messages are skipped.
 */
export function extractResponse(contentType, bodyText, id) {
  if ((contentType || '').includes('text/event-stream')) {
    for (const chunk of bodyText.split(/\r?\n\r?\n/)) {
      const dataLines = chunk
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
      if (!dataLines.length) continue
      let message
      try {
        message = JSON.parse(dataLines.join('\n'))
      } catch {
        continue
      }
      if (message && message.id === id && ('result' in message || 'error' in message)) {
        return message
      }
    }
    throw new McpError(`No JSON-RPC response for request ${id} in event stream`)
  }
  return JSON.parse(bodyText)
}

/**
 * Send one JSON-RPC request to /mcp and return its `result`.
 *
 * Throws McpError on transport failures (status set) and on JSON-RPC error
 * responses (code set). A 401 gets a person-readable message because it
 * surfaces through the in-browser agent to the user.
 */
export async function mcpRequest(method, params = {}, { fetchImpl } = {}) {
  const doFetch = fetchImpl || fetch
  const id = ++_requestId
  const res = await doFetch('/mcp', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      // The Streamable-HTTP transport rejects POSTs whose Accept does not
      // offer BOTH representations, whichever one it ends up sending.
      Accept: 'application/json, text/event-stream',
      'MCP-Protocol-Version': '2025-06-18',
    },
    body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
  })

  if (res.status === 401) {
    throw new McpError(
      'jobContext session expired — sign in to the dashboard again, then retry.',
      { status: 401 },
    )
  }
  if (!res.ok) {
    throw new McpError(`MCP request failed (${res.status})`, { status: res.status })
  }

  const message = extractResponse(res.headers.get('content-type'), await res.text(), id)
  if (message.error) {
    throw new McpError(
      `MCP error ${message.error.code}: ${message.error.message}`,
      { code: message.error.code },
    )
  }
  return message.result
}

/** List every tool the server offers, following pagination cursors. */
export async function listTools(options) {
  const tools = []
  let cursor
  do {
    const result = await mcpRequest('tools/list', cursor ? { cursor } : {}, options)
    tools.push(...(result.tools || []))
    cursor = result.nextCursor
  } while (cursor)
  return tools
}

/** Invoke one tool and return the MCP CallToolResult. */
export function callTool(name, args, options) {
  return mcpRequest('tools/call', { name, arguments: args || {} }, options)
}
