# HTTP API Reference

Complete endpoint reference for the FastAPI transport (`transport/http/`), derived from the code. For a practical getting-started guide see [http-api.md](http-api.md); for auth setup see [aks-deployment.md](aks-deployment.md).

## Authentication

Two providers, selected at startup (`transport/http/security.py`):

- **API key** (self-hosted default): set `API_KEY`; every request needs `Authorization: Bearer <API_KEY>` or the `jc_session` cookie. **If `API_KEY` is unset, auth is disabled entirely** — the server logs a warning; never combine that with `ENABLE_REMOTE=true`.
- **Entra ID** (hosted, multi-tenant): set `ENTRA_TENANT_ID` + `ENTRA_CLIENT_ID`. Requests carry an Entra access JWT (validated against the tenant JWKS, audience `CLIENT_ID` or `api://CLIENT_ID`) **or** a personal access token.

**Personal access tokens (PATs)**: format `jcmcp_…`, created in the dashboard's API Keys tab (`POST /api/dashboard/api-keys`, plaintext shown once, stored as SHA-256). PATs work anywhere a bearer token is accepted — including `/mcp` — and are the credential for the mobile app, iOS Shortcuts, desktop cloud sync, and scripts.

**Partitioning**: authenticated non-admin identities are routed to `DATA_FOLDER/users/{oid}` by middleware; every endpoint below operates on the caller's own partition. Public paths (no auth): `/`, `/health`, `/healthz`, `/metrics`, `/why`, `/setup`, `/architecture`, `/privacy`, `/terms`, `/login`, `/logged-out`, `/app*`, `/favicon*`, `/og-image*`, `/.well-known/*`, `/oauth/*`, `/logout`, `/dashboard/login`, `/dashboard/callback`, `/dashboard/logout`.

### Error conventions

| Status | Meaning |
|---|---|
| 401 | Missing/invalid credentials — `{"detail": "Missing credentials" \| "Invalid credentials"}` |
| 403 | Owner-only feature (LaTeX export), or API-key session on a tenant-scoped hosted route |
| 404 | Unknown resource (job id, file, session, work item) |
| 409 | Actionable client state (Oura not connected, sync not configured) |
| 422 | Semantic body rejection (batch too large, bad token format, non-http URL, bad key prefix) |
| 502 | Upstream/model failure (Oura API error, model returned empty edit) |
| 503 | Local capability missing (no LLM provider configured) |

SSE endpoints emit `event: error` in-stream (status stays 200 once headers are sent).

## Core REST

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs/evaluate` | Queue + assess a pasted JD (`{company, role, job_description, source?, persona?}`) |
| POST | `/jobs/evaluate/stream` | SSE variant — one event per pipeline stage |
| POST | `/jobs/ingest-url` | Scrape URL → queue → fitment in one call (`{url, source?, persona?}`). LinkedIn-blocked pages return 200 with `queue_status: "linkedin_blocked"` (iOS Shortcuts-friendly) |
| POST | `/jobs/decide` | Record `add`/`dismiss` decision |
| POST | `/resumes/generate` | Generate resume or cover letter (`{company, role, job_description, kind, export_pipeline, persona?}`) |
| POST | `/resumes/generate/stream` | SSE variant |
| POST | `/stories/search` | STAR story context by tag |
| GET | `/tone/profile` | Tone profile text |
| GET | `/workflows` · POST `/workflows/{name}` · POST `/workflows/{name}/stream` | List/run/stream LangGraph workflows |
| GET | `/personas` · `/personas/{name}` | Persona presets |

## Health & telemetry

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/healthz` | `{"status":"ok","service":"jobContextMCP","version":"<lib.version>","auth_enabled":bool}` |
| GET | `/metrics` | Prometheus text: request/LLM/work/eval counters plus durable provenance gauges recomputed from SQLite |

## MCP

| Method | Path | Purpose |
|---|---|---|
| POST/GET/DELETE | `/mcp` | MCP Streamable HTTP session endpoint (Entra JWT or PAT) |

## OAuth proxy (MCP clients)

The server fronts Entra with RFC 8414/9728 discovery plus RFC 7591 dynamic client registration so clients like Claude, Cursor, and VS Code can connect without manual app registration. `/oauth/authorize` and `/oauth/token` proxy to Entra, stripping the `resource` parameter (Entra rejects mismatched `resource`+`scope`).

| Method | Path |
|---|---|
| GET | `/.well-known/oauth-protected-resource[/{path}]` |
| GET | `/.well-known/oauth-authorization-server` |
| POST | `/oauth/register` |
| GET | `/oauth/authorize` · POST `/oauth/token` |
| GET/POST | `/logout` · GET `/logged-out` |

## Sync (desktop ⇄ cloud) — `/api/sync`

Journal-based bidirectional sync; see [persistence.md](persistence.md) for semantics.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sync/changes` | `{since_id, limit}` → journal entries + row snapshots after the cursor |
| POST | `/api/sync/apply` | Apply a peer's batch (LWW/dedupe/parent-remap); >2000 changes → 422 |
| POST | `/api/sync/contact` | Fill-empty-only merge of the config `contact` block |
| POST | `/api/sync/files/manifest` | `{rel: {size, mtime, sha256}}` for the workspace |
| POST | `/api/sync/files/get` / `put` | Transfer one file (base64) |

## Mobile companion — `/api`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/events?since_id&limit` | Career Inbox feed derived from the sync journal (`assessment_done`, `job_imported`, `interview_logged`, `application_update`, `activity`, `rejection`) |
| POST | `/api/push/register` | Store an Expo push token (must start `ExponentPushToken`) |
| POST | `/api/capture` | Share-sheet capture: enqueue durable `capture_url` work, return `work_id` immediately; result arrives as a push notification |

## Control plane — `/api/work`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/work?status&limit` | Recent work items in the caller's partition |
| GET | `/api/work/{id}` | One item (`status ∈ queued/running/succeeded/failed/cancelled`) |
| GET | `/api/work/stats` | Aggregates by kind/status + recent failures |

Registered kinds: `capture_url`, `run_evals`. See [control-plane.md](control-plane.md).

## Evals — `/api/evals`

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/evals/results` | Ingest a CLI eval run (suite or layer1 payload); persists per-partition and mirrors into `eval_*` Prometheus gauges |
| GET | `/api/evals/results` | Latest stored results |
| POST | `/api/evals/run` | Run the golden suite server-side via the control plane (`{n?: 1–10, entries?: [GD ids]}`) → `{work_id, status_url}` |

See [evals.md](evals.md).

## Dashboard JSON API (React SPA) — `/api/dashboard`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dashboard/me` | Auth probe (`{authenticated, id, name, firstName}`) |
| GET | `/api/dashboard/home` | Home payload (priorities, Oura readiness, digest) |
| POST | `/api/dashboard/home/dismiss-priority` | Hide a derived priority (expires after `days`, default 14) |
| GET/POST | `/api/dashboard/api-keys` · POST `…/{id}/revoke` | PAT management |
| GET | `/api/dashboard/settings` | Provider/Oura/owner status summary |
| GET | `/api/dashboard/oura/history?days` · POST `…/sync` · `…/disconnect` · `…/pat` | Oura integration |
| GET | `/api/dashboard/export` | Zip of the caller's whole data root (requires a user session; API-key admin gets 403 on the hosted product) |

## Dashboard server-rendered — `/dashboard`

HTML boards plus their JSON `…/data` endpoints: `pipeline` (with generate/edit/accept endpoints, template selection, provenance detail at `/dashboard/pipeline/provenance/latest`), `job-hunt`, `materials` (+ file serving), `rejections`, `posts` (+ CSV import, metrics), `people` (+ follow-up dismissal), `health` (+ check-in), `interviews`, `digest`, `api-keys`, `settings`, and the login/callback/logout session routes. LaTeX export paths are owner-only (403 for beta accounts).

## Desktop-only (mounted when `DEPLOY_MODE=desktop`)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/chat/sessions`, `…/{id}/messages`, `…/{id}/stream` | Chat agent (SSE over POST); `GET /api/chat/config` reports provider readiness |
| POST | `/desktop/shutdown` | Graceful backend shutdown (Tauri shell) |
| GET | `/desktop/mcp-clients` · POST `/desktop/mcp-connect` | Detect and wire local MCP clients (backup written first) |
| GET/POST | `/desktop/ai-provider` | BYOK provider selection (openai / anthropic / ollama; keys write-only, prefix-validated) |
| GET | `/desktop/sync` · POST `/desktop/sync/config` · `/desktop/sync/run` | Cloud sync configuration/run |
| POST | `/desktop/open-file` · `/desktop/open-url` | Open in the OS (validated hrefs only) |
| POST | `/desktop/import-workspace` | Restore a `GET /api/dashboard/export` zip (existing data moved aside, never deleted; restart required) |

Desktop routes are loopback-only by construction: desktop mode forces a `127.0.0.1` bind and strips `ENABLE_REMOTE`/Entra vars from the environment.
