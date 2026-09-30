# Alexa+ add-on integration

Alexa+ connects to self-hosted MCP servers via its MCP Toolkit
(spec ≥ 2025-11-25, Streamable HTTP — both already true of this server).
This doc covers what's server-side vs. what's done in Amazon's tooling.

For the classic skill's briefing, pipeline and interview views, Echo Show
visuals, and the review of all MCP domains, see [the Alexa roadmap](alexa-roadmap.md).

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
- **Discovery (native add-on compatibility unresolved)**: the server adds
  `resource_metadata="…/.well-known/oauth-protected-resource"` to its
  `WWW-Authenticate` challenge. Amazon's current MCP quickstart lists that
  header as unsupported. Do not treat #361 as verified Alexa+ onboarding;
  validate discovery with the actual toolkit before changing shared auth
  behavior. This does not affect the classic `/alexa` webhook.
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

## Classic custom skill (development setup)

Classic skills stay self-serve. Development testing requires the developer
account on the device and Alexa app, a built interaction model in the device's
locale, and testing enabled in the console. Verify invocation in the simulator
and on the target device; these server changes do not establish Alexa+
availability or create a native Alexa+ add-on.
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

The URLs below target **QA**, where #361–363 are merged. Keep the webhook
and both OAuth URLs in the same environment. Use production only after the
QA promotion has deployed successfully; switching environments requires
relinking because keys and workspace data belong to that environment.

1. **Custom** model, **Provision your own** hosting, any template (the model
   is replaced next step).
2. Interaction model: invocation name `job context`; one custom intent
   `BriefingIntent` with samples like "my briefing", "what's my job search
   looking like", "give me the update" (built-ins Stop/Cancel/Help/Fallback
   are handled server-side). Build the model.
3. Endpoint: **HTTPS**, `https://qa.jobcontext.ai/alexa`, certificate type
   *"trusted by a certificate authority"*.
4. Account linking: **Auth Code Grant**.
   - Authorization URI `https://qa.jobcontext.ai/oauth/authorize`
   - Access Token URI `https://qa.jobcontext.ai/oauth/token`
   - Client ID/Secret: any non-empty values (the bridge identifies clients
     by callback prefix, not client_id, and checks PKCE instead of the
     secret) — auth scheme *"Credentials in request body"*.
   - **Enable PKCE** (the bridge 400s without it; S256 is Alexa's only
     method, which is also the only one the bridge accepts).
5. Test tab → set skill testing to **Development**. On the phone's Alexa
   app: More → Skills & Games → Your Skills → Dev → enable + Link Account
   (goes through the bridge consent page → dashboard login).
6. On the Echo: "Alexa, launch the job context skill." This phrase returned
   a linked-account briefing in the simulator. Both `open job context` and
   `ask job context for my briefing` have also received general conversational
   responses instead of reaching the webhook; check logs before blaming auth.

### Diagnose before changing the webhook

1. In the console's Development simulator, select the built locale and enter
   `launch the job context skill`. Record the UTC time and simulator response.
2. Correlate that attempt with ingress `/alexa` traffic and application logs.
   No matching request means the failure is before this handler: check skill
   activation, account, locale, endpoint, and Amazon-side availability.
3. A matching 400 means request verification failed; inspect the rejection
   reason. Never disable signature verification to accommodate an unsigned
   probe. A 200 with a LinkAccount card means invocation works and linking
   is the next step. A spoken briefing completes the backend path.
4. Repeat on the Echo. Simulator success alone does not establish device
   availability. Compare account and locale if only the device fails.

**Observed 2026-09-05:** the retained ingress entries for 02:27, 02:41,
16:50, and 17:00 UTC were all `curl/8.18.0` requests. In particular, the
02:41 request cited in #363 is not evidence of an Alexa-originated call.
The 17:00 rejection also reports a two-byte body. These probes do not prove
Alexa+ omits signing headers.

**Verified later that day (18:34:36 UTC):** the Development simulator's
`ask job context for my briefing` request reached QA and returned HTTP 200
in 118 ms, with the skill's account-linking speech and card. The deployed
signature/certificate/timestamp verifier accepted the request unchanged.
`open job context` had received a general conversational clarification
instead. Account linking and a successful briefing on the physical Echo
remained to be verified at that point; this does not establish native Alexa+
add-on access.

**Linked-account verification (18:44:28 UTC):** after the phone completed
OAuth (token exchange HTTP 200), the simulator answered `ask job context
for my briefing` with an account-linking suggestion without calling `/alexa`.
`launch the job context skill` then returned the actual QA pipeline briefing
with HTTP 200 in 34 ms. No backend auth changes were necessary. Physical
Echo invocation remains a separate check; simulator speech is not proof of
device playback.

`/alexa` requests surface in metrics as `alexa_requests_total`
(result: ok / unlinked / rejected / stop / help / session_ended).
