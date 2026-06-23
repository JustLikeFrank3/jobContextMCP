"""GET /dashboard and GET /dashboard/ — home/landing page."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from transport.http.auth import require_api_key
from .assets import banner_svg

router = APIRouter(dependencies=[Depends(require_api_key)])

_PAGES = [
  (
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><path d="M3 5h14M3 10h10M3 15h6"/><circle cx="16" cy="10" r="2"/></svg>',
    "Pipeline", "/dashboard/pipeline", "Share-sheet intake, assessment, resume selection, cover letter, and apply queue",
  ),
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
    (
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><circle cx="10" cy="8" r="4"/><path d="M3 17c0-3 3-5 7-5s7 2 7 5"/><path d="M14 5l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" stroke-width="1.2"/></svg>',
        "Interviews", "/dashboard/interviews", "Upcoming schedule, debrief log, verbatim quotes",
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
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cdefs%3E%3CclipPath id='c'%3E%3Ccircle cx='42' cy='42' r='30'/%3E%3C/clipPath%3E%3C/defs%3E%3Crect width='100' height='100' fill='%231E1E1E' rx='16'/%3E%3Cline x1='64' y1='64' x2='88' y2='88' stroke='%233FA8A8' stroke-width='10' stroke-linecap='round'/%3E%3Ccircle cx='42' cy='42' r='30' fill='%230f1b2d'/%3E%3Cg clip-path='url(%23c)'%3E%3Crect x='21' y='32' width='9' height='9' fill='%23234060' rx='1.5'/%3E%3Crect x='32' y='32' width='9' height='9' fill='%23234060' rx='1.5'/%3E%3Crect x='43' y='32' width='9' height='9' fill='%233FA8A8' rx='1.5'/%3E%3Crect x='54' y='32' width='9' height='9' fill='%23234060' rx='1.5'/%3E%3Crect x='21' y='43' width='9' height='9' fill='%23234060' rx='1.5'/%3E%3Crect x='32' y='43' width='9' height='9' fill='%233FA8A8' rx='1.5'/%3E%3Crect x='43' y='43' width='9' height='9' fill='%23234060' rx='1.5'/%3E%3Crect x='54' y='43' width='9' height='9' fill='%23234060' rx='1.5'/%3E%3C/g%3E%3Ccircle cx='42' cy='42' r='30' fill='none' stroke='%23EDEDED' stroke-width='6'/%3E%3C/svg%3E" />
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
    .banner-wrap {{ width: 100%; max-width: 620px; margin: 0 auto 8px; }}
    .banner-wrap svg {{ width: 100%; height: auto; display: block; }}
    .tagline {{
      color: #06B6D4; font-size: 0.72rem; font-weight: 700;
      letter-spacing: 0.18em; text-transform: uppercase;
      text-align: center; margin: 0 0 32px;
      opacity: 0.9;
    }}
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
    .signout-wrap {{ margin-top: 28px; text-align: center; }}
    .signout-btn {{
      background: none; border: 1px solid var(--line); color: var(--muted);
      border-radius: 8px; padding: 8px 18px; font-size: 0.83rem;
      cursor: pointer; font-family: inherit;
    }}
    .signout-btn:hover {{ color: #ffdede; border-color: #c0393b; }}
  </style>
</head>
<body>
  <div class="banner-wrap">{banner_svg()}</div>
  <p class="tagline">Career Command Center</p>
  <div class="grid">
    {cards}
  </div>
  <div class="signout-wrap">
    <form method="post" action="/logout">
      <button class="signout-btn" type="submit">Sign out</button>
    </form>
  </div>
</body>
</html>"""
    return HTMLResponse(html)
