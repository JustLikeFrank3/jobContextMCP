# WebMCP bridge — the dashboard as an agent-usable surface

The cloud dashboard registers the server's MCP tools as in-page **WebMCP**
tools (`document.modelContext`, W3C Web Machine Learning CG draft), so
in-browser agents — ChatGPT desktop's built-in browser, Chrome's origin
trial (149–156), Edge preview — can drive jobContext while the user is on
the site.

## How it works

```
in-browser agent ──▶ document.modelContext tool call
                        │  (frontend/src/webmcp/bridge.js)
                        ▼
                same-origin fetch POST /mcp  (jc_session cookie)
                        │  JSON-RPC tools/call, stateless Streamable HTTP
                        ▼
                the exact same 12 consolidated facades every MCP client gets
```

- **No second tool surface.** `frontend/src/webmcp/WebMcpBridge.jsx` waits for
  the session probe (`AuthContext`), then fetches `tools/list` from `/mcp` and
  registers each tool verbatim — names, descriptions, and FastMCP-generated
  input schemas. The facade-coverage test remains the single guard on the
  schema surface; the bridge can't drift because it holds no copies.
- **No new auth.** `UserDataContextMiddleware` already accepts the
  `jc_session` cookie on `/mcp`, so the bridge's same-origin fetches
  authenticate as the signed-in user with zero token plumbing.
- **Stateless is load-bearing.** Each bridge call is one self-contained
  JSON-RPC POST (`frontend/src/webmcp/mcpClient.js`) with no initialize
  handshake and no `Mcp-Session-Id` — legal only because the transport runs
  `stateless_http` (server.py). If session mode ever returns, the client
  needs the full handshake; don't patch it in quietly.

## Security model

An in-page agent acts **as the signed-in user, inside their session** — the
same trust boundary as the user driving the dashboard by hand, and the same
one a ChatGPT/Claude connector gets via OAuth. What WebMCP made load-bearing
is the cookie: it's an ambient credential, and `/mcp` executes side-effecting
tools on a bare POST with no CORS preflight in the way. The middleware
therefore **ignores `jc_session` on cross-site `/mcp` requests**
(`_is_cross_site_browser_request`, transport/http/app.py; tests in
tests/test_webmcp_csrf.py): `Sec-Fetch-Site` is the authority, `Origin` vs
`Host` the fallback, and header-less non-browser clients pass because they
can't be CSRF'd. Bearer credentials are never touched.

All 12 facades are exposed, deliberately: filtering the browser surface below
what the user's own session can already do adds a maintenance seam without a
trust boundary. Revisit if a facade ever grows an action the user themselves
can't trigger from the dashboard.

## Browser enablement

| Consumer | Needs |
|---|---|
| ChatGPT desktop built-in browser | Nothing — ships WebMCP support. User signs into jobcontext.ai inside it once. |
| Chrome 149–156 | Origin-trial token for the origin, from developers.chrome.com/origintrials. |
| Edge preview | User flips the flag; no token. |

The Chrome token is baked at image build: `--build-arg VITE_WEBMCP_OT_TOKEN=…`
(Dockerfile → Vite env → injected as an `origin-trial` meta tag at runtime by
`injectOriginTrialToken`). Register one token per origin served
(jobcontext.ai, app.jobcontext.ai). Without a token nothing breaks — plain
Chrome just doesn't expose `modelContext`.

The spec is young and still moving (March 2026 removed `provideContext`;
Chrome 150 moved the getter from `navigator` to `document`, alias kept). The
bridge feature-detects both roots and treats registration failure as
non-fatal, so spec drift degrades to "no tools", never a broken dashboard.

## Local dev

`vite dev` proxies `/mcp` to `localhost:8000` like the other API routes.
Chromium sends `Sec-Fetch-Site: same-origin` computed against the page origin
(the proxy), so the CSRF guard passes in dev; the `Origin`-header fallback
path would not, which only matters for browsers old enough to lack
`Sec-Fetch-Site`.
