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

## Troubleshooting: "can't connect" with nothing in the server log

Seen 2026-10-09 from an employer (Accenture) tenant. OAuth (Dynamic
discovery), OAuth (Dynamic) and API key auth all failed with the same
generic "can't connect" message, which gave no detail. Meanwhile the same
`jcmcp_` key worked from curl:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://app.jobcontext.ai/mcp \
  -H "Authorization: $KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
# → 200
```

Run `kubectl logs deploy/jcmcp -n jcmcp --since=3m | grep /mcp` right after
clicking **Add**. In this case it showed **no requests** from Copilot Studio,
while the curl above appeared immediately. That means the connection is
refused inside Power Platform before any traffic leaves the tenant. The
usual cause is the tenant's data (DLP) policy blocking custom or MCP
connectors, or allowing only approved endpoints. Nothing on the jobContext
side (server, key, bridge) can fix it.

What to do:
- Check whether the agent lives in a managed or default environment. If the
  tenant allows it, retry from a Power Platform **developer environment**
  to confirm a policy block.
- Otherwise, only a tenant Power Platform admin can allow the connector.
  For a personal job-search workspace, it's usually better to use that
  workspace from Claude.ai or ChatGPT on a personal account instead.
- Revoke any API key minted for the failed connection.

Copilot Studio's "MCP client" channel (preview) runs the other direction. It
exposes a Copilot Studio agent *as* an MCP server for outside clients, and it
needs an app registration in the employer's tenant, so it doesn't get around
the block.
