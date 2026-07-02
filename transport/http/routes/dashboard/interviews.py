"""Interview prep dashboard — GET /dashboard/interviews and /dashboard/interviews/data."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])


def _has_debrief(iv: dict) -> bool:
    """An interview counts as a debrief once any debrief field is populated,
    regardless of its date. Mirrors the truthiness the frontend cards read:
    self_rating != null OR any of the debrief lists is non-empty."""
    if iv.get("self_rating") is not None:
        return True
    for key in ("what_landed", "what_didnt", "verbatim_quotes"):
        value = iv.get(key)
        if value:  # non-empty list/str
            return True
    return False


def _interviews_payload() -> dict:
    data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
    interviews = data.get("interviews", [])

    today = datetime.date.today()

    def _parse_date(d: str):
        try:
            return datetime.date.fromisoformat((d or "")[:10])
        except Exception:
            return None

    upcoming = []
    past = []
    for iv in interviews:
        # Classify by whether a debrief exists, not date alone. A debriefed
        # interview leaves "Upcoming" the moment it has content, even if it is
        # dated today. Only debrief-free interviews dated today-or-later are
        # upcoming (>= today so a midnight-dated interview earlier today isn't
        # treated as future).
        if _has_debrief(iv):
            past.append(iv)
            continue
        d = _parse_date(iv.get("interview_date", ""))
        if d is not None and d >= today:
            upcoming.append(iv)
        else:
            past.append(iv)

    upcoming.sort(key=lambda i: i.get("interview_date", ""))
    past.sort(key=lambda i: i.get("interview_date", ""), reverse=True)

    return {
        "total": len(interviews),
        "upcoming": upcoming,
        "recent": past[:20],
    }


@router.get("/interviews/data")
async def interviews_data() -> JSONResponse:
    return JSONResponse(_interviews_payload())


@router.get("/interviews")
async def interviews_board() -> HTMLResponse:
    extra_css = """
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 680px) { .two-col { grid-template-columns: 1fr; } }
    .list { display: grid; gap: 10px; }
    .iv-card {
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 12px; padding: 14px 16px;
    }
    .iv-card.upcoming { border-color: color-mix(in srgb, var(--accent) 50%, var(--line)); }
    .iv-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
    .iv-company { font-weight: 700; font-size: 1rem; }
    .iv-role { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }
    .iv-meta { color: var(--muted); font-size: 0.78rem; margin-top: 6px; display: flex; gap: 10px; flex-wrap: wrap; }
    .iv-badge {
      font-size: 0.74rem; font-weight: 600; border-radius: 999px; padding: 4px 10px; white-space: nowrap;
    }
    .iv-badge.upcoming { background: color-mix(in srgb, var(--accent) 18%, transparent); color: #d1fbfb; border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
    .iv-badge.past { background: color-mix(in srgb, var(--muted) 12%, transparent); color: var(--muted); border: 1px solid var(--line); }
    .iv-badge.today { background: color-mix(in srgb, var(--warn) 20%, transparent); color: #ffe082; border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent); }
    .iv-rating { font-size: 0.78rem; color: var(--ok); font-weight: 600; }
    .iv-section { font-size: 0.83rem; color: var(--muted); margin-top: 8px; font-weight: 600; letter-spacing: 0.3px; }
    .iv-bullets { margin: 4px 0 0 0; padding-left: 16px; color: var(--text); font-size: 0.85rem; line-height: 1.5; }
    .iv-bullets li { margin-bottom: 2px; }
    .quote { border-left: 3px solid var(--accent); padding-left: 10px; color: #c5d8ff; font-size: 0.85rem; font-style: italic; margin: 6px 0; }
    .empty { color: var(--muted); border: 1px dashed var(--line); border-radius: 12px; padding: 20px; text-align: center; }
    """

    body = """
  <section class="cards">
    <div class="card"><div class="k">Total Logged</div><div class="v" id="v-total">—</div></div>
    <div class="card"><div class="k">Upcoming</div><div class="v ok" id="v-upcoming">—</div></div>
  </section>

  <div class="two-col">
    <div>
      <h2 class="section-title">Upcoming Interviews</h2>
      <div class="list" id="upcoming-list"></div>
    </div>
    <div>
      <h2 class="section-title">Recent Debriefs</h2>
      <div class="list" id="recent-list"></div>
    </div>
  </div>

  <script>
    function esc(s) { return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

    function startOfDayLocal(dateStr) {
      const s = String(dateStr).trim();
      const m = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
      // Parse date-only strings as LOCAL calendar dates. new Date('2026-07-02')
      // parses as UTC midnight, which is the previous day west of UTC.
      if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
      const d = new Date(s.replace(' ', 'T'));
      if (isNaN(d.getTime())) return null;
      d.setHours(0, 0, 0, 0);
      return d;
    }

    function dayLabel(dateStr) {
      if (!dateStr) return '';
      const d = startOfDayLocal(dateStr);
      if (!d) return '';
      const today = new Date(); today.setHours(0,0,0,0);
      const diff = Math.round((d - today) / 86400000);
      if (diff === 0) return 'Today';
      if (diff > 0) return `In ${diff}d`;
      return `${Math.abs(diff)}d Ago`;
    }

    function typeLabel(t) {
      const map = {
        recruiter_screen: 'Recruiter Screen', hiring_manager: 'Hiring Manager',
        technical: 'Technical', panel: 'Panel', onsite_loop: 'Onsite Loop',
        informational: 'Informational', team_match: 'Team Match',
        behavioral: 'Behavioral', system_design: 'System Design',
        coding: 'Coding', debrief: 'Debrief',
      };
      return map[t] || t || '—';
    }

    function renderCard(iv, isUpcoming) {
      const date = (iv.interview_date || '').slice(0, 10);
      const label = dayLabel(iv.interview_date);
      const isToday = label === 'Today';
      const badgeCls = isUpcoming ? (isToday ? 'today' : 'upcoming') : 'past';
      const badgeText = isUpcoming ? (label || date) : (date || '—');

      let html = `<div class="iv-card ${isUpcoming ? 'upcoming' : ''}">
        <div class="iv-top">
          <div>
            <div class="iv-company">${esc(iv.company)}</div>
            <div class="iv-role">${esc(iv.role)}</div>
          </div>
          <span class="iv-badge ${badgeCls}">${esc(badgeText)}</span>
        </div>
        <div class="iv-meta">
          <span>${esc(typeLabel(iv.interview_type))}</span>
          ${iv.interviewer ? `<span>with ${esc(iv.interviewer)}${iv.interviewer_role ? ` (${esc(iv.interviewer_role)})` : ''}</span>` : ''}
          ${iv.duration_minutes ? `<span>${iv.duration_minutes} min</span>` : ''}
          ${iv.self_rating ? `<span class="iv-rating">★ ${iv.self_rating}/10</span>` : ''}
        </div>`;

      if (!isUpcoming) {
        if (iv.what_landed && iv.what_landed.length) {
          html += `<div class="iv-section">What landed</div><ul class="iv-bullets">`
            + iv.what_landed.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
        }
        if (iv.verbatim_quotes && iv.verbatim_quotes.length) {
          html += iv.verbatim_quotes.slice(0,2).map(q => {
            const text = typeof q === 'string' ? q : (q.quote || '');
            return `<div class="quote">"${esc(text)}"</div>`;
          }).join('');
        }
        if (iv.surfaced_priorities && iv.surfaced_priorities.length) {
          html += `<div class="iv-section">Surfaced priorities</div><ul class="iv-bullets">`
            + iv.surfaced_priorities.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
        }
      } else {
        if (iv.notes) {
          html += `<div class="iv-meta" style="margin-top:8px">${esc(iv.notes)}</div>`;
        }
      }

      html += '</div>';
      return html;
    }

    async function boot() {
      const res = await fetch('/dashboard/interviews/data', { credentials: 'same-origin' });
      const data = await res.json();

      document.getElementById('v-total').textContent = data.total;
      document.getElementById('v-upcoming').textContent = data.upcoming.length;

      const upEl = document.getElementById('upcoming-list');
      if (data.upcoming.length) {
        upEl.innerHTML = data.upcoming.map(iv => renderCard(iv, true)).join('');
      } else {
        upEl.innerHTML = '<div class="empty">No upcoming interviews scheduled.</div>';
      }

      const recEl = document.getElementById('recent-list');
      if (data.recent.length) {
        recEl.innerHTML = data.recent.map(iv => renderCard(iv, false)).join('');
      } else {
        recEl.innerHTML = '<div class="empty">No interviews logged yet. Use log_interview() from your AI assistant.</div>';
      }
    }

    boot();
  </script>
"""

    return HTMLResponse(html_page("Interviews", "interviews", "Upcoming schedule + debrief log", extra_css, body))  # NOSONAR
