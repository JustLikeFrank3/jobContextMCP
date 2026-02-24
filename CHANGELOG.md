# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Planned — v0.5
- **`setup_workspace()` workspace generation tool**: conversational, chat-driven workspace bootstrapper;
  checks for required directories and data files, prompts for missing paths, creates folders and starter
  files with sensible defaults, self-heals on subsequent runs; no manual JSON editing required for onboarding

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
