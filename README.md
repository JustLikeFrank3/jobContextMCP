<p align="center">
  <img src="docs/branding/banner/jobcontextmcp-readme.svg" alt="JobContextMCP" width="860"/>
</p>

# JobContextMCP

A personal [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that gives GitHub Copilot and other MCP-compatible AI assistants persistent, structured memory of your job search — so you never have to re-explain your resume, pipeline status, or interview prep from scratch.

Built in Python using [FastMCP](https://github.com/jlowin/fastmcp).

---

## Output

| Resume | Cover Letter |
|--------|-------------|
| ![Resume demo](docs/demo-resume.png) | ![Cover letter demo](docs/demo-cover-letter.png) |

Generated from plain `.txt` files — no design tools, no Canva, no InDesign. The templates live in `templates/` and render via WeasyPrint.

---

## The Problem It Solves

Every new AI chat session starts with zero context. During an active job hunt you're constantly re-explaining:
- Which companies you're interviewing at and what stage you're in
- What your top resume bullets and STAR stories are
- Which problems you've practiced and which algorithm patterns you need to review
- How you're feeling today (if you track mental health alongside productivity)

This MCP server solves that by giving any AI assistant a set of tools it can call to retrieve all of that context instantly.

---

## Architecture

```mermaid
graph TB
    AI["GitHub Copilot / AI Assistant"]

    AI -->|MCP protocol| SERVER

    subgraph SERVER["JobContextMCP  —  FastMCP server"]
        direction TB

        subgraph CTX["Context & Identity"]
            T1["get_session_context()"]
            T2["read_master_resume()"]
            T3["get_personal_context()"]
            T4["get_tone_profile() · log_tone_sample()"]
            T5["get_star_story_context()"]
        end

        subgraph PIPELINE["Application Pipeline"]
            T6["get_job_hunt_status() · update_application()"]
            T6b["log_application_event() · log_rejection() · get_rejections()"]
            T6c["update_compensation() · get_compensation_comparison()"]
            T7["assess_job_fitment() · get_customization_strategy()"]
            T8["generate_resume() · generate_cover_letter()"]
            T9["save_resume_txt() · save_cover_letter_txt() · resume_diff()"]
            T10["export_resume_pdf() · export_cover_letter_pdf()"]
        end

        subgraph INTERVIEW["Interview Prep"]
            T11["get_interview_quick_reference()"]
            T12["get_leetcode_cheatsheet()"]
            T13["generate_interview_prep_context()"]
        end

        subgraph NETWORK["Outreach & People"]
            T14["draft_outreach_message() · review_message()"]
            T15["log_person() · get_people()"]
            T19["log_linkedin_post() · update_post_metrics() · get_linkedin_posts()"]
        end

        subgraph UTIL["Utilities"]
            T16["scan_project_for_skills()"]
            T16b["get_daily_digest() · weekly_summary()"]
            T17["search_materials() · reindex_materials()"]
            T18["log_mental_health_checkin() · get_mental_health_log()"]
        end
    end

    subgraph FILES["Your Files  —  local, gitignored"]
        F1["Master resume .txt\nSTAR stories · tone samples\npipeline · contacts · health log"]
        F2["Generated resumes + cover letters .txt\nExported PDFs"]
        F3["LeetCode folder\nSide project folder"]
    end

    CTX --> F1
    PIPELINE --> F1
    PIPELINE --> F2
    INTERVIEW --> F3
    UTIL --> F3
    UTIL --> F1
```

### End-to-End: Job Description → Submitted Application

```mermaid
sequenceDiagram
    participant You
    participant Copilot
    participant MCP as MCP Server
    participant Files as Your Files

    You->>Copilot: Session opens
    Copilot->>MCP: get_session_context()
    MCP->>Files: master resume + awards + peer feedback
    MCP->>Files: tone samples (voice calibration)
    MCP->>Files: STAR stories + personal context
    MCP->>Files: live pipeline + contacts
    MCP-->>Copilot: Full context bundle (~70KB)
    Note over Copilot: Fully contextualized — no re-explaining

    You->>Copilot: Paste job description
    Copilot->>MCP: assess_job_fitment(company, role, jd)
    MCP-->>Copilot: Fitment score + gaps + emphasis strategy
    Copilot->>MCP: generate_resume(company, role, jd)
    MCP->>Files: Read master resume + customization strategy
    MCP->>Files: Write tailored resume .txt
    MCP->>Files: Parse .txt → render WeasyPrint PDF
    MCP-->>Copilot: resume saved + PDF exported
    Copilot->>MCP: generate_cover_letter(company, role, jd)
    MCP->>Files: Write cover letter .txt (≤325 words enforced)
    MCP->>Files: Parse .txt → render two-column sidebar PDF
    MCP-->>Copilot: cover letter saved + PDF exported
    Copilot->>MCP: update_application(company, role, "applied")
    Note over You,Files: Resume PDF + Cover Letter PDF ready to submit
```

---

## Tools

| Tool | Purpose |
|------|---------|
| `get_job_hunt_status()` | Full pipeline — all active applications, contacts, next steps |
| `update_application(company, role, status, ...)` | Add or update an application |
| `read_master_resume()` | Your master resume (source of truth for all customizations) |
| `list_existing_materials(company?)` | List generated resumes + cover letters |
| `read_existing_resume(filename)` | Read a specific resume file |
| `read_reference_file(filename)` | Read from a reference materials folder |
| `assess_job_fitment(company, role, jd)` | Packages your resume + JD for AI fitment analysis |
| `get_customization_strategy(role_type)` | Resume emphasis guide by role type |
| `get_interview_quick_reference()` | STAR stories + system design framework on demand |
| `get_leetcode_cheatsheet(section?)` | Algorithm patterns — full cheatsheet or by topic |
| `generate_interview_prep_context(company, role, stage)` | Structured context for AI-generated prep docs |
| `get_existing_prep_file(company)` | Read any existing prep file for a company |
| `scan_project_for_skills()` | Scan a side-project repo for resume-worthy skills |
| `log_mental_health_checkin(mood, energy, ...)` | Log a mood/energy entry |
| `get_mental_health_log(days?)` | Recent check-in history with trend summary |
| `search_materials(query, category?)` | **RAG** — semantic search across all indexed materials |
| `reindex_materials()` | **RAG** — (re)build the semantic search index |
| `log_personal_story(story, tags, people?, title?)` | **v3** — log a personal story or memory for context-rich writing |
| `get_personal_context(tag?, person?)` | **v3** — retrieve stories filtered by tag or person |
| `log_tone_sample(text, source, context?)` | **v3** — ingest a writing sample to teach the AI your voice |
| `get_tone_profile()` | **v3** — retrieve all tone samples before drafting communications |
| `scan_materials_for_tone(category?)` | **v3** — auto-scan resumes/cover letters/prep files and index new tone samples |
| `get_star_story_context(tag, company?, role_type?)` | **v3** — retrieve STAR stories, metric bullets, and company-specific framing hints |
| `draft_outreach_message(contact, company, context, message_type?)` | **v4** — package tone profile, personal context, and writing instructions for AI-drafted outreach |
| `export_resume_pdf(filename, footer_tag?, output_filename?)` | **v4** — parse a .txt resume and render it to PDF |
| `export_cover_letter_pdf(filename, output_filename?)` | **v4** — parse a .txt cover letter and render it to PDF with two-column sidebar |
| `generate_resume(company, role, job_description, output_filename?)` | **v4.1** — generate tailored resume via OpenAI API (or context package for Copilot), auto-save + export PDF |
| `generate_cover_letter(company, role, job_description, output_filename?)` | **v4.1** — generate tailored cover letter, auto-save + export PDF |
| `log_linkedin_post(text, source, context?, posted_date?, url?, hashtags?, links?, title?)` | **v4.8** — store a LinkedIn post with metadata; auto-ingests as tone sample by default |
| `update_post_metrics(post_id?, source?, impressions?, reactions?, ...)` | **v4.8** — update engagement metrics and audience demographics on a stored post |
| `get_linkedin_posts(source?, hashtag?, min_reactions?, include_text?)` | **v4.8** — retrieve posts with filterable aggregate metrics summary |
| `log_rejection(company, role, stage, reason?, notes?, date?)` | **v5** — log a rejection; stored in `data/rejections.json` for pattern analysis |
| `get_rejections(company?, stage?, since?, include_pattern_analysis?)` | **v5** — retrieve rejections with optional filters and stage/reason pattern breakdown |
| `log_application_event(company, role, event_type, notes?)` | **v5** — append an event to an application's immutable event log (phone screen, offer, note, etc.) |
| `get_daily_digest()` | **v5** — morning briefing: overdue follow-ups, stale apps, recent rejections, drafted-not-sent messages, 3 focus priorities |
| `weekly_summary()` | **v5** — 7-day aggregate: new apps, rejections by stage, contacts added, mental health trend |
| `update_compensation(company, role, base?, equity_total?, bonus_target_pct?, level?, ...)` | **v5** — attach comp data (base/equity/bonus) to a tracked application; computes total comp estimate |
| `get_compensation_comparison()` | **v5** — side-by-side comp table for all applications with comp data, sorted by total comp |
| `resume_diff(file_a, file_b)` | **v5** — unified diff between two resume `.txt` files with added/removed line summary |
| `review_message(text)` | **v5** — tone review for outreach drafts: flags corporate phrases, desperation signals, hedging, weak openers, missing CTAs |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/jobContextMCP
cd jobContextMCP
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create your resume folder structure

Create a folder anywhere on your machine (iCloud, Dropbox, local — your choice) with this layout:

```
Your Resume Folder/
├── 01-Current-Optimized/     ← .txt resumes go here
├── 02-Cover-Letters/         ← .txt cover letters go here
├── 03-Resume-PDFs/           ← exported PDFs land here (auto-created)
└── 06-Reference-Materials/   ← master resume, awards, feedback, skills
```

Place your master resume `.txt` file in `01-Current-Optimized/`.

### 3. Configure paths

```bash
cp config.example.json config.json
```

Edit `config.json` with your absolute paths and contact info:

```json
{
  "resume_folder": "/path/to/your/Resume Folder",
  "leetcode_folder": "/path/to/your/LeetCodePractice",
  "side_project_folders": [
    "/path/to/your/primary-side-project",
    "/path/to/another-project"
  ],
  "data_folder": "/path/to/jobContextMCP/data",
  "master_resume_path": "01-Current-Optimized/Your Name Resume - MASTER SOURCE.txt",
  "optimized_resumes_dir": "01-Current-Optimized",
  "cover_letters_dir": "02-Cover-Letters",
  "reference_materials_dir": "06-Reference-Materials",
  "openai_api_key": "sk-...",
  "openai_model": "gpt-4o-mini",
  "contact": {
    "name": "YOUR FULL NAME",
    "phone": "555-867-5309",
    "email": "you@example.com",
    "linkedin": "www.linkedin.com/in/yourhandle",
    "address": "123 Your Street",
    "city_state": "Your City, ST 00000"
  }
}
```

> `config.json` is gitignored — your real paths, contact info, and API key never leave your machine.

### 4. Initialize data files

```bash
cp data/status.example.json data/status.json
cp data/mental_health_log.example.json data/mental_health_log.json
cp data/personal_context.example.json data/personal_context.json
cp data/tone_samples.example.json data/tone_samples.json
cp data/rejections.example.json data/rejections.json
```

> ⚠️ **All five files must exist.** The server silently fails to start if any data file is missing — VS Code will report "tool not contributed" with no further explanation. If tools stop working after a pull, check that all five files are present.

### 5. Connect to VS Code

`.vscode/mcp.json` is committed to this repo. Once the `.venv` exists and you open this folder in VS Code, the server starts automatically — no clicking required.

If you need to adapt the paths for your machine, edit `.vscode/mcp.json`:

```json
{
  "servers": {
    "jobContextMCP": {
      "type": "stdio",
      "command": "/absolute/path/to/.venv/bin/python3",
      "args": ["/absolute/path/to/server.py"],
      "cwd": "/absolute/path/to/jobContextMCP"
    }
  }
}
```

Then **Cmd+Shift+P → Developer: Reload Window**.

> ⚠️ **Do not add the server via the VS Code UI** (the plug icon → "Add MCP Server" flow). This writes a broken entry to your global `~/Library/Application Support/Code/User/mcp.json` using `python` instead of `python3` with no `cwd` — it silently conflicts with the workspace config and causes intermittent tool failures. If you're experiencing flaky tools, check your global `mcp.json` and remove any duplicate `jobContextMCP` entry from it.

> **Multi-root workspaces:** Drop the same `mcp.json` into `.vscode/` inside any other workspace root (e.g. your Resume folder) and VS Code will auto-start from either window.

### 6. (Optional) Enable AI generation and RAG search

Add your OpenAI API key to `config.json` (already shown in step 3). Then build the RAG index:

```bash
.venv/bin/python rag.py
```

This embeds all your materials using `text-embedding-3-small`. Cost is typically under $0.10 for a full index. Once built, `search_materials()` runs locally with no further API calls.

---

## Workspace Structure

This server is designed to run inside a multi-root VS Code workspace — one that includes your resume folder, side projects, and interview prep alongside the server itself. Copilot needs direct access to all of it to be useful.

| Folder | Purpose |
|--------|---------|
| `jobContextMCP/` | This repo — MCP server source, templates, data files |
| `Resume 2025/` | All resumes, cover letters, PDFs, prep docs, reference materials |
| `LeetCodePractice/` | LeetCode solutions, cheatsheets, daily review guides |
| Side projects | Source code for things you built during the job search — see below |

### Why side projects are in the workspace

The server can scan any project you're actively building and surface resume bullets you may not have thought to write yet.

**`scan_project_for_skills()`** *(v4)* — iterates over all folders listed in `side_project_folders` in your `config.json`, reads each codebase, and returns a per-project breakdown of technologies used, patterns applied, and metrics worth calling out on a resume. The loop closes itself: you build something, the server notices what you used, and shows you what to add to your master resume before the interview.

Example: built an IoT camera with servo HAT control, Azure Blob Storage, and systemd service management. The scanner caught all three as resume-worthy additions — none of which made it into the original resume draft.

To add a new project:
```json
"side_project_folders": [
  "/path/to/your/primary-project",
  "/path/to/another-project"
]
```

The `.github/copilot-instructions.md` in each folder tells Copilot to call `get_session_context()` first. With `mcp.json` auto-starting the server, that instruction is immediately actionable — tools are live before the first message.

Data files the server reads at runtime (all resolved relative to `resume_folder` in `config.json`):
- `01-Current-Optimized/` — master source resume + all customized versions
- `02-Cover-Letters/` — cover letter `.txt` files
- `03-Resume-PDFs/` — exported PDFs land here
- `06-Reference-Materials/` — resume template, award citations, peer feedback, skills variants

---

## The System Is Only As Good As What You Feed It

`get_session_context()` loads four things every session: your master resume, your tone profile, your personal context library, and your live pipeline. That's it. It does **not** read individual resumes or cover letters — so anything meaningful that lives only in those files is invisible to the AI until you explicitly extract and log it.

**This is the most common reason the AI produces generic output.** The RAG index can reach your cover letters and resumes via `search_materials()`, but that's reactive — it only surfaces content when the AI knows to ask for it. The personal context library and tone profile are active — they load automatically and inform every draft, every fitment, every outreach message.

### What to ingest before you rely on the system

**1. Scan your existing cover letters and resumes for tone samples**

If you've written previous cover letters, run:

```
scan_materials_for_tone(category="cover_letters", limit=100)
scan_materials_for_tone(category="resumes", limit=100)
```

This indexes your existing writing so the AI can mirror your voice. Do this once after setup, then again whenever you add a batch of new materials.

**2. Log personal stories explicitly**

Cover letters accumulate stories that were written in context and then forgotten — family history, non-linear career paths, motivating experiences, the reason you care about a specific company. These don't index themselves into the personal context library. Read through your best cover letters and call `log_personal_story()` for anything worth keeping. Same goes for non-digital sources: going-away cards, award citations, performance reviews, peer feedback forms.

```
log_personal_story(
    story="Full narrative in your own words...",
    tags=["family", "engineering_philosophy", "ford"],
    title="Short memorable title"
)
```

**3. Ingest peer feedback and recognition awards**

Formal feedback cycles and recognition awards contain peer-sourced, manager-attributed language that is more credible in interviews than anything you write about yourself. Log quotes verbatim with their source and date. Useful tags: `peer_feedback`, `manager_recognition`, `attribution`.

**4. Rebuild the RAG index after adding new files**

Whenever you add new resumes, cover letters, or reference materials to your resume folder, run:

```
reindex_materials()
```

The RAG index is not updated automatically. If you skip this, `search_materials()` won't know about anything added since the last index build.

**5. Scan your side project after any sprint**

```
scan_project_for_skills()
```

Skills picked up during the job search (new frameworks, cloud services, languages) won't appear on your resume until you run this and manually add the suggested bullets to your master resume.

### The ingestion loop

The goal is a library where the AI can answer "what's the most honest, specific, human thing Frank can say about X?" without you having to re-explain it. Stories, quotes, tone examples, and peer feedback are the raw material. The more you put in, the less generic the output.

When in doubt: if something made you proud, surprised a colleague, landed in a card, or earned a recognition — log it.

---

## AI Resume & Cover Letter Generation

`generate_resume()` and `generate_cover_letter()` are end-to-end tools: one call produces a
saved `.txt` + exported PDF. They load the master resume, tone profile, and job-fitment
strategy automatically — no manual context assembly needed.

### With OpenAI key (fully automated)
Add `openai_api_key` (and optionally `openai_model`) to `config.json`:

```json
"openai_api_key": "sk-...",
"openai_model": "gpt-4o-mini"
```

Then call from within Copilot:

```
generate_resume("Stripe", "Senior Software Engineer", "<paste JD>")
generate_cover_letter("Stripe", "Senior Software Engineer", "<paste JD>")
```

Generates content, saves `.txt`, and exports PDF in one shot.
Cost: ~$0.002 per document at `gpt-4o-mini` pricing.

### Without OpenAI key (Copilot-assisted)
If no key is configured, each tool returns a full context package — master resume, tone
profile, customization strategy, and format instructions — and Copilot writes the content
itself, then calls `save_resume_txt` / `export_resume_pdf`.

### System constraints (enforced in the prompt)

**Resume**
- All metrics and achievements must come verbatim from your master resume — no invention.
- Section headers must be ALL CAPS: `PROFESSIONAL EXPERIENCE`, `CORE TECHNICAL SKILLS`, `EDUCATION`, `LEADERSHIP & COMMUNITY`.
- Job header format: `Title | Company, Location | Month YYYY - Month YYYY` (three pipe-delimited parts).
- Bullets must use `•` (Unicode U+2022) — not `-` or `*`.
- Contact block uses labeled fields: `phone:`, `email:`, `linkedin:` (lowercase, colon suffix).
- Target length: 650–800 words (one tight page in Courier New 9.2pt).

**Cover letter**
- Hard max: **325 words** in the letter body.
- Exactly **4 paragraphs** — Para 1: hook + role + company; Para 2: technical achievement + metric; Para 3: second differentiator; Para 4: short closer (1–2 sentences).
- No date, no address block, no Re: line, no company name in the body.
- Salutation: `Dear Hiring Manager,` — no variations.
- No bullets, no bold, no headers inside the body — prose only.

> These constraints are baked into the prompts. Deviations cause PDF rendering errors because the
> templates have fixed dimensions. If you add your own generation logic, copy the format specs
> from `tools/generate.py` (`_RESUME_FORMAT_SPEC`, `_COVER_LETTER_FORMAT_SPEC`).

---

## PDF Template Demo

The repo includes two fake-identity demo files so you can preview the PDF output without using real data:

```bash
# Generate the demo PDFs after setup:
python -c "
from tools.export import export_resume_pdf, export_cover_letter_pdf
export_resume_pdf('Nobody MacFakename Resume - Demo Software Engineer.txt')
export_cover_letter_pdf('Nobody MacFakename Cover Letter - Demo Software Engineer.txt')
"
```

PDFs land in `03-Resume-PDFs/` inside your `resume_folder`. The source `.txt` files are in `01-Current-Optimized/` and `02-Cover-Letters/` respectively.

---

## Data Privacy

`config.json` and all files under `data/` — including `status.json`, `mental_health_log.json`, `personal_context.json`, `tone_samples.json`, `rejections.json`, `people.json`, and `linkedin_posts.json` — are gitignored. Your real application data, personal stories, contact names, rejection history, and health entries never leave your machine.

---

## Roadmap

### Workspace Generation Tool *(planned — v0.5)*
A `setup_workspace()` tool that bootstraps a complete job search workspace from scratch via conversational prompts:

- On first run, checks for all required directories and data files.
- Prompts conversationally for missing paths ("Where should resume files go?"), creates folders and starter files with sensible defaults.
- Populates initial data: contacts, tone samples, job pipeline, personal stories — all via chat, no manual JSON editing.
- Self-healing: if a folder or file is later deleted, detects and recreates on next run.
- Target: zero manual config-file editing for onboarding.

Design goal: a non-technical job seeker can clone the repo, open VS Code, and have a fully-configured workspace in under 5 minutes through chat alone.

---

## Adapting the Side-Project Scanner

`scan_project_for_skills()` scans a project folder for technologies used and suggests new resume bullets. Point `side_project_folder` in `config.json` at whatever you're currently building.

---

## Copilot Instructions Template

Include a `.github/copilot-instructions.md` in your workspace pointing to this MCP server so Copilot knows to call its tools. See `copilot-instructions.example.md` for a starting template.

---

## Updating Dependencies

```bash
.venv/bin/pip install -U "mcp[cli]" "openai" "numpy"
```


