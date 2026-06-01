"""Materials dashboard — GET /dashboard/materials and /dashboard/materials/data."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])

_FOLDERS = {
    "optimized_resumes": ("01-Current-Optimized", [".txt", ".docx"]),
    "cover_letters":     ("02-Cover-Letters",     [".txt", ".docx", ".pdf"]),
    "resume_pdfs":       ("03-Resume-PDFs",        [".pdf"]),
    "job_assessments":   ("07-Job-Assessments",    [".md", ".pdf", ".txt"]),
    "interview_prep":    ("08-Interview-Prep-Docs",[".md", ".pdf", ".txt"]),
}


def _workspace_base() -> Path:
    return config.RESUME_FOLDER


def _scan_folders() -> dict:
    base = _workspace_base()
    result = {}
    for key, (folder_name, exts) in _FOLDERS.items():
        d = base / folder_name
        if d.exists():
            files = sorted(
                [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts and not f.name.startswith(".")],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            result[key] = {"folder": folder_name, "count": len(files),
                           "files": [{"name": f.name, "ext": f.suffix.lower()} for f in files]}
        else:
            result[key] = {"folder": folder_name, "count": 0, "files": []}
    return result


def _load_tracked_companies() -> list[str]:
    data = _load_json(config.STATUS_FILE, {"applications": []})
    return [a.get("company", "").strip() for a in data.get("applications", []) if a.get("company")]


def _materials_payload() -> dict:
    folders = _scan_folders()
    tracked = _load_tracked_companies()
    opt_files = [f["name"] for f in folders.get("optimized_resumes", {}).get("files", [])]
    untracked_files = []
    for fname in opt_files:
        fname_lower = fname.lower()
        found = any(
            company.lower() in fname_lower or fname_lower.startswith(company.lower().replace(" ", ""))
            for company in tracked
        )
        if not found:
            untracked_files.append(fname)
    return {
        "folders": folders,
        "tracked_applications": len(tracked),
        "optimized_resumes": folders.get("optimized_resumes", {}).get("count", 0),
        "cover_letters": folders.get("cover_letters", {}).get("count", 0),
        "resume_pdfs": folders.get("resume_pdfs", {}).get("count", 0),
        "gap": len(untracked_files),
        "untracked_resume_files": untracked_files,
    }


@router.get("/materials/data")
async def materials_data() -> JSONResponse:
    return JSONResponse(_materials_payload())


@router.get("/materials")
async def materials_board() -> HTMLResponse:
    extra_css = """
    .folder-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px; margin-bottom: 24px;
    }
    .folder-card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
    .folder-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .folder-name { font-weight: 600; font-size: 0.92rem; color: #c8d8f4; }
    .folder-count { background: var(--chip); border: 1px solid var(--line); border-radius: 999px; padding: 3px 9px; font-size: 0.75rem; color: var(--muted); }
    .file-list { display: flex; flex-direction: column; gap: 4px; max-height: 220px; overflow-y: auto; }
    .file-item { display: flex; align-items: center; gap: 7px; font-size: 0.78rem; color: var(--muted); padding: 4px 6px; border-radius: 6px; }
    .file-item:hover { background: #0e1628; color: var(--text); }
    .ext-badge { font-size: 0.65rem; font-weight: 700; padding: 2px 5px; border-radius: 4px; background: var(--chip); color: var(--accent); text-transform: uppercase; flex-shrink: 0; }
    .gap-item { background: var(--panel); border: 1px solid color-mix(in srgb, var(--warn) 30%, var(--line)); border-radius: 10px; padding: 10px 14px; font-size: 0.82rem; color: #fde9b0; margin-bottom: 6px; }
    @media (max-width: 600px) { .folder-grid { grid-template-columns: 1fr; } }
    """

    body = """
  <section class="cards">
    <div class="card"><div class="k">Optimized Resumes</div><div class="v" id="v-opt">—</div></div>
    <div class="card"><div class="k">Cover Letters</div><div class="v" id="v-cl">—</div></div>
    <div class="card"><div class="k">Resume PDFs</div><div class="v" id="v-pdf">—</div></div>
    <div class="card"><div class="k">Tracked Applications</div><div class="v" id="v-tracked">—</div></div>
    <div class="card"><div class="k">Untracked Resumes</div><div class="v" id="v-gap">—</div></div>
  </section>

  <h2 class="section-title">Folders</h2>
  <div class="folder-grid" id="folder-grid"></div>

  <h2 class="section-title" id="gap-heading"></h2>
  <input class="search" id="gap-search" placeholder="Filter untracked files…" style="width:100%;max-width:440px;margin-bottom:14px" />
  <div id="gap-list"></div>

  <script>
    let data = null;
    const FOLDER_LABELS = {
      optimized_resumes: 'Optimized Resumes',
      cover_letters:     'Cover Letters',
      resume_pdfs:       'Resume PDFs',
      job_assessments:   'Job Assessments',
      interview_prep:    'Interview Prep',
    };
    function esc(s) { return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

    async function boot() {
      const res = await fetch('/dashboard/materials/data', { headers: window._authHeaders });
      data = await res.json();
      const gapEl = document.getElementById('v-gap');
      document.getElementById('v-opt').textContent     = data.optimized_resumes;
      document.getElementById('v-cl').textContent      = data.cover_letters;
      document.getElementById('v-pdf').textContent     = data.resume_pdfs;
      document.getElementById('v-tracked').textContent = data.tracked_applications;
      gapEl.textContent = data.gap;
      gapEl.className = 'v ' + (data.gap > 0 ? 'warn' : 'ok');
      renderFolders();
      renderGap('');
      document.getElementById('gap-search').addEventListener('input', e => renderGap(e.target.value.toLowerCase()));
    }

    function renderFolders() {
      const grid = document.getElementById('folder-grid');
      grid.innerHTML = '';
      for (const [key, label] of Object.entries(FOLDER_LABELS)) {
        const folder = data.folders[key];
        if (!folder) continue;
        const files = folder.files.slice(0, 50);
        const div = document.createElement('div');
        div.className = 'folder-card';
        div.innerHTML = `
          <div class="folder-head">
            <span class="folder-name">${label}</span>
            <span class="folder-count">${folder.count}</span>
          </div>
          <div class="file-list">
            ${files.map(f => `<div class="file-item"><span class="ext-badge">${esc(f.ext.replace('.',''))}</span><span>${esc(f.name)}</span></div>`).join('')}
            ${folder.count > 50 ? `<div class="empty">+ ${folder.count - 50} more…</div>` : ''}
          </div>`;
        grid.appendChild(div);
      }
    }

    function renderGap(q) {
      const files = (data.untracked_resume_files || []).filter(f => !q || f.toLowerCase().includes(q));
      document.getElementById('gap-heading').textContent = `Untracked Resume Files (${files.length})`;
      document.getElementById('gap-list').innerHTML = files.length
        ? files.map(f => `<div class="gap-item">${esc(f)}</div>`).join('')
        : '<div class="empty">All clear — every resume maps to a tracked application.</div>';
    }

    boot();
  </script>
    """

    return HTMLResponse(html_page("Materials", "materials", "Resume & cover letter inventory", extra_css, body))
