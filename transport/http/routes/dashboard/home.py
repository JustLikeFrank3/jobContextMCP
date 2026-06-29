"""GET /dashboard and GET /dashboard/ — home/landing page."""
from __future__ import annotations

import html
from typing import Annotated

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


def _build_snapshot() -> dict:  # NOSONAR
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


# ── Oura helpers ─────────────────────────────────────────────────────────────

def _load_oura() -> "dict | None":
    """Load today's Oura readiness snapshot from the active workspace, if present."""
    try:
        import json
        from lib.config import get_active_workspace_folder
        p = get_active_workspace_folder() / "oura.json"
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None


def _readiness_color_and_label(score: int) -> "tuple[str, str]":
    if score >= 85:
        return "#22C55E", "High readiness"
    if score >= 70:
        return "#f59e0b", "Good readiness"
    return "#ef4444", "Low readiness"


def _metric_bar_color(pct: float) -> str:
    if pct >= 75:
        return "#22C55E"
    if pct >= 50:
        return "#f59e0b"
    return "#ef4444"


def _today_move_text(oura: "dict | None", snap: dict) -> str:
    overdue = snap.get("overdue", 0)
    overdue_plural = "s" if overdue != 1 else ""
    overdue_sfx = (
        f" Clear {overdue} overdue task{overdue_plural} first."
        if overdue else ""
    )
    if oura:
        score = oura.get("readiness_score", 0)
        if score >= 85:
            base = "High readiness day. Good window for outreach and interviews."
        elif score >= 70:
            base = "Decent readiness. Stay focused on your priority tasks."
        else:
            base = "Recovery day. Keep it light. Admin and planning tasks only."
        return base + overdue_sfx
    in_flight = snap.get("in_flight", 0)
    if in_flight:
        return (
            f"{in_flight} application{'s' if in_flight != 1 else ''} in flight."
            f" Keep the momentum going." + overdue_sfx
        )
    return "Start with your top priority action." + overdue_sfx


def _build_hero_html(first_name: str, snap: dict, oura: "dict | None") -> str:  # NOSONAR
    """Build the Oura Readiness + Pipeline hero card HTML block."""
    safe_name  = first_name  # already html.escaped by caller
    has_data   = snap.get("has_data", False)
    active     = snap.get("active", 0)
    in_flight  = snap.get("in_flight", 0)
    overdue    = snap.get("overdue", 0)
    priorities = snap.get("priorities", [])

    priority_items = "".join(
        f"<li>{html.escape(p)}</li>" for p in priorities
    ) or "<li>Check your pipeline and identify next steps</li>"

    overdue_badge = (
        f'<div class="overdue-badge">'
        f'<svg viewBox="0 0 8 8" width="8" height="8" fill="currentColor">'
        f'<circle cx="4" cy="4" r="4"/></svg>'
        f" {overdue} overdue</div>"
    ) if overdue else ""

    move_text = html.escape(_today_move_text(oura, snap))

    # ── Left panel (Oura) ────────────────────────────────────────────────────
    if oura:
        score    = int(oura.get("readiness_score", 0))
        sleep_s  = int(oura.get("sleep_score", 0))
        hrv      = int(oura.get("hrv", 0))
        recovery = int(oura.get("recovery_index", 0))

        ring_color, readiness_label = _readiness_color_and_label(score)
        circ = 439.82  # 2π × 70
        dash = (score / 100) * circ

        def _mrow(name: str, val: int, unit: str, pct: float) -> str:
            color = _metric_bar_color(pct)
            return (
                f'<div class="metric-row">'
                f'<div class="metric-top">'
                f'<span class="metric-name">{name}</span>'
                f'<span class="metric-val" style="color:{color}">'
                f'{val}<span class="metric-unit">{unit}</span></span>'
                f'</div>'
                f'<div class="metric-bar-track">'
                f'<div class="metric-bar-fill" style="width:{min(pct, 100):.0f}%;background:{color}"></div>'
                f'</div></div>'
            )

        left_html = (
            f'<div class="oura-panel">'
            f'<div class="panel-eyebrow">Oura &middot; Readiness</div>'
            f'<div class="ring-wrap">'
            f'<svg viewBox="0 0 180 180" width="136" height="136">'
            f'<circle cx="90" cy="90" r="70" fill="none" stroke="#1c2740" stroke-width="16"/>'
            f'<circle cx="90" cy="90" r="70" fill="none" stroke="{ring_color}"'
            f' stroke-width="16" stroke-linecap="round"'
            f' stroke-dasharray="{dash:.1f} {circ:.2f}"'
            f' transform="rotate(-90 90 90)"/>'
            f'<text x="90" y="82" font-family="Inter,sans-serif" font-size="38"'
            f' font-weight="700" fill="#f1f5f9" text-anchor="middle">{score}</text>'
            f'<text x="90" y="104" font-family="Inter,sans-serif" font-size="10"'
            f' font-weight="600" fill="#9aa8bf" text-anchor="middle"'
            f' letter-spacing="2">SCORE</text>'
            f'</svg>'
            f'<div class="ring-readiness" style="color:{ring_color}">{html.escape(readiness_label)}</div>'
            f'</div>'
            f'<div class="metric-rows">'
            + _mrow("Sleep score", sleep_s, "", sleep_s)
            + _mrow("HRV", hrv, "ms", min(hrv, 100))
            + _mrow("Recovery index", recovery, "", recovery)
            + '</div></div>'
        )
        divider   = '<div class="hero-divider"></div>'
        body_cols = "1fr 1px 1fr"
    else:
        left_html = ""
        divider   = ""
        body_cols = "1fr"

    overdue_inline = (
        f'<div style="margin-left:auto;align-self:center">{overdue_badge}</div>'
    ) if overdue_badge else ""

    right_html = (
        '<div class="pipeline-panel">'
        '<div class="panel-eyebrow">Pipeline &middot; Today</div>'
    )
    if has_data:
        right_html += (
            f'<div class="pipeline-counts">'
            f'<div class="pcount"><span class="pcount-n">{active}</span>'
            f'<span class="pcount-l">Active</span></div>'
            f'<div class="pcount"><span class="pcount-n">{in_flight}</span>'
            f'<span class="pcount-l">In&#x2011;Flight</span></div>'
            f'{overdue_inline}'
            f'</div>'
            f'<div class="priority-eyebrow">Priority Actions</div>'
            f'<ol class="priority-list">{priority_items}</ol>'
        )
    else:
        right_html += (
            '<p style="color:var(--muted);font-size:0.88rem;margin:0 0 8px">'
            'What would you like to work on today?</p>'
        )
    right_html += '</div>'

    return (
        f'<div class="hero-greeting">Welcome back, <span>{safe_name}.</span></div>\n'
        f'  <div class="hero-card">\n'
        f'    <div class="hero-body" style="grid-template-columns:{body_cols}">\n'
        f'      {left_html}{divider}{right_html}\n'
        f'    </div>\n'
        f'    <div class="move-bar">\n'
        f'      <div class="move-label"><span class="move-dot"></span>Today\'s Move</div>\n'
        f'      <div class="move-text">{move_text}</div>\n'
        f'      <div class="move-arrow">&#8594;</div>\n'
        f'    </div>\n'
        f'  </div>'
    )


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
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="24" height="24"><circle cx="10" cy="8" r="4"/><path d="M3 17c0-3 3-5 7-5s7 2 7 5"/><path d="M14 5l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" stroke-width="1.2"/></svg>',
        "Interviews", "/dashboard/interviews", "Upcoming schedule, debrief log, verbatim quotes",
    ),
]


@router.get("/", include_in_schema=False)
async def dashboard_home(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> HTMLResponse:
    snap = _build_snapshot()

    # First name: first token of display name; graceful fallback for api-key users
    raw_name = user.name or ""
    first_name = raw_name.split()[0] if raw_name.lower() not in ("api-key", "") else "there"
    safe_first_name = html.escape(first_name)

    # ── Hero section (Oura Readiness + Pipeline) ─────────────────────────────
    oura      = _load_oura()
    hero_html = _build_hero_html(safe_first_name, snap, oura)

    # ── Cards ─────────────────────────────────────────────────────────────────
    cards = "\n".join(
        f"""<a class="card" href="{html.escape(href, quote=True)}">
      <div class="card-icon">{icon}</div>
      <div class="card-title">{html.escape(label)}</div>
      <div class="card-desc">{html.escape(desc)}</div>
      <div class="card-arrow">Open \u2192</div>
    </a>"""
        for icon, label, href, desc in _PAGES
    )

    page_html = f"""<!doctype html>
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
      --text: #e6edf7; --accent: #00B5C8; --line: #23324d;
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

    /* ── Hero greeting ── */
    .hero-greeting {{
      font-size: 1.15rem; font-weight: 500; color: var(--muted);
      margin-bottom: 12px; letter-spacing: -0.01em;
    }}
    .hero-greeting span {{ color: var(--text); font-weight: 700; }}

    /* ── Hero card ── */
    .hero-card {{
      width: 100%; max-width: 860px;
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 18px; overflow: hidden; margin-bottom: 20px;
      position: relative;
    }}
    .hero-card::before {{
      content: ''; position: absolute; top: 0; left: 0; right: 0;
      height: 3px; background: var(--accent);
    }}
    .hero-body {{ display: grid; gap: 0; padding: 24px 28px; }}
    .hero-divider {{ background: var(--line); margin: 0 4px; }}

    /* ── Oura panel ── */
    .oura-panel {{ padding-right: 24px; }}
    .panel-eyebrow {{
      font-size: 0.67rem; font-weight: 700; letter-spacing: 0.14em;
      text-transform: uppercase; color: var(--accent); opacity: 0.8;
      margin-bottom: 16px;
    }}
    .ring-wrap {{
      display: flex; flex-direction: column;
      align-items: center; margin-bottom: 18px;
    }}
    .ring-readiness {{ font-size: 0.82rem; font-weight: 600; margin-top: 6px; }}
    .metric-rows {{ display: flex; flex-direction: column; gap: 10px; }}
    .metric-row {{ display: flex; flex-direction: column; gap: 3px; }}
    .metric-top {{ display: flex; align-items: baseline; justify-content: space-between; }}
    .metric-name {{ font-size: 0.78rem; color: var(--muted); font-weight: 500; }}
    .metric-val {{ font-size: 0.88rem; font-weight: 700; font-variant-numeric: tabular-nums; }}
    .metric-unit {{ font-size: 0.68rem; font-weight: 500; color: var(--muted); }}
    .metric-bar-track {{ height: 4px; background: var(--line); border-radius: 2px; overflow: hidden; }}
    .metric-bar-fill {{ height: 100%; border-radius: 2px; }}

    /* ── Pipeline panel ── */
    .pipeline-panel {{ padding-left: 24px; }}
    .pipeline-counts {{
      display: flex; align-items: flex-start; gap: 20px; margin-bottom: 16px;
    }}
    .pcount {{ display: flex; flex-direction: column; gap: 2px; }}
    .pcount-n {{
      font-size: 2.4rem; font-weight: 800; line-height: 1;
      color: var(--text); font-variant-numeric: tabular-nums;
    }}
    .pcount-l {{
      font-size: 0.67rem; font-weight: 600; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--muted);
    }}
    .overdue-badge {{
      display: inline-flex; align-items: center; gap: 5px;
      background: color-mix(in srgb, var(--red) 15%, var(--panel));
      border: 1px solid color-mix(in srgb, var(--red) 40%, transparent);
      color: #fca5a5; font-size: 0.72rem; font-weight: 600;
      border-radius: 999px; padding: 3px 10px;
    }}
    .priority-eyebrow {{
      font-size: 0.67rem; font-weight: 700; letter-spacing: 0.14em;
      text-transform: uppercase; color: var(--muted); margin-bottom: 10px;
    }}
    .priority-list {{
      list-style: none; margin: 0; padding: 0;
      display: flex; flex-direction: column; gap: 7px;
      counter-reset: priority-counter;
    }}
    .priority-list li {{
      counter-increment: priority-counter;
      display: flex; align-items: flex-start; gap: 10px;
      font-size: 0.83rem; color: var(--text); line-height: 1.4;
    }}
    .priority-list li::before {{
      content: counter(priority-counter);
      min-width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px;
      background: color-mix(in srgb, var(--accent) 18%, var(--panel));
      border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
      color: var(--accent); font-size: 0.65rem; font-weight: 700;
      border-radius: 50%; display: flex; align-items: center; justify-content: center;
    }}

    /* ── Today's Move bar ── */
    .move-bar {{
      display: flex; align-items: center; gap: 12px;
      background: color-mix(in srgb, var(--accent) 7%, var(--panel));
      border-top: 1px solid var(--line); padding: 13px 28px;
    }}
    .move-label {{
      font-size: 0.67rem; font-weight: 700; letter-spacing: 0.14em;
      text-transform: uppercase; color: var(--accent);
      white-space: nowrap; display: flex; align-items: center; gap: 6px;
    }}
    .move-dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }}
    .move-text {{ font-size: 0.83rem; color: var(--text); line-height: 1.4; flex: 1; }}
    .move-arrow {{ color: var(--accent); font-size: 1rem; flex-shrink: 0; }}
    @media (max-width: 600px) {{
      .hero-body {{ grid-template-columns: 1fr !important; }}
      .hero-divider {{ display: none; }}
      .oura-panel {{ padding-right: 0; padding-bottom: 20px; border-bottom: 1px solid var(--line); }}
      .pipeline-panel {{ padding-left: 0; padding-top: 20px; }}
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
      grid-template-columns: repeat(4, 1fr);
    }}
    @media (max-width: 860px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 480px) {{ .grid {{ grid-template-columns: 1fr;
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
  {hero_html}
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
    return HTMLResponse(page_html)  # NOSONAR
