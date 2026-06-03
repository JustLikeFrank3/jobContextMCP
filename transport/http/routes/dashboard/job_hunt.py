"""Job Hunt Kanban board — GET /dashboard/job-hunt and /dashboard/job-hunt/data."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import BASE_CSS, _auth_header_js, nav_tabs, page_header

router = APIRouter(dependencies=[Depends(require_api_key)])


def _load_applications() -> dict:
    data = _load_json(config.STATUS_FILE, {"applications": [], "last_updated": "unknown"})
    apps = data.get("applications", [])
    apps_sorted = sorted(apps, key=lambda a: (a.get("last_updated") or ""), reverse=True)
    status_counts = Counter((a.get("status") or "unknown").strip().lower() for a in apps_sorted)
    status_summary = [
        {"status": s, "count": c}
        for s, c in sorted(status_counts.items(), key=lambda x: (-x[1], x[0]))
    ]
    return {
        "last_updated": data.get("last_updated", "unknown"),
        "total": len(apps_sorted),
        "by_status": status_summary,
        "applications": apps_sorted,
    }


@router.get("/job-hunt/data")
async def job_hunt_data() -> JSONResponse:
    return JSONResponse(_load_applications())


_JOB_HUNT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContextMCP — Job Hunt Tracker</title>
  <style>
    BASE_CSS_PLACEHOLDER
    .kanban {
      display: grid;
      grid-template-columns: repeat(4, minmax(180px, 1fr));
      gap: 10px; margin-bottom: 16px;
    }
    .lane { background: #0f1728; border: 1px solid var(--line); border-radius: 12px; padding: 10px; min-height: 150px; }
    .lane-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; color: #c7d7ef; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.4px; }
    .lane-count { background: var(--chip); border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; font-size: 0.72rem; color: #c4d2ea; }
    .lane-items { display: grid; gap: 8px; }
    .lane-item { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 8px; font-size: 0.8rem; }
    .lane-item .company { font-weight: 600; color: #e9f1ff; }
    .lane-item .role { margin-top: 3px; color: var(--muted); line-height: 1.3; }
    .bar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin: 8px 0 14px; flex-wrap: wrap; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip { background: var(--chip); border: 1px solid var(--line); color: var(--text); border-radius: 999px; padding: 6px 10px; font-size: 0.78rem; }
    .list { display: grid; gap: 10px; }
    .item { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
    .top { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: baseline; }
    .title { font-weight: 650; font-size: 1rem; }
    .meta { color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
    .status { font-size: 0.8rem; font-weight: 600; border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; background: #0f1728; color: #dbe8ff; text-transform: lowercase; }
    .status.offer { border-color: color-mix(in srgb, var(--ok) 45%, var(--line)); color: #d9ffe6; }
    .status.rejected { border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); color: #ffdede; }
    .detail { margin-top: 10px; color: var(--text); font-size: 0.9rem; line-height: 1.45; white-space: pre-wrap; }
    @media (max-width: 980px) { .kanban { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 680px) { .kanban { grid-template-columns: 1fr; } }
  </style>
  AUTH_HEADER_JS_PLACEHOLDER
</head>
<body>
<main class="wrap">
  PAGE_HEADER_PLACEHOLDER
  NAV_TABS_PLACEHOLDER

  <section class="cards" id="summary-cards"></section>
  <div class="bar">
    <div class="chips" id="status-chips"></div>
    <input id="search" class="search" type="search" placeholder="Filter by company, role, status, notes…"
           style="min-width:280px;max-width:440px;flex:1" />
  </div>
  <h2 class="section-title">Status Board</h2>
  <section class="kanban" id="kanban"></section>
  <h2 class="section-title">Application Log</h2>
  <section class="list" id="app-list"></section>
</main>

<script>
  const el = {
    cards: document.getElementById('summary-cards'),
    chips: document.getElementById('status-chips'),
    list:  document.getElementById('app-list'),
    kanban: document.getElementById('kanban'),
    search: document.getElementById('search'),
  };
  let state = { applications: [], by_status: [], total: 0, last_updated: 'unknown' };

  function esc(s) {
    return String(s || '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  }
  function fmtStatus(s) { return (s || 'unknown').trim().toLowerCase(); }

  function renderSummary() {
    el.cards.innerHTML = [
      { k: 'Total Applications', v: state.total },
      { k: 'Unique Statuses',    v: state.by_status.length },
      { k: 'Offers',    v: state.by_status.find(x => x.status === 'offer')?.count || 0 },
      { k: 'Rejected',  v: state.by_status.find(x => x.status === 'rejected')?.count || 0 },
    ].map(c => `<article class="card"><div class="k">${esc(c.k)}</div><div class="v">${esc(c.v)}</div></article>`).join('');
    el.chips.innerHTML = state.by_status.map(s =>
      `<span class="chip">${esc(s.status)} (${esc(s.count)})</span>`
    ).join('');
  }

  function getFiltered() {
    const q = (el.search.value || '').trim().toLowerCase();
    return state.applications.filter(a => {
      if (!q) return true;
      return [a.company, a.role, a.status, a.next_steps, a.contact, a.notes].join(' ').toLowerCase().includes(q);
    });
  }

  function laneFor(status) {
    const s = fmtStatus(status);
    if (s.includes('offer')) return 'offer';
    if (s.includes('reject') || s.includes('pass')) return 'rejected';
    if (s.includes('interview') || s.includes('screen') || s.includes('onsite')) return 'interview';
    return 'active';
  }

  function renderKanban() {
    const lanes = {
      active:    { label: 'Active',          items: [] },
      interview: { label: 'Interviewing',    items: [] },
      offer:     { label: 'Offer',           items: [] },
      rejected:  { label: 'Rejected/Passed', items: [] },
    };
    getFiltered().forEach(a => lanes[laneFor(a.status)].items.push(a));
    el.kanban.innerHTML = Object.entries(lanes).map(([key, lane]) => {
      const items = lane.items.slice(0, 6).map(a =>
        `<article class="lane-item"><div class="company">${esc(a.company)}</div><div class="role">${esc(a.role)}</div></article>`
      ).join('');
      return `<section class="lane" data-lane="${key}">
        <div class="lane-head"><span>${esc(lane.label)}</span><span class="lane-count">${lane.items.length}</span></div>
        <div class="lane-items">${items || '<div class="empty">No items</div>'}</div>
      </section>`;
    }).join('');
  }

  function renderList() {
    const apps = getFiltered();
    if (!apps.length) { el.list.innerHTML = '<div class="empty">No matching applications.</div>'; return; }
    el.list.innerHTML = apps.map(a => {
      const status = fmtStatus(a.status);
      const statusClass = status.replace(/[^a-z0-9_-]/g, '-');
      return `<article class="item">
        <div class="top">
          <div>
            <div class="title">${esc(a.company)} — ${esc(a.role)}</div>
            <div class="meta">Last update: ${esc(a.last_updated || '—')}</div>
          </div>
          <span class="status ${statusClass}">${esc(status)}</span>
        </div>
        ${a.next_steps ? `<div class="detail"><strong>Next:</strong> ${esc(a.next_steps)}</div>` : ''}
        ${a.contact    ? `<div class="detail"><strong>Contact:</strong> ${esc(a.contact)}</div>`    : ''}
        ${a.notes      ? `<div class="detail"><strong>Notes:</strong> ${esc(a.notes)}</div>`        : ''}
      </article>`;
    }).join('');
  }

  async function boot() {
    const res = await fetch('/dashboard/job-hunt/data', { credentials: 'same-origin' });
    if (!res.ok) { el.list.innerHTML = `<div class="empty">Failed to load (${res.status}).</div>`; return; }
    state = await res.json();
    renderSummary(); renderKanban(); renderList();
    el.search.addEventListener('input', () => { renderKanban(); renderList(); });
  }
  boot();
</script>
</body>
</html>"""


@router.get("/job-hunt")
async def job_hunt_board() -> HTMLResponse:
    html = (
        _JOB_HUNT_HTML
        .replace("BASE_CSS_PLACEHOLDER", BASE_CSS)
        .replace("AUTH_HEADER_JS_PLACEHOLDER", _auth_header_js())
        .replace("PAGE_HEADER_PLACEHOLDER", page_header("Job Hunt Tracker", "Applications & Kanban board"))
        .replace("NAV_TABS_PLACEHOLDER", nav_tabs("job-hunt"))
    )
    return HTMLResponse(html)
