import { useState } from 'react'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, EmptyState, EYEBROW,
} from './_shared.jsx'
import { Panel } from '../design-system'
import useDesktopMode from '../shell/useDesktopMode.js'
import { openFileNative } from '../shell/nativeOpen.js'

/* Materials — generated resumes, cover letters, PDFs, and prep docs.
   Data: GET /dashboard/materials/data (_materials_payload).

   Folder boxes are uniform-height with an internal scroll so the grid stays
   even no matter how many files a folder holds. Clicking a file opens a
   preview window with a Print button (works for PDF / text / images). */

const FOLDER_LABEL = {
  optimized_resumes: 'Optimized resumes',
  cover_letters: 'Cover letters',
  resume_pdfs: 'Resume PDFs',
  cover_letter_pdfs: 'Cover letter PDFs',
  job_assessments: 'Job assessments',
  interview_prep: 'Interview prep',
}
const FOLDER_ORDER = [
  'optimized_resumes', 'cover_letters', 'resume_pdfs',
  'cover_letter_pdfs', 'job_assessments', 'interview_prep',
]

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
    : `<div class="msg">This file type can\u2019t be previewed inline.<br/>
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

function FileButton({ file }) {
  const ext = extOf(file) || 'file'
  // Desktop: the webview can't open popup previews or downloads — the
  // backend opens the file in its OS-default app instead (view/print/save).
  const isDesktop = useDesktopMode()
  return (
    <button
      type="button"
      onClick={() => (isDesktop ? openFileNative(file.href) : openPreview(file))}
      title={`Preview ${file.name}`}
      style={{
        appearance: 'none', cursor: 'pointer', textAlign: 'left', width: '100%',
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '7px 9px', borderRadius: 'var(--radius-sm)',
        background: 'transparent', border: '1px solid transparent',
        color: 'var(--text-soft)', fontSize: 'var(--fs-sm)',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-sunken)' }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
    >
      <span
        style={{
          flexShrink: 0, fontSize: 'var(--fs-2xs)', fontWeight: 'var(--fw-bold)',
          textTransform: 'uppercase', letterSpacing: '0.3px',
          padding: '2px 6px', borderRadius: 4,
          background: 'var(--surface-chip)', color: 'var(--cyan-300)',
        }}
      >
        {ext}
      </span>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {file.name}
      </span>
    </button>
  )
}

function FolderBox({ label, folder }) {
  const files = folder.files || []
  return (
    <Panel pad="0" style={{ display: 'flex', flexDirection: 'column', height: 300, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 14px', borderBottom: '1px solid var(--border-soft)', flexShrink: 0,
        }}
      >
        <span style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-sm)' }}>
          {label}
        </span>
        <Badge tone="muted">{folder.count}</Badge>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 8px', display: 'grid', gap: 2, alignContent: 'start' }}>
        {files.length > 0
          ? files.map((f) => <FileButton key={f.name} file={f} />)
          : <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', padding: '8px 6px' }}>Empty.</div>}
      </div>
    </Panel>
  )
}

function UntrackedSection({ files }) {
  const [q, setQ] = useState('')
  const filtered = files.filter((f) => !q || f.toLowerCase().includes(q.toLowerCase()))

  return (
    <div style={{ marginTop: 24 }}>
      <SectionHead title="Untracked resume files" right={`${filtered.length}`} />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter untracked files\u2026'}
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
          All clear {'\u2014'} every resume maps to a tracked application.
        </div>
      )}
    </div>
  )
}

export default function Materials() {
  const { data, loading, error } = useApi('/dashboard/materials/data')
  const folders = data?.folders || {}
  const totalFiles = Object.values(folders).reduce((n, f) => n + (f.count || 0), 0)
  const untracked = data?.untracked_resume_files || []

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && totalFiles === 0}
      emptyLabel="No materials generated yet."
      emptyHint="Resumes and cover letters you generate will appear here."
    >
      <StatGrid>
        <Stat label="Resumes" value={data?.optimized_resumes ?? 0} tone="accent" />
        <Stat label="Cover letters" value={data?.cover_letters ?? 0} />
        <Stat label="PDFs" value={(data?.resume_pdfs ?? 0) + (data?.cover_letter_pdfs ?? 0)} tone="green" />
        <Stat label="Tracked apps" value={data?.tracked_applications ?? 0} tone="muted" />
        <Stat
          label="Untracked"
          value={data?.gap ?? 0}
          tone={data?.gap ? 'warn' : 'muted'}
          sub={data?.gap ? 'resumes with no application' : 'all tracked'}
        />
      </StatGrid>

      <div style={{ ...EYEBROW, margin: '4px 2px 12px' }}>Folders {'\u2014'} click a file to preview &amp; print</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
        {FOLDER_ORDER.filter((k) => folders[k]).map((key) => (
          <FolderBox key={key} label={FOLDER_LABEL[key] || key} folder={folders[key]} />
        ))}
      </div>

      {untracked.length > 0 && <UntrackedSection files={untracked} />}

      {totalFiles === 0 && <EmptyState label="No files in any folder yet." />}
    </Screen>
  )
}
