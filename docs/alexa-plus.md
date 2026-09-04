# Alexa+ add-on integration

Alexa+ connects to self-hosted MCP servers via its MCP Toolkit
(spec ≥ 2025-11-25, Streamable HTTP — both already true of this server).
This doc covers what's server-side vs. what's done in Amazon's tooling.

## Server side (this repo)

- **Auth**: Alexa+ speaks OAuth 2.1 + PKCE (S256) only, and does NOT support
  the Dynamic Client Registration our Entra proxy relies on. Alexa therefore
  rides the **connector key bridge** (`transport/http/routes/oauth.py`) — the
  same code flow ChatGPT uses: consent page on the jc_session cookie, one-time
  code, exchanged for a non-expiring `jcmcp_` key (the same trade the mobile
  app made 2026-07-17). The key shows on the dashboard's API Keys tab as
  "Alexa+ connector".
- **Callback allowlist**: the bridge ships with Alexa's regional
  account-linking prefixes (pitangui / layla / alexa.amazon.co.jp
  `/api/skill/link/`). If Alexa+ onboarding surfaces a different callback
  shape, extend without a deploy via `KEYBRIDGE_REDIRECT_URIS`
  (comma-separated; trailing `*` = prefix rule). Keys minted for
  override-admitted callbacks get the generic "MCP connector" label.
- **Discovery**: a credential-less 401 now carries
  `resource_metadata="…/.well-known/oauth-protected-resource"` (RFC 9728 §5.1)
  so Alexa's probe walks itself to the PRM. Header presence semantics are
  unchanged — can't-verify is still 503, never 401
  (docs/connector-resilience.md).
- **Latency**: Alexa+ cuts tool calls off at ~500ms round-trip. Long work must
  go through the durable submit-and-poll actions; `insights.briefing` exists
  specifically as a fast, speakable (plain-prose, no markdown) summary for
  voice surfaces.

## Amazon side (one-time, not in this repo)

1. Amazon developer account → install the Alexa AI CLI → `alexa-ai configure`
   (Login with Amazon).
2. `alexa-ai new mcp --name "jobContext" --locale en-US \
      --mcp-server-url "https://app.jobcontext.ai/mcp"`
3. Fill `addon-package/addon.json` (descriptions, 3–4 example phrases,
   privacy/terms URLs, icons in 6 sizes, one 600×900 carousel image).
4. `alexa-ai deploy` → add-on reaches *development stage*; test in the web
   simulator or on a physical Echo signed into the developer account.
5. `alexa-ai submit` only for public certification — not needed for testing.

Console: developer.amazon.com/alexa/console/ask/addons
Docs: developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html
