// WebMCP bridge: republish the server's MCP tools as in-page WebMCP tools.
//
// WebMCP (W3C Web Machine Learning CG draft) lets a page register tools that
// in-browser agents — ChatGPT desktop's browser, Chrome's origin trial, Edge
// preview — can call while the user is on the site. The definitions come
// straight from the server's tools/list, so the browser surface can never
// drift from the MCP surface: the facade-coverage test guards the schemas,
// and this bridge inherits them verbatim.

import { listTools, callTool, getInstructions } from './mcpClient.js'

/**
 * Feature-detect the WebMCP registration root. The spec moved the getter
 * from navigator.modelContext to document.modelContext (Chrome 150 keeps the
 * old name as a deprecated alias), so probe both, newest first.
 */
export function getModelContext(scope = globalThis) {
  return scope.document?.modelContext || scope.navigator?.modelContext || null
}

/**
 * Chrome gates WebMCP behind an origin trial (149–156); the token is issued
 * per-origin at developers.chrome.com/origintrials and injected here at
 * runtime, before feature detection. Baked in at build time via
 * VITE_WEBMCP_OT_TOKEN (Dockerfile arg of the same name). ChatGPT's built-in
 * browser and Edge don't use Chrome's trial infrastructure, so absence of a
 * token only affects plain Chrome.
 */
export function injectOriginTrialToken(token, doc = document) {
  const meta = doc.createElement('meta')
  meta.httpEquiv = 'origin-trial'
  meta.content = token
  doc.head.appendChild(meta)
  return meta
}

/** Map one MCP tool descriptor to a WebMCP tool whose execute() proxies to /mcp. */
export function toWebMcpTool(tool) {
  return {
    name: tool.name,
    description: tool.description || '',
    inputSchema: tool.inputSchema || { type: 'object', properties: {} },
    async execute(input) {
      const result = await callTool(tool.name, input || {})
      // MCP CallToolResult and WebMCP's expected return share the same
      // {content: [...], isError?} shape — pass it through untouched. Wrap
      // only a result that carries no content array (defensive; the
      // consolidated facades always return text content).
      if (result && Array.isArray(result.content)) return result
      return { content: [{ type: 'text', text: JSON.stringify(result ?? null) }] }
    },
  }
}

/**
 * Hand the server's instructions to implementations that accept page-level
 * context. WebMCP's provideContext has carried two meanings across drafts:
 * an instructions channel alongside registered tools, and a full-context
 * REPLACEMENT call whose tools array becomes the whole surface. Passing the
 * same tool definitions with the instructions is correct under both
 * readings — replacement semantics get an identical surface back,
 * instruction semantics ignore the extra field. Absence of the method or a
 * throw is fine: the tool surface registered above stands on its own, and
 * the same contract also rides in tool results (generate's untracked-
 * application nudge), which every client acts on.
 */
export function provideInstructions(modelContext, instructions, tools) {
  if (!instructions || typeof modelContext?.provideContext !== 'function') return false
  try {
    modelContext.provideContext({ description: instructions, tools })
    return true
  } catch (err) {
    console.warn('[webmcp] provideContext failed:', err)
    return false
  }
}

/**
 * Fetch the server's tool list and register every tool with the given
 * modelContext. Returns { names, unregister }; call unregister() when the
 * session ends so a signed-out page stops advertising tools it can no
 * longer execute.
 */
export async function registerJobContextTools(modelContext) {
  const tools = await listTools()
  const controller = new AbortController()
  const names = []
  const defs = []
  for (const tool of tools) {
    const def = toWebMcpTool(tool)
    try {
      modelContext.registerTool(def, { signal: controller.signal })
      names.push(def.name)
      defs.push(def)
    } catch (err) {
      // One bad registration must not take down the rest of the surface.
      console.warn(`[webmcp] failed to register tool ${def.name}:`, err)
    }
  }
  // Server instructions reach MCP clients at connection time but WebMCP
  // agents never see them — deliver them through provideContext where the
  // implementation offers one. Best-effort: a failure to brief must not
  // fail the registration that already succeeded.
  try {
    const instructions = await getInstructions()
    provideInstructions(modelContext, instructions, defs)
  } catch (err) {
    console.warn('[webmcp] failed to fetch server instructions:', err)
  }
  return {
    names,
    unregister() {
      // Spec-current implementations unregister via the AbortSignal; older
      // ones (and the alias era) only have unregisterTool(name). Do both —
      // double-unregistration is a no-op we swallow.
      controller.abort()
      if (typeof modelContext.unregisterTool === 'function') {
        for (const name of names) {
          try {
            modelContext.unregisterTool(name)
          } catch {
            // already gone via the signal — fine
          }
        }
      }
    },
  }
}
