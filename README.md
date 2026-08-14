<p align="center">
  <img src="docs/branding/banner/banner.svg" alt="jobContext — The memory layer for your career" width="860"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.4.0-blue" alt="Version 1.4.0"/>
  <img src="https://img.shields.io/badge/tests-1981%20passing-brightgreen" alt="1981 tests passing"/>
  <a href="https://sonarcloud.io/component_measures?id=JustLikeFrank3_jobContextMCP&metric=coverage"><img src="https://sonarcloud.io/api/project_badges/measure?project=JustLikeFrank3_jobContextMCP&metric=coverage" alt="Coverage"/></a>
  <img src="https://img.shields.io/badge/tools-12%20domains%20%C2%B7%2096%20actions-informational" alt="12 domain tools, 96 actions"/>
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT License"/>
  <img src="https://img.shields.io/badge/Works%20with-Oura%20Ring-00B5C8" alt="Works with Oura Ring"/>
</p>
<p align="center">
  <a href="https://sonarcloud.io/summary/new_code?id=JustLikeFrank3_jobContextMCP"><img src="https://sonarcloud.io/images/project_badges/sonarcloud-light.svg" alt="SonarQube Cloud"/></a>
</p>

# jobContext

The memory layer for your job search: a desktop app, a hosted cloud workspace, and a mobile companion built on one capability layer. Your resume, pipeline, interview history, outreach context, and portfolio live as structured context that persists across sessions — AI assistants (GitHub Copilot, Claude, Cursor, Windsurf, Zed) plug in over the [Model Context Protocol](https://modelcontextprotocol.io/), while the dashboard, CLI, and mobile app drive the same tools over HTTP. You never re-explain yourself from scratch.

Built in Python with [FastMCP](https://github.com/jlowin/fastmcp), FastAPI, SQLite (dual-write JSON audit trail), a React dashboard, WeasyPrint/LaTeX PDF export, and pluggable LLM generation (OpenAI, Azure AI Foundry, Anthropic Claude, or local Ollama — all BYOK, or run keyless and let your AI client do the writing).

> **The agent is optional.** MCP servers are protocol-driven capability layers — any client that speaks the protocol can call them. jobContext ships a CLI ([`cli.py`](cli.py)) that invokes the tool surface directly from the terminal, no AI client required. Automation scripts, CI pipelines, cron jobs, the web dashboard, and the mobile app consume the same capabilities as Claude or Copilot. The AI is one type of client, not the only one.

**Three ways to run it** — *desktop creates knowledge, mobile captures reality, cloud synchronizes*:

| | What | For |
|---|---|---|
| **Desktop** | Tauri 2 app with embedded chat, one-click MCP connect, local SQLite | Daily driver — everything stays on your machine |
| **Cloud** | Multi-tenant AKS deployment behind Entra ID ([jobcontext.ai](https://jobcontext.ai)) | Remote MCP for Claude.ai/Cursor, sync hub, always-on evals |
| **Mobile** | Expo companion app with share-sheet capture | Queue + assess jobs from your phone, Career Inbox |

---

## TL;DR

jobContext keeps your job-search context structured and persistent, and exposes it every way you work: MCP tools for AI assistants, HTTP APIs for automation, a web dashboard, a desktop app, and a mobile companion.

| | |
|---|---|
| 12 MCP tools | 96 domain actions behind them |
| 1981 passing tests | Resume + cover letter generation with a deterministic truth gate |
| SQLite persistence + JSON audit trail | Job fitment analysis with persona lenses |
| Local RAG semantic search | Interview prep + debrief logging |
| Desktop app (macOS · Windows · Linux) | Outreach + relationship tracking |
| Azure AKS multi-tenant deployment | Three-layer eval framework with LLM-as-judge |
| Journal-based desktop ⇄ cloud sync | Prometheus + Grafana observability |

**Works with:** GitHub Copilot · VS Code · Claude Desktop · Claude.ai · Cursor · Windsurf · Zed · HTTP clients · CLI automation

---

## Why I Built This

I got laid off and started using AI assistants to manage my job search. Every new session started from zero. I was re-explaining my resume, my pipeline, which companies I'd already talked to, what my STAR stories were, how I was holding up. The context overhead was brutal on top of everything else.

I built a few tools to stop re-explaining myself. They grew into this.

If you're in the same situation, it's yours.

---

## jobContext Desktop

The whole platform as a native app — no terminal, no Python, no account.
Download, drag to Applications (or run the installer), double-click.

**[⬇ Download the latest desktop release](https://github.com/JustLikeFrank3/jobContextMCP/releases?q=desktop&expanded=true)** — look for the newest `desktop-v*` tag.

| Platform | File | Notes |
|----------|------|-------|
| macOS (Apple Silicon) | `jobContext_*_aarch64.dmg` | Signed + notarized |
| macOS (Intel) | `jobContext_*_x64.dmg` | Signed + notarized |
| Windows | `jobContext_*_x64-setup.exe` | Per-user install (unsigned — SmartScreen will warn) |
| Linux | `.AppImage` / `.deb` | AppImage auto-updates; deb is manual |

On top of the server you get an **embedded AI chat** over your own job-search data (OpenAI/Anthropic BYOK or local Ollama), **one-click MCP connect** for Claude Desktop / VS Code / Cursor, **cloud workspace import/export**, **desktop ⇄ cloud sync**, Oura readiness, and **automatic updates**. Everything stays on your machine: local SQLite, loopback-only server, keys in your local config.

| | |
|---|---|
| ![Desktop — Home](docs/images/desktop/home.png) | ![Desktop — Chat](docs/images/desktop/chat.png) |
| Home: the same command center as the cloud, running against local SQLite | Chat: embedded AI over your own data — here on a local Ollama model, no keys, no cloud |

Architecture, build docs, and the full decision log: [desktop/README.md](desktop/README.md).

---

## jobContext Mobile — iOS beta (TestFlight)

The Expo companion app, now in TestFlight beta. *Desktop creates knowledge, mobile captures reality*: share a job posting from Safari or LinkedIn straight into your pipeline (pages are extracted on-device, so it reads postings that block datacenter IPs), triage what's awaiting assessment, log a wellbeing check-in from the couch. It talks to your cloud workspace with an API key from the dashboard's API Keys tab — paste it once into Settings and it lives in the device keychain. Everything it captures syncs back to desktop.

| | | | |
|---|---|---|---|
| ![Mobile — splash](docs/images/mobile/splash.png) | ![Mobile — Home](docs/images/mobile/home.png) | ![Mobile — Pipeline](docs/images/mobile/pipeline.png) | ![Mobile — Wellbeing](docs/images/mobile/wellbeing.png) |
| Restoring your context | Home: today's priority + readiness | Pipeline: assessed vs awaiting | Wellbeing: check-ins + Oura |

Screens, capture flow, and build/ship docs: [mobile/README.md](mobile/README.md).

---

## Output

### The dashboard

The same React SPA serves the desktop app and the cloud ([app.jobcontext.ai](https://app.jobcontext.ai)) — these captures are the live cloud workspace, synced from desktop and mobile. Screens: Home, Pipeline, Job Hunt, Materials, Interviews, People (with a liveness-aware follow-up queue), Posts, Rejections, Wellbeing, Chat (desktop), Settings, and API Keys.

![Home — your career command center](docs/images/dashboard/home.png)
*Home: active/in-flight counts, dismissible priorities, daily digest, and Oura readiness driving "today's move".*

| | |
|---|---|
| ![Pipeline](docs/images/dashboard/pipeline.png) | ![Job Hunt Tracker](docs/images/dashboard/job-hunt.png) |
| Pipeline: intake → assessment (fitment score + signals) → generate → queue apply, with per-job templates and AI edit dialogs | Job Hunt Tracker: applications kanban from outreach through offer |
| ![Wellbeing](docs/images/dashboard/wellbeing.png) | ![Settings](docs/images/dashboard/settings.png) |
| Wellbeing: mood/energy check-ins beside Oura readiness | Settings: AI provider status, Oura connection, one-click workspace export |

### Generated documents

Generated from plain `.txt` files — no design tools. Templates live in `templates/` and render via WeasyPrint; an owner-only LaTeX pipeline (Tectonic) handles typeset output.

### Resume template gallery

4 layout formats x 5 color themes = 20 variants. All consume the same resume data; only the presentation changes. Template and theme are selected per-job in the pipeline.

| Sidebar resume | Sidebar cover letter |
|----------------|----------------------|
| ![Sidebar resume](docs/demo/demo_resume_sidebar.png) | ![Sidebar cover letter](docs/demo/demo_coverletter_sidebar.png) |
| Two-column: contact/skills sidebar + experience/projects main | Matching sidebar layout for the cover letter |

| Modern resume | Modern cover letter |
|---------------|---------------------|
| ![Modern resume](docs/demo/demo_resume_modern.png) | ![Modern cover letter](docs/demo/demo_coverletter_modern.png) |
| Single-column, ATS-friendly, clean typography | Clean header band, flush prose paragraphs |

| Executive resume | Executive cover letter |
|------------------|------------------------|
| ![Executive resume](docs/demo/demo_resume_executive_p1.png) | ![Executive cover letter](docs/demo/demo_coverletter_executive.png) |
| Centered letterhead, serif, achievement-focused | Matching executive letterhead |

| Portfolio resume | Portfolio cover letter |
|------------------|------------------------|
| ![Portfolio resume](docs/demo/demo_resume_portfolio.png) | ![Portfolio cover letter](docs/demo/demo_coverletter_portfolio.png) |
| Projects-first, GitHub-prominent, technical profile | Accent-strip header, project-centric intro |

Themes: **Navy** (default) · **Slate** · **Forest** · **Warm** · **Classic**

> **⚠️ No template selected?** If no template preference is saved in the pipeline, output falls back to the legacy format — Courier New, monospaced, hacker-tag header/footer. It's a genuine aesthetic choice if you want it. But if you haven't actively chosen it, your recruiter may have thoughts.
>
> | Legacy resume | Legacy cover letter |
> |---------------|---------------------|
> | ![Legacy resume](docs/demo/demo_resume_legacy.png) | ![Legacy cover letter](docs/demo/demo_coverletter_legacy.png) |
>
> Select a template in the pipeline and this will never happen to you.

---

## The Tool Surface

12 consolidated domain tools, 96 actions. Each tool takes an `action` parameter; its docstring documents every action's required and optional parameters. Full reference with per-action tables: **[docs/tools.md](docs/tools.md)**.

| Tool | Actions | Covers |
|---|---|---|
| `applications` | 10 | Pipeline status, evaluation queue, fitment assessments, application events |
| `job_search` | 4 | Open-web search, Greenhouse/Lever boards, URL scraping |
| `documents` | 13 | Resume/cover-letter generation, PDF + LaTeX export, diffs, strategy |
| `materials` | 9 | Master resume (read + audited in-place edit), saved materials, semantic search |
| `interviews` | 9 | Debrief logging, company process context, prep docs, cheatsheets |
| `people` | 10 | Contacts, referral chains, outreach drafting/review, cross-reference queue |
| `stories` | 10 | Personal stories, STAR context, writing-tone profile |
| `wellbeing` | 7 | Mood/energy check-ins, Oura readiness, HBDI profile |
| `brand` | 7 | LinkedIn post pipeline + metrics, GitHub/portfolio stats, skill scans |
| `insights` | 7 | Daily/weekly digests, session context, rejection funnel, comp comparison |
| `certification` | 8 | Weekly work-search certification reports, employer directory, portal-ready exports |
| `workspace` | 2 | Workspace diagnosis and zero-manual-setup creation |

A coverage test guarantees every capability of the historical 88-function surface is reachable through the facades; `JOBCONTEXT_LEGACY_TOOLS=1` restores the per-function surface if a client needs it.

### Architecture

```mermaid
flowchart LR
    subgraph Clients
        AI["MCP clients<br/>(Copilot · Claude · Cursor)"]
        WEB["Dashboard SPA + mobile app"]
        CLI["cli.py / scripts"]
    end
    subgraph Server
        TOOLS["12 MCP / CLI tools"]
        HTTP["FastAPI transport<br/>REST + SSE + /mcp"]
        WORK["Control plane<br/>(durable work_items)"]
        GATE["Provenance truth gate"]
        EVALS["Eval framework"]
    end
    subgraph Storage
        DB[("SQLite per partition")]
        WS[("Workspace files")]
        SYNC["Journal-based sync"]
    end
    AI -->|stdio / streamable-http| TOOLS
    WEB --> HTTP
    CLI --> TOOLS
    HTTP --> TOOLS
    HTTP --> WORK
    TOOLS --> GATE
    TOOLS --> DB
    TOOLS --> WS
    DB <--> SYNC
    WORK --> EVALS
```

Every tenant's data lives under `DATA_FOLDER/users/{oid}` with per-request context routing; background work goes through a durable control plane so it can never run against the wrong partition ([docs/control-plane.md](docs/control-plane.md)). Desktop and cloud stay consistent through journal-based bidirectional sync ([docs/persistence.md](docs/persistence.md)).

---

## Truth, Evals & Observability

**Provenance gate** — a deterministic truth check on every generated document: numeric claims (percentages, dollar amounts, multipliers, years) must trace to the master resume, stories, or JD, or the run is flagged — an LLM reviewer checks quality, this checks *truth*. Verdicts surface in the dashboard (violations modal) and Grafana; in-place master-resume edits are audit-logged so an agent can't legalize a fabricated claim by editing the source. Details: [docs/generation.md](docs/generation.md).

**Eval framework** — three layers in [`evals/`](evals/): declarative tool evals through the exact MCP dispatch path (a <95% smoke pass rate blocks deploys in CI), scoring rubrics with hard thresholds, and an adversarial LLM-as-judge over a committed golden dataset with N-run variance analysis (hallucination rate, verdict flips, baseline deltas). The judge itself is measured, not trusted: a planted-error fixture corpus records per-class catch rates against a synthetic master resume, blind human labels on the golden entries calibrate judge scores per dimension, and every run cross-checks the judge's hallucination list against the provenance gate's record. The judge can run on a separate provider/model from the generator. Runs from the CLI, or server-side via the control plane on a nightly schedule. Details: [docs/evals.md](docs/evals.md).

**Observability** — a dependency-free metrics registry exposes Prometheus counters for requests, LLM calls/tokens, work items, evals, and provenance verdicts at `/metrics`; dashboards-as-code under [`k8s/monitoring/`](k8s/monitoring/) render them on an always-on wallboard (a Raspberry Pi running k3s + Prometheus + Grafana, federating the AKS cluster and scraping the workstation's local-LLM exporter).

| | |
|---|---|
| ![Cloud health](docs/images/wallboard/kiosk-cloud.png) | ![Local LLM](docs/images/wallboard/kiosk-ollama.png) |
| Production — jobcontext.ai on AKS | Local LLM — Ollama + desktop app on the workstation |
| ![Evals](docs/images/wallboard/kiosk-evals.png) | ![Provenance](docs/images/wallboard/kiosk-provenance.png) |
| Golden-dataset judge scores, variance, alerts | Truth-gate verdicts (the red pass rate is the gate catching a local model fabricating) |

---

## Setup

### Option A — Desktop app (no terminal)

[Download](https://github.com/JustLikeFrank3/jobContextMCP/releases?q=desktop&expanded=true), install, launch. The app provisions its own workspace, walks you through AI provider setup (or none), and wires MCP clients with one click.

### Option B — Local server

```bash
git clone https://github.com/JustLikeFrank3/jobContextMCP.git && cd jobContextMCP
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# MCP stdio server (what AI clients spawn)
.venv/bin/python server.py

# Or the HTTP server: REST + dashboard + MCP Streamable HTTP at /mcp
PORT=8000 .venv/bin/python -m transport.http.main
```

Smoke-test the tool surface:

```bash
.venv/bin/python -c "import server; print('OK,', len(server.mcp._tool_manager.list_tools()), 'tools')"
# Expected: OK, 12 tools
```

Then connect a client — for VS Code, add a stdio entry to `.vscode/mcp.json` and restart the server from the MCP panel; the Output pane should show `Discovered 12 tools`. Per-client walkthroughs (VS Code, Claude Desktop, ChatGPT desktop, Cursor, Windsurf): **[docs/client-setup.md](docs/client-setup.md)** and [docs/setup-claude-desktop.md](docs/setup-claude-desktop.md).

There's no manual JSON authoring: ask your AI client to run `workspace(action="check")`, then `workspace(action="setup")` with your details — it creates the directory tree, seeds the data files, and writes config. Feeding the system well (stories, tone samples, reference materials) is what makes generation good: [docs/generation.md](docs/generation.md).

Docker works too: `docker compose run --rm jobcontextmcp` (stdio) or `MCP_TRANSPORT=sse docker compose up`. See [Dockerfile](Dockerfile) and [docker-compose.yml](docker-compose.yml).

### Option C — Cloud (AKS) or self-hosted Kubernetes

The hosted deployment ([jobcontext.ai](https://jobcontext.ai)) runs the HTTP server multi-tenant on AKS behind Entra ID: any Microsoft account can be invited as a guest and gets an isolated partition on first login; MCP clients (Claude.ai, Cursor, VS Code) connect over Streamable HTTP with OAuth (dynamic client registration + PKCE proxied to Entra). Deploys are CI-driven with an eval smoke gate. Manifests in [`k8s/`](k8s/); full guide: **[docs/aks-deployment.md](docs/aks-deployment.md)**.

Self-hosting without Azure: a disposable local k3d cluster or single-node k3s (proven on a Raspberry Pi 4) — [docs/local-cluster.md](docs/local-cluster.md).

---

## Configuration

Everything the code reads — env vars, `config.json` keys, feature flags, per-deployment defaults — is documented in **[docs/configuration.md](docs/configuration.md)**. Highlights:

- **LLM provider**: `llm_provider` = `openai` · `ollama` · `anthropic` · `foundry` (BYOK for all; Ollama needs no key; Foundry can use AKS workload identity). Keyless mode still works — generation tools return a full context package for your AI client to write from.
- **Auth**: single-tenant `API_KEY`, or Entra ID + per-user `jcmcp_` personal access tokens (mobile, sync, scripts).
- **Storage**: `USE_SQLITE` / `SQLITE_ONLY` switch the datastore; JSON dual-write is the audit trail.

---

## Documentation

| Guide | Covers |
|---|---|
| [docs/tools.md](docs/tools.md) | Every MCP tool, action, and parameter + the CLI |
| [docs/api-reference.md](docs/api-reference.md) | Every HTTP endpoint, schema, auth requirement, error code |
| [docs/http-api.md](docs/http-api.md) | HTTP quick start, dashboard, LAN/phone mode, iOS Shortcut, API keys |
| [docs/client-setup.md](docs/client-setup.md) | Connecting VS Code, Claude Desktop, ChatGPT, Cursor, Windsurf |
| [docs/generation.md](docs/generation.md) | Generation modes, provenance gate, personas, PDF export, feeding the system |
| [docs/evals.md](docs/evals.md) | Three-layer eval framework, LLM-as-judge, nightly runs, CI gate |
| [docs/configuration.md](docs/configuration.md) | Every env var and config.json key |
| [docs/persistence.md](docs/persistence.md) | SQLite/JSON tiers, migrations, partitioning, sync, backup/export |
| [docs/local-development.md](docs/local-development.md) | Dev workflow, venv vs Docker, SQLite locally, test gotchas |
| [docs/control-plane.md](docs/control-plane.md) | Durable background work: design, incident history, roadmap |
| [docs/aks-deployment.md](docs/aks-deployment.md) | AKS + Entra ID: deploy, app registration, isolation, QA env |
| [docs/local-cluster.md](docs/local-cluster.md) | k3d locally; k3s on a Raspberry Pi |
| [desktop/README.md](desktop/README.md) | Desktop architecture, signing, updater, release pipeline |
| [mobile/README.md](mobile/README.md) | Mobile companion: screens, capture, build/ship |
| [CHANGELOG.md](CHANGELOG.md) | Full release history |

Legal: [privacy policy](docs/files/jobcontext-privacy-policy.md) · [terms of service](docs/files/jobcontext-terms-of-service.md). Agent instruction template for Copilot: [copilot-instructions.example.md](copilot-instructions.example.md).

---

## Recent Releases

Full details in the [CHANGELOG](CHANGELOG.md).

- **v1.4.0** — Cover-letter edit dialogs with draft versioning, provenance verdict surfacing + violations modal, follow-up queue sanity (timeouts, dismissals), dismissible Home priorities, desktop beta updates.
- **v1.3.x** — Desktop ⇄ cloud sync (journal-based, LWW, file manifests), workspace export/import, per-user API keys, Oura OAuth + encryption at rest.
- **v1.2** — jobContext rebrand, React SPA dashboard, QA environment, desktop app GA (signed macOS/Windows/Linux builds, auto-update).
- **v1.0–v1.1** — Multi-tenant AKS with Entra ID, per-user isolation, OAuth proxy for remote MCP clients, control plane P0, Prometheus/Grafana monitoring, mobile companion app.
- **Unreleased** — Three-layer eval framework with adversarial LLM-as-judge, planted-error fixture corpus with measured per-class catch rates, blind human-label judge calibration (local + production-candidate judge tables), judge/generator model split, judge ⇄ provenance agreement tracking on the wallboard, server-side nightly eval runs, CI eval smoke gate, scraper guards against non-job pages, wallboard GPU rotation, `mcp<2` pin.

### What's next

Route document generation through the control plane (P1), automatic re-assessment on master-resume change (P2), eval-run work kind hardening, richer mobile capture (WebView escalation for authwalled pages), voice debriefs, Azure Trusted Signing for the Windows installer.

---

## Requirements

- Python 3.12+ (3.13 works) for the server; Node 20+ only if you rebuild the dashboard SPA
- macOS, Linux, or Windows
- Optional: an LLM key (OpenAI / Anthropic / Azure AI Foundry) or local Ollama — keyless mode degrades gracefully
- Optional: Docker, or `kubectl` + an AKS/k3s/k3d cluster for containerized deployment

## License

MIT — see [LICENSE](LICENSE).
