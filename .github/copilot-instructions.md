# job-search-mcp — Developer Instructions

This is a Python MCP (Model Context Protocol) server built with [FastMCP](https://github.com/jlowin/fastmcp).
It gives AI assistants (GitHub Copilot, Claude, etc.) persistent, structured memory of a job search.

> **For end-users (job seekers):** See `copilot-instructions.example.md` for the Copilot
> instructions template to copy into your Resume folder workspace.

---

## Project Structure

```
server.py          — MCP server entry point; registers all tools via FastMCP
lib/
  config.py        — Config loading (_load_config, _reconfigure) and path globals
  io.py            — File I/O helpers (_read, _load_json, _save_json, _now)
  helpers.py       — Pure logic helpers (story builders, filters, formatters)
tools/
  session.py       — get_session_context
  job_hunt.py      — get_job_hunt_status, update_application
  resume.py        — list/read/save resume and cover letter files
  fitment.py       — assess_job_fitment, get_customization_strategy
  interview.py     — get_interview_quick_reference, get_leetcode_cheatsheet
  export.py        — export_resume_pdf, export_cover_letter_pdf (WeasyPrint)
  generate.py      — generate_resume, generate_cover_letter (OpenAI or Copilot)
  health.py        — log_mental_health_checkin, get_mental_health_log
  context.py       — log_personal_story, get_personal_context
  tone.py          — log_tone_sample, get_tone_profile, scan_materials_for_tone
  star.py          — get_star_story_context
  rag.py           — search_materials, reindex_materials (RAG/semantic search)
  outreach.py      — draft_outreach_message
  people.py        — log_person, get_people
  project_scanner.py — scan_project_for_skills
templates/         — WeasyPrint HTML/CSS templates for PDF rendering
data/              — Runtime JSON data files (gitignored; see *.example.json)
tests/             — pytest test suite
```

---

## Development Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json      # edit paths as needed
cp data/status.example.json data/status.json
cp data/mental_health_log.example.json data/mental_health_log.json
cp data/personal_context.example.json data/personal_context.json
cp data/tone_samples.example.json data/tone_samples.json
```

`config.json` and all `data/*.json` files are gitignored — never commit real user data.

---

## Running Tests

```bash
.venv/bin/pytest                  # run full test suite
.venv/bin/pytest tests/test_helpers.py   # run a specific file
.venv/bin/pytest --cov            # run with coverage (must stay ≥ 50%)
```

Tests use `isolated_server` fixture (in `tests/conftest.py`) to redirect all file-path
globals to a `tmp_path`, keeping tests hermetic. Any test that touches the filesystem
should use this fixture.

---

## Code Conventions

- Python 3.10+; type hints preferred on public functions.
- Tool functions are defined in `tools/` modules and registered to `mcp` in `server.py`.
- All file I/O goes through `lib/io.py` helpers (`_read`, `_load_json`, `_save_json`).
- Config/path globals live in `lib/config.py`; use `_reconfigure()` to update them.
- Add new tools to `tools/` and import/register in `server.py` following the existing pattern.
- Do not add `config.json` or any `data/*.json` file (other than `*.example.json`) to commits.
- Coverage threshold is enforced in `pyproject.toml` (`fail_under = 50`); raise it as coverage grows.
