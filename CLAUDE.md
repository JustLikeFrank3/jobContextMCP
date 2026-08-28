# jobContextMCP — working notes for Claude

Job-search copilot: Python MCP server (FastAPI + FastMCP, SQLite, React
dashboard) shipping three ways — **cloud** (multi-tenant on AKS,
jobcontext.ai), **desktop** (Tauri 2 shell + PyInstaller sidecar, BYOK), and
**mobile** (Expo companion app in `mobile/`, share-sheet capture). Philosophy:
*desktop creates knowledge, mobile captures reality, cloud synchronizes.*

## Process (non-negotiable)

Feature work goes **branch → PR → qa → main**. Never commit directly to main;
promotion is a `qa → main` PR after the qa deploy is green. Direct-to-main
only when Frank explicitly says so for that specific change. Frank merges PRs
unless he delegates it in the moment.

CI triggers: Desktop CI (build matrix) runs on push to `feat/*` and `fix/*` —
**a renamed branch fires no push event** (use `gh workflow run` to dispatch).
`deploy.yml` runs on qa/main pushes (tests + Sonar + AKS deploy);
paths-ignore includes `**.md` and `mobile/**`. Desktop releases: tag
`desktop-v*` **on the exact tested main SHA** (badge-bot pushes `[skip ci]`
commits — never tag those) → desktop-release workflow → rolling
`desktop-latest` release hosts the updater's latest.json.

## Architecture landmarks

- **Partitioning**: every tenant's data lives under `DATA_FOLDER/users/{oid}`.
  Per-request routing via contextvars (`lib/user_context.py`, middleware in
  `transport/http/app.py`). NEVER offload work with bare `run_in_executor` —
  contextvars don't propagate (caused a prod incident). Background work goes
  through the control plane.
- **Control plane** (`lib/work.py`, docs/control-plane.md): durable
  `work_items` rows + in-process dispatcher; executors get partition context
  FROM THE ROW. Status: `GET /api/work`, `/api/work/stats`. Kinds:
  `capture_url`, `run_evals`, `certification.weekly`, `generate.*`
  (P1/P2 shipped 2026-08-10; P3 scheduler is backlog).
- **Sync**: journal-based bidirectional (lib/sync.py), AFTER-triggers into
  `sync_log`; upsert tables LWW by ts; file sync by sha256 manifest.
- **Telemetry**: `lib/metrics.py` (no deps) → `GET /metrics` (Prometheus);
  in-cluster Prometheus+Grafana under `k8s/monitoring/` (dashboards as code).
- **LLM calls** all funnel through `lib/openai_calls.create_chat_completion`
  (rate-spacing, 429/400 retries, thinking-budget empty-at-cap retry).
  Provider resolution: `lib/config.get_llm_client()`; status surfaces use
  `llm_generation_status()` — keep them in lockstep.
- **MCP surface**: 12 consolidated domain tools (`tools/consolidated.py`).
  The facade-coverage test fails if an underlying tool grows a param the
  facade doesn't expose — update the facade signature.
- **WebMCP bridge** (`frontend/src/webmcp/`, docs/webmcp.md): the SPA
  re-registers the server's tools/list verbatim as `document.modelContext`
  tools for in-browser agents (ChatGPT desktop, Chrome OT), calling `/mcp`
  same-origin on the jc_session cookie. Corollary: the middleware IGNORES
  that cookie on cross-site `/mcp` requests (Sec-Fetch-Site, Origin/Host
  fallback) — the cookie is ambient and `/mcp` mutates without a CORS
  preflight. Bearer auth is untouched; don't loosen the guard.
- **Streamable HTTP runs stateless** (`stateless_http=True`, server.py).
  Session mode keeps sessions in a process-local dict with no event store,
  so `Recreate` deploys stranded hosted connectors on a dead session id →
  404 → manual reconnect (2026-08-01 incident, docs/connector-resilience.md).
  Adding anything that needs a live session — MCP `Context`, progress
  notifications, sampling, elicitation, resource subscriptions — breaks
  this; it needs a shared event store first, not just flipping the flag.
  Corollary: auth must never answer "can't verify" with 401. A JWKS fetch
  failure raises `AuthUnavailable` → 503 + `Retry-After`; only a real
  `InvalidTokenError` is a 401. Readiness (`/ready`) gates on the JWKS
  being warm; liveness (`/health`) never checks a dependency. An unknown
  `kid` is not a verdict either: Entra's JWKS is CDN-served, so even a
  forced re-fetch can miss a just-rotated key. `lib/auth.py` resolves keys
  itself (not `get_signing_key_from_jwt`) so the fetch is dated and rate
  limited — first miss 503, same kid still missing from a fresh key set
  60s later 401, unproven freshness always 503. The miss ledger is keyed
  by digest, capped and TTL'd because `kid` is attacker-chosen.
- **`/oauth/token` must inject `scope` on a refresh** — RFC 6749 makes it
  optional (defaults to the granted scope) and MCP clients omit it, but
  Entra v2.0 then resolves the resource to the calling app and returns
  AADSTS90009 "requesting a token for itself" (one app registration is both
  client and API here). Every refresh failed this way until 2026-08-10;
  the connector only ever worked until the first token expiry. Keep
  `_granted_scope()` as the single source for both the injected scope and
  what `/oauth/register` advertises — Entra matches a refresh against
  consented scopes, so drift between them breaks it again.
- **Deploy strategy is `Recreate` on purpose** — SQLite is the sole
  datastore on a ReadWriteOnce Azure Disk. `maxSurge>0` either co-schedules
  two writers on the disk's node (corruption) or blocks the surge pod in
  ContainerCreating until it detaches (longer outage). Don't "fix" it.

## Test & CI gotchas

- `tests/conftest.py` autouse fixture stubs `lib.config.get_llm_client` to
  `(None, None)` — code needing real key-resolution truth in tests must not
  call it.
- CI's test env sets `LLM_PROVIDER=foundry` — provider-sensitive tests must
  `monkeypatch.delenv("LLM_PROVIDER")`. Run suites both ways when touching
  provider logic.
- `isolated_server` fixture is canonical isolation; static module-level path
  constants (e.g. `INTERVIEWS_FILE`) are computed at import — repoint them.
- Sonar quality gate: ≥80% coverage on new code; S107 excluded for
  tools/consolidated.py (wide signatures ARE the schema).

## Desktop specifics

- Frozen processes NEVER write beside the executable; config lives in
  app-data (`JOBCONTEXT_CONFIG` env / `desktop_data_dir()`); read paths must
  match write paths (two incidents from this).
- macOS: rcodesign two-pass (sidecar with runtime+entitlements, then whole
  app with --exclude), notarize via rcodesign; updater `.app.tar.gz` built
  AFTER signing; TAURI_SIGNING_* env-only.
- Windows: sidecar is console-subsystem (stdout carries the port handshake) —
  spawn with `CREATE_NO_WINDOW`. Installer + sidecar are Authenticode-signed
  via Azure Trusted Signing (guarded on AZURE_CLIENT_ID — forks build
  unsigned); SmartScreen can still warn until the cert builds reputation.
  Filenames are sanitized at creation
  (`lib.helpers.sanitize_filename`) and sync file transfers skip-and-report
  per file (`last_summary.files.errors`) — but the cloud has no file-delete
  propagation, so a bad-named file already in a partition must be renamed
  there by hand (kubectl exec + mv). Sync manifest rels are POSIX
  (`rel.as_posix()`) — `str(rel)` forked every key on Windows and
  re-transferred the whole workspace both ways, littering the cloud with
  flat literal-backslash files (2026-07-13 incident; peers on old builds
  can re-push that junk until updated). Case-fold collisions (two cloud
  files differing only in case) also wedge Windows into a re-pull loop —
  resolve by renaming one at source.

## Mobile specifics (mobile/)

- Expo SDK 57 / RN 0.86; `eas init/build` sometimes re-adds a duplicate
  ShareExtension block under `app.json` `extra.eas.build` — strip it.
  eas-cli must NOT be a project dep (`npx eas-cli`). ascAppId pinned in
  eas.json. Mobile is merged to main; build from main.
- Share capture: on-device page extraction (`src/pageExtract.ts`) — the phone
  reads pages that authwall datacenter IPs; server fallback in
  tools/job_scraper.py (jobs-guest fragment). LinkedIn dropped JSON-LD from
  many job pages; the parser reads top-card markup. Raw linkedin.com URLs
  can still extract empty on-device (WebView escalation is the next step).
- Auth: API key only (personal access token from the dashboard's API Keys
  tab, pasted into Settings, stored in the device keychain) — no Entra
  OAuth sign-in on mobile. Removed 2026-07-17: a static PAT has no
  inactivity expiry and no refresh-token rotation to go stale while the
  app sits unopened, which is the common case for a personal app; the
  Entra flow's rotating refresh tokens produced exactly that failure. The
  cloud's OAuth proxy (dynamic client registration, PKCE) stays in place
  for other MCP clients (Claude.ai, Cursor, VS Code) — only the mobile
  app's auth path changed.


## Where the history lives

Design docs in `docs/` (control-plane.md is the roadmap). PR descriptions
carry incident post-mortems (#90 partition escape, #99 chat poisoning,
#108 capture success-detection). The work_items table + Grafana are the
first stops for "what happened" — not pod logs.
