"""Daily Digest dashboard — GET /dashboard/digest and POST /dashboard/digest/generate."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from tools.digest import get_daily_digest
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/digest/generate")
async def digest_generate() -> JSONResponse:
    """Run the existing digest logic and return the result as plain text."""
    result = get_daily_digest()
    return JSONResponse({"digest": result})


@router.get("/digest")
async def digest_page() -> HTMLResponse:
    extra_css = """
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

    .digest-wrap { display: flex; flex-direction: column; gap: 0; }

    .digest-toolbar {
      display: flex; align-items: center; gap: 14px; margin-bottom: 24px;
      flex-wrap: wrap;
    }
    .btn-generate {
      background: var(--accent); color: #0b1220;
      border: none; border-radius: 10px;
      padding: 10px 22px; font-size: 0.95rem; font-weight: 700;
      cursor: pointer; transition: opacity .15s;
      display: flex; align-items: center; gap: 8px; flex-shrink: 0;
    }
    .btn-generate:hover  { opacity: 0.85; }
    .btn-generate:disabled { opacity: 0.45; cursor: not-allowed; }
    .spinner {
      width: 15px; height: 15px; border: 2px solid #0b122080;
      border-top-color: #0b1220; border-radius: 50%;
      animation: spin .6s linear infinite; display: none;
    }
    .btn-generate.loading .spinner  { display: block; }
    .btn-generate.loading .btn-label { display: none; }
    .ts { font-size: 0.78rem; color: var(--muted); }

    .digest-header {
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 12px; padding: 14px 18px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.82rem; color: var(--muted); margin-bottom: 12px;
      white-space: pre;
    }

    .sections { display: flex; flex-direction: column; gap: 8px; }

    details.ds {
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 12px; overflow: hidden;
      animation: fadeIn .2s ease both;
    }
    details.ds[open] { border-color: color-mix(in srgb, var(--accent) 40%, var(--line)); }

    details.ds summary {
      display: flex; align-items: center; justify-content: space-between;
      padding: 13px 18px; cursor: pointer; list-style: none;
      user-select: none; gap: 12px;
    }
    details.ds summary::-webkit-details-marker { display: none; }
    details.ds summary:hover { background: color-mix(in srgb, var(--accent) 5%, var(--panel)); }

    .ds-title {
      font-size: 0.82rem; font-weight: 700; letter-spacing: 0.5px;
      text-transform: uppercase; color: var(--accent);
    }
    .ds-badge {
      font-size: 0.72rem; background: var(--chip);
      border: 1px solid var(--line); border-radius: 20px;
      padding: 2px 8px; color: var(--muted);
      white-space: nowrap; flex-shrink: 0;
    }
    details.ds[open] .ds-badge { display: none; }
    .ds-chevron {
      color: var(--muted); font-size: 0.75rem; flex-shrink: 0;
      transition: transform .2s;
    }
    details.ds[open] .ds-chevron { transform: rotate(180deg); }

    .ds-body {
      padding: 0 18px 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.84rem; line-height: 1.7; color: var(--text);
    }
    .ds-body .line { white-space: pre-wrap; word-break: break-word; }
    .ds-body .line.overdue { color: var(--danger); }
    .ds-body .line.action  { color: var(--warn); }
    .ds-body .line.waiting { color: var(--muted); }
    .ds-body .line.progress { color: var(--ok); }
    .ds-body .line.focus   { color: var(--text); font-weight: 600; }
    .ds-body .line.nudge   { color: var(--warn); }

    .empty-state {
      text-align: center; color: var(--muted); padding: 48px 20px;
      font-size: 0.9rem;
    }
    .empty-state .hint { margin-top: 6px; font-size: 0.8rem; }
    """

    body = """
    <div class="digest-wrap">
      <div class="digest-toolbar">
        <button class="btn-generate" id="generateBtn" onclick="generateDigest()">
          <span class="spinner"></span>
          <span class="btn-label">Generate Today's Digest</span>
        </button>
        <span class="ts" id="ts"></span>
      </div>

      <div id="digestHeader" class="digest-header" style="display:none"></div>
      <div id="sections"     class="sections"></div>
      <div id="emptyState"   class="empty-state">
        <div>No digest generated yet.</div>
        <div class="hint">Press the button above to run your morning briefing.</div>
      </div>
    </div>

    <script>
    // ── section definitions (order matters) ─────────────────────────────────
    const SECTIONS = [
      { key: 'PIPELINE',          label: 'Pipeline',          defaultOpen: true  },
      { key: 'ACTION',            label: 'Action Required',   defaultOpen: true  },
      { key: 'WAITING ON OTHERS', label: 'Waiting on Others', defaultOpen: false },
      { key: 'NEEDS REVIEW',      label: 'Needs Review',      defaultOpen: false },
      { key: 'RECENT PROGRESS',   label: 'Recent Progress',   defaultOpen: false },
      { key: 'TOTALS',            label: 'Totals',            defaultOpen: false },
      { key: "TODAY'S FOCUS",     label: "Today's Focus",     defaultOpen: true  },
      { key: 'WELLBEING',         label: 'Wellbeing',         defaultOpen: true  },
    ];

    // Classify a line for colour treatment
    function lineClass(text, sectionKey) {
      const t = text.trim();
      if (!t) return '';
      if (sectionKey === 'ACTION' && t.startsWith('[')) return 'overdue';
      if (sectionKey === 'ACTION') return 'action';
      if (sectionKey === 'WAITING ON OTHERS') return 'waiting';
      if (sectionKey === 'RECENT PROGRESS') return 'progress';
      if (sectionKey === "TODAY'S FOCUS" && /^\\d+\\./.test(t)) return 'focus';
      if (sectionKey === 'WELLBEING') return 'nudge';
      return '';
    }

    function parseDigest(text) {
      const allLines = text.split('\\n');

      // Extract box header (first 3 lines + blank)
      let headerLines = [], bodyLines = [];
      let inHeader = true;
      for (const ln of allLines) {
        if (inHeader && (ln.startsWith('╔') || ln.startsWith('║') || ln.startsWith('╚') || ln === '')) {
          headerLines.push(ln);
          if (ln === '' && headerLines.some(l => l.startsWith('║'))) inHeader = false;
        } else {
          bodyLines.push(ln);
        }
      }

      // Split body into sections by heading lines (ALL-CAPS words after leading spaces)
      const sectionHeadingRe = /^\\s{1,4}([A-Z][A-Z '\\-]+?)(?:\\s+—\\s+[^:]+)?:?\\s*$/;
      const result = [];
      let current = null;

      for (const ln of bodyLines) {
        const m = ln.match(sectionHeadingRe);
        const matchedDef = m ? SECTIONS.find(s => ln.toUpperCase().includes(s.key)) : null;

        if (matchedDef) {
          if (current) result.push(current);
          current = { def: matchedDef, heading: ln.trim(), lines: [] };
        } else if (current) {
          current.lines.push(ln);
        } else {
          // orphan lines before first section — attach to a synthetic header section
          if (!result.length && ln.trim()) {
            if (!current) current = { def: { key: '_pre', label: '', defaultOpen: true }, heading: '', lines: [] };
            current.lines.push(ln);
          }
        }
      }
      if (current) result.push(current);

      return { header: headerLines.join('\\n'), sections: result };
    }

    function buildSections(parsed) {
      const container = document.getElementById('sections');
      container.innerHTML = '';

      for (const sec of parsed.sections) {
        // Count meaningful lines for badge
        const contentLines = sec.lines.filter(l => l.trim());
        const badge = contentLines.length > 0 ? contentLines.length + ' item' + (contentLines.length > 1 ? 's' : '') : '';

        const det = document.createElement('details');
        det.className = 'ds';
        if (sec.def.defaultOpen) det.open = true;

        // Summary row
        const summ = document.createElement('summary');
        summ.innerHTML =
          '<span class="ds-title">' + escHtml(sec.def.label || sec.heading) + '</span>' +
          (badge ? '<span class="ds-badge">' + badge + '</span>' : '') +
          '<span class="ds-chevron">&#9660;</span>';
        det.appendChild(summ);

        // Body
        const body = document.createElement('div');
        body.className = 'ds-body';
        // Trim leading/trailing blank lines from section content
        const trimmed = sec.lines.slice(
          sec.lines.findIndex(l => l.trim() !== ''),
        );
        while (trimmed.length && !trimmed[trimmed.length - 1].trim()) trimmed.pop();

        for (const ln of trimmed) {
          const div = document.createElement('div');
          div.className = 'line ' + lineClass(ln, sec.def.key);
          div.textContent = ln;
          body.appendChild(div);
        }
        det.appendChild(body);
        container.appendChild(det);
      }
    }

    function escHtml(s) {
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    async function generateDigest() {
      const btn   = document.getElementById('generateBtn');
      const ts    = document.getElementById('ts');
      const hdr   = document.getElementById('digestHeader');
      const empty = document.getElementById('emptyState');

      btn.disabled = true;
      btn.classList.add('loading');

      try {
        const res = await fetch('/dashboard/digest/generate', {
          method: 'POST',
          credentials: 'same-origin',
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        const parsed = parseDigest(data.digest);

        hdr.textContent = parsed.header;
        hdr.style.display = 'block';

        buildSections(parsed);

        empty.style.display = 'none';
        ts.textContent = 'Generated at ' + new Date().toLocaleTimeString();
      } catch (err) {
        document.getElementById('sections').innerHTML =
          '<div style="color:var(--danger);padding:16px">Error: ' + escHtml(err.message) + '</div>';
        empty.style.display = 'none';
      } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
      }
    }
    </script>
    """

    return HTMLResponse(  # NOSONAR
        html_page(
            title="Daily Digest",
            active_tab="digest",
            subtitle="On-demand morning briefing",
            extra_css=extra_css,
            body=body,
        )
    )

