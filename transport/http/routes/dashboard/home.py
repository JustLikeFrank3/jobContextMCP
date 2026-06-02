"""GET /dashboard and GET /dashboard/ — home/landing page."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from transport.http.auth import require_api_key
from .assets import banner_svg

router = APIRouter(dependencies=[Depends(require_api_key)])

_PAGES = [
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><rect x="3" y="3" width="14" height="14" rx="2"/><path d="M7 7h6M7 10h6M7 13h4"/></svg>',
        "Job Hunt", "/dashboard/job-hunt", "Applications, Kanban board, status breakdown",
    ),
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><path d="M4 4h8l4 4v8a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z"/><path d="M12 4v4h4"/></svg>',
        "Materials", "/dashboard/materials", "Resumes, cover letters, PDFs, and untracked files",
    ),
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><circle cx="10" cy="10" r="7"/><path d="M10 6v4l3 3"/></svg>',
        "Rejections", "/dashboard/rejections", "Funnel analysis, patterns, company breakdown",
    ),
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><path d="M2 13l4-4 3 3 4-5 5 6"/></svg>',
        "Posts", "/dashboard/posts", "LinkedIn pipeline: draft → written → approved → posted",
    ),
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><circle cx="8" cy="7" r="3"/><path d="M2 17c0-3 2.5-5 6-5s6 2 6 5"/><circle cx="15" cy="7" r="2"/><path d="M15 12c2 .5 3 2 3 4"/></svg>',
        "Outreach", "/dashboard/people", "Contacts, follow-up queue, warm vs cold",
    ),
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><path d="M3 14l3-4 3 2 3-5 3 3"/><path d="M3 17h14"/></svg>',
        "Wellbeing", "/dashboard/health", "Mood & energy log, trend sparklines",
    ),
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><path d="M4 4h12v2H4zM4 9h8v2H4zM4 14h10v2H4z"/></svg>',
        "Daily Digest", "/dashboard/digest", "On-demand morning briefing: follow-ups, stale apps, priorities",
    ),
]


@router.get("/", include_in_schema=False)
async def dashboard_home() -> HTMLResponse:
    cards = "\n".join(
        f"""<a class="card" href="{href}">
      <div class="card-icon">{icon}</div>
      <div class="card-title">{label}</div>
      <div class="card-desc">{desc}</div>
      <div class="card-arrow">Open →</div>
    </a>"""
        for icon, label, href, desc in _PAGES
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContextMCP — Dashboard</title>
  <style>
    :root {{
      --bg: #0b1220; --panel: #111a2b; --muted: #9aa8bf;
      --text: #e6edf7; --accent: #3FA8A8; --line: #23324d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh;
      background: linear-gradient(180deg, #0b1220 0%, #0a1020 100%);
      color: var(--text);
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
                   Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; padding: 32px 16px;
    }}
    .banner-wrap {{ width: 100%; max-width: 420px; margin: 0 auto 8px; }}
    .banner-wrap svg {{ width: 100%; height: auto; display: block; }}
    .tagline {{ color: var(--muted); font-size: 0.92rem; text-align: center; margin-bottom: 32px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px; width: 100%; max-width: 860px;
    }}
    .card {{
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 14px; padding: 20px 22px;
      text-decoration: none; color: var(--text);
      display: flex; flex-direction: column; gap: 6px;
      transition: border-color .15s, background .15s;
    }}
    .card:hover {{
      border-color: var(--accent);
      background: color-mix(in srgb, var(--accent) 8%, var(--panel));
    }}
    .card-icon {{ width: 24px; height: 24px; color: var(--accent); margin-bottom: 2px; }}
    .card-title {{ font-weight: 700; font-size: 1rem; }}
    .card-desc {{ color: var(--muted); font-size: 0.83rem; line-height: 1.4; }}
    .card-arrow {{ color: var(--accent); font-size: 0.85rem; margin-top: 6px; }}
  </style>
</head>
<body>
  <div class="banner-wrap">{banner_svg()}</div>
  <p class="tagline">Job search command center</p>
  <div class="grid">
    {cards}
  </div>
</body>
</html>"""
    return HTMLResponse(html)
