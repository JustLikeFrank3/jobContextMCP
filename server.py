#!/usr/bin/env python3
"""
JobContextMCP Server
--------------------
Model Context Protocol server providing persistent job-search memory
for GitHub Copilot and other MCP-compatible AI assistants.

Tools provided:
  - Session context (resume, pipeline, tone, stories in one call)
  - Job hunt status tracking and pipeline management
  - Resume / cover letter context generation and PDF export
  - Job fitment assessment and customization strategy
  - Interview prep, STAR stories, and LeetCode cheatsheet
  - Side project skill scanning
  - Mental health check-in logging
  - Personal story / context library (v3)
  - Tone ingestion + voice profile (v3)
  - Outreach drafting and contacts management (v4)
  - LinkedIn post tracking with engagement metrics (v4.8)
"""
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from lib import config
from lib.config import _load_config
from lib.io import _read, _load_json, _save_json, _now
from lib.helpers import (
    _build_story_entry,
    _filter_stories,
    _format_story_list,
    _build_checkin_entry,
    _build_tone_sample_entry,
    _scan_dirs,
)

from tools import (
    session,
    job_hunt,
    resume,
    fitment,
    interview,
    interviews,
    project_scanner,
    health,
    oura,
    context,
    tone,
    rag,
    star,
    outreach,
    export,
    people,
    generate,
    langgraph_pipeline,
    setup,
    posts,
    rejections,
    digest,
    compensation,
    ingest,
    hbdi,
    crossref,
    job_queue,
    job_scraper,
    github,
)


def _sync_config_exports() -> None:
    global _cfg
    global RESUME_FOLDER, LEETCODE_FOLDER, SIDE_PROJECT_FOLDERS, SIDE_PROJECT_REPOS, DATA_FOLDER
    global STATUS_FILE, HEALTH_LOG_FILE, PERSONAL_CONTEXT_FILE, TONE_FILE, SCAN_INDEX_FILE, PEOPLE_FILE, LINKEDIN_POSTS_FILE, REJECTIONS_FILE, INTERVIEWS_FILE
    global CONTACT_CROSSREF_FILE, LINKEDIN_CONNECTIONS_FILE, GITHUB_METRICS_FILE, FB_FRIENDS_FOLDER
    global MASTER_RESUME, LEETCODE_CHEATSHEET, QUICK_REFERENCE
    global RESUME_TEMPLATE_PNG, COVER_LETTER_TEMPLATE_PNG, TEMPLATE_FORMAT
    global ACHIEVEMENTS, FEEDBACK_RECEIVED, SKILLS_SHORTER
    global INTERVIEW_PREP_FOLDER, JOB_QUEUE_FILE
    global JOB_ASSESSMENTS_FOLDER, SERPAPI_KEY, LATEX_RESUME_DIR, OWNER_OID, APP_ENCRYPTION_KEY

    _cfg = config._cfg

    RESUME_FOLDER = config.RESUME_FOLDER
    LEETCODE_FOLDER = config.LEETCODE_FOLDER
    SIDE_PROJECT_FOLDERS = config.SIDE_PROJECT_FOLDERS
    SIDE_PROJECT_REPOS = config.SIDE_PROJECT_REPOS
    DATA_FOLDER = config.DATA_FOLDER

    STATUS_FILE = config.STATUS_FILE
    HEALTH_LOG_FILE = config.HEALTH_LOG_FILE
    PERSONAL_CONTEXT_FILE = config.PERSONAL_CONTEXT_FILE
    TONE_FILE = config.TONE_FILE
    SCAN_INDEX_FILE = config.SCAN_INDEX_FILE
    PEOPLE_FILE = config.PEOPLE_FILE
    LINKEDIN_POSTS_FILE = config.LINKEDIN_POSTS_FILE
    REJECTIONS_FILE = config.REJECTIONS_FILE
    INTERVIEWS_FILE = config.INTERVIEWS_FILE
    CONTACT_CROSSREF_FILE = config.CONTACT_CROSSREF_FILE
    LINKEDIN_CONNECTIONS_FILE = config.LINKEDIN_CONNECTIONS_FILE
    GITHUB_METRICS_FILE = config.GITHUB_METRICS_FILE
    FB_FRIENDS_FOLDER = config.FB_FRIENDS_FOLDER

    MASTER_RESUME = config.MASTER_RESUME
    LEETCODE_CHEATSHEET = config.LEETCODE_CHEATSHEET
    QUICK_REFERENCE = config.QUICK_REFERENCE

    RESUME_TEMPLATE_PNG = config.RESUME_TEMPLATE_PNG
    COVER_LETTER_TEMPLATE_PNG = config.COVER_LETTER_TEMPLATE_PNG
    TEMPLATE_FORMAT = config.TEMPLATE_FORMAT
    ACHIEVEMENTS = config.ACHIEVEMENTS
    FEEDBACK_RECEIVED = config.FEEDBACK_RECEIVED
    SKILLS_SHORTER = config.SKILLS_SHORTER
    INTERVIEW_PREP_FOLDER = config.INTERVIEW_PREP_FOLDER
    JOB_QUEUE_FILE = config.JOB_QUEUE_FILE
    JOB_ASSESSMENTS_FOLDER = config.JOB_ASSESSMENTS_FOLDER
    SERPAPI_KEY = config.SERPAPI_KEY
    OWNER_OID = config.OWNER_OID
    APP_ENCRYPTION_KEY = config.APP_ENCRYPTION_KEY
    LATEX_RESUME_DIR = config.LATEX_RESUME_DIR


def _reconfigure(cfg: dict) -> None:
    config._reconfigure(cfg)
    _sync_config_exports()


_sync_config_exports()


# Disable the MCP SDK's localhost-only DNS rebinding check only when running
# behind a reverse proxy (AKS nginx-ingress + TLS) where the proxy is the
# security boundary.  ENABLE_REMOTE alone is not sufficient — it is also set
# for local LAN / Tailscale stdio binds where the rebinding check should stay
# on.  Require an explicit DISABLE_REBINDING_CHECK=true opt-out to minimise
# exposure surface.
_transport_security: TransportSecuritySettings | None = None
_behind_proxy = (
    os.getenv("ENABLE_REMOTE", "false").lower() in ("1", "true", "yes")
    and os.getenv("DISABLE_REBINDING_CHECK", "false").lower() in ("1", "true", "yes")
)
if _behind_proxy:
    _transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "jobContextMCP",
    transport_security=_transport_security,
    instructions=(
        "You are a tenant-scoped job search assistant. "
        "You have direct filesystem access to the current user's resume materials, job hunt status, "
        "and interview prep files. Use the available tools to retrieve context before "
        "generating resumes, cover letters, prep docs, or assessments. "
        "Always read the master resume before generating any application material."
    ),
)


# Default surface: 11 consolidated domain tools (action-dispatch facades over
# the same functions) — MCP clients budget tools, and VS Code caps 128 across
# every server. JOBCONTEXT_LEGACY_TOOLS=1 restores the historical per-function
# surface (85 tools) for anything that hardcoded the old names.
if os.getenv("JOBCONTEXT_LEGACY_TOOLS", "").strip().lower() in ("1", "true", "yes"):
    session.register(mcp)  # MUST be first — session startup tool
    job_hunt.register(mcp)
    resume.register(mcp)
    fitment.register(mcp)
    interview.register(mcp)
    interviews.register(mcp)
    project_scanner.register(mcp)
    health.register(mcp)
    oura.register(mcp)
    context.register(mcp)
    tone.register(mcp)
    rag.register(mcp)
    star.register(mcp)
    outreach.register(mcp)
    export.register(mcp)
    generate.register(mcp)
    langgraph_pipeline.register(mcp)
    people.register(mcp)
    posts.register(mcp)
    rejections.register(mcp)
    digest.register(mcp)
    compensation.register(mcp)
    ingest.register(mcp)
    hbdi.register(mcp)
    crossref.register(mcp)
    job_queue.register(mcp)
    setup.register(mcp)
    job_scraper.register(mcp)
    github.register(mcp)
else:
    from tools import consolidated

    consolidated.register(mcp)


get_job_hunt_status = job_hunt.get_job_hunt_status
update_application = job_hunt.update_application

read_master_resume = resume.read_master_resume
list_existing_materials = resume.list_existing_materials
read_existing_resume = resume.read_existing_resume
read_reference_file = resume.read_reference_file

assess_job_fitment = fitment.assess_job_fitment
get_customization_strategy = fitment.get_customization_strategy
run_job_assessment = fitment.run_job_assessment

get_interview_quick_reference = interview.get_interview_quick_reference
get_leetcode_cheatsheet = interview.get_leetcode_cheatsheet
generate_interview_prep_context = interview.generate_interview_prep_context
get_existing_prep_file = interview.get_existing_prep_file
save_interview_prep = interview.save_interview_prep

log_interview = interviews.log_interview
get_interviews = interviews.get_interviews
get_interview_context = interviews.get_interview_context

scan_project_for_skills = project_scanner.scan_project_for_skills

log_mental_health_checkin = health.log_mental_health_checkin
get_mental_health_log = health.get_mental_health_log

log_personal_story = context.log_personal_story
update_personal_story = context.update_personal_story
delete_personal_story = context.delete_personal_story
get_personal_context = context.get_personal_context

log_tone_sample = tone.log_tone_sample
get_tone_profile = tone.get_tone_profile
get_tone_profile_budgeted = tone.get_tone_profile_budgeted
get_cover_letter_tone_profile_budgeted = tone.get_cover_letter_tone_profile_budgeted
scan_materials_for_tone = tone.scan_materials_for_tone

search_materials = rag.search_materials
reindex_materials = rag.reindex_materials
reindex_stories = rag.reindex_stories

get_star_story_context = star.get_star_story_context

draft_outreach_message = outreach.draft_outreach_message

export_resume_pdf = export.export_resume_pdf
export_cover_letter_pdf = export.export_cover_letter_pdf
export_cover_letter_latex = export.export_cover_letter_latex
export_resume_latex = export.export_resume_latex
read_latex_asset = export.read_latex_asset
write_latex_section = export.write_latex_section

generate_resume = generate.generate_resume
generate_cover_letter = generate.generate_cover_letter
preview_story_retrieval = generate.preview_story_retrieval

log_person = people.log_person
get_people = people.get_people
get_person = people.get_person

log_linkedin_post = posts.log_linkedin_post
update_post_metrics = posts.update_post_metrics
get_linkedin_posts = posts.get_linkedin_posts

log_rejection = rejections.log_rejection
get_rejections = rejections.get_rejections

get_daily_digest = digest.get_daily_digest
weekly_summary = digest.weekly_summary

update_compensation = compensation.update_compensation
get_compensation_comparison = compensation.get_compensation_comparison

log_application_event = job_hunt.log_application_event
review_message = outreach.review_message
resume_diff = resume.resume_diff
ingest_anecdote = ingest.ingest_anecdote

run_hbdi_assessment = hbdi.run_hbdi_assessment
get_hbdi_profile = hbdi.get_hbdi_profile

check_workspace = setup.check_workspace
setup_workspace = setup.setup_workspace

queue_job = job_queue.queue_job
get_job_queue = job_queue.get_job_queue
evaluate_queued_job = job_queue.evaluate_queued_job
decide_job = job_queue.decide_job

scrape_job_url = job_scraper.scrape_job_url
search_jobs = job_scraper.search_jobs
search_greenhouse_jobs = job_scraper.search_greenhouse_jobs
search_lever_jobs = job_scraper.search_lever_jobs

get_upcoming_interviews = interviews.get_upcoming_interviews

get_session_context = session.get_session_context

save_resume_txt = resume.save_resume_txt
save_cover_letter_txt = resume.save_cover_letter_txt

save_job_assessment = fitment.save_job_assessment

get_daily_checkin_nudge = health.get_daily_checkin_nudge

get_all_star_context = star.get_all_star_context

draft_reply = outreach.draft_reply

ResumeAgentState = langgraph_pipeline.ResumeAgentState
load_context_node = langgraph_pipeline.load_context_node
retrieve_node = langgraph_pipeline.retrieve_node
draft_node = langgraph_pipeline.draft_node
validate_provenance_node = langgraph_pipeline.validate_provenance_node
review_node = langgraph_pipeline.review_node
revise_node = langgraph_pipeline.revise_node
finalize_node = langgraph_pipeline.finalize_node
route_after_review = langgraph_pipeline.route_after_review
generate_resume_agent = langgraph_pipeline.generate_resume_agent

lookup_person_context = people.lookup_person_context
get_referral_chains = people.get_referral_chains

run_contact_crossref = crossref.run_contact_crossref
get_contact_crossref = crossref.get_contact_crossref
get_fb_outreach_queue = crossref.get_fb_outreach_queue

get_github_stats = github.get_github_stats
refresh_portfolio_metrics = github.refresh_portfolio_metrics
get_portfolio_metrics = github.get_portfolio_metrics

_TOOL_MODULES = [
    session, job_hunt, resume, fitment, interview, interviews, project_scanner,
    health, context, tone, rag, star, outreach, export, generate,
    langgraph_pipeline, people, posts, rejections, digest, compensation,
    ingest, hbdi, crossref, job_queue, setup, job_scraper, github,
]


if __name__ == "__main__":
    import os

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport in ("sse", "streamable-http"):
        import uvicorn
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.responses import JSONResponse as _JSONResponse
        from starlette.routing import Mount, Route

        from lib.auth import EntraAuthMiddleware, oauth_discovery_json

        def _oauth_discovery(request):  # noqa: ANN001
            return _JSONResponse(oauth_discovery_json())

        mcp_app = mcp.streamable_http_app()

        app = Starlette(
            routes=[
                Route(
                    "/.well-known/oauth-authorization-server",
                    _oauth_discovery,
                ),
                Mount("/", app=mcp_app),
            ],
            middleware=[Middleware(EntraAuthMiddleware)],
        )

        uvicorn.run(
            app,
            # Binding is operator-controlled via MCP_HOST; 0.0.0.0 is the
            # documented default for containerized/remote deployment. nosec B104
            host=os.getenv("MCP_HOST", "0.0.0.0"),  # nosec B104
            port=int(os.getenv("MCP_PORT", "8000")),
        )
    else:
        mcp.run()
