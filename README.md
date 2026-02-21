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
```

### 4. Connect to VS Code

Create or update `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "job-search-assistant": {
      "type": "stdio",
      "command": "/absolute/path/to/job-search-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/job-search-mcp/server.py"]
    }
  }
}
```

Then **Cmd+Shift+P → Developer: Reload Window**.

To enable the tools in Copilot chat:
1. Open a Copilot Chat panel (the chat sidebar, not inline chat)
2. Click the **Tools** icon (looks like a wrench/plug) at the bottom of the chat input
3. Find **job-search-assistant** in the list and toggle it on
4. Tools will now be available in every new chat in this workspace

---

## Data Privacy

`config.json`, `data/status.json`, and `data/mental_health_log.json` are all gitignored. Your real application data, contact names, and health entries never leave your machine.

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

---

## A Note on the Name

`JustLikeFrank3` means two things.

I'm the third Frank Vladimir MacBride. My grandfather was the first. He started working at a Ford dealership in Wisconsin in 1930 — sixteen years old, in the teeth of the Depression, making ten cents an hour. By nineteen he was service manager. He kept that for fifty years. Above my home office desk hangs a 1933 photograph of him and his team — three of the four men in clean white service coats. Immaculate, despite the work they did every day. I was told that was intentional: when a customer asked for the manager, the white coat had to be spotless.

I grew up with that photograph. I didn't fully understand it until I was in the workforce myself.

The `JustLikeFrank` part comes from a Less Than Jake song introduced to me by my friend Sean Evans — the most authentically himself person I've ever met. Lust for life, no pretense, no performance. Some people just stick with you.

This repo is dedicated to both of them.
