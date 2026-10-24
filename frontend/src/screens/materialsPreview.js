import { renderMarkdownDoc } from './markdownPreview.js'

const PREVIEWABLE = new Set(['pdf', 'txt', 'md', 'png', 'jpg', 'jpeg', 'gif', 'svg'])

export function extOf(file) {
  return (file.ext || '').replace('.', '').toLowerCase()
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  )
}

/* Open a same-origin file in a dedicated preview window with a Print toolbar.
   The file is served from /dashboard/materials/file/... so the iframe is
   same-origin and contentWindow.print() works for PDFs and text alike.
   Markdown gets a rendered document view instead of raw source (fetched,
   rendered with marked, sanitized with DOMPurify — see markdownPreview.js);
   if the fetch fails it degrades to the raw iframe. */
export function buildPreviewDoc({ name, href, body }) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<title>${name}</title>
<link rel="stylesheet" href="${import.meta.env.BASE_URL}materials-preview.css">
<script src="${import.meta.env.BASE_URL}materials-preview.js" defer></script></head><body>
  <div class="bar">
    <span class="name">${name}</span>
    <a class="btn" href="${href}" target="_blank" rel="noreferrer">Open original</a>
    <button class="btn primary" id="print-preview" type="button">Print</button>
  </div>
  ${body}

</body></html>`
}

function writePreviewDoc(win, doc) {
  if (win.closed) return
  win.document.open()
  win.document.write(doc)
  win.document.close()
}

export function openPreview(file) {
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
  const href = escapeHtml(file.href) // backend URL-encoded; also escape HTML attribute delimiters
  const ext = extOf(file)
  const rawIframe = `<iframe id="pv" src="${href}" title="${name}"></iframe>`

  if (ext === 'md') {
    // The window must open synchronously (popup blockers), so show a loading
    // shell, then swap in the rendered document once the fetch lands.
    writePreviewDoc(win, buildPreviewDoc({
      name, href, body: '<div class="msg">Rendering…</div>',
    }))
    fetch(file.href, { credentials: 'same-origin' })
      .then((res) => {
        if (!res.ok) throw new Error(`fetch failed (${res.status})`)
        return res.text()
      })
      .then((text) => {
        const doc = `<main class="doc">${renderMarkdownDoc(text)}</main>`
        writePreviewDoc(win, buildPreviewDoc({ name, href, body: doc }))
      })
      .catch(() => {
        // Raw-source fallback: exactly the pre-rendering behavior.
        writePreviewDoc(win, buildPreviewDoc({ name, href, body: rawIframe }))
      })
    return
  }

  const previewable = PREVIEWABLE.has(ext)
  const body = previewable
    ? rawIframe
    : `<div class="msg">This file type can’t be previewed inline.<br/>
         <a class="btn" href="${href}" download>Download ${name}</a></div>`
  writePreviewDoc(win, buildPreviewDoc({ name, href, body }))
}
