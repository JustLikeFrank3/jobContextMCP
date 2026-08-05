# Configuration Reference

Every knob the code actually reads, derived from source. Two layers: **environment variables** (deploy-time) and **`config.json`** (workspace/user-level). Env wins where both exist.

`config.json` resolution (`lib/config.py`): `$JOBCONTEXT_CONFIG` → `<repo>/config.json` → `<repo>/config.example.json`. The desktop app sets `JOBCONTEXT_CONFIG=<app-data>/config.json`; on the hosted product each tenant gets a per-partition `config.json` deep-merged over the base.

## Environment variables

### HTTP transport

| Variable | Default | Effect |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8000` | Bind port (non-numeric values ignored) |
| `ENABLE_REMOTE` | `false` | Truthy → bind `0.0.0.0` (LAN/Tailscale). Forced off in desktop mode. **Never enable without auth configured** |
| `DISABLE_REBINDING_CHECK` | `false` | With `ENABLE_REMOTE`, disables the MCP SDK DNS-rebinding check (needed behind a TLS-terminating ingress). Both flags required by design |
| `API_KEY` | unset | Bearer token for single-tenant auth. **Unset = auth disabled** (warning logged) |
| `API_KEY_USER_NAME` | `Admin` | Display name for the API-key identity (partition id stays `admin`) |
| `CORS_ORIGINS` | empty | Comma-separated allowed origins; empty = same-origin only |
| `SERVER_BASE_URL` | `https://app.jobcontext.ai` | Public base URL for Entra/Oura redirect URIs (must match the app registration) |
| `DEPLOY_MODE` | unset | `desktop` → loopback bind, mounts `/desktop/*` + chat routes |

### MCP server (`server.py`)

| Variable | Default | Effect |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `sse` / `streamable-http` → standalone Starlette + uvicorn with Entra middleware |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | Bind for SSE/streamable-http MCP mode |
| `JOBCONTEXT_LEGACY_TOOLS` | unset | Truthy → 88 per-function tools instead of the 11 domain facades |

### Identity & auth (Entra ID)

| Variable | Effect |
|---|---|
| `ENTRA_TENANT_ID` + `ENTRA_CLIENT_ID` | Both set → Entra auth provider (JWT validation, OAuth proxy). Otherwise API-key provider |
| `ENTRA_CLIENT_SECRET` | Confidential-client secret for the dashboard's browser PKCE code exchange |
| `ENTRA_OWNER_OID` | Owner's object id: gates owner-only features (LaTeX export), selects the nightly-evals partition. Falls back to config key `entra_owner_oid` |
| `APP_ENCRYPTION_KEY` | Fernet key for secrets at rest (`enc:v1:` prefix, used for Oura tokens). Unset/malformed → encryption is a no-op (plaintext) |

### LLM provider

| Variable | Effect |
|---|---|
| `LLM_PROVIDER` | Overrides config `llm_provider`: `openai` (default), `ollama`, `anthropic`, `foundry` |
| `LLM_API_KEY` | Provider-agnostic key override (openai/anthropic/foundry; ignored for ollama) |
| `JUDGE_LLM_PROVIDER` / `JUDGE_LLM_MODEL` | Eval-judge split: provider/model for `task="eval_judge"` only. Required wherever `LLM_PROVIDER` is exported (AKS, CI) — see the precedence note below |
| `OPENAI_API_KEY` | **Embeddings only** (semantic search fallback) — *not* consulted for generation; use `LLM_API_KEY` or config keys for that |

### Persistence

| Variable | Default | Effect |
|---|---|---|
| `USE_SQLITE` | off (env) / `1` (docker, k8s, desktop) | Reads from SQLite; writes dual-write SQLite + JSON audit trail |
| `SQLITE_ONLY` | off / `1` on desktop | Skips the JSON write leg for mapped tables |
| `JOBCONTEXT_CONFIG` | unset | Highest-precedence `config.json` path |
| `JOBCONTEXT_DATA_DIR` | unset | Overrides the desktop per-OS app-data dir |

### Evals & metrics

| Variable | Effect |
|---|---|
| `EVALS_NIGHTLY_HOUR_UTC` | Hour 0–23 → nightly golden-suite run via the control plane (prod sets `8`). Unset = disabled |
| `JOBCONTEXT_EVAL_URL` / `JOBCONTEXT_API_KEY` | Defaults for `python -m evals … --push-url / --api-key` |
| `JOBCONTEXT_EXTRA_METRICS_PORTS` | Extra loopback ports for the workstation ollama-exporter to scrape/merge |

### Integrations

| Variable | Effect |
|---|---|
| `OURA_CLIENT_ID` / `OURA_CLIENT_SECRET` | Oura OAuth app (falls back to config keys) |
| `GITHUB_TOKEN` | GitHub API token; falls back to `gh auth token` |
| `JOBCONTEXTMCP_OFFLINE` | Truthy → GitHub tools return canned stubs (no network). Note the name: no underscore between JOBCONTEXT and MCP |

### Container/shell-only

| Variable | Default | Effect |
|---|---|---|
| `START_MODE` | `mcp` | Entrypoint dispatch: `http` → REST/dashboard server, `mcp` → stdio MCP |
| `RESUME_PATH` / `LEETCODE_PATH` | `./workspace` / `/dev/null` | docker-compose bind-mount sources |
| `PI_HOST` | `pi-node1` | SSH target for `scripts/pi-deploy.sh` |

## config.json keys

| Key | Default | Purpose |
|---|---|---|
| `llm_provider` | `openai` | `openai` \| `ollama` \| `anthropic` \| `foundry` |
| `judge_provider` / `judge_model` | — | Eval-judge split; empty ⇒ the judge runs on the generation provider/model (it grades its own output). Read only where `LLM_PROVIDER` is unset — see the precedence note below |
| `openai_api_key` / `openai_model` | — / `gpt-4o-mini` | OpenAI BYOK |
| `anthropic_api_key` / `anthropic_model` | — / `claude-sonnet-5` | Claude via Anthropic's OpenAI-compatible endpoint (chat + tool calling work unchanged) |
| `ollama_base_url` / `ollama_model` | `http://localhost:11434/v1` / `llama3.1:8b` | Local Ollama (no key needed) |
| `azure_foundry_endpoint` / `azure_foundry_deployment` / `azure_foundry_api_version` / `azure_foundry_api_key` / `azure_foundry_scope` | — / `gpt-4.1-mini` / `2025-01-01-preview` / — / `https://ai.azure.com/.default` | Azure AI Foundry; key optional in AKS (workload identity via `DefaultAzureCredential`) |
| `data_folder` / `resume_folder` / `leetcode_folder` | — | Storage roots (desktop bootstrap pins these to the app-data dir) |
| `contact` | `{}` | Name/email/phone/linkedin block used in document headers; synced fill-empty-only between desktop and cloud |
| `cloud_sync_url` / `cloud_sync_pat` / `cloud_sync_auto` | — / — / `true` | Desktop ⇄ cloud sync target (PAT from the dashboard's API Keys tab) |
| `entra_owner_oid` / `app_encryption_key` | — | Fallbacks for the corresponding env vars |
| `oura_client_id` / `oura_client_secret` | — | Fallbacks for the Oura env vars |
| `followup_timeout_days` | `21` | Days before an untouched outreach thread goes to the "Gone cold" bucket |
| `chat_tools` | the 11 domains | Overrides the chat agent's tool allowlist |
| `generation_budgets` | see [generation.md](generation.md) | Token budgets for context packing |
| `github_metrics` | — | `{username, repos}` for portfolio tracking |
| `side_project_folders` | `[]` | Array of folders for the skill scanner |
| `side_project_repos` | `[]` | Remote repos for the skill scanner (URL string or `{url, branch}`); shallow-cloned to a temp dir when no local checkout exists |
| `latex_resume_dir` / `resume_pdfs_dir` | — / `03-Resume-PDFs` | Owner-only LaTeX assets; PDF output dir |

Provider selection notes:

- `get_llm_client()` returns `(None, "")` when the chosen provider is missing its key/endpoint — callers degrade to context-package mode instead of crashing.
- An env-pinned `LLM_PROVIDER` silently overrides whatever the desktop Settings UI saved.
- That includes the judge: plain `LLM_PROVIDER` beats config `judge_provider` (env wins is the convention throughout). Config `judge_provider`/`judge_model` only take effect where `LLM_PROVIDER` is unset; prod and CI, which export it, must use `JUDGE_LLM_PROVIDER`/`JUDGE_LLM_MODEL`. Until one of these is configured, the eval judge is the generator's model.
- `llm_generation_status()` mirrors the same resolution for status badges and must stay in lockstep with `get_llm_client()` (documented invariant in `lib/config.py`).

## Provenance gate

The generation truth gate (`lib/provenance.py`) is **always on** — there is no configuration switch. See [generation.md](generation.md).
