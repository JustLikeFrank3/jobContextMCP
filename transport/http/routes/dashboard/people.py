"""Outreach / People dashboard — GET /dashboard/people and /dashboard/people/data."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from lib import config, dismissals
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])

# A contact only belongs in the follow-up queue while the thread is alive.
# After this many days with no touch, "follow up" is fiction — the entry
# moves to the gone-cold bucket instead of nagging forever. Override with
# config value "followup_timeout_days".
DEFAULT_FOLLOWUP_TIMEOUT_DAYS = 21

# Tags that mean "this thread is closed" regardless of outreach_status —
# a ghosted recruiter marked unresponsive must never be a suggested follow-up.
_EXCLUDED_TAGS = {"unresponsive", "closed-loop", "do-not-contact", "dormant", "archived"}

_ACTIONABLE_STATUSES = ("drafted", "sent", "follow-up")


def _followup_timeout_days() -> int:
    try:
        return int(config.get_config_value("followup_timeout_days", DEFAULT_FOLLOWUP_TIMEOUT_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_FOLLOWUP_TIMEOUT_DAYS


def _last_touch(person: dict) -> "datetime | None":
    """Best-effort parse of the contact's most recent touch date."""
    for field in ("last_contacted", "last_updated"):
        value = str(person.get(field) or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value[:10]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _has_excluded_tag(person: dict) -> bool:
    tags = person.get("tags") or []
    return any(str(t).strip().lower().replace("_", "-") in _EXCLUDED_TAGS for t in tags)


def _is_followup_fresh(person: dict, timeout_days: int) -> bool:
    """True while the thread is recent enough that a follow-up makes sense.

    No parseable date means we cannot claim the thread is alive — treat as
    timed out rather than nagging about a contact of unknown age.
    """
    touched = _last_touch(person)
    if touched is None:
        return False
    return (datetime.now(timezone.utc) - touched).days <= timeout_days


def _people_payload() -> dict:
    raw = _load_json(config.PEOPLE_FILE, [])
    people = raw if isinstance(raw, list) else raw.get("people", [])
    def _recency_key(person: dict) -> str:
        last_contacted = person.get("last_contacted")
        if last_contacted not in (None, ""):
            return str(last_contacted)
        last_updated = person.get("last_updated")
        if last_updated not in (None, ""):
            return str(last_updated)
        return ""

    people_sorted = sorted(people, key=_recency_key, reverse=True)

    status_counts = Counter(p.get("outreach_status", "none") for p in people)
    relationship_counts = Counter(p.get("relationship", "unknown") for p in people)

    timeout_days = _followup_timeout_days()
    dismissed = dismissals.active_keys("followup")

    actionable = [
        p for p in people
        if (p.get("outreach_status") or "").lower() in _ACTIONABLE_STATUSES
        and not _has_excluded_tag(p)
        and str(p.get("name") or "") not in dismissed
    ]
    follow_up = [p for p in actionable if _is_followup_fresh(p, timeout_days)]
    # Timed-out threads: not hidden (the data is real), just not a to-do.
    gone_cold = [p for p in actionable if not _is_followup_fresh(p, timeout_days)]
    follow_up.sort(key=_recency_key, reverse=True)
    gone_cold.sort(key=_recency_key, reverse=True)

    return {
        "total": len(people),
        "by_status": [{"status": s, "count": c} for s, c in status_counts.most_common()],
        "by_relationship": [{"relationship": r, "count": c} for r, c in relationship_counts.most_common()],
        "follow_up_queue": follow_up[:30],
        "gone_cold": gone_cold[:30],
        "gone_cold_total": len(gone_cold),
        "followup_timeout_days": timeout_days,
        "recent": people_sorted[:20],
        # Full roster (recency-sorted, sanity-capped) so clients can filter by
        # outreach_status/relationship without a round-trip per facet.
        "people": people_sorted[:500],
    }


class _DismissFollowupRequest(BaseModel):
    name: str
    days: int | None = None  # None = permanent
    restore: bool = False


@router.post("/people/dismiss-followup", responses={400: {"description": "Missing contact name"}})
async def people_dismiss_followup(req: _DismissFollowupRequest) -> JSONResponse:
    """Drop (or restore) a contact from the follow-up surfaces.

    The queue is a derived view, so this records a per-user overlay entry
    rather than mutating the contact. Dismissal also removes the contact
    from the gone-cold bucket and from Home's drafted-message priority.
    """
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Contact name is required")
    if req.restore:
        dismissals.restore("followup", name)
    else:
        dismissals.dismiss("followup", name, days=req.days)
    return JSONResponse({"ok": True, "name": name, "restored": req.restore})


@router.get("/people/data")
async def people_data() -> JSONResponse:
    return JSONResponse(_people_payload())


@router.get("/people")
async def people_board() -> HTMLResponse:
    extra_css = """
    .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 24px; }
    .status-tile { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; }
    .status-tile .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }
    .status-tile .count { font-size: 1.4rem; font-weight: 700; margin-top: 6px; }
    .person-list { display: grid; gap: 10px; }
    .person-card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
    .person-top { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }
    .person-name { font-weight: 700; font-size: 1rem; }
    .person-company { color: var(--muted); font-size: 0.83rem; margin-top: 2px; }
    .status-badge { font-size: 0.75rem; font-weight: 600; border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px; color: var(--accent); white-space: nowrap; }
    .person-context { margin-top: 8px; color: var(--muted); font-size: 0.83rem; line-height: 1.4; }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .tag { background: var(--chip); border: 1px solid var(--line); border-radius: 6px; padding: 2px 7px; font-size: 0.72rem; color: var(--muted); }
    .search-bar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    """

    body = """
  <section class="cards">
    <div class="card"><div class="k">Total Contacts</div><div class="v" id="v-total">—</div></div>
    <div class="card"><div class="k">Follow-up Queue</div><div class="v" id="v-queue">—</div></div>
  </section>

  <h2 class="section-title">By Outreach Status</h2>
  <div class="status-grid" id="status-grid"></div>

  <h2 class="section-title">Follow-up Queue</h2>
  <div class="person-list" id="follow-up-list"></div>

  <h2 class="section-title">Recent Contacts</h2>
  <div class="search-bar">
    <input class="search" id="people-search" placeholder="Filter by name, company, tags…" style="flex:1;max-width:440px" />
  </div>
  <div class="person-list" id="people-list"></div>

  <script>
    function esc(s) { return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
    let allPeople = [];

    function renderPerson(p) {
      const tags = (p.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
      return `<div class="person-card">
        <div class="person-top">
          <div>
            <div class="person-name">${esc(p.name || '—')}</div>
            <div class="person-company">${esc(p.company || '')} ${p.relationship ? '· ' + esc(p.relationship) : ''}</div>
          </div>
          ${p.outreach_status ? `<span class="status-badge">${esc(p.outreach_status)}</span>` : ''}
        </div>
        ${p.context ? `<div class="person-context">${esc(p.context)}</div>` : ''}
        ${tags ? `<div class="tags">${tags}</div>` : ''}
      </div>`;
    }

    async function boot() {
      const res = await fetch('/dashboard/people/data', { credentials: 'same-origin' });
      const data = await res.json();
      allPeople = data.recent || [];

      document.getElementById('v-total').textContent = data.total;
      document.getElementById('v-queue').textContent = data.follow_up_queue.length;

      document.getElementById('status-grid').innerHTML = data.by_status.map(s =>
        `<div class="status-tile"><div class="label">${esc(s.status)}</div><div class="count">${s.count}</div></div>`
      ).join('') || '<div class="empty">No contacts yet.</div>';

      document.getElementById('follow-up-list').innerHTML = data.follow_up_queue.map(renderPerson).join('')
        || '<div class="empty">No follow-ups needed right now.</div>';

      document.getElementById('people-list').innerHTML = allPeople.map(renderPerson).join('')
        || '<div class="empty">No contacts logged yet.</div>';

      document.getElementById('people-search').addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        const filtered = allPeople.filter(p =>
          [p.name, p.company, p.relationship, p.context, ...(p.tags||[])].join(' ').toLowerCase().includes(q)
        );
        document.getElementById('people-list').innerHTML = filtered.map(renderPerson).join('')
          || '<div class="empty">No matches.</div>';
      });
    }

    boot();
  </script>
    """

    return HTMLResponse(html_page("Outreach", "people", "Contacts, follow-up queue & warm paths", extra_css, body))  # NOSONAR
