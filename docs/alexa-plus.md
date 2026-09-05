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

> **Access reality (2026-09-04):** the Alexa AI CLI lives in a private
> CodeArtifact registry (`npm install -g @alexa-ai/cli` after
> `aws codeartifact login … --domain alexa-ai --domain-owner 372468808636`)
> that only admits AWS accounts allowlisted by an Alexa Solutions Architect.
> There is no self-serve signup, and the Build/Ship/Shape hackathon does NOT
> grant it — organizers confirmed participants should *simulate* the Alexa+
> interaction layer over a real MCP backend. Until Amazon opens the preview,
> the way onto real Echo hardware is the **classic custom skill** below.

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

## Classic custom skill (works on a real Echo today)

Classic skills stay self-serve: a *development-stage* skill runs on any Echo
signed into the developer account, no certification, no preview access.
Server side is `transport/http/routes/alexa.py` — a public `/alexa` webhook
that proves Alexa origin itself (SignatureCertChainUrl pinning, cert-chain
trust + `echo-api.amazon.com` SAN, RSA signature over the raw body, ±150s
timestamp) before resolving the account-linked `jcmcp_` key and speaking
`insights.briefing` from that user's partition.

Account linking rides the connector key bridge unchanged — Alexa's
account-linking PKCE (S256, console toggle) satisfies the bridge's PKCE
requirement, and the pitangui/layla/alexa.amazon.co.jp callbacks are already
in the allowlist. The linked token is a non-expiring `jcmcp_` key labeled
"Alexa+ connector" on the dashboard's API Keys tab.

Console setup (developer.amazon.com/alexa/console/ask → Create Skill):

1. **Custom** model, **Provision your own** hosting, any template (the model
   is replaced next step).
2. Interaction model: invocation name `job context`; one custom intent
   `BriefingIntent` with samples like "my briefing", "what's my job search
   looking like", "give me the update" (built-ins Stop/Cancel/Help/Fallback
   are handled server-side). Build the model.
3. Endpoint: **HTTPS**, `https://app.jobcontext.ai/alexa`, certificate type
   *"trusted by a certificate authority"*.
4. Account linking: **Auth Code Grant**.
   - Authorization URI `https://app.jobcontext.ai/oauth/authorize`
   - Access Token URI `https://app.jobcontext.ai/oauth/token`
   - Client ID/Secret: any non-empty values (the bridge identifies clients
     by callback prefix, not client_id, and checks PKCE instead of the
     secret) — auth scheme *"Credentials in request body"*.
   - **Enable PKCE** (the bridge 400s without it; S256 is Alexa's only
     method, which is also the only one the bridge accepts).
5. Test tab → set skill testing to **Development**. On the phone's Alexa
   app: More → Skills & Games → Your Skills → Dev → enable + Link Account
   (goes through the bridge consent page → dashboard login).
6. On the Echo: "Alexa, open job context."

During a prod freeze, substitute `qa.jobcontext.ai` for `app.jobcontext.ai`
in the endpoint and both account-linking URIs — dev-stage skills are
per-account, so pointing one at qa affects nobody. Note the linked key and
the briefing's data both live in that environment's partition (qa's data is
not prod's), and switching hosts later means updating the three URIs and
relinking the account.

Caveat: Echos migrated to Alexa+ early access have reported flaky custom
skill invocation; opting the device out of early access restores classic
behavior. `/alexa` requests surface in metrics as `alexa_requests_total`
(result: ok / unlinked / rejected / stop / help / session_ended).
