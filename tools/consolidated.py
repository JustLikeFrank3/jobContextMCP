"""Consolidated MCP tool surface — 11 domain tools over the full function registry.

Why: MCP clients budget tools (VS Code caps 128 across every server), and 85
near-duplicate names both hog that budget and give the model look-alike
choices to fumble. Each domain tool exposes an ``action`` enum and the union
of its actions' parameters; dispatch passes through to the exact same
functions the legacy per-function surface registered, so capabilities are
identical.

Set ``JOBCONTEXT_LEGACY_TOOLS=1`` to register the old 85-tool surface
instead (escape hatch; the underlying modules are unchanged).

Adding an action: add one row to the domain's spec below — the per-action
"Requires/Optional" documentation in the tool description is generated from
the target function's real signature, so it can't drift.

Wide signatures are intentional (Sonar S107 is excluded for this file in
sonar-project.properties): FastMCP derives each tool's inputSchema from the
function signature, so a facade's parameter list must be the union of its
actions' parameters. These functions are dispatch-only — no human call sites.
"""
from __future__ import annotations

import inspect
import json
import types

# anyio: facade dispatch runs in a worker thread (see the facades below).
import anyio
from typing import Literal, get_args, get_origin, Union

from tools import (
    certification as certification_mod,
    compensation,
    context,
    crossref,
    digest,
    eval_results,
    export,
    fitment,
    generate,
    generate_async,
    github,
    hbdi,
    health,
    ingest,
    interview,
    interviews,
    job_hunt,
    job_queue,
    job_scraper,
    job_discovery,
    langgraph_pipeline,
    oura,
    outreach,
    people,
    posts,
    project_scanner,
    rag,
    rejections,
    resume,
    session,
    setup,
    star,
    tone,
)
from tools.latex_export import read_latex_asset, write_latex_section

# ── dispatch core ──────────────────────────────────────────────────────────────

# Domain name → {action name → (target function, one-line summary)}.
DOMAINS: dict[str, dict[str, tuple]] = {
    "applications": {
        "status": (job_hunt.get_job_hunt_status, "Current tracked pipeline snapshot."),
        "update": (job_hunt.update_application, "Create/update a tracked application."),
        "log_event": (job_hunt.log_application_event, "Timestamped event on an application."),
        "queue": (job_queue.queue_job, "Queue a job posting for evaluation."),
        "get_queue": (job_queue.get_job_queue, "List queued jobs."),
        "evaluate": (job_queue.evaluate_queued_job, "Evaluate a queued job against your profile."),
        "decide": (job_queue.decide_job, "Record an apply/skip decision."),
        "assess": (fitment.assess_job_fitment, "Quick fitment assessment for a role — auto-includes workspace signal: known contacts, application events, scheduled interviews."),
        "full_assessment": (fitment.run_job_assessment, "Full structured job assessment, conditioned on workspace signal (known interviewers, pipeline events); returns the existing saved assessment for the company+role unless force=True."),
        "save_assessment": (fitment.save_job_assessment, "Persist an assessment to the workspace."),
    },
    "job_search": {
        "discover": (job_discovery.discover_jobs, "Find new jobs across your saved public boards; returns a search ID and numbered matches, without queuing."),
        "boards": (job_discovery.list_boards, "List your saved boards and supported board sources inferred from your queue."),
        "save_board": (job_discovery.save_board, "Save a company board for discovery."),
        "remove_board": (job_discovery.remove_board, "Remove a board from future searches."),
        "result": (job_discovery.read_result, "Read one numbered result's fetched description."),
        "queue_result": (job_discovery.queue_result, "Queue one selected search result for evaluation; does not submit an application."),
        "web": (job_scraper.search_jobs, "Search job boards on the open web."),
        "greenhouse": (job_scraper.search_greenhouse_jobs, "Search a company's Greenhouse board."),
        "lever": (job_scraper.search_lever_jobs, "Search a company's Lever board."),
        "ashby": (job_scraper.search_ashby_jobs, "Search a company's Ashby board."),
        "recruitee": (job_scraper.search_recruitee_jobs, "Search a company's Recruitee careers site."),
        "url": (job_scraper.scrape_job_url, "Scrape a specific job posting URL."),
    },
    "documents": {
        "generate_resume": (generate.generate_resume, "Generate a tailored resume (synchronous, 60-120s — clients with short tool timeouts should use submit_resume instead)."),
        "generate_resume_agent": (langgraph_pipeline.generate_resume_agent, "Agentic multi-step resume generation (synchronous, 60-120s — clients with short tool timeouts should use submit_resume instead)."),
        "generate_cover_letter": (generate.generate_cover_letter, "Generate a tailored cover letter (synchronous, 60-120s — clients with short tool timeouts should use submit_cover_letter instead)."),
        "submit_resume": (generate_async.submit_resume, "Queue resume generation in the background; returns a work id immediately. Use when generate_resume would exceed the client's tool timeout (in-browser agents allow ~25s)."),
        "submit_cover_letter": (generate_async.submit_cover_letter, "Queue cover-letter generation in the background; returns a work id immediately. Use when generate_cover_letter would exceed the client's tool timeout (in-browser agents allow ~25s)."),
        "generation_status": (generate_async.generation_status, "Poll a queued generation by work_id; returns the finished document with its attestation once the run succeeds (read-only)."),
        "export_resume_pdf": (export.export_resume_pdf, "Render a resume to PDF."),
        "export_cover_letter_pdf": (export.export_cover_letter_pdf, "Render a cover letter to PDF."),
        "export_resume_latex": (export.export_resume_latex, "Typeset a resume via LaTeX."),
        "export_cover_letter_latex": (export.export_cover_letter_latex, "Typeset a cover letter via LaTeX."),
        "save_resume": (resume.save_resume_txt, "Save resume text to the workspace."),
        "save_cover_letter": (resume.save_cover_letter_txt, "Save cover letter text to the workspace."),
        "diff": (resume.resume_diff, "Diff two resume files."),
        "write_latex_section": (write_latex_section, "Write a LaTeX resume section file."),
        "customization_strategy": (fitment.get_customization_strategy, "Resume customization strategy for a role type."),
        "preview_story_retrieval": (generate.preview_story_retrieval, "Preview which stories generation would pull."),
        "provenance": (generate.get_provenance_report, "Truth-gate trust report for the latest generated document (read-only)."),
    },
    "materials": {
        "read_master_resume": (resume.read_master_resume, "Read the master resume."),
        "update_master_resume": (resume.update_master_resume, "Edit the master resume in place (exact-match find/replace)."),
        "read_resume": (resume.read_existing_resume, "Read an existing resume file."),
        "read_reference": (resume.read_reference_file, "Read a reference-materials file."),
        "read_latex_asset": (read_latex_asset, "Read a LaTeX template/section asset."),
        "list": (resume.list_existing_materials, "List existing materials (optionally by company)."),
        "delete": (resume.delete_material, "Delete a saved resume/letter file (records a sync tombstone so the deletion propagates to peers)."),
        "search": (rag.search_materials, "Semantic search across materials."),
        "reindex": (rag.reindex_materials, "Rebuild the materials search index."),
        "reindex_stories": (rag.reindex_stories, "Rebuild the story retrieval index."),
    },
    "interviews": {
        "log": (interviews.log_interview, "Log an interview debrief."),
        "list": (interviews.get_interviews, "List logged interviews (filterable)."),
        "context": (interviews.get_interview_context, "Everything known about a company's process."),
        "upcoming": (interviews.get_upcoming_interviews, "Upcoming interviews."),
        "prep_context": (interview.generate_interview_prep_context, "Build prep context for an interview — auto-includes known interviewers, scheduled interviews, and prior in-room signal from the workspace."),
        "save_prep": (interview.save_interview_prep, "Save a prep doc (the filename is company-slugged so get_prep finds it)."),
        "get_prep": (interview.get_existing_prep_file, "Read existing prep docs for a company (punctuation-insensitive name match)."),
        "quick_reference": (interview.get_interview_quick_reference, "One-page interview quick reference."),
        "leetcode_cheatsheet": (interview.get_leetcode_cheatsheet, "LeetCode pattern cheatsheet."),
    },
    "people": {
        "log": (people.log_person, "Add/update a contact."),
        "list": (people.get_people, "List contacts (filterable)."),
        "get": (people.get_person, "Full profile for one contact."),
        "referral_chains": (people.get_referral_chains, "Referral paths into a company."),
        "draft_outreach": (outreach.draft_outreach_message, "Draft an outreach message in your voice."),
        "draft_reply": (outreach.draft_reply, "Draft a reply to an incoming message."),
        "review_message": (outreach.review_message, "Critique a drafted message."),
        "crossref_run": (crossref.run_contact_crossref, "Cross-reference FB friends against contacts."),
        "crossref_get": (crossref.get_contact_crossref, "Read cross-reference insights."),
        "fb_queue": (crossref.get_fb_outreach_queue, "FB outreach queue."),
    },
    "stories": {
        "log": (context.log_personal_story, "Log a personal story/anecdote."),
        "update": (context.update_personal_story, "Correct a story in place (fix a wrong fact)."),
        "delete": (context.delete_personal_story, "Delete a story (e.g. a duplicate)."),
        "ingest": (ingest.ingest_anecdote, "Ingest an anecdote (story + optional tone sample)."),
        "personal_context": (context.get_personal_context, "Retrieve personal context by tag/person."),
        "star_context": (star.get_star_story_context, "STAR stories for a company/role."),
        "star_all": (star.get_all_star_context, "All STAR story context."),
        "tone_log": (tone.log_tone_sample, "Log a writing-tone sample."),
        "tone_profile": (tone.get_tone_profile, "Current tone profile."),
        "tone_scan": (tone.scan_materials_for_tone, "Scan materials for tone samples."),
    },
    "wellbeing": {
        "checkin": (health.log_mental_health_checkin, "Log a mood/energy check-in."),
        "log": (health.get_mental_health_log, "Recent check-in history."),
        "oura_sync": (oura.sync_oura_readiness, "Pull latest readiness from Oura."),
        "oura_log": (oura.log_oura_readiness, "Manually log a readiness snapshot."),
        "oura_get": (oura.get_oura_readiness, "Recent readiness history."),
        "hbdi_run": (hbdi.run_hbdi_assessment, "Run the HBDI thinking-style assessment."),
        "hbdi_profile": (hbdi.get_hbdi_profile, "Stored HBDI profile."),
    },
    "brand": {
        "post_log": (posts.log_linkedin_post, "Log a LinkedIn post."),
        "post_metrics": (posts.update_post_metrics, "Update a post's metrics."),
        "posts": (posts.get_linkedin_posts, "List logged posts (filterable)."),
        "github_stats": (github.get_github_stats, "GitHub contribution stats."),
        "portfolio": (github.get_portfolio_metrics, "Stored portfolio metrics."),
        "portfolio_refresh": (github.refresh_portfolio_metrics, "Refresh portfolio metrics."),
        "scan_project_skills": (project_scanner.scan_project_for_skills, "Scan side projects for skills."),
    },
    "insights": {
        "daily_digest": (digest.get_daily_digest, "Morning briefing: pipeline + action items."),
        "briefing": (digest.get_voice_briefing, "Speakable one-breath briefing (plain prose, no markdown) for voice assistants; fast local reads only."),
        "weekly_summary": (digest.weekly_summary, "Week-in-review summary."),
        "session_context": (session.get_session_context, "Session startup context bundle."),
        "rejection_log": (rejections.log_rejection, "Log a rejection."),
        "rejections": (rejections.get_rejections, "Rejection history + funnel patterns."),
        "compensation_update": (compensation.update_compensation, "Record a comp datapoint."),
        "compensation_compare": (compensation.get_compensation_comparison, "Compare recorded comp."),
        "evals_results": (eval_results.get_eval_results, "Latest eval-suite results: scores, alerts, flagged claims (read-only)."),
    },
    "workspace": {
        "check": (setup.check_workspace, "Diagnose what's present/missing (read-only)."),
        "setup": (setup.setup_workspace, "Create/complete the workspace from your details."),
    },
    "certification": {
        "weekly_report": (certification_mod.weekly_certification_report, "Derive, enrich, rank, and freeze this week's work-search report."),
        "list_reports": (certification_mod.list_certification_reports, "History of frozen weekly reports."),
        "export": (certification_mod.export_certification_report, "Render a frozen report for the claim portal."),
        "swap_entry": (certification_mod.swap_certification_entry, "Replace an entry with an alternate (new version)."),
        "mark_submitted": (certification_mod.mark_certification_submitted, "Stamp a report as the version filed with the state."),
        "employer_lookup": (certification_mod.lookup_employer, "Read/refresh one employer directory row."),
        "employer_override": (certification_mod.override_employer, "Manually correct an employer (locks the row)."),
        "state_profile": (certification_mod.certification_state_profile, "Read/update the state's certification rules."),
    },
}


def _literal_choices(annotation) -> list | None:
    """Return a Literal type's allowed values, unwrapping an `X | None`."""
    target = _unwrap_optional(annotation)
    if get_origin(target) is Literal:
        return list(get_args(target))
    return None


def _param_label(p: inspect.Parameter) -> str:
    choices = _literal_choices(p.annotation)
    return f"{p.name} (one of: {', '.join(map(str, choices))})" if choices else p.name


def _actions_doc(domain: str) -> str:
    """Generate per-action parameter docs from the real target signatures."""
    lines = ["", "Actions:"]
    for action, (fn, summary) in DOMAINS[domain].items():
        sig = inspect.signature(fn)
        required = [_param_label(p) for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
        optional = [_param_label(p) for p in sig.parameters.values() if p.default is not inspect.Parameter.empty]
        parts = [f"  {action} — {summary}"]
        if required:
            parts.append(f" Requires: {', '.join(required)}.")
        if optional:
            parts.append(f" Optional: {', '.join(optional)}.")
        lines.append("".join(parts))
    return "\n".join(lines)


def _unwrap_optional(annotation):
    """Strip an ``X | None`` union down to X; pass through anything else.

    ``X | None`` (PEP 604) and ``typing.Union[X, None]`` are two different
    origins at runtime (``types.UnionType`` vs ``typing.Union``) — every
    real target function in this codebase uses the former, so both must be
    checked or this silently never unwraps anything.
    """
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _coerce_param(name: str, value, annotation):
    """Bridge the facade's simple-typed (str) schema to a real function's
    richer type (int/list/dict) — facades intentionally expose plain
    strings (see module docstring) since not every MCP client renders
    nested array/object schemas well; something has to turn the string
    back into what the target function actually wants.

    Raises ValueError with a caller-facing message on bad input instead of
    letting a raw TypeError (e.g. "'str' object is not a mapping") or a
    silent str/int mismatch (matches nothing, no error) leak through.
    """
    if not isinstance(value, str):
        return value
    target = _unwrap_optional(annotation)
    if target is int:
        try:
            return int(value.strip().lstrip("#"))
        except ValueError:
            raise ValueError(f"{name} must be a number, got {value!r}.") from None
    if get_origin(target) is list:
        return [v.strip() for v in value.split(",") if v.strip()]
    if target is dict:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(f"{name} must be a JSON object, got {value!r}.") from None
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} must be a JSON object, got {value!r}.")
        return parsed
    return value


def _run(domain: str, action: str, params: dict) -> str:
    """Dispatch a domain call: validate the action, coerce facade-simple
    values to each param's real type, pass only provided params."""
    actions = DOMAINS[domain]
    spec = actions.get(action)
    if spec is None:
        return (
            f"Unknown {domain} action {action!r}. "
            f"Valid actions: {', '.join(actions)}."
        )
    fn = spec[0]
    try:
        # eval_str resolves postponed annotations — target modules using
        # `from __future__ import annotations` otherwise present their types
        # as strings ('dict | None') and silently dodge coercion.
        sig = inspect.signature(fn, eval_str=True)
    except Exception:  # noqa: BLE001 — unresolvable hints coerce nothing, as before
        sig = inspect.signature(fn)
    provided = {}
    for k, v in params.items():
        if k == "action" or v is None or k not in sig.parameters:
            continue
        try:
            provided[k] = _coerce_param(k, v, sig.parameters[k].annotation)
        except ValueError as e:
            return f"✗ {domain}.{action}: {e}"
    missing = [
        p.name for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty and p.name not in provided
    ]
    if missing:
        return (
            f"{domain}.{action} is missing required parameter(s): {', '.join(missing)}. "
            f"({spec[1]})"
        )
    return fn(**provided)


# ── domain tools ───────────────────────────────────────────────────────────────
# Every parameter is optional (None = "not provided"); _run forwards only the
# ones the chosen action's real function accepts, so per-function defaults
# still apply. Docstrings get the generated per-action Requires/Optional
# listing appended at registration.


# The facades are async and push _run onto a worker thread because FastMCP
# calls SYNC tools directly on the event loop (mcp/server/fastmcp/utilities/
# func_metadata.py: `return fn(**arguments)`), so a slow action — LLM
# generation, an assessment — froze the WHOLE server for the call's duration:
# health probes included, which got the prod pod liveness-killed mid-request
# twice on 2026-08-27. anyio.to_thread.run_sync copies the caller's context,
# so the per-request partition contextvars (lib/user_context.py) survive the
# hop — unlike bare run_in_executor, which is why that remains forbidden.
async def applications(
    action: Literal["status", "update", "log_event", "queue", "get_queue", "evaluate", "decide", "assess", "full_assessment", "save_assessment"],
    company: str | None = None,
    role: str | None = None,
    jd: str | None = None,
    job_description: str | None = None,
    source: str | None = None,
    status: str | None = None,
    persona: str | None = None,
    decision: str | None = None,
    notes: str | None = None,
    fitment_score: int | None = None,
    next_steps: str | None = None,
    contact: str | None = None,
    event_type: str | None = None,
    date: str | None = None,
    auto_save: bool | None = None,
    force: bool | None = None,
    filename: str | None = None,
    content: str | None = None,
) -> str:
    """Track and evaluate job applications: pipeline status, the evaluation queue, fitment assessments, and application events. Assessments and evaluations automatically pull workspace signal — known contacts, logged events, scheduled interviews — so their output reflects the live pipeline, not just the JD."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("applications", action, params))


async def job_search(
    action: Literal["web", "greenhouse", "lever", "ashby", "recruitee", "url", "discover", "boards", "save_board", "remove_board", "result", "queue_result"],
    query: str | None = None,
    location: str | None = None,
    num_results: int | None = None,
    company_slug: str | None = None,
    url: str | None = None,
    auto_queue: bool | None = None,
    page_text: str | None = None,
    provider: Literal["greenhouse", "lever", "ashby", "recruitee"] | None = None,
    company: str | None = None,
    search_id: str | None = None,
    result_number: int | None = None,
    include_known: bool | None = None,
) -> str:
    """Find job postings: open-web search, a company board (Greenhouse, Lever, Ashby, Recruitee), or scrape a posting URL (pass page_text with copied page content for sites that block server fetches, e.g. LinkedIn)."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("job_search", action, params))


async def documents(
    action: Literal["generate_resume", "generate_resume_agent", "generate_cover_letter", "submit_resume", "submit_cover_letter", "generation_status", "export_resume_pdf", "export_cover_letter_pdf", "export_resume_latex", "export_cover_letter_latex", "save_resume", "save_cover_letter", "diff", "write_latex_section", "customization_strategy", "preview_story_retrieval", "provenance"],
    company: str | None = None,
    role: str | None = None,
    job_description: str | None = None,
    output_filename: str | None = None,
    template: str | None = None,
    style: str | None = None,
    filename: str | None = None,
    content: str | None = None,
    footer_tag: str | None = None,
    role_title: str | None = None,
    letter_date: str | None = None,
    body: str | None = None,
    resume_text: str | None = None,
    export_pipeline: bool | None = None,
    cl_template: str | None = None,
    cl_style: str | None = None,
    file_a: str | None = None,
    file_b: str | None = None,
    role_type: str | None = None,
    section_filename: str | None = None,
    work_id: int | None = None,
) -> str:
    """Generate, export, and manage application documents: resumes and cover letters (text, PDF, LaTeX), diffs, and customization strategy. Long generations can run in the background: submit_resume / submit_cover_letter return a work_id, generation_status polls it."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("documents", action, params))


async def materials(
    action: Literal["read_master_resume", "update_master_resume", "read_resume", "read_reference", "read_latex_asset", "list", "delete", "search", "reindex", "reindex_stories"],
    filename: str | None = None,
    company: str | None = None,
    query: str | None = None,
    category: str | None = None,
    old_text: str | None = None,
    new_text: str | None = None,
) -> str:
    """Read, search, and maintain your existing materials: master resume (read and in-place edit), saved resumes/letters (list, read, delete), reference files, LaTeX assets, and the semantic index."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("materials", action, params))


async def interviews_tool(
    action: Literal["log", "list", "context", "upcoming", "prep_context", "save_prep", "get_prep", "quick_reference", "leetcode_cheatsheet"],
    company: str | None = None,
    role: str | None = None,
    stage: str | None = None,
    job_description: str | None = None,
    content: str | None = None,
    filename: str | None = None,
    interview_date: str | None = None,
    interview_type: str | None = None,
    interviewer: str | None = None,
    interviewer_role: str | None = None,
    duration_minutes: int | None = None,
    self_rating: int | None = None,
    interview_format: str | None = None,
    what_landed: str | None = None,
    what_didnt: str | None = None,
    verbatim_quotes: str | None = None,
    surfaced_priorities: str | None = None,
    process_details: str | None = None,
    comp_signals: str | None = None,
    follow_up_commitments: str | None = None,
    tags: str | None = None,
    notes: str | None = None,
    tag: str | None = None,
    since: str | None = None,
    include_full: bool | None = None,
    days_ahead: int | None = None,
    section: str | None = None,
) -> str:
    """Interview lifecycle: log debriefs, review history and company context, see upcoming interviews, and build/save prep docs."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("interviews", action, params))


async def people_tool(
    action: Literal["log", "list", "get", "referral_chains", "draft_outreach", "draft_reply", "review_message", "crossref_run", "crossref_get", "fb_queue"],
    name: str | None = None,
    relationship: str | None = None,
    company: str | None = None,
    context: str | None = None,
    tags: str | None = None,
    contact_info: str | None = None,
    outreach_status: str | None = None,
    notes: str | None = None,
    sent_message: str | None = None,
    tag: str | None = None,
    slim: bool | None = None,
    target_company: str | None = None,
    contact: str | None = None,
    message_type: str | None = None,
    text: str | None = None,
    incoming_message: str | None = None,
    intent: str | None = None,
    fb_folder: str | None = None,
    insight: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort_by: str | None = None,
    include_pending: bool | None = None,
) -> str:
    """Contacts and outreach: log/list people, referral paths, draft and review outreach messages, and the FB cross-reference queue."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("people", action, params))


async def stories(
    action: Literal["log", "update", "delete", "ingest", "personal_context", "star_context", "star_all", "tone_log", "tone_profile", "tone_scan"],
    story_id: str | None = None,
    story: str | None = None,
    tags: str | None = None,
    people: str | None = None,
    title: str | None = None,
    tag: str | None = None,
    person: str | None = None,
    tone_sample: bool | None = None,
    company: str | None = None,
    role_type: str | None = None,
    text: str | None = None,
    source: str | None = None,
    context: str | None = None,
    category: str | None = None,
    limit: int | None = None,
    force: bool | None = None,
) -> str:
    """Personal stories and voice: log anecdotes, retrieve STAR/personal context for applications, and manage your writing-tone profile."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("stories", action, params))


async def wellbeing(
    action: Literal["checkin", "log", "oura_sync", "oura_log", "oura_get", "hbdi_run", "hbdi_profile"],
    mood: int | None = None,
    energy: int | None = None,
    notes: str | None = None,
    productive: bool | None = None,
    days: int | None = None,
    readiness_score: int | None = None,
    sleep_score: int | None = None,
    hrv: int | None = None,
    recovery_index: int | None = None,
    date: str | None = None,
    raw_json: str | None = None,
    q1_no_spec_project: str | None = None,
    q2_critical_feedback: str | None = None,
    q3_tedious_finish: str | None = None,
    q4_senior_disagreement: str | None = None,
    score_a: int | None = None,
    score_b: int | None = None,
    score_c: int | None = None,
    score_d: int | None = None,
) -> str:
    """Wellbeing during the hunt: mood/energy check-ins, Oura readiness (sync/log/history), and the HBDI thinking-style profile."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("wellbeing", action, params))


async def brand(
    action: Literal["post_log", "post_metrics", "posts", "github_stats", "portfolio", "portfolio_refresh", "scan_project_skills"],
    text: str | None = None,
    source: str | None = None,
    context: str | None = None,
    posted_date: str | None = None,
    url: str | None = None,
    hashtags: str | None = None,
    links: str | None = None,
    title: str | None = None,
    auto_log_tone: bool | None = None,
    post_id: str | None = None,
    impressions: int | None = None,
    members_reached: int | None = None,
    reactions: int | None = None,
    comments: int | None = None,
    reposts: int | None = None,
    saves: int | None = None,
    link_clicks: int | None = None,
    profile_views_from_post: int | None = None,
    followers_gained: int | None = None,
    audience_highlights: str | None = None,
    hashtag: str | None = None,
    min_reactions: int | None = None,
    include_text: bool | None = None,
    username: str | None = None,
) -> str:
    """Professional brand: LinkedIn post pipeline + metrics, GitHub stats, portfolio metrics, and side-project skill scans."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("brand", action, params))


async def insights(
    action: Literal["daily_digest", "briefing", "weekly_summary", "session_context", "rejection_log", "rejections", "compensation_update", "compensation_compare", "evals_results"],
    company: str | None = None,
    role: str | None = None,
    stage: str | None = None,
    reason: str | None = None,
    notes: str | None = None,
    date: str | None = None,
    since: str | None = None,
    include_pattern_analysis: bool | None = None,
    base: int | None = None,
    equity_total: int | None = None,
    equity_vest_years: int | None = None,
    bonus_target_pct: int | None = None,
    level: str | None = None,
    location: str | None = None,
    remote: bool | None = None,
    raw: bool | None = None,
) -> str:
    """Digests and analysis: daily/weekly summaries, session context, rejection funnel patterns, eval-suite results, and compensation comparison."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("insights", action, params))


async def workspace(
    action: Literal["check", "setup"],
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    linkedin: str | None = None,
    city_state: str | None = None,
    master_resume_content: str | None = None,
    address: str | None = None,
    openai_api_key: str | None = None,
    leetcode_language: str | None = None,
    side_project_folders: str | None = None,
) -> str:
    """Workspace setup: check what's present/missing, and create or complete the workspace from your details."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("workspace", action, params))


async def certification(
    action: Literal["weekly_report", "list_reports", "export", "swap_entry", "mark_submitted", "employer_lookup", "employer_override", "state_profile"],
    week_ending: str | None = None,
    limit: int | None = None,
    report_id: int | None = None,
    format: str | None = None,
    out_entry: int | None = None,
    in_entry: str | None = None,
    confirmation_number: str | None = None,
    name: str | None = None,
    # str | dict, not just str: several MCP clients (claude.ai, Claude Code)
    # auto-parse JSON-looking argument strings into objects before sending —
    # a string-only schema hard-rejects those calls at validation.
    fields: str | dict | None = None,
    mode: str | None = None,
    state: str | None = None,
    min_activities_per_week: int | None = None,
    week_ends_on: str | None = None,
    accepted_activity_kinds: str | None = None,
    counts_inbound_recruiter: bool | None = None,
    counts_materials_prep: bool | None = None,
) -> str:
    """Weekly work-search certification: frozen weekly reports derived from logged events, employer address directory, portal-ready exports, and per-state rules."""
    params = locals()
    return await anyio.to_thread.run_sync(lambda: _run("certification", action, params))


# MCP tool name → facade. interviews/people shadow imported modules, hence
# the _tool suffix on the functions; the registered names stay clean.
FACADES: dict[str, object] = {
    "applications": applications,
    "job_search": job_search,
    "documents": documents,
    "materials": materials,
    "interviews": interviews_tool,
    "people": people_tool,
    "stories": stories,
    "wellbeing": wellbeing,
    "brand": brand,
    "insights": insights,
    "workspace": workspace,
    "certification": certification,
}


def register(mcp) -> None:
    for name, fn in FACADES.items():
        if "Actions:" not in (fn.__doc__ or ""):
            fn.__doc__ = (fn.__doc__ or "").rstrip() + "\n" + _actions_doc(name)
        mcp.tool(name=name)(fn)
