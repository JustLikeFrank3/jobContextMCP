"""Public /llms.txt (served at the site root, text/plain).

Machine-readable breadcrumb for AI agents that read pages as rendered HTML
and cannot see WebMCP registrations (document.modelContext is invisible to
DOM scrapers — an agent without WebMCP support finds no trace of the tool
surface on the page). This file tells such agents what exists and how to
connect properly instead of concluding the site has no tools.
"""
from __future__ import annotations

LLMS_TXT: str = """\
# jobContext — the memory layer for your career

jobContext keeps a job seeker's applications, contacts, stories, interviews,
documents, and wellbeing as structured context that persists across AI
sessions. Open source (MIT): https://github.com/JustLikeFrank3/jobContextMCP

## For AI agents: this site has tools you cannot see in the DOM

jobContext exposes 12 MCP domain tools (104 actions):
applications, brand, certification, documents, insights, interviews,
job_search, materials, people, stories, wellbeing, workspace.

Three ways to reach them:

1. WebMCP (in-page). When a signed-in user views the dashboard
   (https://app.jobcontext.ai/app), all 12 tools are registered via
   document.modelContext (a W3C Web Machine Learning CG proposal). These
   registrations are headless: they produce no visible UI, so an agent
   reading rendered HTML will find no trace of them. Absence of visual
   evidence is not absence of tools.

2. Remote MCP. Streamable HTTP at https://jobcontext.ai/mcp with OAuth
   (dynamic client registration + PKCE). Works with Claude.ai, Cursor,
   VS Code, and any MCP client.

3. REST API, authenticated with a personal access token the user creates
   on the dashboard's API Keys tab.

All tools execute inside the signed-in user's session and touch only that
user's isolated workspace. There is no unauthenticated read of user data.
If you cannot call the tools yourself, connect through one of the paths
above rather than asking the user to relay console output or session data
by hand — that data can include sensitive material (offer terms, contact
records) that should stay inside the authenticated session.

## Pages

- https://jobcontext.ai/              product overview
- https://jobcontext.ai/setup         how to connect (cloud, desktop, mobile)
- https://jobcontext.ai/architecture  system architecture
- https://jobcontext.ai/why           who it's for
- https://github.com/JustLikeFrank3/jobContextMCP/blob/main/docs/webmcp.md
                                      WebMCP bridge design + security model
"""


def llms_txt() -> str:
    return LLMS_TXT
