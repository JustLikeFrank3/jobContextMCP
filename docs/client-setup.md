# JobContextMCP — Client Setup Guide

How to connect any MCP-compatible AI client to JobContextMCP, whether you're running the server locally on your own machine or connecting to a shared AKS-hosted instance that requires Entra ID login.

---

## Quick-reference

| Client | Local stdio | AKS HTTP (Entra auth) |
|--------|-------------|----------------------|
| VS Code + GitHub Copilot | ✅ `.vscode/mcp.json` (already committed) | ✅ HTTP entry in `.vscode/mcp.json` + port-forward |
| Claude Desktop | ✅ `claude_desktop_config.json` | ✅ remote HTTP with session cookie |
| ChatGPT desktop | ❌ no stdio support | ✅ HTTP MCP (ChatGPT desktop app ≥ v1.2025) |
| Cursor | ✅ `.cursor/mcp.json` | ✅ HTTP entry |
| Windsurf | ✅ `~/.codeium/windsurf/mcp_config.json` | ✅ HTTP entry |

---

## Prerequisites

### Local mode

- Python 3.12 + virtual environment set up (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`)
- `config.json` created via `setup_workspace()` or copied from `config.example.json`
- (Optional) Docker Desktop if using `MCP_MODE=docker`

See the main [README.md](../README.md#setup) for full local setup steps.

### AKS mode

- `kubectl` installed and configured (`az aks get-credentials --resource-group jcmcp-rg --name jcmcp-aks`)
- AKS pod running: `kubectl get pods -n jcmcp` → `2/2 Running`
- A valid Entra ID account (Microsoft personal account, work account, or a B2B guest invitation accepted from the service owner)
- Port-forward active (see below)

---

## Part 1 — VS Code + GitHub Copilot

### 1a. Local stdio (recommended for development)

The workspace-scoped `.vscode/mcp.json` is already committed. It points at `scripts/run_mcp.sh` which reads `MCP_MODE` from `.env` and dispatches to local Python or Docker.

**Switch to local mode** (fastest iteration):

```dotenv
# .env
MCP_MODE=local
```

Reload: **Command Palette → MCP: List Servers → restart jobContextMCP**

You should see `Discovered N tools` within ~0.5s in the Output panel.

> **Do not** use the VS Code "Add MCP Server" UI plug icon. It writes a broken global entry to `~/Library/Application Support/Code/User/mcp.json` that conflicts with this workspace config.

**Switch to Docker mode:**

```dotenv
# .env
MCP_MODE=docker
```

Requires `docker compose build` after any code change.

---

### 1b. AKS HTTP (connect to the live cloud instance)

#### Step 1 — Start the port-forward

Run the built-in VS Code task:

**Command Palette → Tasks: Run Task → AKS port-forward**

Or in a terminal:

```bash
kubectl port-forward svc/jcmcp 8099:80 -n jcmcp
```

Keep this terminal open. The tunnel is local-only; nothing is exposed on the internet.

#### Step 2 — Verify the pod is healthy

```bash
kubectl get pods -n jcmcp
# NAME                     READY   STATUS    RESTARTS   AGE
# jcmcp-xxxxxxxxx-xxxxx    2/2     Running   0          ...

curl http://localhost:8099/health
# {"status":"ok","service":"jobContextMCP",...}
```

#### Step 3 — Configure VS Code

Edit (or create) `.vscode/mcp.json` in the project root:

```jsonc
{
  "servers": {
    "jobContextMCP-aks": {
      "type": "http",
      "url": "http://localhost:8099/mcp"
    }
  }
}
```

> The committed `.vscode/mcp.json` already has a `jobContextMCP-aks` entry. You can keep both the local and AKS entries — VS Code lets you pick which server to use per session.

Reload: **Command Palette → MCP: List Servers → restart jobContextMCP-aks**

#### Step 4 — Dashboard access (Entra auth)

MCP tool calls over `/mcp` work without browser auth. To use the web dashboard:

1. Open `http://localhost:8099/` in a browser.
2. Click **Sign in** — you'll be redirected to Microsoft's login page.
3. Sign in with your Microsoft account (tenant user or accepted guest invite).
4. After login you'll land on the dashboard. A **Sign out** button appears in the header of every page.

> **First login for guests:** your data partition is auto-provisioned automatically — no `setup_workspace()` required. A placeholder master resume is written to your `01-Current-Optimized/` folder so tools work immediately. Replace it with your real resume using `setup_workspace()` or by editing the file directly.

#### Tear down

```bash
pkill -f "port-forward svc/jcmcp"
```

---

## Part 2 — Claude Desktop

### 2a. Local stdio

Edit the Claude Desktop config file:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

**Local Python:**

```json
{
  "mcpServers": {
    "jobContextMCP": {
      "command": "/absolute/path/to/jobContextMCP/.venv/bin/python3",
      "args": ["/absolute/path/to/jobContextMCP/server.py"],
      "cwd": "/absolute/path/to/jobContextMCP"
    }
  }
}
```

Replace `/absolute/path/to/jobContextMCP` with the real path (e.g. `/Users/frank/Projects/jobContextMCP`).

**Docker (alternative):**

```json
{
  "mcpServers": {
    "jobContextMCP": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/absolute/path/to/jobContextMCP/config.json:/app/config.json:ro",
        "-v", "/absolute/path/to/jobContextMCP/data:/app/data:rw",
        "-v", "/absolute/path/to/your/resumes:/workspace:rw",
        "-e", "MCP_TRANSPORT=stdio",
        "jobcontextmcp:latest"
      ]
    }
  }
}
```

Restart Claude Desktop after saving. You should see the tools listed in the sidebar under **MCP Tools**.

---

### 2b. AKS HTTP (remote cloud instance)

Claude Desktop (v0.10.0+) supports remote HTTP MCP servers.

#### Step 1 — Start the port-forward

```bash
kubectl port-forward svc/jcmcp 8099:80 -n jcmcp
```

#### Step 2 — Add the remote server

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jobContextMCP-aks": {
      "type": "http",
      "url": "http://localhost:8099/mcp"
    }
  }
}
```

#### Step 3 — Authenticate

The MCP transport endpoint (`/mcp`) itself does not require Entra login — it's authenticated at the infrastructure level (port-forward is local-only). Dashboard views require Entra auth in a browser; MCP tool calls from Claude Desktop do not.

Restart Claude Desktop. You should see the tools listed under **jobContextMCP-aks** in the sidebar.

> **If you expose the AKS service publicly** (e.g. via an Ingress with a real domain), add `Authorization: Bearer <token>` to the HTTP headers in the config. The token can be any short-lived Entra access token retrieved via the PKCE flow.

---

## Part 3 — ChatGPT Desktop

The ChatGPT desktop app (macOS, v1.2025.x+) supports MCP servers via a JSON config file.

> **Note:** ChatGPT's MCP support is for local HTTP servers. The app does not support stdio MCP servers directly, and it does not implement OAuth discovery — you cannot use Entra PKCE directly inside the ChatGPT client. The recommended approach is a local port-forward to the AKS instance (same as VS Code and Claude Desktop).

#### Step 1 — Start the port-forward

```bash
kubectl port-forward svc/jcmcp 8099:80 -n jcmcp
```

#### Step 2 — Locate the ChatGPT MCP config

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/ChatGPT/mcp.json` |
| Windows | `%APPDATA%\ChatGPT\mcp.json` |

Create the file if it does not exist.

#### Step 3 — Add the server

```json
{
  "mcpServers": {
    "jobContextMCP": {
      "type": "http",
      "url": "http://localhost:8099/mcp"
    }
  }
}
```

#### Step 4 — Restart ChatGPT

Quit and re-open the ChatGPT desktop app. You should see the MCP tools available in a new conversation under the **Tools** or **Plugins** panel (exact label depends on app version).

#### Data isolation with ChatGPT

Because ChatGPT connects over the MCP HTTP transport (not through the dashboard browser flow), it does **not** authenticate with Entra ID — there is no JWT and no `oid` claim. The server treats unauthenticated MCP requests as the service owner and routes them to the full data corpus. If you share the port-forward with guests, be aware that MCP tool calls are not scoped to a per-user partition unless the client sends a valid Entra bearer token.

---

## Part 4 — Cursor

Create or edit `.cursor/mcp.json` in the project root (project-scoped), or add via **Settings → MCP** (global):

**Local:**

```json
{
  "mcpServers": {
    "jobContextMCP": {
      "command": "/absolute/path/to/.venv/bin/python3",
      "args": ["server.py"],
      "cwd": "/absolute/path/to/jobContextMCP"
    }
  }
}
```

**AKS HTTP:**

```json
{
  "mcpServers": {
    "jobContextMCP-aks": {
      "type": "http",
      "url": "http://localhost:8099/mcp"
    }
  }
}
```

Cursor also reads `.cursorrules` — use `copilot-instructions.example.md` as a template.

---

## Part 5 — Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

**Local:**

```json
{
  "mcpServers": {
    "jobContextMCP": {
      "command": "/absolute/path/to/.venv/bin/python3",
      "args": ["server.py"],
      "cwd": "/absolute/path/to/jobContextMCP"
    }
  }
}
```

**AKS HTTP:**

```json
{
  "mcpServers": {
    "jobContextMCP-aks": {
      "type": "http",
      "url": "http://localhost:8099/mcp"
    }
  }
}
```

Windsurf also reads `.windsurfrules` — same `copilot-instructions.example.md` template applies.

---

## Entra Auth — Guest Invite Flow

If you are inviting someone to use the shared AKS dashboard (not just the MCP tools), they need a Microsoft account and a B2B guest invitation.

**As the service owner:**

```bash
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/invitations" \
  --headers "Content-Type=application/json" \
  --body '{
    "invitedUserEmailAddress": "guest@example.com",
    "inviteRedirectUrl": "https://<your-domain>/dashboard/login",
    "sendInvitationMessage": true
  }'
```

**As the guest:**

1. Accept the email invitation — this links their Microsoft account to your Entra tenant.
2. Open the dashboard URL in a browser (or `http://localhost:8099/` via port-forward).
3. Click **Sign in** and authenticate with their Microsoft account.
4. Their data partition is auto-provisioned on first login — placeholder resume, blank pipeline, empty SQLite DB.
5. They can now call any MCP tool (via their AI client over the HTTP transport) and their data is fully isolated from the service owner.

**Accepted guest accounts:**

| Guest | Email | Status |
|-------|-------|--------|
| Shannon Murdie | shannonmurdie@yahoo.com | Invited (pending acceptance) |
| Randi MacBride | randi.macbride@gmail.com | Invited (pending acceptance) |
| Max Batki | max.batki@gmail.com | Invited (pending acceptance) |

---

## Troubleshooting

### VS Code: tools not appearing

- Confirm `MCP_MODE` in `.env` matches your setup (`local` or `docker`).
- Check **Output → MCP: jobContextMCP** for startup errors.
- Make sure you didn't add the server via the VS Code UI (which writes a broken global config).

### `AADSTS7000229: Service principal not found`

The Entra app registration and its service principal in your tenant are separate objects. Run:

```bash
az ad sp create --id <CLIENT_ID>
```

This only needs to be done once per tenant.

### `{"detail": "Invalid credentials"}` after Entra login

The JWT audience may be `api://<CLIENT_ID>` (v1 tokens) rather than the bare `CLIENT_ID` (v2 tokens). The server handles both. If you see this error it likely means the `jcmcp-app-secrets` k8s secret has a stale or incorrect `entra_client_id` value — re-patch it:

```bash
kubectl create secret generic jcmcp-app-secrets \
  --from-literal=entra_client_id=<CLIENT_ID> \
  ... \
  -n jcmcp --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/jcmcp -n jcmcp
```

### Port-forward drops after network change

The tunnel is tied to your TCP connection. If your Mac changes Wi-Fi or wakes from sleep, restart:

```bash
pkill -f "port-forward svc/jcmcp"
kubectl port-forward svc/jcmcp 8099:80 -n jcmcp
```

### Claude Desktop: server not listed

- Confirm JSON syntax in `claude_desktop_config.json` — a trailing comma or missing brace will silently prevent load.
- Verify the Python path is absolute, not `python3` (which may resolve to the wrong version).
- Restart Claude Desktop fully (Quit, not just close the window).

### ChatGPT: tools not available

- Confirm the app version is ≥ v1.2025 (MCP support was added in early 2025).
- Confirm the port-forward is running: `curl http://localhost:8099/health`
- Confirm `mcp.json` syntax is valid JSON.
- Quit and restart the ChatGPT desktop app — it reads the config on launch only.
