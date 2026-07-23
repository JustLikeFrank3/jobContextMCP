import { useMemo, useRef, useState } from 'react'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, EmptyState, EYEBROW,
} from './_shared.jsx'
import { Panel } from '../design-system'
import useDesktopMode from '../shell/useDesktopMode.js'
import { openFileNative } from '../shell/nativeOpen.js'

/* Materials — the four folders that get opened in practice: assessments,
   interview prep, and the shippable PDFs (resumes + cover letters). The
   TXT intermediates (optimized_resumes / cover_letters sources) stay in
   the workspace and payload but are not surfaced — they're generation
   inputs, not deliverables. Data: GET /dashboard/materials/data.

   No mtime-based "recent" strip or ages: sync rewrites file mtimes on
   transfer, so after any sync everything looks minutes old — showing that
   is worse than showing nothing (2026-07-23 cloud screenshot).

   Clicking a file opens a preview window (hosted) or the OS-default app
   (desktop — the webview can't do popups/downloads). Failures render
   inline on the row; window.alert is unreliable in the Tauri webview. */

const FOLDER_LABEL = {
  job_assessments: 'Job assessments',
  interview_prep: 'Interview prep',
  resume_pdfs: 'Resume PDFs',
  cover_letter_pdfs: 'Cover letter PDFs',
}
const FOLDER_ORDER = [
  'job_assessments', 'interview_prep', 'resume_pdfs', 'cover_letter_pdfs',
]

/* Per-folder accent — the grid reads as equal gray boxes otherwise. */
const FOLDER_ACCENT = {
  job_assessments: '#E39393',
  interview_prep: '#8AB6C4',
  resume_pdfs: 'var(--green-300)',
  cover_letter_pdfs: 'var(--warn)',
}

/* File-type chip colors — pdf warm, text cyan, markdown violet, docs/images green. */
const EXT_COLOR = {
  pdf: 'var(--warn)',
  md: '#C7A9E8',
  markdown: '#C7A9E8',
  txt: 'var(--cyan-300)',
  docx: 'var(--green-300)',
  png: 'var(--green-300)',
  jpg: 'var(--green-300)',
  jpeg: 'var(--green-300)',
}

const PREVIEWABLE = new Set(['pdf', 'txt', 'md', 'png', 'jpg', 'jpeg', 'gif', 'svg'])

function extOf(file) {
  return (file.ext || '').replace('.', '').toLowerCase()
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  )
}

/* Open a same-origin file in a dedicated preview window with a Print toolbar.
   The file is served from /dashboard/materials/file/... so the iframe is
   same-origin and contentWindow.print() works for PDFs and text alike. */
function openPreview(file) {
  const win = window.open('', '_blank', 'width=940,height=1000')
  if (!win) {
    window.alert('Allow pop-ups for this site to preview files in a window.')
    return
  }
  // Sever the opener link before writing content. The preview loads
  // user-controlled files (including SVG, which can execute script), so a
  // live window.opener would expose the SPA to reverse-tabnabbing / same-origin
  // opener attacks. We keep the `win` handle for document.write but null its
  // opener so the child can't reach back via window.opener / window.top.opener.
  win.opener = null
  const name = escapeHtml(file.name)
  const href = file.href // already URL-encoded by the backend
  const previewable = PREVIEWABLE.has(extOf(file))
  const content = previewable
    ? `<iframe id="pv" src="${href}" title="${name}"></iframe>`
    : `<div class="msg">This file type can’t be previewed inline.<br/>
         <a class="btn" href="${href}" download>Download ${name}</a></div>`

  win.document.write(`<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<title>${name}</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #0a1018; color: #e6edf6;
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  .bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
    background: #0e1726; border-bottom: 1px solid #223049; position: sticky; top: 0; }
  .bar .name { font-weight: 600; flex: 1; min-width: 0; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .btn { appearance: none; cursor: pointer; text-decoration: none; display: inline-flex;
    align-items: center; gap: 6px; border-radius: 8px; padding: 7px 13px; font-size: 13px;
    border: 1px solid #2a3a5e; background: #16223a; color: #d6e3f7; }
  .btn.primary { background: #00b5c8; border-color: transparent; color: #04222a; font-weight: 600; }
  .btn:hover { filter: brightness(1.08); }
  iframe { border: 0; width: 100%; height: calc(100vh - 53px); background: #fff; }
  .msg { padding: 48px 24px; text-align: center; color: #9fb0c8; }
  .msg .btn { margin-top: 14px; }
</style></head><body>
  <div class="bar">
    <span class="name">${name}</span>
    <a class="btn" href="${href}" target="_blank" rel="noreferrer">Open original</a>
    <button class="btn primary" onclick="doPrint()">Print</button>
  </div>
  ${content}
  <script>
    function doPrint() {
      var f = document.getElementById('pv');
      try {
        if (f && f.contentWindow) { f.contentWindow.focus(); f.contentWindow.print(); }
        else { window.print(); }
      } catch (e) { window.print(); }
    }
  </script>
</body></html>`)
  win.document.close()
}

/* Shared open lifecycle: idle | busy | error. The native open has no
   visible in-app response, so the row/card itself confirms the click and
   surfaces failures inline. */
function useOpenFile(file) {
  const isDesktop = useDesktopMode()
  const [state, setState] = useState('idle')
  const resetTimer = useRef(null)
  const open = async () => {
    if (!isDesktop) {
      openPreview(file)
      return
    }
    if (state === 'busy') return
    clearTimeout(resetTimer.current)
    setState('busy')
    const ok = await openFileNative(file.href, { notify: false })
    setState(ok ? 'idle' : 'error')
    if (!ok) resetTimer.current = setTimeout(() => setState('idle'), 4000)
  }
  return { open, state, isDesktop }
}

function ExtChip({ ext }) {
  const color = EXT_COLOR[ext] || 'var(--cyan-300)'
  return (
    <span
      style={{
        flexShrink: 0, fontSize: 'var(--fs-2xs)', fontWeight: 'var(--fw-bold)',
        textTransform: 'uppercase', letterSpacing: '0.3px',
        padding: '2px 6px', borderRadius: 4,
        background: `color-mix(in srgb, ${color} 13%, transparent)`,
        color,
      }}
    >
      {ext}
    </span>
  )
}

function OpenState({ state }) {
  if (state === 'busy') {
    return <span style={{ flexShrink: 0, fontSize: 'var(--fs-2xs)', color: 'var(--muted)' }}>Opening…</span>
  }
  if (state === 'error') {
    return (
      <span style={{ flexShrink: 0, fontSize: 'var(--fs-2xs)', color: 'var(--warn)' }}>
        Couldn&rsquo;t open
      </span>
    )
  }
  return null
}

function FileRow({ file }) {
  const ext = extOf(file) || 'file'
  const { open, state, isDesktop } = useOpenFile(file)
  return (
    <button
      type="button"
      onClick={open}
      title={isDesktop ? `Open ${file.name}` : `Preview ${file.name}`}
      style={{
        appearance: 'none', cursor: 'pointer', textAlign: 'left', width: '100%',
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '7px 9px', borderRadius: 'var(--radius-sm)',
        background: 'transparent', border: '1px solid transparent',
        color: 'var(--text-soft)', fontSize: 'var(--fs-sm)',
        opacity: state === 'busy' ? 0.6 : 1,
        transition: 'background .12s ease, border-color .12s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--surface-sunken)'
        e.currentTarget.style.borderColor = 'var(--border-soft)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.borderColor = 'transparent'
      }}
    >
      <ExtChip ext={ext} />
      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {file.name}
      </span>
      <OpenState state={state} />
    </button>
  )
}

function FolderBox({ folderKey, folder, query }) {
  const label = FOLDER_LABEL[folderKey] || folderKey
  const accent = FOLDER_ACCENT[folderKey] || 'var(--cyan-300)'
  const all = folder.files || []
  const files = query
    ? all.filter((f) => f.name.toLowerCase().includes(query))
    : all
  if (query && files.length === 0) return null
  return (
    <Panel pad="0" style={{ display: 'flex', flexDirection: 'column', height: 340, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 14px', flexShrink: 0,
          background: `linear-gradient(150deg, color-mix(in srgb, ${accent} 10%, transparent), transparent 70%)`,
          borderBottom: `1px solid color-mix(in srgb, ${accent} 18%, var(--border-soft))`,
        }}
      >
        <span
          style={{
            color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-sm)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0,
          }}
        >
          {label}
        </span>
        <Badge tone="muted">{query ? `${files.length}/${folder.count}` : folder.count}</Badge>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 8px', display: 'grid', gap: 2, alignContent: 'start' }}>
        {files.length > 0
          ? files.map((f) => <FileRow key={f.name} file={f} />)
          : <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', padding: '8px 6px' }}>Nothing generated here yet.</div>}
      </div>
    </Panel>
  )
}

function UntrackedSection({ files }) {
  const [q, setQ] = useState('')
  const filtered = files.filter((f) => !q || f.toLowerCase().includes(q.toLowerCase()))

  return (
    <div style={{ marginTop: 28 }}>
      <SectionHead title="Untracked resume files" right={`${filtered.length}`} />
      <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--muted)', margin: '-4px 0 10px' }}>
        Resumes with no tracked application — worth linking or archiving.
      </div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter untracked files…'}
        style={{
          width: '100%', maxWidth: 440, marginBottom: 12,
          background: 'var(--surface-sunken)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', padding: '9px 11px',
          color: 'var(--text)', fontSize: 'var(--fs-sm)',
        }}
      />
      {filtered.length > 0 ? (
        <div style={{ display: 'grid', gap: 6 }}>
          {filtered.map((f) => (
            <div
              key={f}
              style={{
                background: 'var(--panel)',
                border: '1px solid color-mix(in srgb, var(--warn) 30%, var(--border))',
                borderRadius: 'var(--radius-md)', padding: '9px 13px',
                fontSize: 'var(--fs-sm)', color: 'var(--warn)',
              }}
            >
              {f}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>
          All clear {'—'} every resume maps to a tracked application.
        </div>
      )}
    </div>
  )
}

export default function Materials() {
  const { data, loading, error } = useApi('/dashboard/materials/data')
  const [query, setQuery] = useState('')
  const folders = useMemo(() => data?.folders || {}, [data])
  // Count only the folders this page shows — the TXT intermediates still
  // exist in the payload but aren't part of this page's story.
  const totalFiles = FOLDER_ORDER.reduce((n, k) => n + (folders[k]?.count || 0), 0)
  const untracked = data?.untracked_resume_files || []
  const q = query.trim().toLowerCase()

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && totalFiles === 0}
      emptyLabel="No materials generated yet."
      emptyHint="Resumes and cover letters you generate will appear here."
    >
      <StatGrid>
        <Stat label="Job assessments" value={folders.job_assessments?.count ?? 0} tone="accent" />
        <Stat label="Interview prep" value={folders.interview_prep?.count ?? 0} />
        <Stat label="Resume PDFs" value={data?.resume_pdfs ?? 0} tone="green" />
        <Stat label="Cover letter PDFs" value={data?.cover_letter_pdfs ?? 0} />
        <Stat
          label="Untracked"
          value={data?.gap ?? 0}
          tone={data?.gap ? 'warn' : 'muted'}
          sub={data?.gap ? 'resumes with no application' : 'all tracked'}
        />
      </StatGrid>

      <div
        style={{
          display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
          gap: 14, flexWrap: 'wrap', margin: '4px 2px 12px',
        }}
      >
        <div style={EYEBROW}>Folders {'—'} click a file to open &amp; print</div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Filter ${totalFiles} files…`}
          style={{
            flex: '0 1 300px',
            background: 'var(--surface-sunken)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', padding: '8px 11px',
            color: 'var(--text)', fontSize: 'var(--fs-sm)',
          }}
        />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
        {FOLDER_ORDER.filter((k) => folders[k]).map((key) => (
          <FolderBox key={key} folderKey={key} folder={folders[key]} query={q} />
        ))}
      </div>
      {q && FOLDER_ORDER.every((k) => {
        const fs = folders[k]?.files || []
        return fs.every((f) => !f.name.toLowerCase().includes(q))
      }) && (
        <EmptyState label={`No files match “${query.trim()}”.`} />
      )}

      {untracked.length > 0 && <UntrackedSection files={untracked} />}

      {totalFiles === 0 && <EmptyState label="No files in any folder yet." />}
    </Screen>
  )
}
