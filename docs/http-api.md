# HTTP API, Dashboard & Mobile Capture

The FastAPI transport (`transport/http/`) exposes the same capabilities as the MCP tools over REST + Server-Sent Events, for clients that don't speak MCP — the browser dashboard, the mobile app, iOS Shortcuts, scripts, and Open WebUI.

```bash
# From the project root (reads HOST / PORT / ENABLE_REMOTE / API_KEY from environment)
PORT=8000 .venv/bin/python -m transport.http.main

# LAN / Tailscale access
ENABLE_REMOTE=true PORT=8000 .venv/bin/python -m transport.http.main
```

## Endpoints

The most-used routes, grouped. The complete reference — every route, request/response schema, auth requirement, and error code — is in [api-reference.md](api-reference.md).

- `GET /health`
- `POST /resumes/generate` — sync resume generation; body `{ "company", "role", "job_description", "persona?" }`
- `POST /resumes/generate/stream` — same call, SSE stream of progress events
- `POST /jobs/evaluate` — queue + assess a pasted job description
- `POST /jobs/ingest-url` — fetch a job URL, queue it, and run fitment evaluation; used by the iOS Share Sheet shortcut and the mobile app's server-fallback path. Works best with canonical ATS pages (Greenhouse, Lever, Ashby, Workday, company career sites).
- `POST /jobs/decide` — add or dismiss an evaluated job
- `GET /personas` / `GET /personas/{name}` — list/inspect persona configs
- `GET /workflows` / `POST /workflows/{name}` / `POST /workflows/{name}/stream` — invoke LangGraph workflows
- `GET /api/work` / `GET /api/work/{id}` / `GET /api/work/stats` — control-plane work item status
- `GET /api/events`, `POST /api/capture`, `POST /api/push/register` — mobile companion (Career Inbox, share-sheet capture, push)
- `POST /api/evals/run`, `GET|POST /api/evals/results` — eval framework ([evals.md](evals.md))
- `POST /api/sync/*` — desktop ⇄ cloud sync ([persistence.md](persistence.md))
- `GET /metrics` — Prometheus metrics
- `GET /dashboard/` and `/dashboard/*` — server-rendered dashboard routes; `/app` — the React SPA; `/mcp` — the MCP Streamable HTTP endpoint
- All write endpoints require `Authorization: Bearer <token>` when auth is configured; bind to `127.0.0.1` for local-only use or expose over Tailscale.

## Dashboard

The dashboard is the visual layer over the same local data and services exposed through MCP/HTTP. React SPA screens (`/app`): Home (priorities + daily digest), Pipeline (queue → assess → generate → decide, with template selection and provenance verdicts), Job Hunt (status, immutable event history, comp data), Materials, Interviews, People (with follow-up queue), Posts, Rejections, Wellbeing, Chat (desktop), Settings, and API Keys.

When `API_KEY` is configured, browser login uses the same token model as the HTTP API: `/dashboard/login` sets an HTTP-only `jc_session` cookie, `/dashboard/logout` clears it, and API-style calls can still use `Authorization: Bearer <token>`. The auth provider reads settings fresh at request time, so rotating the token doesn't require a restart.

### LAN / phone mode

```text
http://<YOUR_LAN_IP>:8000/dashboard/
```

- Computer and phone must be on the same Wi-Fi (or a shared Tailscale network).
- If the browser can't connect, allow incoming connections for Terminal/Python in your firewall.
- If you expose LAN access, set `API_KEY` in your environment before running.

## Per-user API keys

Each authenticated user can generate personal programmatic access tokens from the dashboard's **API Keys** tab. Unlike the global `API_KEY` environment variable (admin-level), per-user keys are scoped to your own data partition — the recommended credential for the mobile app, iOS Shortcuts, CLI scripts, and any automation that calls HTTP endpoints without a browser session.

Keys start with `jcmcp_` and are shown once at generation time. Multiple keys can be active simultaneously — one per device or script — and each is individually revokable (Dashboard → API Keys → Revoke; takes effect immediately).

```bash
# Single request
curl -H "Authorization: Bearer jcmcp_<your-token>" https://your-server/api/work/stats

# Set for the session
export JCMCP_TOKEN="jcmcp_<your-token>"
curl -X POST -H "Authorization: Bearer $JCMCP_TOKEN" -H "Content-Type: application/json" \
  -d '{"company":"Acme","role":"Staff Engineer","job_description":"..."}' \
  https://your-server/jobs/evaluate
```

## Mobile capture

Two ways to queue jobs from a phone:

### The companion app (recommended)

The Expo app in [`mobile/`](../mobile/) registers with the system share sheet. Share a job posting from any app and it captures the page **on-device** (`src/pageExtract.ts`) — the phone can read pages that authwall datacenter IPs — with a server-side fallback for pages that need it. Auth is a per-user API key pasted into Settings (stored in the device keychain). See [mobile/README.md](../mobile/README.md).

### iOS Shortcut (no app install)

A Shortcuts workflow that POSTs the shared URL to `/jobs/ingest-url`:

1. Open **Shortcuts**, tap **+**, name it `Queue Job in JobContextMCP`.
2. Shortcut info → enable **Show in Share Sheet**; allow **URLs** and **Safari Web Pages** as input types.
3. Add actions: **Receive URLs from Share Sheet** → **Get URLs from Input** → **Get Contents of URL**:
   - URL: `http://<YOUR_SERVER>:8000/jobs/ingest-url`, Method `POST`
   - Headers: `Content-Type: application/json`, and `Authorization: Bearer <key>` if auth is enabled
   - JSON body: `url` = output of Get URLs from Input, `source` = `ios_share_sheet`, optional `persona`
4. Add **Show Result**; optionally end with **Open URLs** → your `/dashboard/pipeline` page.

**LinkedIn note:** LinkedIn restricts automated access to its job pages, so sharing a `linkedin.com/jobs/view/` URL to the *shortcut* won't extract the posting (the mobile app's on-device extraction handles many of these). Use LinkedIn as the discovery layer: tap **Apply** to reach the employer's ATS page, then share that URL. ATS pages have more complete JDs, accurate location requirements, and salary data when posted.

For jobs without an Apply button, the Pipeline page has a **＋ Add Job** button — paste company, role, and JD text directly.

### Troubleshooting

- `401` — the `Authorization` header is missing or the token doesn't match.
- Can't connect — confirm both devices share a network, the server is running, and the firewall allows incoming connections.
- LinkedIn-blocked message from `/jobs/ingest-url` — you shared the LinkedIn URL instead of the ATS URL.
- IP changed — LAN IPs move with DHCP; re-check your machine's current address (`ip addr` / `ipconfig`).
