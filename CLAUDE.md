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
  FROM THE ROW. Status: `GET /api/work`, `/api/work/stats`. First kind:
  `capture_url`. P1 (route doc generation through it) is task backlog.
- **Sync**: journal-based bidirectional (lib/sync.py), AFTER-triggers into
  `sync_log`; upsert tables LWW by ts; file sync by sha256 manifest.
- **Telemetry**: `lib/metrics.py` (no deps) → `GET /metrics` (Prometheus);
  in-cluster Prometheus+Grafana under `k8s/monitoring/` (dashboards as code).
- **LLM calls** all funnel through `lib/openai_calls.create_chat_completion`
  (rate-spacing, 429/400 retries, thinking-budget empty-at-cap retry).
  Provider resolution: `lib/config.get_llm_client()`; status surfaces use
  `llm_generation_status()` — keep them in lockstep.
- **MCP surface**: 11 consolidated domain tools (`tools/consolidated.py`).
  The facade-coverage test fails if an underlying tool grows a param the
  facade doesn't expose — update the facade signature.

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
  spawn with `CREATE_NO_WINDOW`. Installer is unsigned → SmartScreen warning
  (task: Azure Trusted Signing). Filenames are sanitized at creation
  (`lib.helpers.sanitize_filename`) and sync file transfers skip-and-report
  per file (`last_summary.files.errors`) — but the cloud has no file-delete
  propagation, so a bad-named file already in a partition must be renamed
  there by hand (kubectl exec + mv).

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
- Auth: Entra via the cloud's own OAuth proxy (dynamic client registration,
  PKCE); refresh is single-flight (rotating refresh tokens).

## Where the history lives

Design docs in `docs/` (control-plane.md is the roadmap). PR descriptions
carry incident post-mortems (#90 partition escape, #99 chat poisoning,
#108 capture success-detection). The work_items table + Grafana are the
first stops for "what happened" — not pod logs.
