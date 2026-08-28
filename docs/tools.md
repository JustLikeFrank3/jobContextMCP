# MCP Tool Reference — 12 Domain Tools, 97 Actions

The default MCP surface is **12 consolidated domain tools** (`tools/consolidated.py`). Each takes an `action` parameter plus that action's arguments; the generated docstring on every tool lists each action's required and optional parameters. Rationale: MCP clients budget tools (VS Code caps 128 across every server), and 85 near-duplicate names both hog that budget and give the model look-alike choices to fumble.

`JOBCONTEXT_LEGACY_TOOLS=1` restores the historical per-function surface (88 tools) instead. The two surfaces are mutually exclusive.

**Calling convention:** every action returns a plain string, never JSON. Write confirmations start with `✓ `, caller errors with `✗ `, reads are multi-line plain-text reports, and empty results name the next tool to call. Errors cross the MCP boundary as strings, never exceptions.

**Parameter coercion:** string inputs are coerced to the target's type — `int` accepts `"39"` and `"#39"`; `list[str]` accepts comma-separated strings; `dict` accepts a JSON object string. `None` and unknown parameters are dropped so target defaults apply. A dispatch with a missing required parameter, unknown action, or uncoercible value returns an actionable error message listing what's wrong.

**Guarantees enforced by tests** (`tests/test_consolidated_tools.py`): exactly 11 facades; the action total is pinned at 88; every parameter of every underlying function must exist by name on its domain facade ("otherwise a capability is silently unreachable"); the chat agent's tool allowlist matches the 11 domains. The eval framework's cases double as a drift guard — every eval case must reference a real domain, action, and parameter (`tests/test_evals.py`).

---

## applications — 10 actions

Track and evaluate job applications: pipeline status, the evaluation queue, fitment assessments, and application events.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `status` | Current tracked pipeline snapshot | — | — |
| `update` | Create/update a tracked application | `company`, `role`, `status` | `next_steps`, `contact`, `notes` |
| `log_event` | Timestamped event on an application | `company`, `role`, `event_type` | `notes` |
| `queue` | Queue a job posting for evaluation | `company`, `role`, `jd` | `source` |
| `get_queue` | List queued jobs | — | `status` |
| `evaluate` | Evaluate a queued job against your profile | `company`, `role` | `persona` |
| `decide` | Record an apply/skip decision | `company`, `role`, `decision` | `notes`, `fitment_score` |
| `assess` | Quick fitment assessment for a role | `company`, `role`, `job_description` | `persona` |
| `full_assessment` | Full structured job assessment | `company`, `role`, `job_description` | `persona`, `auto_save` |
| `save_assessment` | Persist an assessment to the workspace | `company`, `content` | `filename`, `source` |

Example: `applications(action="queue", company="Acme", role="Staff Engineer", jd="<pasted JD>")` → `✓ queue: Acme — Staff Engineer (pending)`. Typical workflow: `queue` → `evaluate` → `decide` → `update` as the application progresses, with `log_event` for interviews/recruiter touches.

## job_search — 4 actions

Find job postings: open-web search, Greenhouse/Lever company boards, or scrape a posting URL.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `web` | Search job boards on the open web | `query` | `location`, `num_results`, `auto_queue` |
| `greenhouse` | Search a company's Greenhouse board | `company_slug` | `query`, `num_results`, `auto_queue` |
| `lever` | Search a company's Lever board | `company_slug` | `query`, `num_results`, `auto_queue` |
| `url` | Scrape a specific job posting URL | `url` | `auto_queue`, `page_text` |

For sites that block server fetches (LinkedIn), pass `page_text` with copied page content — the mobile app does this automatically with on-device extraction.

## documents — 13 actions

Generate, export, and manage application documents: resumes and cover letters (text, PDF, LaTeX), diffs, and customization strategy. See [generation.md](generation.md) for the generation pipeline, provenance gate, and personas.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `generate_resume` | Generate a tailored resume | `company`, `role`, `job_description` | `output_filename`, `template`, `style` |
| `generate_resume_agent` | Agentic multi-step resume generation (LangGraph + provenance gate) | `company`, `role`, `job_description` | — |
| `generate_cover_letter` | Generate a tailored cover letter | `company`, `role`, `job_description` | `output_filename`, `export_pipeline`, `role_title`, `cl_template`, `cl_style` |
| `export_resume_pdf` | Render a resume to PDF | `filename` | `footer_tag`, `output_filename`, `template`, `style` |
| `export_cover_letter_pdf` | Render a cover letter to PDF | `filename` | `output_filename`, `footer_tag`, `template`, `style` |
| `export_resume_latex` | Typeset a resume via LaTeX | `company`, `role` | `resume_text`, `output_filename`, `role_title` |
| `export_cover_letter_latex` | Typeset a cover letter via LaTeX | `company`, `role` | `body`, `filename`, `role_title`, `letter_date` |
| `save_resume` | Save resume text to the workspace | `filename`, `content` | — |
| `save_cover_letter` | Save cover letter text to the workspace | `filename`, `content` | — |
| `diff` | Diff two resume files | `file_a`, `file_b` | — |
| `write_latex_section` | Write a LaTeX resume section file | `section_filename`, `content` | — |
| `customization_strategy` | Resume customization strategy for a role type | `role_type` | — |
| `preview_story_retrieval` | Preview which stories generation would pull | `role` | `job_description` |

## materials — 9 actions

Read, search, and maintain your existing materials: master resume (read and in-place edit), saved resumes/letters, reference files, LaTeX assets, and the semantic index.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `read_master_resume` | Read the master resume | — | — |
| `update_master_resume` | Edit the master resume in place (exact-match find/replace) | `old_text`, `new_text` | — |
| `read_resume` | Read an existing resume file | `filename` | — |
| `read_reference` | Read a reference-materials file | `filename` | — |
| `read_latex_asset` | Read a LaTeX template/section asset | `filename` | — |
| `list` | List existing materials (optionally by company) | — | `company` |
| `search` | Semantic search across materials | `query` | `category` |
| `reindex` | Rebuild the materials search index | — | — |
| `reindex_stories` | Rebuild the story retrieval index | — | — |

`update_master_resume` requires an exact, unique match — ambiguous or missing targets return `✗` with the file untouched, and every accepted edit is recorded in an audit table (`master_resume_edits`) because the provenance gate validates generated claims *against* the master resume.

## interviews — 9 actions

Interview lifecycle: log debriefs, review history and company context, see upcoming interviews, and build/save prep docs.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `log` | Log an interview debrief | `company`, `role`, `interview_date`, `interview_type` | `interviewer`, `interviewer_role`, `duration_minutes`, `self_rating`, `interview_format`, `what_landed`, `what_didnt`, `verbatim_quotes`, `surfaced_priorities`, `process_details`, `comp_signals`, `follow_up_commitments`, `tags`, `notes` |
| `list` | List logged interviews (filterable) | — | `company`, `role`, `interviewer`, `interview_type`, `tag`, `since`, `include_full` |
| `context` | Everything known about a company's process | `company` | `role` |
| `upcoming` | Upcoming interviews | — | `days_ahead` |
| `prep_context` | Build prep context for an interview | `company`, `role` | `stage`, `job_description` |
| `save_prep` | Save a prep doc | `company`, `content` | `filename` |
| `get_prep` | Read the existing prep doc for a company | `company` | — |
| `quick_reference` | One-page interview quick reference | — | — |
| `leetcode_cheatsheet` | LeetCode pattern cheatsheet | — | `section` |

List-valued debrief fields (`what_landed`, `verbatim_quotes`, `tags`, …) accept comma-separated strings.

## people — 10 actions

Contacts and outreach: log/list people, referral paths, draft and review outreach messages, and the FB cross-reference queue.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `log` | Add/update a contact | `name`, `relationship`, `company`, `context` | `tags`, `contact_info`, `outreach_status` (one of: none, drafted, sent, responded), `notes`, `sent_message` |
| `list` | List contacts (filterable) | — | `name`, `company`, `tag`, `outreach_status`, `slim` |
| `get` | Full profile for one contact | `name` | — |
| `referral_chains` | Referral paths into a company | `target_company` | — |
| `draft_outreach` | Draft an outreach message in your voice | `contact`, `company`, `context` | `message_type` |
| `draft_reply` | Draft a reply to an incoming message | `incoming_message` | `contact`, `company`, `intent` |
| `review_message` | Critique a drafted message | `text` | — |
| `crossref_run` | Cross-reference FB friends against contacts | — | `fb_folder` |
| `crossref_get` | Read cross-reference insights | — | `insight`, `name` |
| `fb_queue` | FB outreach queue | — | `limit`, `offset`, `sort_by`, `include_pending` |

## stories — 10 actions

Personal stories and voice: log anecdotes, retrieve STAR/personal context for applications, and manage your writing-tone profile.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `log` | Log a personal story/anecdote | `story`, `tags` | `people`, `title` |
| `update` | Correct a story in place | `story_id` | `story`, `tags`, `people`, `title` |
| `delete` | Delete a story (e.g. a duplicate) | `story_id` | — |
| `ingest` | Ingest an anecdote (story + optional tone sample) | `story`, `tags` | `title`, `people`, `tone_sample` |
| `personal_context` | Retrieve personal context by tag/person | — | `tag`, `person` |
| `star_context` | STAR stories for a company/role | `tag` | `company`, `role_type` |
| `star_all` | All STAR story context | — | — |
| `tone_log` | Log a writing-tone sample | `text`, `source` | `context` |
| `tone_profile` | Current tone profile | — | — |
| `tone_scan` | Scan materials for tone samples | — | `category`, `limit`, `company`, `force` |

## wellbeing — 7 actions

Wellbeing during the hunt: mood/energy check-ins, Oura readiness (sync/log/history), and the HBDI thinking-style profile.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `checkin` | Log a mood/energy check-in | `mood` (a label, e.g. `good`, `anxious`), `energy` (1–10) | `notes`, `productive` |
| `log` | Recent check-in history | — | `days` |
| `oura_sync` | Pull latest readiness from Oura | — | — |
| `oura_log` | Manually log a readiness snapshot | `readiness_score`, `sleep_score`, `hrv`, `recovery_index` | `date`, `raw_json` |
| `oura_get` | Recent readiness history | — | `days` |
| `hbdi_run` | Run the HBDI thinking-style assessment | `q1_no_spec_project`, `q2_critical_feedback`, `q3_tedious_finish`, `q4_senior_disagreement`, `score_a`–`score_d` (1–4) | `notes` |
| `hbdi_profile` | Stored HBDI profile | — | — |

## brand — 7 actions

Professional brand: LinkedIn post pipeline + metrics, GitHub stats, portfolio metrics, and side-project skill scans.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `post_log` | Log a LinkedIn post | `text`, `source` | `context`, `posted_date`, `url`, `hashtags`, `links`, `title`, `auto_log_tone`, `post_id` |
| `post_metrics` | Update a post's metrics | — | `post_id`, `source`, `impressions`, `members_reached`, `reactions`, `comments`, `reposts`, `saves`, `link_clicks`, `profile_views_from_post`, `followers_gained`, `audience_highlights` (JSON object) |
| `posts` | List logged posts (filterable) | — | `source`, `hashtag`, `min_reactions`, `include_text` |
| `github_stats` | GitHub contribution stats | `username` | — |
| `portfolio` | Stored portfolio metrics | — | — |
| `portfolio_refresh` | Refresh portfolio metrics | — | — |
| `scan_project_skills` | Scan side projects for skills | — | — |

## insights — 8 actions

Digests and analysis: daily/weekly summaries, session context, rejection funnel patterns, and compensation comparison.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `daily_digest` | Morning briefing: pipeline + action items | — | — |
| `weekly_summary` | Week-in-review summary | — | — |
| `session_context` | Session startup context bundle | — | — |
| `rejection_log` | Log a rejection | `company`, `role`, `stage` | `reason`, `notes`, `date` |
| `rejections` | Rejection history + funnel patterns | — | `company`, `stage`, `since`, `include_pattern_analysis` |
| `compensation_update` | Record a comp datapoint | `company`, `role` | `base`, `equity_total`, `equity_vest_years`, `bonus_target_pct`, `level`, `location`, `remote`, `notes` |
| `compensation_compare` | Compare recorded comp | — | — |
| `evals_results` | Latest eval-suite results: scores, alerts, flagged claims (read-only) | — | `raw` |

`insights(action="session_context")` is the session-startup call — run it first in a new AI session to load pipeline state, recent activity, and workspace status.

## workspace — 2 actions

Workspace setup: check what's present/missing, and create or complete the workspace from your details.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `check` | Diagnose what's present/missing (read-only) | — | — |
| `setup` | Create/complete the workspace from your details | `name`, `email`, `phone`, `linkedin`, `city_state`, `master_resume_content` | `address`, `openai_api_key`, `leetcode_language`, `side_project_folders` |

`workspace(action="setup")` creates the whole directory tree, seeds data files, and writes config — no manual JSON editing required.

## certification — 8 actions

Weekly work-search certification: frozen weekly reports derived from logged events, employer address directory, portal-ready exports, and per-state rules.

| Action | Purpose | Required | Optional |
|---|---|---|---|
| `weekly_report` | Derive, enrich, rank, and freeze this week's work-search report | — | `week_ending` |
| `list_reports` | History of frozen weekly reports | — | `limit` |
| `export` | Render a frozen report for the claim portal | `report_id` | `format` (csv, portal_text, pdf, docx) |
| `swap_entry` | Replace an entry with an alternate (new version) | `report_id`, `out_entry` | `in_entry` |
| `mark_submitted` | Stamp a frozen report as the version filed with the state | `report_id` | `confirmation_number` |
| `employer_lookup` | Read/refresh one employer directory row | `name` | — |
| `employer_override` | Manually correct an employer (locks the row) | `name`, `fields` | — |
| `state_profile` | Read/update the state's certification rules | — | `mode`, `state`, `min_activities_per_week`, `week_ends_on`, `accepted_activity_kinds`, `counts_inbound_recruiter`, `counts_materials_prep` |

Entries must trace to logged events (`source_event_ids`) — export is blocked otherwise, and an under-target week is reported loudly rather than padded. Ships with Georgia defaults (3 activities/week, week ends Saturday); other states are `state_profile` config, not code.

---

## The CLI

[`cli.py`](../cli.py) invokes the **legacy per-function surface** directly from the terminal — useful for development, debugging, and scripted updates:

```bash
.venv/bin/python3 cli.py --list                                  # every tool + signature
.venv/bin/python3 cli.py get_job_hunt_status
.venv/bin/python3 cli.py log_person '{"name":"Hawk","relationship":"beta tester"}'
.venv/bin/python3 cli.py log_person @/tmp/person.json            # kwargs from a file
.venv/bin/python3 cli.py --schedule get_daily_digest --time 08:00  # prints cron/launchd config
```

Note: `cli.py` registers the per-function tools (not the 11 facades) and omits the `oura` and `langgraph_pipeline` modules, so `--list` shows 84 entries.
