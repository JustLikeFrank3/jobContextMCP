"""Rejections dashboard — GET /dashboard/rejections and /dashboard/rejections/data."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])


def _rejections_payload() -> dict:
    data = _load_json(config.REJECTIONS_FILE, {"rejections": []})
    rejections = data.get("rejections", [])

    stage_counts = Counter(r.get("stage", "unknown") for r in rejections)
    company_counts = Counter(r.get("company", "unknown") for r in rejections)

    return {
        "total": len(rejections),
        "by_stage": [{"stage": s, "count": c} for s, c in stage_counts.most_common()],
        "by_company": [{"company": co, "count": c} for co, c in company_counts.most_common(15)],
        "recent": sorted(rejections, key=lambda r: r.get("date", ""), reverse=True)[:20],
    }


@router.get("/rejections/data")
async def rejections_data() -> JSONResponse:
    return JSONResponse(_rejections_payload())


@router.get("/rejections")
async def rejections_board() -> HTMLResponse:
    extra_css = """
    .funnel { display: flex; flex-direction: column; gap: 8px; margin-bottom: 24px; }
    .funnel-row { display: flex; align-items: center; gap: 12px; }
    .funnel-label { width: 160px; font-size: 0.82rem; color: var(--muted); flex-shrink: 0; text-align: right; }
    .funnel-bar-wrap { flex: 1; background: #0e1628; border-radius: 6px; overflow: hidden; height: 28px; }
    .funnel-bar { height: 100%; background: color-mix(in srgb, var(--danger) 70%, var(--accent)); border-radius: 6px; display: flex; align-items: center; padding: 0 10px; font-size: 0.78rem; font-weight: 700; color: #fff; min-width: 32px; transition: width .4s; }
    .list { display: grid; gap: 10px; }
    .item { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
    .item-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
    .item-company { font-weight: 700; font-size: 1rem; }
    .item-role { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }
    .stage-badge { font-size: 0.75rem; font-weight: 600; border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--line)); color: #ffdede; border-radius: 999px; padding: 5px 10px; white-space: nowrap; }
    .item-date { color: var(--muted); font-size: 0.78rem; margin-top: 6px; }
    .item-notes { color: var(--text); font-size: 0.88rem; margin-top: 8px; line-height: 1.45; }
    .bar-chart { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 24px; }
    .bar-card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; }
    .bar-card .co { font-size: 0.82rem; font-weight: 600; color: #d7e3f8; margin-bottom: 4px; }
    .bar-card .ct { font-size: 1.3rem; font-weight: 700; color: var(--danger); }
    """

    body = """
  <section class="cards">
    <div class="card"><div class="k">Total Rejections</div><div class="v danger" id="v-total">—</div></div>
    <div class="card"><div class="k">Unique Stages</div><div class="v" id="v-stages">—</div></div>
    <div class="card"><div class="k">Companies</div><div class="v" id="v-companies">—</div></div>
  </section>

  <h2 class="section-title">Rejection Funnel by Stage</h2>
  <div class="funnel" id="funnel"></div>

  <h2 class="section-title">Top Companies by Rejections</h2>
  <div class="bar-chart" id="bar-chart"></div>

  <h2 class="section-title">Recent Rejections</h2>
  <div class="list" id="reject-list"></div>

  <script>
    function esc(s) { return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

    async function boot() {
      const res = await fetch('/dashboard/rejections/data');
      const data = await res.json();

      document.getElementById('v-total').textContent    = data.total;
      document.getElementById('v-stages').textContent   = data.by_stage.length;
      document.getElementById('v-companies').textContent = data.by_company.length;

      // Funnel
      const maxCount = Math.max(...data.by_stage.map(s => s.count), 1);
      document.getElementById('funnel').innerHTML = data.by_stage.map(s => {
        const pct = Math.round((s.count / maxCount) * 100);
        return `<div class="funnel-row">
          <div class="funnel-label">${esc(s.stage)}</div>
          <div class="funnel-bar-wrap"><div class="funnel-bar" style="width:${pct}%">${s.count}</div></div>
        </div>`;
      }).join('') || '<div class="empty">No rejection stage data yet.</div>';

      // Top companies
      document.getElementById('bar-chart').innerHTML = data.by_company.map(c =>
        `<div class="bar-card"><div class="co">${esc(c.company)}</div><div class="ct">${c.count}</div></div>`
      ).join('') || '<div class="empty">No company data yet.</div>';

      // Recent list
      document.getElementById('reject-list').innerHTML = data.recent.map(r => `
        <article class="item">
          <div class="item-top">
            <div>
              <div class="item-company">${esc(r.company || '—')}</div>
              <div class="item-role">${esc(r.role || '—')}</div>
            </div>
            <span class="stage-badge">${esc(r.stage || 'unknown')}</span>
          </div>
          <div class="item-date">${esc(r.date || '—')}</div>
          ${r.notes ? `<div class="item-notes">${esc(r.notes)}</div>` : ''}
        </article>
      `).join('') || '<div class="empty">No rejections logged yet.</div>';
    }

    boot();
  </script>
    """

    return HTMLResponse(html_page("Rejections", "rejections", "Funnel analysis & patterns", extra_css, body))
