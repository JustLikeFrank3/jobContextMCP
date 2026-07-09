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
from typing import Literal

from tools import (
    compensation,
    context,
    crossref,
    digest,
    export,
    fitment,
    generate,
    github,
    hbdi,
    health,
    ingest,
    interview,
    interviews,
    job_hunt,
    job_queue,
    job_scraper,
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
        "assess": (fitment.assess_job_fitment, "Quick fitment assessment for a role."),
        "full_assessment": (fitment.run_job_assessment, "Full structured job assessment."),
        "save_assessment": (fitment.save_job_assessment, "Persist an assessment to the workspace."),
    },
    "job_search": {
        "web": (job_scraper.search_jobs, "Search job boards on the open web."),
        "greenhouse": (job_scraper.search_greenhouse_jobs, "Search a company's Greenhouse board."),
        "lever": (job_scraper.search_lever_jobs, "Search a company's Lever board."),
        "url": (job_scraper.scrape_job_url, "Scrape a specific job posting URL."),
    },
    "documents": {
        "generate_resume": (generate.generate_resume, "Generate a tailored resume."),
        "generate_resume_agent": (langgraph_pipeline.generate_resume_agent, "Agentic multi-step resume generation."),
        "generate_cover_letter": (generate.generate_cover_letter, "Generate a tailored cover letter."),
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
    },
    "materials": {
        "read_master_resume": (resume.read_master_resume, "Read the master resume."),
        "read_resume": (resume.read_existing_resume, "Read an existing resume file."),
        "read_reference": (resume.read_reference_file, "Read a reference-materials file."),
        "read_latex_asset": (read_latex_asset, "Read a LaTeX template/section asset."),
        "list": (resume.list_existing_materials, "List existing materials (optionally by company)."),
        "search": (rag.search_materials, "Semantic search across materials."),
        "reindex": (rag.reindex_materials, "Rebuild the materials search index."),
        "reindex_stories": (rag.reindex_stories, "Rebuild the story retrieval index."),
    },
    "interviews": {
        "log": (interviews.log_interview, "Log an interview debrief."),
        "list": (interviews.get_interviews, "List logged interviews (filterable)."),
        "context": (interviews.get_interview_context, "Everything known about a company's process."),
        "upcoming": (interviews.get_upcoming_interviews, "Upcoming interviews."),
        "prep_context": (interview.generate_interview_prep_context, "Build prep context for an interview."),
        "save_prep": (interview.save_interview_prep, "Save a prep doc."),
        "get_prep": (interview.get_existing_prep_file, "Read the existing prep doc for a company."),
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
        "weekly_summary": (digest.weekly_summary, "Week-in-review summary."),
        "session_context": (session.get_session_context, "Session startup context bundle."),
        "rejection_log": (rejections.log_rejection, "Log a rejection."),
        "rejections": (rejections.get_rejections, "Rejection history + funnel patterns."),
        "compensation_update": (compensation.update_compensation, "Record a comp datapoint."),
        "compensation_compare": (compensation.get_compensation_comparison, "Compare recorded comp."),
    },
    "workspace": {
        "check": (setup.check_workspace, "Diagnose what's present/missing (read-only)."),
        "setup": (setup.setup_workspace, "Create/complete the workspace from your details."),
    },
}


def _actions_doc(domain: str) -> str:
    """Generate per-action parameter docs from the real target signatures."""
    lines = ["", "Actions:"]
    for action, (fn, summary) in DOMAINS[domain].items():
        sig = inspect.signature(fn)
        required = [p.name for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
        optional = [p.name for p in sig.parameters.values() if p.default is not inspect.Parameter.empty]
        parts = [f"  {action} — {summary}"]
        if required:
            parts.append(f" Requires: {', '.join(required)}.")
        if optional:
            parts.append(f" Optional: {', '.join(optional)}.")
        lines.append("".join(parts))
    return "\n".join(lines)


def _run(domain: str, action: str, params: dict) -> str:
    """Dispatch a domain call: validate the action, pass only provided params."""
    actions = DOMAINS[domain]
    spec = actions.get(action)
    if spec is None:
        return (
            f"Unknown {domain} action {action!r}. "
            f"Valid actions: {', '.join(actions)}."
        )
    fn = spec[0]
    sig = inspect.signature(fn)
    provided = {
        k: v for k, v in params.items()
        if k != "action" and v is not None and k in sig.parameters
    }
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


def applications(
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
    auto_save: bool | None = None,
    filename: str | None = None,
    content: str | None = None,
) -> str:
    """Track and evaluate job applications: pipeline status, the evaluation queue, fitment assessments, and application events."""
    return _run("applications", action, locals())


def job_search(
    action: Literal["web", "greenhouse", "lever", "url"],
    query: str | None = None,
    location: str | None = None,
    num_results: int | None = None,
    company_slug: str | None = None,
    url: str | None = None,
    auto_queue: bool | None = None,
    page_text: str | None = None,
) -> str:
    """Find job postings: open-web search, Greenhouse/Lever company boards, or scrape a posting URL (pass page_text with copied page content for sites that block server fetches, e.g. LinkedIn)."""
    return _run("job_search", action, locals())


def documents(
    action: Literal["generate_resume", "generate_resume_agent", "generate_cover_letter", "export_resume_pdf", "export_cover_letter_pdf", "export_resume_latex", "export_cover_letter_latex", "save_resume", "save_cover_letter", "diff", "write_latex_section", "customization_strategy", "preview_story_retrieval"],
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
) -> str:
    """Generate, export, and manage application documents: resumes and cover letters (text, PDF, LaTeX), diffs, and customization strategy."""
    return _run("documents", action, locals())


def materials(
    action: Literal["read_master_resume", "read_resume", "read_reference", "read_latex_asset", "list", "search", "reindex", "reindex_stories"],
    filename: str | None = None,
    company: str | None = None,
    query: str | None = None,
    category: str | None = None,
) -> str:
    """Read and search your existing materials: master resume, saved resumes/letters, reference files, LaTeX assets, and the semantic index."""
    return _run("materials", action, locals())


def interviews_tool(
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
    return _run("interviews", action, locals())


def people_tool(
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
    return _run("people", action, locals())


def stories(
    action: Literal["log", "ingest", "personal_context", "star_context", "star_all", "tone_log", "tone_profile", "tone_scan"],
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
    return _run("stories", action, locals())


def wellbeing(
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
    return _run("wellbeing", action, locals())


def brand(
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
    return _run("brand", action, locals())


def insights(
    action: Literal["daily_digest", "weekly_summary", "session_context", "rejection_log", "rejections", "compensation_update", "compensation_compare"],
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
) -> str:
    """Digests and analysis: daily/weekly summaries, session context, rejection funnel patterns, and compensation comparison."""
    return _run("insights", action, locals())


def workspace(
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
    return _run("workspace", action, locals())


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
}


def register(mcp) -> None:
    for name, fn in FACADES.items():
        if "Actions:" not in (fn.__doc__ or ""):
            fn.__doc__ = (fn.__doc__ or "").rstrip() + "\n" + _actions_doc(name)
        mcp.tool(name=name)(fn)
