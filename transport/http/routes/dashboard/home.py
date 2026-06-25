"""GET /dashboard and GET /dashboard/ — home/landing page."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from transport.http.auth import require_api_key, require_authenticated_user
from transport.http.security import User
from .assets import banner_svg

# Snapshot data helpers — resolved per-request via contextvars middleware
from tools.digest import (
    _load_apps,
    _load_queue,
    _load_people,
    _load_health,
    _is_closed,
    _is_waiting,
    _days_since,
)
from tools.job_hunt import _check_overdue_followups

router = APIRouter(dependencies=[Depends(require_api_key)])


def _build_snapshot() -> dict:
    """Return lightweight structured data for the home page welcome snapshot."""
    try:
        apps        = _load_apps()
        queue_jobs  = _load_queue()
        people      = _load_people()
        health      = _load_health()
    except Exception:
        return {"has_data": False}

    active = [a for a in apps if not _is_closed(a)]
    if not active and not queue_jobs:
        return {"has_data": False}

    waiting      = [a for a in active if _is_waiting(a)]
    closed_count = sum(1 for a in apps if _is_closed(a))

    overdue      = _check_overdue_followups(active)

    drafted_unsent = [
        p for p in people
        if p.get("outreach_status", "").lower() == "drafted"
    ]
    undecided = [j for j in queue_jobs if j.get("status") in ("pending", "evaluated")]

    needs_review = sorted(
        [
            a for a in active
            if not _is_waiting(a) and _days_since(a.get("last_updated", "")) >= 14
        ],
        key=lambda x: _days_since(x.get("last_updated", "")),
        reverse=True,
    )

    # Build today's focus (mirrors digest priority logic)
    priorities: list[str] = []
    if overdue:
        company = overdue[0].split("]")[-1].split("—")[0].strip() if "]" in overdue[0] else "overdue item"
        priorities.append(f"Follow up with {company}")
    if drafted_unsent:
        priorities.append(f"Send message to {drafted_unsent[0]['name']}")
    if needs_review and len(priorities) < 3:
        a = needs_review[0]
        priorities.append(f"Review: {a['company']} — {a['role']}")
    if undecided and len(priorities) < 3:
        j = undecided[0]
        verb = "Apply to" if j.get("status") == "evaluated" else "Evaluate"
        priorities.append(f"{verb}: {j['company']} — {j['role']}")
    if not priorities:
        if waiting:
            priorities.append(f"Check in on {waiting[0]['company']}")
        priorities.append("Apply to 2–3 new roles today")
        if not health or _days_since(health[-1].get("date", "2000-01-01")) >= 3:
            priorities.append("Log a check-in after your session")

    return {
        "has_data":      True,
        "active":        len(active),
        "in_flight":     len(waiting),
        "closed":        closed_count,
        "overdue":       len(overdue),
        "drafted_unsent": len(drafted_unsent),
        "undecided":     len(undecided),
        "priorities":    priorities[:3],
    }

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
async def dashboard_home(
    user: User = Depends(require_authenticated_user),
) -> HTMLResponse:
    snap = _build_snapshot()

    # First name: first token of display name; graceful fallback for api-key users
    raw_name = user.name or ""
    first_name = raw_name.split()[0] if raw_name.lower() not in ("api-key", "") else "there"

    # ── Greeting section ─────────────────────────────────────────────────────
    if snap["has_data"]:
        stat_pills = (
            f'<span class="stat-pill">'
            f'<span class="stat-n">{snap["active"]}</span>'
            f'<span class="stat-l">active</span></span>'
            f'<span class="stat-sep">\u00b7</span>'
            f'<span class="stat-pill">'
            f'<span class="stat-n">{snap["in_flight"]}</span>'
            f'<span class="stat-l">in flight</span></span>'
            f'<span class="stat-sep">\u00b7</span>'
            f'<span class="stat-pill dim">'
            f'<span class="stat-n">{snap["closed"]}</span>'
            f'<span class="stat-l">closed</span></span>'
        )
        if snap["overdue"]:
            n = snap["overdue"]
            stat_pills += f'<span class="badge-alert">&#9888; {n} overdue</span>'
        if snap["undecided"]:
            n = snap["undecided"]
            stat_pills += f'<span class="badge-warn">{n} to evaluate</span>'

        focus_items = "".join(f"<li>{p}</li>" for p in snap["priorities"])

        greeting_html = f"""  <div class="greeting-wrap">
    <p class="greeting-salutation">Welcome back, <span class="greeting-name">{first_name}.</span></p>
    <div class="stat-row">{stat_pills}</div>
    <div class="snapshot-card">
      <div class="snap-eyebrow">Here&#8217;s what you&#8217;ve got</div>
      <ol class="focus-ol">{focus_items}</ol>
    </div>
  </div>"""
    else:
        greeting_html = f"""  <div class="greeting-wrap">
    <p class="greeting-salutation">Welcome back, <span class="greeting-name">{first_name}.</span></p>
    <p class="greeting-sub">What would you like to get started on today?</p>
  </div>"""

    # ── Cards ─────────────────────────────────────────────────────────────────
    cards = "\n".join(
        f"""<a class="card" href="{href}">
      <div class="card-icon">{icon}</div>
      <div class="card-title">{label}</div>
      <div class="card-desc">{desc}</div>
      <div class="card-arrow">Open \u2192</div>
    </a>"""
        for icon, label, href, desc in _PAGES
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContext \u2014 Dashboard</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <style>
    :root {{
      --bg: #0b1220; --panel: #111a2b; --muted: #9aa8bf;
      --text: #e6edf7; --accent: #3FA8A8; --line: #23324d;
      --amber: #f59e0b; --red: #ef4444;
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

    /* ── Greeting ── */
    .greeting-wrap {{
      width: 100%; max-width: 860px;
      display: flex; flex-direction: column; align-items: center;
      gap: 10px; margin-bottom: 24px;
    }}
    .greeting-salutation {{
      margin: 0;
      font-size: 1.35rem; font-weight: 500; color: var(--muted);
      letter-spacing: -0.01em;
    }}
    .greeting-name {{ color: var(--text); font-weight: 700; }}
    .greeting-sub {{
      margin: 4px 0 0; font-size: 0.9rem;
      color: var(--muted); font-style: italic;
    }}

    /* ── Stat row ── */
    .stat-row {{
      display: flex; align-items: center; flex-wrap: wrap;
      gap: 6px 10px; justify-content: center;
    }}
    .stat-pill {{ display: inline-flex; align-items: baseline; gap: 4px; }}
    .stat-pill.dim .stat-n {{ color: var(--muted); }}
    .stat-n {{
      font-size: 1.05rem; font-weight: 700; color: var(--accent);
      font-variant-numeric: tabular-nums;
    }}
    .stat-l {{ font-size: 0.75rem; color: var(--muted); font-weight: 500; }}
    .stat-sep {{ color: var(--line); font-size: 1rem; }}
    .badge-alert {{
      display: inline-flex; align-items: center; gap: 4px;
      background: color-mix(in srgb, var(--red) 15%, var(--panel));
      border: 1px solid color-mix(in srgb, var(--red) 40%, transparent);
      color: #fca5a5; font-size: 0.72rem; font-weight: 600;
      border-radius: 999px; padding: 2px 10px; letter-spacing: 0.01em;
    }}
    .badge-warn {{
      display: inline-flex; align-items: center;
      background: color-mix(in srgb, var(--amber) 12%, var(--panel));
      border: 1px solid color-mix(in srgb, var(--amber) 35%, transparent);
      color: #fcd34d; font-size: 0.72rem; font-weight: 600;
      border-radius: 999px; padding: 2px 10px;
    }}

    /* ── Snapshot card ── */
    .snapshot-card {{
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 14px; padding: 16px 22px 18px;
      width: 100%; max-width: 480px;
    }}
    .snap-eyebrow {{
      font-size: 0.67rem; font-weight: 700; letter-spacing: 0.14em;
      text-transform: uppercase; color: var(--accent);
      opacity: 0.8; margin-bottom: 10px;
    }}
    .focus-ol {{
      margin: 0; padding: 0; list-style: none;
      display: flex; flex-direction: column; gap: 7px;
      counter-reset: focus-counter;
    }}
    .focus-ol li {{
      counter-increment: focus-counter;
      display: flex; align-items: flex-start; gap: 10px;
      font-size: 0.85rem; color: var(--text); line-height: 1.4;
    }}
    .focus-ol li::before {{
      content: counter(focus-counter);
      min-width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px;
      background: color-mix(in srgb, var(--accent) 18%, var(--panel));
      border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
      color: var(--accent); font-size: 0.65rem; font-weight: 700;
      border-radius: 50%; display: flex; align-items: center; justify-content: center;
    }}

    /* ── Why link ── */
    .why-link {{
      display: inline-flex; align-items: center; gap: 6px;
      color: var(--muted); font-size: 0.78rem; text-decoration: none;
      border: 1px solid var(--line); border-radius: 999px;
      padding: 4px 12px; margin-bottom: 16px;
      transition: color .15s, border-color .15s;
    }}
    .why-link:hover {{ color: var(--accent); border-color: var(--accent); }}

    /* ── Card grid ── */
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

    /* ── Sign out ── */
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
  {greeting_html}
  <a class="why-link" href="/why" target="_blank" rel="noopener noreferrer">
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="13" height="13"><circle cx="8" cy="8" r="6"/><path d="M8 5.5v.5"/><path d="M8 8v3" stroke-linecap="round"/></svg>
    Why use jobContext?
  </a>
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
