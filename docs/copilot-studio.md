# Microsoft 365 Copilot (Copilot Studio) integration

M365 Copilot reaches MCP servers through a **Copilot Studio agent**: the
agent gets an MCP tool (Streamable HTTP, already what `/mcp` speaks), and the
agent is published to the Teams + Microsoft 365 Copilot channel. Copilot
Studio runs each MCP tool as a Power Platform connector, and the connector
owns the OAuth flow.

## Server side (this repo)

- **Auth: the connector key bridge.** Every Power Platform connector's OAuth
  callback lands on the shared consent host
  `https://global.consent.azure-apim.net/redirect`, either bare or followed by
  `/<connector id>`. That callback is not registered on our Entra app, so the
  Entra proxy path would fail with AADSTS50011. The bridge
  (`transport/http/routes/oauth.py`) admits it instead. This is the same code
  flow ChatGPT and Alexa+ use:
  1. A consent page authenticates you with the jc_session cookie.
  2. It issues a one-time code.
  3. The code is exchanged for a non-expiring `jcmcp_` key.

  The key appears on the dashboard's API Keys tab as **"Copilot Studio
  connector"** and you revoke it there.
- **The workspace is chosen by whoever approves the consent page.** The key
  is bound to the partition of the dashboard session that clicked Approve. If
  you sign into jobcontext.ai as a different identity, such as a B2B guest
  for an employer-tenant workspace, you get that identity's isolated
  partition.
- **PKCE (S256) is required.** "Dynamic discovery" registers through
  `/oauth/register`, which advertises a public client with
  `token_endpoint_auth_method: none`, so the connector has to send a code
  challenge. If the consent step returns
  `400 PKCE with S256 is required`, the connector is not sending one. The
  bridge has no client-secret mode.
- **Sovereign clouds.** Only the commercial consent host
  (`global.consent.azure-apim.net`) is listed. To add GCC High or other
  consent hosts, use `KEYBRIDGE_REDIRECT_URIS`. Note that the override
  *replaces* the built-in list, so include the defaults you still want.

## Copilot Studio side (one-time)

1. Go to copilotstudio.microsoft.com and choose **Create agent**. Then open
   **Tools → Add a tool → New tool → Model Context Protocol**.
2. Set **Server URL** to `https://jobcontext.ai/mcp`.
3. Set **Authentication** to **OAuth 2.0**, then choose **Dynamic discovery**.
   If that option is missing because the wizard hasn't rolled out to your
   tenant, choose **Manual** and fill in:
   - Authorization URL: `https://jobcontext.ai/oauth/authorize`
   - Token URL (and refresh URL): `https://jobcontext.ai/oauth/token`
   - Client ID: any non-empty value. The bridge ignores it.
   - Client secret: leave blank if allowed. Otherwise use any placeholder;
     the bridge ignores it too.
   - Scope: leave blank.
4. Click **Create**, then **Create connection**. A browser window opens the
   jobContext consent page. Sign in as the identity whose workspace this
   agent should see, then click **Approve**.
5. Publish the agent to the **Teams and Microsoft 365 Copilot** channel.

### Employer-tenant caveats

- Your tenant's admins can audit everything the agent reads and sends. Point
  it at a workspace that holds only what you'd be comfortable with them
  seeing.
- Power Platform DLP policies can block custom or MCP connectors.
  Publishing to M365 Copilot may also need admin approval.
- The issued key never expires. Revoke it from the API Keys tab when you're
  done with the agent.
