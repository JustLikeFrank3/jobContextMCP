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
from mcp.server.fastmcp import FastMCP

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
    github,
)


# Tool modules in registration order (session MUST be first).
_TOOL_MODULES = [
    session,
    job_hunt,
    resume,
    fitment,
    interview,
    interviews,
    project_scanner,
    health,
    context,
    tone,
    rag,
    star,
    outreach,
    export,
    generate,
    langgraph_pipeline,
    people,
    posts,
    rejections,
    digest,
    compensation,
    ingest,
    hbdi,
    crossref,
    job_queue,
    github,
    setup,
]


def _sync_config_exports() -> None:
    """Mirror every UPPERCASE attribute from lib.config (plus _cfg) onto this
    module so tests and legacy callers can read paths via `server.STATUS_FILE`.
    Auto-discovers new path constants — no manual additions needed when
    lib.config grows.
    """
    module_globals = globals()
    module_globals["_cfg"] = config._cfg
    for name in dir(config):
        if name.startswith("_"):
            continue
        if not name.isupper() and not name[0].isupper():
            continue
        module_globals[name] = getattr(config, name)


def _sync_tool_exports() -> None:
    """Alias every public callable defined in each tool module onto this
    module so tests and legacy callers can call them as `server.queue_job(...)`.
    Auto-discovers new tools — no manual aliases needed.
    Skips `register`, dunders, and re-imported callables from other modules.
    """
    module_globals = globals()
    for mod in _TOOL_MODULES:
        for name, value in vars(mod).items():
            if name.startswith("_") or name == "register":
                continue
            if not callable(value):
                continue
            # Only alias things defined IN this tool module, not re-imports.
            if getattr(value, "__module__", "") != mod.__name__:
                continue
            module_globals[name] = value


def _reconfigure(cfg: dict) -> None:
    config._reconfigure(cfg)
    _sync_config_exports()


_sync_config_exports()


mcp = FastMCP(
    "jobContextMCP",
    instructions=(
        "You are Frank MacBride's personal job search assistant. "
        "You have direct filesystem access to his resume materials, job hunt status, "
        "and interview prep files. Use the available tools to retrieve context before "
        "generating resumes, cover letters, prep docs, or assessments. "
        "Always read the master resume before generating any application material."
    ),
)


session.register(mcp)  # MUST be first — session startup tool
for _mod in _TOOL_MODULES[1:]:
    _mod.register(mcp)


# Auto-alias every public tool function onto this module so tests and legacy
# callers can use `server.queue_job(...)`. Stable across new tool additions.
_sync_tool_exports()


if __name__ == "__main__":
    import os

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport in ("sse", "streamable-http"):
        mcp.run(
            transport=transport,
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("MCP_PORT", "8000")),
        )
    else:
        mcp.run()
