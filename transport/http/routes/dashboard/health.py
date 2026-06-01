"""Wellbeing dashboard — GET /dashboard/health and /dashboard/health/data."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])


def _health_payload() -> dict:
    data = _load_json(config.HEALTH_LOG_FILE, {"entries": []})
    entries = data.get("entries", [])
    entries_sorted = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)

    recent = entries_sorted[:30]

    def _to_num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    mood_values   = [n for e in recent if (n := _to_num(e.get("mood"))) is not None]
    energy_values = [n for e in recent if (n := _to_num(e.get("energy"))) is not None]
    avg_mood   = round(sum(mood_values) / len(mood_values), 1) if mood_values else None
    avg_energy = round(sum(energy_values) / len(energy_values), 1) if energy_values else None

    return {
        "total_entries": len(entries),
        "avg_mood": avg_mood,
        "avg_energy": avg_energy,
        "recent": recent,
    }


@router.get("/health/data")
async def health_data() -> JSONResponse:
    return JSONResponse(_health_payload())


@router.get("/health")
async def health_board() -> HTMLResponse:
    extra_css = """
    .sparkline-wrap { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin-bottom: 24px; }
    .sparkline-title { font-size: 0.82rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 10px; }
    .sparkline { display: flex; align-items: flex-end; gap: 4px; height: 60px; }
    .spark-bar { flex: 1; border-radius: 3px 3px 0 0; min-width: 4px; transition: opacity .2s; }
    .spark-bar:hover { opacity: 0.75; }
    .entry-list { display: grid; gap: 10px; }
    .entry-card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
    .entry-top { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
    .entry-date { font-size: 0.85rem; color: var(--muted); }
    .meter-row { display: flex; gap: 16px; margin-top: 10px; flex-wrap: wrap; }
    .meter { display: flex; align-items: center; gap: 8px; }
    .meter-label { font-size: 0.75rem; color: var(--muted); width: 52px; }
    .meter-track { width: 100px; height: 8px; background: #0e1628; border-radius: 4px; overflow: hidden; }
    .meter-fill { height: 100%; border-radius: 4px; }
    .meter-val { font-size: 0.8rem; font-weight: 700; }
    .entry-notes { margin-top: 8px; color: var(--text); font-size: 0.88rem; line-height: 1.45; }
    """

    body = """
  <section class="cards">
    <div class="card"><div class="k">Total Check-ins</div><div class="v" id="v-total">—</div></div>
    <div class="card"><div class="k">Avg Mood (30d)</div><div class="v" id="v-mood">—</div></div>
    <div class="card"><div class="k">Avg Energy (30d)</div><div class="v" id="v-energy">—</div></div>
  </section>

  <div class="sparkline-wrap">
    <div class="sparkline-title">Mood — last 30 check-ins (blue) &amp; Energy (teal)</div>
    <div class="sparkline" id="sparkline"></div>
  </div>

  <h2 class="section-title">Recent Check-ins</h2>
  <div class="entry-list" id="entry-list"></div>

  <script>
    function esc(s) { return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

    async function boot() {
      const res = await fetch('/dashboard/health/data');
      const data = await res.json();

      document.getElementById('v-total').textContent  = data.total_entries;
      document.getElementById('v-mood').textContent   = data.avg_mood != null ? data.avg_mood + ' / 10' : '—';
      document.getElementById('v-energy').textContent = data.avg_energy != null ? data.avg_energy + ' / 10' : '—';

      // Sparkline
      const recent = [...(data.recent || [])].reverse(); // oldest→newest for left-to-right
      document.getElementById('sparkline').innerHTML = recent.map(e => {
        const mood   = (e.mood || 0) / 10 * 100;
        const energy = (e.energy || 0) / 10 * 100;
        return `<div style="flex:1;display:flex;align-items:flex-end;gap:2px;height:100%">
          <div class="spark-bar" title="Mood: ${e.mood}" style="height:${mood}%;background:#3b82f6;flex:1"></div>
          <div class="spark-bar" title="Energy: ${e.energy}" style="height:${energy}%;background:#3FA8A8;flex:1"></div>
        </div>`;
      }).join('') || '<div style="color:var(--muted);font-size:0.8rem;padding:8px">No data yet.</div>';

      // Entry list
      document.getElementById('entry-list').innerHTML = (data.recent || []).map(e => {
        const moodPct   = ((e.mood || 0) / 10 * 100).toFixed(0);
        const energyPct = ((e.energy || 0) / 10 * 100).toFixed(0);
        return `<div class="entry-card">
          <div class="entry-top">
            <div class="entry-date">${esc(e.date || '—')}</div>
            ${e.label ? `<span style="font-size:0.8rem;color:var(--muted)">${esc(e.label)}</span>` : ''}
          </div>
          <div class="meter-row">
            <div class="meter">
              <span class="meter-label">Mood</span>
              <div class="meter-track"><div class="meter-fill" style="width:${moodPct}%;background:#3b82f6"></div></div>
              <span class="meter-val">${e.mood ?? '—'}</span>
            </div>
            <div class="meter">
              <span class="meter-label">Energy</span>
              <div class="meter-track"><div class="meter-fill" style="width:${energyPct}%;background:#3FA8A8"></div></div>
              <span class="meter-val">${e.energy ?? '—'}</span>
            </div>
          </div>
          ${e.notes ? `<div class="entry-notes">${esc(e.notes)}</div>` : ''}
        </div>`;
      }).join('') || '<div class="empty">No check-ins logged yet.</div>';
    }

    boot();
  </script>
    """

    return HTMLResponse(html_page("Wellbeing", "health", "Mood & energy log", extra_css, body))
