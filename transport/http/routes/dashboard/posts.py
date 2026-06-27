"""LinkedIn Posts pipeline dashboard — GET /dashboard/posts and /dashboard/posts/data."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])


def _posts_payload() -> dict:
    data = _load_json(config.LINKEDIN_POSTS_FILE, {"posts": []})
    posts = data if isinstance(data, list) else data.get("posts", [])

    def _metric(p, key):
        # metrics may be a nested dict or top-level key
        m = p.get("metrics") or {}
        if key in p and p.get(key) is not None:
            return p.get(key)
        if key in m and m.get(key) is not None:
            return m.get(key)
        return 0

    total_impressions = sum(_metric(p, "impressions") for p in posts)
    total_reactions   = sum(_metric(p, "reactions") for p in posts)
    total_comments    = sum(_metric(p, "comments") for p in posts)

    enriched = [
        {
            "source": p.get("source", ""),
            "title": p.get("title", ""),
            "posted_date": p.get("posted_date", ""),
            "url": p.get("url", ""),
            "hashtags": p.get("hashtags", []),
            "impressions": _metric(p, "impressions"),
            "reactions": _metric(p, "reactions"),
            "comments": _metric(p, "comments"),
        }
        for p in sorted(posts, key=lambda x: x.get("posted_date") or "", reverse=True)
    ]

    return {
        "total": len(posts),
        "total_impressions": total_impressions,
        "total_reactions": total_reactions,
        "total_comments": total_comments,
        "posts": enriched,
    }


@router.get("/posts/data")
async def posts_data() -> JSONResponse:
    return JSONResponse(_posts_payload())


@router.get("/posts")
async def posts_board() -> HTMLResponse:
    extra_css = """
    .post-list { display: grid; gap: 10px; }
    .post-item { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
    .post-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
    .post-title { font-weight: 600; font-size: 0.95rem; color: #e9f1ff; line-height: 1.35; }
    .post-date { color: var(--muted); font-size: 0.78rem; white-space: nowrap; }
    .post-stats { display: flex; gap: 14px; margin-top: 10px; flex-wrap: wrap; }
    .stat { display: flex; flex-direction: column; gap: 2px; }
    .stat-val { font-size: 1.1rem; font-weight: 700; color: var(--accent); }
    .stat-label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }
    .tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
    .tag { background: var(--chip); border: 1px solid var(--line); border-radius: 6px; padding: 2px 7px; font-size: 0.7rem; color: var(--muted); }
    .search-bar { margin-bottom: 14px; }
    """

    body = """
  <section class="cards">
    <div class="card"><div class="k">Total Posts</div><div class="v" id="v-total">—</div></div>
    <div class="card"><div class="k">Total Impressions</div><div class="v" id="v-impr">—</div></div>
    <div class="card"><div class="k">Total Reactions</div><div class="v" id="v-react">—</div></div>
    <div class="card"><div class="k">Total Comments</div><div class="v" id="v-comments">—</div></div>
  </section>

  <div class="search-bar">
    <input class="search" id="post-search" placeholder="Filter by title, hashtag…" style="width:100%;max-width:440px" />
  </div>

  <div class="post-list" id="post-list"></div>

  <script>
    function esc(s) { return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
    let allPosts = [];

    function renderPost(p) {
      const tags = (p.hashtags || []).map(t => `<span class="tag">#${esc(t)}</span>`).join('');
      const hasStats = p.impressions || p.reactions || p.comments;
      return `<div class="post-item">
        <div class="post-top">
          <div class="post-title">${esc(p.title || p.source || '(untitled)')}</div>
          ${p.posted_date ? `<div class="post-date">${esc(p.posted_date)}</div>` : ''}
        </div>
        ${hasStats ? `<div class="post-stats">
          ${p.impressions ? `<div class="stat"><span class="stat-val">${(p.impressions).toLocaleString()}</span><span class="stat-label">Impressions</span></div>` : ''}
          ${p.reactions  ? `<div class="stat"><span class="stat-val">${p.reactions}</span><span class="stat-label">Reactions</span></div>` : ''}
          ${p.comments   ? `<div class="stat"><span class="stat-val">${p.comments}</span><span class="stat-label">Comments</span></div>` : ''}
        </div>` : ''}
        ${tags ? `<div class="tags">${tags}</div>` : ''}
      </div>`;
    }

    async function boot() {
      const res = await fetch('/dashboard/posts/data', { credentials: 'same-origin' });
      const data = await res.json();
      allPosts = data.posts || [];

      document.getElementById('v-total').textContent    = data.total;
      document.getElementById('v-impr').textContent     = (data.total_impressions || 0).toLocaleString();
      document.getElementById('v-react').textContent    = data.total_reactions || 0;
      document.getElementById('v-comments').textContent = data.total_comments || 0;

      document.getElementById('post-list').innerHTML = allPosts.map(renderPost).join('')
        || '<div class="empty">No posts logged yet.</div>';

      document.getElementById('post-search').addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        const filtered = allPosts.filter(p =>
          [p.title, p.source, ...(p.hashtags||[])].join(' ').toLowerCase().includes(q)
        );
        document.getElementById('post-list').innerHTML = filtered.map(renderPost).join('')
          || '<div class="empty">No matches.</div>';
      });
    }

    boot();
  </script>
    """

    return HTMLResponse(html_page("LinkedIn Posts", "posts", "Engagement metrics & post log", extra_css, body))
