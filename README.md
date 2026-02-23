# job-search-mcp

A personal [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that gives GitHub Copilot and other MCP-compatible AI assistants persistent, structured memory of your job search — so you never have to re-explain your resume, pipeline status, or interview prep from scratch.

Built in Python using [FastMCP](https://github.com/jlowin/fastmcp).

---

## The Problem It Solves

Every new AI chat session starts with zero context. During an active job hunt you're constantly re-explaining:
- Which companies you're interviewing at and what stage you're in
- What your top resume bullets and STAR stories are
- Which problems you've practiced and which algorithm patterns you need to review
- How you're feeling today (if you track mental health alongside productivity)

This MCP server solves that by giving any AI assistant a set of tools it can call to retrieve all of that context instantly.

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
| `scan_spicam_for_skills()` | Scan a side-project repo for resume-worthy skills |
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
| `draft_outreach_message(contact, company, context, message_type?)` | **v4** — package tone profile, personal context, and writing instructions for AI-drafted outreach (thank-you, follow-up, referral ask, recruiter nudge, cold outreach) |
| `export_resume_pdf(filename, footer_tag?, output_filename?)` | **v4** — parse a .txt resume and render it to a pixel-perfect PDF matching the Courier New / code-aesthetic Canva template |
| `export_cover_letter_pdf(filename, output_filename?)` | **v4** — parse a .txt cover letter and render it to PDF with the two-column sidebar layout |
| `generate_resume(company, role, job_description, output_filename?)` | **v4.1** — generate a tailored resume via OpenAI API (if key configured), auto-save .txt, and export PDF; falls back to context package for Copilot if no key |
| `generate_cover_letter(company, role, job_description, output_filename?)` | **v4.1** — generate a tailored cover letter via OpenAI API, auto-save .txt, and export PDF; same fallback behavior |

---

## Setup

### 1. Clone + install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/job-search-mcp
cd job-search-mcp
python3 -m venv .venv
.venv/bin/pip install "mcp[cli]>=1.3.0" "openai>=1.0.0" "numpy>=1.24.0"
```

### 2. Configure your paths

```bash
cp config.example.json config.json
```

Edit `config.json` with the absolute paths to your own folders:

```json
{
  "resume_folder": "/path/to/your/Resume Folder",
  "leetcode_folder": "/path/to/your/LeetCodePractice",
  "spicam_folder": "/path/to/your/side-project",
  "data_folder": "/path/to/job-search-mcp/data",

  "master_resume_path": "01-Current-Optimized/YourName Resume - MASTER SOURCE.txt",
  "leetcode_cheatsheet_path": "YourCheatsheet.md",
  "quick_reference_path": "INTERVIEW_DAY_QUICK_REFERENCE.md",
  "optimized_resumes_dir": "01-Current-Optimized",
  "cover_letters_dir": "02-Cover-Letters",
  "reference_materials_dir": "06-Reference-Materials"
}
```

### 3. Initialize your data files

```bash
cp data/status.example.json data/status.json
cp data/mental_health_log.example.json data/mental_health_log.json
cp data/personal_context.example.json data/personal_context.json
cp data/tone_samples.example.json data/tone_samples.json
```

> **Note:** If `config.json` is absent (e.g., on a clean clone or in CI), the server automatically falls back to `config.example.json` so imports don't crash. Fill in real paths before running in production.

### 4. Connect to VS Code

`.vscode/mcp.json` is already committed to this repo pointing to `.venv/bin/python3` and `server.py`. Once the `.venv` exists (step 1) and you open this folder in VS Code, the server starts automatically — no clicking required.

If you need to adapt paths for your own setup, edit `.vscode/mcp.json`:

```json
{
  "servers": {
    "job-search-as": {
      "type": "stdio",
      "command": "/absolute/path/to/job-search-mcp/.venv/bin/python3",
      "args": ["/absolute/path/to/job-search-mcp/server.py"],
      "cwd": "/absolute/path/to/job-search-mcp"
    }
  }
}
```

Then **Cmd+Shift+P → Developer: Reload Window** to pick up changes.

> **Multi-root workspaces:** Drop the same `mcp.json` into `.vscode/` inside any workspace root folder — VS Code will auto-start from whichever it finds. For this setup, an identical `mcp.json` lives in both `job-search-mcp/.vscode/` and `Resume 2025/.vscode/` so the server starts reliably from either window.

---

## Workspace Structure (Personal Reference)

This server runs across a multi-root VS Code workspace:

| Folder | Purpose |
|--------|---------|
| `job-search-mcp/` | This repo — MCP server source, templates, data files |
| `Resume 2025/` | All resumes, cover letters, PDFs, prep docs, reference materials |
| `LeetCodePractice/` | LeetCode solutions, cheatsheets, daily review guides |
| `LiveVoxWeb/` | React 19 + TypeScript side project (2.8ms web latency demo) |
| `LiveVoxNative/` | React Native + Swift/Kotlin side project (12.7ms iPhone latency) |
| `RetrosPiCam/` | Python/FastAPI + React Native IoT camera (Raspberry Pi, Azure Blob) |

The `.github/copilot-instructions.md` in each folder tells Copilot to call `get_session_context()` first. With `mcp.json` auto-starting the server, that instruction is immediately actionable — tools are live before the first message.

Data files the server reads at runtime (all resolved relative to `resume_folder` in `config.json`):
- `01-Current-Optimized/` — master source resume + all customized versions
- `02-Cover-Letters/` — cover letter `.txt` files
- `03-Resume-PDFs/` — exported PDFs land here
- `06-Reference-Materials/` — template format, GM awards, peer feedback, skills variants

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

The repo ships two fake-identity demo files for previewing the PDF output:

| File | Description |
|------|-------------|
| `01-Current-Optimized/Nobody MacFakename Resume - Demo Software Engineer.txt` | Full resume in plain `.txt` format — fake name, fake company, fake metrics |
| `02-Cover-Letters/Nobody MacFakename Cover Letter - Demo Software Engineer.txt` | Matching cover letter with fake contact info |

To generate the PDFs locally after setup:

```python
from tools.export import export_resume_pdf, export_cover_letter_pdf
export_resume_pdf("Nobody MacFakename Resume - Demo Software Engineer.txt")
export_cover_letter_pdf("Nobody MacFakename Cover Letter - Demo Software Engineer.txt")
```

PDFs land in `03-Resume-PDFs/` inside your `resume_folder`.

---

## Data Privacy

`config.json` and all files under `data/` — including `status.json`, `mental_health_log.json`, `personal_context.json`, and `tone_samples.json` — are gitignored. Your real application data, personal stories, contact names, and health entries never leave your machine.

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

`scan_spicam_for_skills()` scans a project folder for technologies used and suggests new resume bullets. The `spicam_folder` key in `config.json` can point to any side project — rename it to anything meaningful in your fork.

---

## Copilot Instructions Template

Include a `.github/copilot-instructions.md` in your workspace pointing to this MCP server so Copilot knows to call its tools. See `copilot-instructions.example.md` for a starting template.

### 5. (Optional) Enable RAG semantic search

Add your OpenAI API key to `config.json`:

```json
"openai_api_key": "sk-..."
```

Then build the index:

```bash
.venv/bin/python rag.py
```

This embeds all your materials (~1000–1500 chunks depending on your file count) using `text-embedding-3-small`. Cost is typically under $0.10 for a full index. Once built, `search_materials()` does fast local cosine similarity — no further API calls until you reindex.

The index files (`data/rag_embeddings.npy`, `data/rag_index.json`) are gitignored.

---

## Updating Dependencies

```bash
.venv/bin/pip install -U "mcp[cli]" "openai" "numpy"
```


