# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Refactoring

- Split three monolithic source files into focused single-responsibility modules:
  - `tools/export.py` 1,035 → 184 lines; all `.txt` resume/cover-letter parsers extracted to `lib/resume_parser.py`
  - `transport/http/routes/dashboard/pipeline.py` 1,696 → 1,080 lines; request models, data-access helpers, and scoring logic extracted to `pipeline_helpers.py`
  - `tools/generate.py` 1,618 → 1,351 lines; all format-spec and system-prompt constants extracted to `tools/generate_prompts.py`
  - All public symbols re-exported from their original modules — no call-site changes required

### Bug fixes

- `k8s/deployment.yaml`: added `DISABLE_REBINDING_CHECK=true` next to `ENABLE_REMOTE=true` — the MCP SDK's DNS rebinding protection was responding 421 to all `/mcp` requests from the AKS ingress because `Host: jobcontextmcp.eastus.cloudapp.azure.com` is not `localhost`

### CI/CD

- `deploy.yml`: added `workflow_dispatch` trigger with built-in branch/tag selector so deploys can be triggered manually from any branch directly in the GitHub Actions UI

---

## [1.0.0] - 2026-06-19

Completes the transformation from a local stdio context server into a multi-user, cloud-hosted job-search platform. 77 tools, 627 tests, production-verified on AKS with Entra ID auth, per-user data isolation, and GitHub Copilot app HTTP/SSE connectivity confirmed.

### Multi-tenant Entra ID authentication

- Full PKCE OAuth2 login flow for the AKS-hosted dashboard — `/dashboard/login`, `/dashboard/callback`, `/dashboard/logout`. JWT validation accepts both bare `CLIENT_ID` and `api://CLIENT_ID` audiences (Entra v1/v2 compat). Secure `jc_session` HTTP-only cookie; logout button on every dashboard page.
- Per-user data isolation via `lib/user_context.py` `ContextVar` — every authenticated user gets their own SQLite DB, workspace folder tree, and JSON partition under `/app/data/users/{entra_oid}/`. Owner OID (`ENTRA_OWNER_OID`) bypasses isolation and routes to the full corpus.
- Auto-provisioning on first login — `lib/user_provisioning.py` idempotently creates the user data directory, initializes a blank `jobcontextmcp.db` (all 16 tables), creates workspace subdirs `01`–`09`, and writes a placeholder master resume so generation tools work immediately.
- Workspace file isolation — `lib/config.py` `get_active_workspace_folder()` returns the user-scoped path; `lib/helpers.py` `_scan_dirs()` uses it dynamically.
- Guest user invitation support via Entra B2B — invited users are auto-provisioned on first login with isolated data partitions.
- Root landing page at `/` — project banner SVG + Sign In CTA; previously returned bare FastAPI 404.

### SQLite persistence + dual-write layer

- `lib/db.py` connection helper + `scripts/migrate_to_sqlite.py` one-shot migration from JSON.
- `lib/io_sqlite.py` dual-write adapter — all writes go to SQLite AND JSON simultaneously; reads from SQLite when `USE_SQLITE=1`.
- 9 table handlers: applications + events, job queue, people, interviews, rejections, tone samples, health log, LinkedIn posts, personal context.
- Sync-delete on save — dismissed/removed entries don't linger in SQLite.
- `SQLITE_ONLY=1` skips JSON writes for SQLite-mapped tables (default on in AKS, default off locally).
- 36 new round-trip + sync-delete tests.

### AKS production deployment

- Full `k8s/` manifests: PVC (5Gi Premium SSD), ConfigMap, Deployment, Service.
- Workload identity + federated credential — zero secrets in production.
- Init container seeds all 9 workspace dirs from Azure Blob Storage on pod start.
- `workspace-sync` sidecar pushes PVC workspace files + SQLite DB back to blob every 15 min — survives pod replacement without data loss (worst-case 15 min).
- `scripts/provision_aks.sh` — idempotent one-shot provisioner for all Azure infrastructure.
- `scripts/upload_workspace.sh` — config-driven bulk uploader for all 9 workspace subdirs.
- Provider-agnostic LLM via `lib/config.get_llm_client()`: OpenAI / Azure AI Foundry (keyless `DefaultAzureCredential`) / Ollama.

### MCP Streamable HTTP transport (`2025-03-26`)

- `transport/http/app.py` mounts `mcp.streamable_http_app()` at `/mcp`; verified `protocolVersion: 2025-03-26`.
- `.vscode/mcp.json` includes both stdio (local/Docker) and HTTP (AKS) entries.
- `AKS port-forward` VS Code background task in `.vscode/tasks.json`.
- **GitHub Copilot app** — verified working via Settings → MCP servers GUI (HTTP tab, URL = deployed endpoint, no config file editing). Entra ID OAuth flow on save.

### Dashboard: daily digest + cover-letter editor

- `GET /dashboard/digest` + `POST /dashboard/digest/generate` — browser digest with collapsible sections, spinner, timestamps, **NEEDS DECISION** queue section.
- Cover-letter edit dialog with draft versioning (`{stem}.edit1.tmp`, …) — source never overwritten mid-session. Accept/cancel/discard flow.
- `09-Cover-Letter-PDFs/` dedicated output folder (previously mixed into `03-Resume-PDFs/`).
- Job-id-based pipeline actions — assess, select resume, generate materials, export PDFs, unqueue, remove, add, dismiss without brittle company/role string matching.
- Inline assessment details — fitment scores, gaps, angles, and recommendations visible in the pipeline.
- Cover-letter narrative routing — `PRIMARY COVER LETTER HOOK` from personal context surfaced when a matching company story exists; cross-company hooks filtered.
- Semantic personal-story retrieval — `lib/story_retrieval.py` blends keyword scores with OpenAI embeddings, mission queries, and hook-tag boosts for cover letter generation.
- LaTeX export path — Tectonic-based cover letter renderer; date, role title, and export pipeline configurable per generation.
- NEEDS DECISION in `get_daily_digest()` — queue items now appear in digest and TODAY'S FOCUS.

### Fixes

- iOS Share Sheet URL whitespace/non-printable char stripping.
- Jina scraper 4xx tolerance when body has content.
- `_save_json` double `write_text` call removed.
- Init container: `az login` federated token, `--overwrite true`, 0-byte DB guard.
- Dashboard auth provider settings staleness on token rotation.
- `IndentationError` CrashLoopBackOff in root route — Python AST check added as pre-commit gate.
- JWT audience mismatch (`api://CLIENT_ID` vs bare) — both accepted.
- `transport/http/config.py` `_env_port()` port validation fix.
- `workspace-sync` sidecar — `Storage Blob Data Contributor` role required (not just `Reader`).
- All shell scripts pass shellcheck.

### Tests

627 passing (up from 591 at last main merge).

### Upgrade notes

- Run `python scripts/migrate_to_sqlite.py` once to bootstrap `data/jobcontextmcp.db` from existing JSON.
- Set `USE_SQLITE=1` in `.env` to activate SQLite reads/writes.
- AKS users: run `./scripts/upload_workspace.sh` before the next pod restart to seed all workspace dirs into blob.
- No tool API changes — existing `config.json` and data files work as-is.

## [0.9.0] - 2026-06-01

Adds local LLM support via Ollama, a LangGraph-powered resume agent tool, three new context tools, and a verified GitHub Copilot app (HTTP/SSE) client path. Tool count 65 → 73. Full suite 523/523 green.

### Added

- **Ollama provider support** (`lib/config.py` — `get_llm_client()`) — new factory function returns `(client, model_name)` for whichever LLM provider is configured. Setting `llm_provider = "ollama"` in `config.json` routes all generation calls to a local Ollama server via the OpenAI-compatible API (`base_url = ollama_base_url`, `api_key = "ollama"`). Defaults to `"openai"` when not set. Config keys:
  - `llm_provider` — `"openai"` (default) or `"ollama"`
  - `ollama_base_url` — default `http://localhost:11434/v1`
  - `ollama_model` — default `llama3.1:8b`
  - All three generation paths (`generate_resume`, `generate_cover_letter`, `generate_resume_agent`) and the fitment path (`run_job_assessment`) now call `get_llm_client()` instead of constructing their own OpenAI clients.

- **`generate_resume_agent(company, role, job_description)`** (`tools/langgraph_pipeline.py`) — LangGraph multi-stage resume pipeline exposed as an MCP tool. Runs a 4-node `StateGraph`: `load_context → retrieve (RAG) → draft → review → [revise →] finalize`. Each node has a narrow mandate so no context is lost between stages. Falls back to `generate_resume()` context-packing when no LLM client is configured. Returns header with pipeline summary (revision count, final review excerpt) prepended to the finished draft.

- **`get_all_star_context()`** (`tools/star.py`) — full STAR library dump in one call: all personal stories with tags and people, all resume metric bullets organized by category (`cloud_migration`, `testing`, `ai_adoption`, etc.), and all company-specific framing hints. Intended for session boot when a complete interview prep picture is needed without filtering by tag.

- **`get_fb_outreach_queue(limit?, offset?, sort_by?, include_pending?)`** (`tools/crossref.py`) — prioritized queue of Facebook friends who are not yet LinkedIn connections. Sorted by recency (most recently added FB friend first) to surface the freshest relationships. Active job target companies are pulled from `status.json` and included in the header so the AI can flag contacts who work at target companies. Supports pagination (`limit` / `offset`) and optional inclusion of pending FB requests (`include_pending=True`).

- **`save_job_assessment(company, content, filename?, source?)`** (`tools/fitment.py`) — saves a generated fitment assessment to `07-Job-Assessments/` as a `.md` file. Optional `source` parameter saves into a named subfolder (e.g. `07-Job-Assessments/Miguel Referral/`) for intake-source organization. Filename defaults to `{Company} - Fitment Assessment.md`.

### Changed

- **`server.py` — missing exports wired** — `run_job_assessment`, session/star/health tool aliases, and `_TOOL_MODULES` list added to module-level exports; `JOB_ASSESSMENTS_FOLDER` and `SERPAPI_KEY` added to `_sync_config_exports()` so downstream tools and tests resolve these correctly.
- **`cli.py` — tool discovery fixed** — `job_scraper` and `job_queue` modules added to `_discover_tools()` so all 73 tools are callable via the CLI.
- **`tools.json` regenerated** — static tool manifest rebuilt from live server registry; count 65 → 73.

### Client Support

- **GitHub Copilot app (HTTP/SSE) — verified** — the standalone GitHub Copilot desktop application connects via its **Settings → MCP servers** GUI. Select HTTP or SSE transport, enter your deployed endpoint URL (e.g. `https://your-server/mcp`), and save. No config file editing required. OAuth/Entra ID login prompt appears when auth is configured on the server. Verified working with Azure-hosted endpoint.

## [0.8.0] - 2026-05-29

Adds web-based job ingestion — four new MCP tools for scraping individual job postings by URL and searching Greenhouse, Lever, and Google Jobs boards directly from the server. All results funnel into the existing `queue_job` pipeline. 34 new tests; full suite 499/499 green.

### Added

- **`scrape_job_url`** — fetches any job posting URL (Greenhouse, Lever, Ashby, Workday, most company career pages) via Jina Reader (`r.jina.ai`), extracts company/role/description, and optionally queues it. No extra dependencies; works without API keys.
- **`search_jobs`** — searches Google Jobs via SerpAPI and returns ranked postings. Requires `serpapi_key` in config. Accepts `auto_queue=True` to pipeline results directly.
- **`search_greenhouse_jobs`** — browses all open roles on any company's Greenhouse board via the public Greenhouse API. Free, no API key required.
- **`search_lever_jobs`** — browses all open roles on any company's Lever board via the public Lever API. Free, no API key required.
- **`docs/remote-mobile-architecture.md`** — full architecture plan for the upcoming HTTP/SSE/WebSocket remote transport layer, covering FastAPI server, service abstraction, LangGraph integration, auth, and mobile/iPad UX target.
- **34 new tests** in `tests/test_job_scraper.py` covering all four tools, HTML stripping, URL parsing, mock HTTP responses, and `auto_queue` pipeline integration.

### Changed

- `config.example.json` and `lib/config.py` updated with `serpapi_key` field.
- `tools/export.py` and `tools/langgraph_pipeline.py` minor fixes landed alongside this branch.

## [0.7.1] - 2026-05-25

### Added

- **Persona-aware fitment assessment** — fitment tooling now accepts an optional `persona` parameter that flows cleanly through every layer (HTTP request → `JobAnalysisService` → `tools.fitment` / `tools.job_queue`), mirroring the existing `ResumeGenerateRequest.persona` pattern. When set, the named persona's prompt block is prepended either to the returned context pack (`assess_job_fitment`, `evaluate_queued_job`, `POST /jobs/evaluate`) or to the LLM system prompt (`run_job_assessment`). Same JD against `faang_technical`, `executive_polish`, and `startup_founder` now produces materially different lenses on the same candidate. Unknown persona names emit a non-fatal warning instead of crashing. Real-world validation against a FanDuel JD showed the `faang_technical` lens sharpened gap framing (Azure→AWS adaptation, BFF pattern callout) without altering the underlying fit score. New `tests/test_fitment.py` (11 tests) covers persona injection across the tool, service, and route layers; full suite 476/476 green.

### Fixed

- **Circular-import guard** — `PersonaService` is now lazy-imported inside `tools.fitment` to break the `services/__init__ → resume_service → tools.generate → tools.fitment` cycle that would otherwise crash server boot when persona awareness was added.

## [0.7.0] - 2026-05-25

First release of the remote/mobile track. Adds an HTTP+SSE transport (so the iPad can talk to the server without an MCP client on-device), a LangGraph-driven resume pipeline with draft/review/revise nodes, data-driven persona configs, an auto-discovering tool registry, and a feature track of five new tools (GitHub stats, upcoming interviews, referral chains, reply drafting, CLI scheduling). 465/465 tests passing.

### Agent Customization (2026-05-25)

- **Recruiting consultant persona** — added `AGENT PERSONA & LENS` section to `.github/copilot-instructions.md`; gives the agent a calibrated external voice (20 years placing engineers, Atlanta market, full U.S. remote range, 2026 comp benchmarks) for job assessment, outreach review, and resume critique.
- **`.github/agents/tech-interviewer.agent.md`** — dedicated interviewer mode agent; strict guide-without-solving behavior for coding, system design, and behavioral screens; honest debrief mode on demand.
- **`.github/agents/resume-writer.agent.md`** — resume writer agent; loads master resume + tone profile before writing; hard honesty checkpoint before saving any file; customization strategy table by role type.
- **`.github/agents/linkedin-outreach.agent.md`** — LinkedIn voice agent; enforces tone rules, logs every confirmed post/send to MCP database, distinguishes post / comment / DM / connection note formats.

## Background

Built during an active job search after a layoff. What began as a few tools to stop re-explaining context to AI assistants every session grew into a full MCP server. Shared here for anyone in the same situation.

## [0.6.5] - 2026-05-25

### Added
- **Job evaluation queue** (`tools/job_queue.py`) — pre-pipeline inbox for vetting job descriptions before committing to an application. Four new MCP tools implement a gated `queue → evaluate → decide` workflow:
  - `queue_job(company, role, jd, source?)` — drops a JD into the queue at status `pending`; duplicate submissions return an informative message rather than overwriting.
  - `get_job_queue(status?)` — returns all queued jobs, optionally filtered by status (`pending`, `evaluated`, `added`, `dismissed`); shows fitment score and decision notes when present.
  - `evaluate_queued_job(company, role)` — loads the stored JD, calls `assess_job_fitment` to assemble a full fitment context package for review, and advances the job to status `evaluated`. Evaluation is required before `decide_job` will accept a decision (gate enforced at the data layer, not just convention).
  - `decide_job(company, role, decision, notes?, fitment_score?)` — commits `add` or `dismiss`; `add` calls `update_application(company, role, "interested")` to create a pre-applied pipeline entry; `dismiss` soft-deletes the record (still queryable); both paths store `notes` and optional `fitment_score` from the AI's analysis.
- **`data/job_queue.json`** runtime data file (gitignored) + `data/job_queue.example.json` reference schema — two-entry example showing `evaluated` and `dismissed` states.
- **`JOB_QUEUE_FILE`** path constant added to `lib/config.py` and wired through `server.py` `_sync_config_exports()`.
- **`tests/test_job_queue.py`** — 21 tests covering entry creation, auto-increment IDs, duplicate detection, status filtering, fitment context assembly, the evaluation gate, `add` pipeline write-through, `dismiss` isolation (does not touch `status.json`), fitment score storage, double-decision guard, and missing-job error paths; 21/21 passing, full suite 383/383.



### Added
- **`get_person(name)`** (`tools/people.py`) — single-record people lookup by partial, case-insensitive name match. Returns the full person record when exactly one match is found; returns a disambiguation list when multiple names match. Does not emit the `PEOPLE DATABASE` list header — output is a flat record string, not a table. Token cost is proportional to one person's data rather than the entire 75-person database. Use this instead of `get_people()` whenever you only need one contact.
- **`get_people(slim=True)`** — new `slim` boolean parameter on the existing `get_people()` tool. When `True`, the formatter strips `context` and `notes` fields and returns only `id`, `name`, `company`, `relationship`, `outreach_status`, and `tags` per record. Adds a `[slim]` label to the result header. Useful for scanning the full contact list without loading months of accumulated conversation notes per person.
- **`tests/test_people_tools.py`** — 16 tests covering `get_person` (exact match, partial match, case-insensitivity, not-found, multiple-match disambiguation, notes inclusion, contact info inclusion, empty database, no list header) and `get_people` slim mode (notes excluded, context excluded, essential fields present, slim label, full mode default, slim + filter combined, no results); 16/16 passing.

## [0.6.3] - 2026-05-21

### Added
- **Multi-platform contact cross-reference** (`tools/crossref.py`) — two new MCP tools that ingest a Facebook data export and cross-reference it against LinkedIn connections and the internal people tracker to surface relationship signals across platforms:
  - `run_contact_crossref(fb_folder?)` — reads four Facebook export files (`your_friends.json`, `sent_friend_requests.json`, `received_friend_requests.json`, `removed_friends.json`), matches names against `linkedin_connections.json` and `people.json` using normalized name matching with middle-name and diacritic variance, writes a full multi-platform registry to `data/contact_crossref.json`, and updates each LinkedIn connection record with a `facebook_match` block. Re-runnable on any fresh export. Defaults to `fb_friends_folder` in `config.json`; accepts an explicit path override.
  - `get_contact_crossref(insight?, name?)` — query the stored registry by insight bucket (`all_three_platforms`, `fb_friend_and_linkedin`, `fb_friend_and_internal`, `linkedin_and_internal_no_fb`, `fb_pending_sent_on_linkedin`, `fb_pending_received_on_linkedin`, `fb_removed_still_on_linkedin`, `linkedin_only`, `fb_friend_only`, `internal_only`) or look up any individual contact by name (partial match supported). Returns platform presence, relationship types, and action hints per contact. Returns a full summary with bucket counts when called with no arguments.
- **`fb_friends_folder` config key** — optional path to your Facebook export folder; set in `config.json` so `run_contact_crossref()` can be called with no arguments. Added to `config.example.json`, `lib/config.py`, and `server.py` `_sync_config_exports()`.
- **`data/contact_crossref.json`** runtime data file (gitignored) + `data/contact_crossref.example.json` reference schema.
- **`data/linkedin_connections.json`** runtime data file (gitignored) + `data/linkedin_connections.example.json` reference schema — stores parsed LinkedIn connections with per-record `facebook_match` metadata populated after crossref.
- **`data/Connections.csv`** (raw LinkedIn export) added to `.gitignore`.
- **`tests/test_crossref.py`** — 40 tests covering name normalization, diacritic stripping, middle-name variance, FB index signal priority (friend > pending_received > pending_sent > removed), all lookup paths, all 6 action hint variants, and all 13 integration scenarios for `run_contact_crossref` and `get_contact_crossref`; 40/40 passing in 0.10s.

## [0.6.2] - 2026-05-11

### Added
- **Interview tracking tool family** (`tools/interviews.py`) — three new MCP tools for capturing structured debriefs after recruiter screens, hiring manager calls, panels, and onsite loops:
  - `log_interview(company, role, interview_date, interview_type, interviewer, ...)` — adds or updates a structured record keyed on `(company, interview_date)`. Captures `what_landed`, `what_didnt`, `verbatim_quotes` (with speaker + context), `surfaced_priorities` (HM-stated priorities absent from the JD), `process_details`, `comp_signals`, `follow_up_commitments`, `self_rating`, `tags`, and `notes`. Validates `interview_type` against a known set (`recruiter_screen`, `hiring_manager`, `technical_phone`, `panel`, `onsite`, `system_design`, `coding`, `behavioral`, `bar_raiser`, `other`) and `interview_format` against `phone | video | in_person | async`.
  - `get_interviews(company?, role?, interview_type?, since?, limit?)` — retrieves stored interviews with filters; returns most-recent-first.
  - `get_interview_context(company, role?)` — assembles all interviews for a company/role into a single context block (verbatim quotes, surfaced priorities, follow-ups) for injection into prep, fitment, resume, and cover letter generation.
- **Auto-pull of interview context** in `assess_job_fitment()`, `generate_resume()`, and `generate_cover_letter()` — when a matching `(company, role)` interview record exists, its context block is appended to the model prompt automatically. Prevents the model from re-asking what the HM already told you.
- **`data/interviews.json`** runtime data file (gitignored) + `data/interviews.example.json` reference schema; wired through `lib/config.py` and `server.py` `_sync_config_exports()`.
- **`tests/test_interviews.py`** — covers add, update-by-key, filtering, validation, and context assembly.

### Fixed
- **`github:` line bleeding into resume synopsis** — `_parse_header()` in `tools/export.py` now skips `github`, `address`, `location`, and `city_state` contact lines (in addition to the existing `phone`, `email`, `linkedin` skips) so they don't get rendered as the first paragraph of the synopsis section.
- **Cover letter body font size** — bumped from 9.2pt to 10.5pt in `templates/cover_letter.html` for readability at print scale.
- **Bold rendering on recognition lines** — adopted the `Label: description` prefix pattern in resume `LEADERSHIP & RECOGNITION` blocks so the prefix renders bold via the existing template rule.

## [0.6.1] - 2026-03-06

### Fixed
- **Cover letter closing** — sign-off changed from `Sincerely,` to `Kindest Regards,`; new rule in `_COVER_LETTER_FORMAT_SPEC` instructs the model to sign the name in Title Case (not ALL CAPS) with the name on its own line below the closing
- **Filename casing (`name.title()` bug)** — `_safe_filename()` was calling `.title()` on the name from config, mangling roman numerals: "Frank Vladmir MacBride III" → "Frank Vladmir Macbride Iii"; removed the `.title()` call; the name in `config.json` is now used verbatim
- **"Kindest Regards, Name" merged on one line** — `_parse_cover_letter_txt()` in `export.py` now detects closing salutations (`Kindest Regards,`, `Sincerely,`, `Best Regards,`, `Best,`) merged with the signature on the same line and splits them into separate paragraphs for correct PDF rendering

### Added
- **GitHub in cover letter contact block** — `github` field added to `_get_contact_defaults()` and `_extract_contact()` in `export.py`; `templates/cover_letter.html` sidebar now renders a GitHub row when the field is non-empty; `_build_cover_letter_user_message()` already injected the field from config
- **`run_generate.py`** — CLI runner script for agent-driven generation; reads the JD from a file instead of inline Python strings (avoids terminal heredoc mangling by the VS Code Copilot chat tool); auto-resolves JDs from `workspace/jds/` by company name when no explicit path is given; usage: `python run_generate.py cover "Company" "Role" [jd_file]`
- **`workspace/jds/`** — new directory for persisting job descriptions by company; covered by the existing `workspace/` gitignore; enables no-argument regeneration: `python run_generate.py cover "Meta" "Software Engineer, Infrastructure"`
- **"zero downtime" added to master resume Azure bullet** — Azure migration bullet in `Frank MacBride Resume - MASTER SOURCE WITH METRICS.txt` now explicitly states "achieving zero downtime"; flows into all future resume and cover letter generations automatically

## [0.6.0] - 2026-02-28

### Added
- **Docker support** — multi-stage `Dockerfile` (`python:3.12-slim` / Debian trixie), `docker-compose.yml` with volume mounts for `config.json`, `data/`, `RESUME_PATH`, and `LEETCODE_PATH`; `MCP_TRANSPORT` env var switches the server between `stdio` (default), `sse`, and `streamable-http`; `MCP_HOST` and `MCP_PORT` configurable for SSE/HTTP deployments. Single-command startup: `docker compose up`.
- **`tools.json`** — static 52-tool manifest for Docker MCP Registry CI compliance; auto-introspected from FastMCP at registration time so CI doesn't need a live server.
- **MIT LICENSE** — required for Docker MCP Registry submission.
- **`cli.py` `@file` / `@-` stdin support** — JSON args can now be passed as `@/path/to/args.json` or piped via stdin (`echo '{}' | python3 cli.py tool @-`); improves scripted workflows and CI integration.
- **`save_job_assessment` `source` parameter** — optional subfolder organiser; assessments saved to `07-Job-Assessments/<source>/` when provided, keeping the directory clean across multiple intake flows.
- **Cover letter assessment strategy injection** — `generate_cover_letter()` now scans `07-Job-Assessments/` for a matching assessment file and extracts the `## Cover Letter Strategy` section, injecting it as a mandatory override block in the GPT-4o prompt; ensures company-specific positioning is always respected.
- **`setup_workspace(name, email, phone, linkedin, city_state, master_resume_content, ...)`** — conversational workspace bootstrapper; creates `config.json`, all 7 data files, resume folders `01–08`, and a LeetCode workspace scaffolded for the user's preferred language (java / python / javascript / typescript / cpp). Idempotent — skips everything that already exists. User can drag their existing resume into the chat and pass the text as `master_resume_content`. After one call, `get_session_context()` and `generate_resume()` are fully operational.
- **`check_workspace()`** — read-only diagnostic scan; reports present/missing config, data files, resume subdirs, master resume word count, OpenAI key status, and LeetCode language. Safe to call at any time. Directs user to `setup_workspace()` with the minimum required parameters if anything is missing.
- **`run_hbdi_assessment(q1, q2, q3, q4, score_a, score_b, score_c, score_d, notes?)`** — HBDI (Herrmann Whole Brain Model) cognitive style profiler; takes answers to 4 guided questions + quadrant scores (A/B/C/D, 1–4); synthesizes dominant/secondary/weaponized quadrant patterns; generates interview framing advice calibrated to the primary quadrant (e.g. flip order for A-dominant interviewers, name B gap with tooling strategy); persists profile to `personal_context.json` under `hbdi_profile` key.
- **`get_hbdi_profile()`** — retrieves the stored HBDI profile with full synthesis and framing advice; prompts to run assessment if none recorded.
- **`lib/config.py` — optional key hardening**: all reference material path keys (`leetcode_cheatsheet_path`, `quick_reference_path`, `resume_template_png`, etc.) now use `.get()` with safe defaults instead of hard `[]` access; a fresh `config.json` generated by `setup_workspace()` no longer requires these keys to be populated.
- **`workspace/` gitignored** — the consolidated workspace directory (`workspace/resumes/`, `workspace/leetcode/`) is gitignored so user data never gets committed on a fresh clone.
- **`cli.py` — first-class MCP client**: `python3 cli.py <tool> [json_kwargs]` dispatches to any of the 52 registered MCP tools without an AI client; supports `--list` to enumerate all tools with signatures; supports `@file` and `@-` for reading JSON args from a file or stdin. This makes jobContextMCP a capability gateway — automation scripts, cron jobs, and CI pipelines can consume the same tools as Claude or Copilot. The AI is one type of client, not the only one. Eliminates the temp-script workaround for scripted updates and development workflows.
- 20 new tests in `tests/test_setup.py`, 15 new tests in `tests/test_hbdi.py` — 262 → 277 passing.

### Planned — v0.7
- **`get_github_stats()` repo traffic sync**: hits the GitHub API to pull clone counts, unique visitors, stars, and
  views for configured repos; surfaces in daily digest when numbers change; eliminates hardcoded stats in profile READMEs
- **`get_upcoming_interviews()` interview countdown**: cross-references application events with scheduled dates;
  returns days-until, prep checklist status, and a readiness score per upcoming interview; surfaces in daily digest
- **`get_referral_chains()` referral graph**: lightweight relationship graph over existing contacts data; surfaces
  connected threads (e.g. Cheyenne → FanDuel, Pat → camera feature) so warm paths don't get lost in a flat contact list
- **`draft_reply()` reply drafter**: context-aware follow-up reply tool; takes prior thread text + intent and generates
  a response in Frank's voice — distinct from `draft_outreach_message()` which handles cold/first contact only
- **Scheduled triggers via `cli.py`**: cron-driven daily digest push (e.g. `get_daily_digest()` at 8am without opening a chat); demonstrates the agent-optional architecture — the capability layer runs on a schedule, the AI is never in the loop unless you want it to be
- **Honcho persistent memory layer** (opt-in, API cost): seeds STAR stories, tone samples, and contact context into Honcho on ingest; generation calls query Honcho before building the GPT-4o prompt so the model has cross-session memory without re-reading every JSON file; gated behind `honcho_api_key` in `config.json` — all existing workflows unchanged when key is absent

## [0.5.2] - 2026-02-26

### Added
- **`ingest_anecdote(story, tags, title?, people?, tone_sample?)`** — intent-level bundler that routes a story or anecdote to all relevant stores in one call: writes to `personal_context.json` (always), ingests into `tone_samples.json` (if `tone_sample=True` and ≥40 words), and detects STAR interview tags so the caller knows the story will surface in `get_star_story_context()` queries. Replaces the pattern of calling `log_personal_story` + `log_tone_sample` manually.
- 8 new tests in `tests/test_ingest.py` — 234 → 242 passing.

## [0.5.1] - 2026-02-26

### Fixed
- **`data/rejections.json` missing from `.gitignore`** — file introduced in v0.5.0 was not gitignored; added alongside all other private data files
- **Silent startup failure on missing data files** — server would crash on startup with no useful error if any required data file was absent (symptom: VS Code reports "tool not contributed"); README step 4 now includes an explicit warning with all required files listed
- **VS Code "Add MCP Server" UI conflict** — using the VS Code UI to register the server writes a broken global `mcp.json` entry (`python` instead of `python3`, no `cwd`) that silently conflicts with the workspace config causing intermittent tool failures; README step 5 now warns against this flow and documents the fix (remove the duplicate `jobContextMCP` entry from `~/Library/Application Support/Code/User/mcp.json`)

## [0.5.0] - 2026-02-25

### Added — v4 feature sprint (all issues closed)

- **`log_rejection(company, role, stage, reason?, notes?, date?)`** — structured rejection tracker; persists to `data/rejections.json`; auto-assigns sequential IDs
- **`get_rejections(company?, stage?, since?, include_pattern_analysis?)`** — retrieves rejections with optional filters; includes pattern analysis (stage breakdown, multi-rejection companies, reason frequency, early-funnel bottleneck flag) when ≥2 results
- **`log_application_event(company, role, event_type, notes?)`** — append-only event log per application; events stored under `applications[].events` array in `status.json`; types: `applied`, `phone_screen`, `technical_screen`, `take_home`, `onsite`, `offer`, `rejected`, `withdrew`, `follow_up`, `note`, `referral_submitted`, `recruiter_contact`, `hiring_manager_contact`
- **`get_daily_digest()`** — morning briefing: pipeline snapshot, overdue/due-today follow-ups, stale applications (7+ days), recent rejections (past 7 days), drafted-but-unsent contact messages, 3 auto-generated focus priorities, health nudge
- **`weekly_summary()`** — 7-day aggregate: new/updated apps, rejection count with stage breakdown, contacts added, mental health trend (avg energy, mood distribution, productive days)
- **`update_compensation(company, role, base?, equity_total?, equity_vest_years?, bonus_target_pct?, level?, location?, remote?, notes?)`** — adds/updates comp block on a tracked application; computes annual equity + bonus amount + total comp estimate
- **`get_compensation_comparison()`** — side-by-side compensation table for all apps with comp data; sorted descending by total comp estimate; highlights best offer
- **`resume_diff(file_a, file_b)`** — human-readable unified diff between two resume `.txt` files from `01-Current-Optimized/`; supports `ref:filename` prefix to resolve against `06-Reference-Materials/`; shows added/removed line counts in summary header
- **`review_message(text)`** — tone/sentiment review for outreach drafts; detects corporate stiffness phrases, desperation signals, hedging language, weak openers, missing calls to action; flags issues with emoji indicators; appends original text for reference

### Fixed

- **`update_application()` notes clobbering bug** (issue #2) — passing `notes=""` (default) no longer overwrites existing notes; non-empty `notes` parameter now appends with `[timestamp]` prefix instead of replacing
- New applications created by `update_application()` now include an empty `events: []` list for `log_application_event()` compatibility

### Tests

- **201 → 234 tests** — 33 new tests covering all v4 tools in `tests/test_v4_features.py`
- Updated `test_job_hunt_tools.py`: replaced clobber-notes test with append-behavior test; added `test_update_empty_notes_preserves_existing`

## [0.4.9.1] - 2026-02-24

### Changed
- **`scan_project_for_skills()` — multi-project support**: `side_project_folder` (single string) replaced by `side_project_folders` (array) in `config.json` and `config.example.json`; backward-compatible — single string still accepted
  - `config.py`: `SIDE_PROJECT_FOLDER` global replaced by `SIDE_PROJECT_FOLDERS: list[Path]`
  - `project_scanner.py`: rewritten to iterate over all configured folders; git pull and file scan run per-project; output shows per-project tech breakdown; new tech detected: `Model Context Protocol (MCP)`, `FastMCP`, `WeasyPrint / PDF generation`, `RAG / semantic search`
  - `server.py` and `tests/conftest.py` updated to `SIDE_PROJECT_FOLDERS`
  - README: config snippet and Workspace Structure section updated; `scan_project_for_skills()` description updated

### Added
- **Ingestion guide in README** — new "The System Is Only As Good As What You Feed It" section explaining that `get_session_context()` alone is insufficient; documents all five ingestion steps: `scan_materials_for_tone()`, `log_personal_story()`, peer feedback ingestion via `log_tone_sample()`, `reindex_materials()` after new files, and `scan_project_for_skills()` after sprints

## [0.4.9] - 2026-02-24

### Changed
- **Rebrand**: project renamed from `job-search-mcp` to `JobContextMCP`
  - FastMCP server key changed from `job-search-as` to `jobContextMCP`; MCP tool prefix is now `mcp_jobContextMCP_`
  - `.vscode/mcp.json` server key updated
  - README: title, banner (`docs/branding/banner/jobcontextmcp-readme.png`), Mermaid diagram label, clone URL, and setup snippet all updated
  - `copilot-instructions.example.md` and `.github/copilot-instructions.md` headers updated
  - Workspace `copilot-instructions.md` files (Resume 2025, LeetCodePractice) updated to new `jobContextMCP/` path
  - `JobSearch.code-workspace` folder path updated to `Projects/jobContextMCP`

### Fixed
- `requirements.txt` was missing `jinja2` and `weasyprint` — both required at runtime (PDF export); any fresh clone would fail to start without these
- Added `requirements-dev.txt` (`-r requirements.txt` + `pytest`, `pytest-cov`, `anyio`) so new contributors get the full dev environment in one command

### Added
- Branding assets committed to `docs/branding/`: logo SVG/PNG (light + dark), README banner SVG/PNG, favicons (16×16, 32×32)
- v5 strategy docs committed to `docs/jobContextMCP-FullDocs/`: roadmap, monetization strategy, backlog, marketing plan, branding guidelines

## [0.4.8] - 2026-02-24

### Added
- `tools/posts.py` — new LinkedIn post tracking module with three tools:
  - `log_linkedin_post(text, source, context?, posted_date?, url?, hashtags?, links?, title?, auto_log_tone?)` — add or update a post record; optionally auto-ingests full post text as a tone sample (default: True) so public writing voice calibrates outreach and cover letter drafts
  - `update_post_metrics(post_id?, source?, impressions?, members_reached?, reactions?, comments?, reposts?, saves?, link_clicks?, profile_views_from_post?, followers_gained?, audience_highlights?)` — patch engagement numbers and audience demographics by post ID or source slug; only provided fields are updated
  - `get_linkedin_posts(source?, hashtag?, min_reactions?, include_text?)` — filterable summary with aggregate stats across all posts
- `data/linkedin_posts.json` — post store with full metrics schema (impressions, reach, reactions, comments, reposts, saves, link clicks, profile views, followers gained, audience demographics); pre-loaded with 7 posts dating back to January 2022
- `data/linkedin_posts.example.json` — sanitized example for new users
- `lib/config.py` — `LINKEDIN_POSTS_FILE` path global added
- `server.py` — `posts` module imported, registered, and `log_linkedin_post` / `update_post_metrics` / `get_linkedin_posts` exposed as module-level aliases

## [0.4.7] - 2026-02-23

### Added
- `save_interview_prep(company, content, filename?)` — saves generated interview prep documents to
  the LeetCode folder as `.md` files; filename defaults to `{COMPANY}_INTERVIEW_PREP.md`; strips
  trailing whitespace per line; overwrites existing files so AI-generated prep can be iteratively
  improved without manual file management
- **Follow-up reminder system** — `get_job_hunt_status()` now parses `next_steps` fields for
  date references (`Feb 24`, `~Feb 25`, etc.) and surfaces a `⚠ FOLLOW-UP ACTIONS DUE` section
  for any application whose follow-up date is today or past; dates are compared against today's
  date with automatic year rollover for months already passed
- **`git pull` before skill scan** — `scan_project_for_skills()` now runs `git -C <side_project_folder> pull`
  before scanning so stale local checkouts don't produce outdated or missing resume bullets; pull
  status shown in scan output; timeouts and errors are caught gracefully and reported without
  interrupting the scan

### Fixed
- `get_existing_prep_file()` — was only searching `RESUME_FOLDER`; now searches both
  `RESUME_FOLDER` and `LEETCODE_FOLDER` (matching the documented behavior in the tool description);
  deduplicates results by path so the same file is never shown twice

### Tests
- 19 new tests: `TestSaveInterviewPrep` (8 cases), `TestFollowUpReminders` (10 cases),
  `test_get_existing_prep_file_finds_md_in_leetcode_folder`, `test_get_existing_prep_file_finds_in_both_folders`
- Total: 153 tests (up from 134)

## [0.4.6] - 2026-02-22

### Changed
- `scan_spicam_for_skills()` renamed to `scan_project_for_skills()` — tool was named after a personal project; generic name makes the intent clear for any user
- `tools/spicam.py` → `tools/project_scanner.py`
- `spicam_folder` config key → `side_project_folder` in `config.json`, `config.example.json`, and `lib/config.py`
- `SPICAM_FOLDER` → `SIDE_PROJECT_FOLDER` throughout `lib/config.py` and `server.py`
- Scanner output header updated: "RETROSPICAM SKILL SCAN" → "SIDE PROJECT SKILL SCAN"
- `copilot-instructions.example.md` and all workspace `.github/copilot-instructions.md` files updated to new tool name

## [0.4.5] - 2026-02-22

### Added
- `tools/generate.py` — new `generate_resume(company, role, job_description)` and `generate_cover_letter(company, role, job_description)` tools
  - If `openai_api_key` is configured in `config.json`: calls OpenAI API (model: `openai_model`, default `gpt-4o-mini`), auto-saves `.txt` via `save_resume_txt` / `save_cover_letter_txt`, and auto-exports PDF; returns finished PDF path + token/cost summary
  - If no API key: returns a fully-structured context package (master resume + tone profile + fitment strategy + exact format spec) for Copilot / Claude to handle the writing step
  - `_infer_role_type()` maps job title keywords to customization strategy types automatically
  - `_RESUME_FORMAT_SPEC` and `_COVER_LETTER_FORMAT_SPEC` document all PDF parser constraints in one place; referenced from README
  - Temperature: 0.3 (resume), 0.4 (cover letter) for consistent structured output
  - Cost estimate returned in tool output: based on gpt-4o-mini pricing ($0.15/$0.60 per 1M in/out)
- `config.example.json`: `openai_model` key added (default `gpt-4o-mini`); documents `openai_api_key` pairing
- `server.py`: `generate` module imported, registered, and `generate_resume` / `generate_cover_letter` exposed as module-level aliases
- README: **AI Resume & Cover Letter Generation** section added documenting both modes, cost, and all system constraints for resume and cover letter format

## [0.4.4] - 2026-02-22

### Added
- `.vscode/mcp.json` committed to repo — server now auto-starts when the workspace opens in VS Code; no manual "Start" click required
- Identical `mcp.json` placed in `Resume 2025/.vscode/` so the server auto-starts from the Resume workspace window as well
- README: new **Workspace Structure** section documenting the full multi-root layout (job-search-mcp, Resume 2025, LeetCodePractice, LiveVoxWeb, LiveVoxNative, RetrosPiCam) and the role of each folder at runtime
- README: **Connect to VS Code** section rewritten to reflect auto-start behavior and multi-root `mcp.json` placement strategy
- README: **Demo** section added with links to demo `.txt` source files so new users can preview the PDF output without using real resume data
- LeetCodePractice `copilot-instructions.md`: removed outdated 5-step manual "click Start" instructions now that auto-start is in place
- `config.json` now requires a `contact` block (`name`, `phone`, `email`, `linkedin`, `address`, `city_state`, `location`) — moves all PII out of source and into the gitignored config file; `config.example.json` updated with placeholder values
- Demo files added for README screenshots: `01-Current-Optimized/Nobody MacFakename Resume - Demo Software Engineer.txt` and `02-Cover-Letters/Nobody MacFakename Cover Letter - Demo Software Engineer.txt` — fully fake contact info, safe to commit

### Fixed
- `tools/export.py` — `_CONTACT_DEFAULTS` hardcoded dict removed; replaced with `_get_contact_defaults()` reading from `config._cfg["contact"]` so no PII lives in source code
- `tools/export.py` `_extract_contact` — added labeled-field parsing for `address:`, `city_state:`, and `location:` lines so demo/custom txt files can supply their own contact info without falling through to config defaults
- `tools/export.py` `_parse_resume_txt` — added `_OPENING_TAG_RE` to strip `<NAME>` wrapper tags before parsing; extracts `tag_name` from the opening tag as a name fallback; name resolution order: explicit header line → tag name → `config.contact.name`
- Demo txt `Nobody MacFakename Resume` — missing explicit name line after `<NOBODY MACFAKENAME>` wrapper caused the headline to be parsed as the name; added `NOBODY MACFAKENAME` as first content line so the header renders correctly
- `tools/export.py` `_parse_skills_section` — hyphen missing from character class caused `Event-Driven & Messaging` to lose its label and render as `: Event-Driven...`; added `-` to `[A-Za-z0-9 &/\(\)_\-]`
- `tools/export.py` `_parse_education_section` — `details` was a single `" | "`-joined string; changed to `list[str]` so each coursework line renders as a separate indented bullet in the PDF
- `tools/export.py` `_strip_separator_lines` — only matched Unicode `─────` box-drawing chars; updated to `[-─*=]{3,}` so ASCII `---` separators are also stripped before body parsing
- `tools/export.py` `_parse_cover_letter_txt` — `Dear Hiring Manager,` (< 60 chars) was being dropped as header noise before the body-start trigger; `Dear...` lines now unconditionally trigger body start regardless of length
- `tools/export.py` `_render_pdf` — `footer_tag` values with spaces were not normalized; now auto-replaces spaces with underscores so the closing bracket always renders as `</SOFTWARE_ENGINEER>`
- `tools/export.py` `export_cover_letter_pdf` — now passes `footer_tag="SOFTWARE_ENGINEER"` explicitly so all cover letter PDFs get the correct footer tag
- `templates/resume.html` — `.tagline` CSS + `{% if tagline %}` block added; `.skill-lbl` now only renders when `item.label` is non-empty (prevents phantom colons for unlabeled skill groups); education `details` iterates a list with per-line `.edu-bullet` indentation
- `templates/cover_letter.html` — all heights changed from `11in` to `10.48in` to prevent overflow; `@page` margin set to `0 0 0.52in 0`; `@bottom-right` gets `margin-right: 0.48in` for proper inset tag positioning

## [0.4.3] - 2026-02-22

### Added
- `lib/io._load_master_context()` — bundles master resume + GM Recognition Awards + peer feedback verbatim into one enriched context block; used by `fitment`, `interview`, `resume`, `outreach`, and `session` tools so recognition quotes and peer feedback are always available when the AI drafts application materials
- `tools/people.py` — contact/relationship tracking tool (`log_person`) for recruiters, hiring managers, referrals, and connections
- `tools/session.py` — `get_session_context()` single-call session startup: returns master resume (with awards + feedback), tone profile, personal stories, and live job hunt status in one shot; registered first so it's always the top tool in Copilot
- `data/people.json` added to `.gitignore`

### Fixed
- **Tests: 134/134 passing** — `tests/conftest.py` `fake_cfg`/`original_cfg` was missing 6 config keys added in v0.4.0 (`resume_template_png`, `cover_letter_template_png`, `template_format_path`, `gm_awards_path`, `feedback_received_path`, `skills_shorter_path`); `server.py` `_sync_config_exports()` was not re-exporting those same globals, causing `AttributeError` on test teardown
- **PDF export — experience parser rewrite** — `_parse_experience_section()` now uses an `after_blank` flag as the canonical job-boundary signal; previous `had_bullets` approach caused the second plain-text bullet to be treated as a new job title
- **PDF export — date detection** — `_is_date_part()` replaces `_is_date_line()` (which had an 85-char limit); checks only the last pipe-segment so `General Motors - Georgia IT Innovation Center, Atlanta, GA | January 2024 - December 2025` (89 chars) now finalizes correctly
- **PDF export — plain-text bullets** — bullet lines without a `•` prefix (common in MCP-saved `.txt` resumes) are now captured as implicit bullets after the job header is finalized
- **PDF export — education parser** — `_parse_education_section()` now handles compact pipe format `Degree | School | Year` on a single line
- **PDF export — section classifier** — `_classify_section()` now maps `KEY ACHIEVEMENTS` and `CERTIFICATIONS` sections to `leadership` type instead of falling through to generic `text`
- **PDF export — encoding** — both `export_resume_pdf` and `export_cover_letter_pdf` now fall back to `latin-1` when a `.txt` file is not valid UTF-8
- **Cover letter template** — closing `>` bracket now renders gray (`#6b6b6b`) to match Canva reference design
- **`_finalize_job()`** — now handles 2-part pipe pattern `Company | Dates` (previously only 3-part `Title | Company | Dates` was fast-pathed)
- **`config.example.json`** — updated to document the 6 new path keys added in v0.4.0

## [0.4.2] - 2026-02-21

### Fixed
- `server.py` — unterminated triple-quoted docstring (missing closing `"""`) caused server to crash with `SyntaxError` on startup; all tools appeared disabled in VS Code
- All 22 tool functions across 10 modules (`job_hunt`, `resume`, `fitment`, `interview`, `spicam`, `health`, `star`, `tone`, `rag`, `context`) were missing docstrings, causing VS Code MCP to warn "Tool does not have a description" and refuse to call them; added accurate descriptions to every tool

## [0.4.1] - 2026-02-21

### Fixed
- `templates/resume.html` — increased bottom page margin (`0.42in` → `0.52in`) and changed footer `vertical-align` from `bottom` to `middle` so the `</ROLE>` tag no longer sits flush against the paper edge
- `templates/cover_letter.html` — name sidebar font size bumped from `15pt` to `18pt` for better visual weight
- `tools/export.py` `_parse_cover_letter_txt` — salutation lines (`Dear …`, `To whom …`, `Hello`, `Hi`) were being mistakenly parsed as the author's name; now excluded from name detection and correctly fall back to the hardcoded default
- `tools/export.py` — closing salutation now normalised to `"Kindest regards,"` on its own line with `"Frank Vladmir MacBride III"` as a separate line below; replaces the old single-line `"Best regards, Frank V. MacBride III"` across all cover letters
- `tools/export.py` — full middle name **Vladmir** added to the cover-letter sidebar default (`FRANK VLADMIR MACBRIDE III`) and all generated signatures

## [0.4.0] - 2026-02-21

### Added
- `draft_outreach_message(contact, company, context, message_type?)` — packages tone profile, personal context, application status, and message-type-specific writing instructions so the AI can draft ready-to-send outreach in Frank's voice; supports `linkedin_followup`, `thank_you`, `referral_ask`, `recruiter_nudge`, and `cold_outreach`; auto-detects message type from context when not specified
- `export_resume_pdf(filename, footer_tag?, output_filename?)` — parses a `.txt` resume from `01-Current-Optimized/` and renders a pixel-perfect PDF matching the Courier New / code-aesthetic template (header bracket `<NAME>`, section underlines, `</ROLE>` footer tag); renders via Jinja2 + WeasyPrint
- `export_cover_letter_pdf(filename, output_filename?)` — parses a `.txt` cover letter from `02-Cover-Letters/` and renders a PDF with the two-column sidebar layout (stacked name, bracket aesthetic, contact block); PDFs land in `03-Resume-PDFs/`
- `tools/outreach.py` module — new tool module following the `register(mcp)` pattern
- `tools/export.py` module — resume/cover-letter parser + WeasyPrint renderer; `templates/resume.html` and `templates/cover_letter.html` are Jinja2 templates matching the Canva design
- **System dep:** `pango` (Homebrew) required by WeasyPrint on macOS (`brew install pango`)

## [0.3.0] - 2026-02-21

### Added
- **Modular architecture** — split monolithic `server.py` (1200+ lines) into `lib/` (config, I/O, pure helpers) and `tools/` packages (11 modules), each with a `register(mcp)` pattern; `server.py` is now a thin ~120-line orchestrator
- `log_personal_story(story, tags, people?, title?)` — log personal STAR stories with tags and optional people/title metadata
- `get_personal_context(tag?, person?)` — retrieve stories filtered by tag or person
- `log_tone_sample(text, source, context?)` — ingest a writing sample to teach tone/voice
- `get_tone_profile()` — retrieve all tone samples for AI drafting context
- `scan_materials_for_tone(category?)` — auto-scan resumes, cover letters, and prep files to index new tone samples; persists a scan index to avoid re-ingesting unchanged files
- `get_star_story_context(tag, company?, role_type?)` — retrieve matching STAR stories, derived metric bullets (via tag chains), and company-specific framing hints in one call
- **Implied daily check-in nudge** — `get_job_hunt_status()` appends a reminder to log a mental health check-in if none exists for today
- **Test coverage** — 134 tests, 69% total coverage across `server`, `lib`, and `tools`; `pyproject.toml` now tracks all three sources with `fail_under = 50`

### Changed
- `server.py` re-exports all tool functions + path globals for backward compatibility with existing test fixtures
- `lib/config._load_config()` now falls back to `config.example.json` when `config.json` is absent — clean clones and CI no longer crash on import
- `log_personal_story` `people` parameter changed from mutable default `[]` to `None` (normalized inside the function) — fixes classic Python mutable-default-argument bug

### Fixed
- Resolved all 3 Copilot automated code review suggestions from PR #10: mutable default argument, eager config load in CI, and misleading conftest docstring

## [0.2.0] - 2026-02-20

### Added
- **RAG semantic search** (`rag.py`) — chunks and embeds all job search materials using OpenAI `text-embedding-3-small`
- `search_materials(query, category?, n_results?)` MCP tool — returns ranked chunks across resume, cover letters, LeetCode, interview prep, and reference files
- `reindex_materials()` MCP tool — rebuilds the full semantic index on demand
- Pure numpy cosine similarity search — no external vector database required

### Changed
- Replaced ChromaDB with numpy + JSON — fully compatible with Python 3.14 (ChromaDB uses Pydantic V1, which is incompatible)
- Updated README setup instructions to include `openai` and `numpy` in the install step

### Dependencies
- Added: `openai>=1.0.0`, `numpy>=1.24.0`
- Removed: `chromadb` (incompatible with Python 3.14)

---

## [0.1.0] - 2026-02-19

### Added
- Initial release — 15-tool FastMCP server for persistent job search context
- `get_job_hunt_status()` — live application pipeline
- `update_application()` — add/update applications with status, notes, contacts
- `read_master_resume()` — full master resume with all metrics and achievements
- `assess_job_fitment(company, role, jd)` — packages resume + JD for fitment analysis
- `get_customization_strategy(role_type)` — resume emphasis strategy by role type
- `generate_interview_prep_context(company, role, stage)` — structured interview prep
- `get_leetcode_cheatsheet(section?)` — algorithm patterns reference
- `get_interview_quick_reference()` — STAR stories, system design framework, behavioral talking points
- `scan_spicam_for_skills()` — scans IoT side-project codebase for new resume skills
- `log_mental_health_checkin(mood, energy, ...)` — mood/energy logging
- `get_mental_health_log(days?)` — recent check-in history
- `list_existing_materials(company?)` — list resumes and cover letters
- `read_existing_resume(filename)` — read a specific resume file
- `read_reference_file(filename)` — read reference materials
- `get_existing_prep_file(company)` — read an interview prep document
- `config.json`-based path loading — no hardcoded paths in source
- Sanitized for public GitHub — `config.example.json`, example data templates, `.gitignore`
