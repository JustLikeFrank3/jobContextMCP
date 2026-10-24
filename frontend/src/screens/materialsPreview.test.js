// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { buildPreviewDoc, extOf, openPreview } from './materialsPreview.js'

const file = { name: 'Assessment.md', href: '/dashboard/materials/file/job_assessments/Assessment.md', ext: 'md' }
const parse = (html) => new DOMParser().parseFromString(html, 'text/html')

function popup() {
  const win = { closed: false, opener: window, document: { open: vi.fn(), write: vi.fn(), close: vi.fn() } }
  vi.spyOn(window, 'open').mockReturnValue(win)
  return win
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('CSP-compatible preview document', () => {
  it('loads script and styles from same-origin configured-base assets, with no inline handlers', () => {
    const doc = parse(buildPreviewDoc({ name: 'Assessment', href: '/file', body: '<main class="doc">Hello</main>' }))
    expect(doc.querySelector('link[rel="stylesheet"]').getAttribute('href')).toBe(`${import.meta.env.BASE_URL}materials-preview.css`)
    expect(doc.querySelector('script').getAttribute('src')).toBe(`${import.meta.env.BASE_URL}materials-preview.js`)
    expect(doc.querySelector('script').defer).toBe(true)
    expect(doc.querySelector('script').textContent).toBe('')
    expect(doc.querySelector('style, [style], [onclick]')).toBeNull()
    expect(doc.querySelector('#print-preview').textContent).toBe('Print')
  })

  it('preserves raw-file preview and severs the opener before writing', () => {
    const win = popup()
    openPreview({ ...file, ext: '.PDF', name: 'Resume.pdf' })
    expect(extOf({ ext: '.PDF' })).toBe('pdf')
    expect(win.opener).toBeNull()
    const doc = parse(win.document.write.mock.calls[0][0])
    expect(doc.querySelector('iframe').getAttribute('src')).toBe(file.href)
    expect(doc.querySelector('iframe').title).toBe('Resume.pdf')
    expect(win.document.close).toHaveBeenCalledOnce()
  })

  it('renders sanitized markdown after the synchronous loading shell', async () => {
    const win = popup()
    const fetch = vi.fn().mockResolvedValue({ ok: true, text: async () => '# Verdict\n\n<script>bad()</script>' })
    vi.stubGlobal('fetch', fetch)
    openPreview(file)
    expect(win.document.write.mock.calls[0][0]).toContain('Rendering…')
    expect(fetch).toHaveBeenCalledWith(file.href, { credentials: 'same-origin' })
    await vi.waitFor(() => expect(win.document.write).toHaveBeenCalledTimes(2))
    const doc = parse(win.document.write.mock.calls[1][0])
    expect(doc.querySelector('main.doc h1').textContent).toBe('Verdict')
    expect(doc.querySelector('main.doc script')).toBeNull()
    expect(doc.querySelector('style, [onclick]')).toBeNull()
  })

  it.each(['network', 'http'])('keeps raw iframe fallback on %s errors', async (kind) => {
    const win = popup()
    vi.stubGlobal('fetch', kind === 'network'
      ? vi.fn().mockRejectedValue(new Error('offline'))
      : vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    openPreview(file)
    await vi.waitFor(() => expect(win.document.write).toHaveBeenCalledTimes(2))
    expect(parse(win.document.write.mock.calls[1][0]).querySelector('iframe').getAttribute('src')).toBe(file.href)
  })

  it('does not rewrite a popup closed while markdown fetch is pending', async () => {
    const win = popup()
    let finish
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise((resolve) => { finish = resolve })))
    openPreview(file)
    win.closed = true
    finish({ ok: true, text: async () => '# Finished' })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(win.document.write).toHaveBeenCalledOnce()
  })

  it('shows the download fallback for unsupported files', () => {
    const win = popup()
    openPreview({ ...file, ext: 'docx' })
    const doc = parse(win.document.write.mock.calls[0][0])
    expect(doc.querySelector('iframe')).toBeNull()
    expect(doc.querySelector('a[download]').getAttribute('href')).toBe(file.href)
  })

  it('reports popup blocking without starting a fetch', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => {})
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    openPreview(file)
    expect(alert).toHaveBeenCalledOnce()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('escapes names and URL attribute delimiters in the popup', () => {
    const win = popup()
    openPreview({ name: '<img src=x onerror=bad()>', href: '/file?name=" onload="bad()', ext: 'txt' })
    const doc = parse(win.document.write.mock.calls[0][0])
    expect(doc.querySelector('img, [onload], [onerror]')).toBeNull()
    expect(doc.querySelector('.name').textContent).toBe('<img src=x onerror=bad()>')
    expect(doc.querySelector('iframe').getAttribute('src')).toBe('/file?name=" onload="bad()')
  })
})

describe('external Print listener', () => {
  const script = readFileSync('public/materials-preview.js', 'utf8')

  it.each(['markdown', 'iframe', 'frame-error'])('prints %s and falls back safely', (kind) => {
    const button = { addEventListener: vi.fn() }
    const frame = kind === 'markdown' ? null : { contentWindow: {
      focus: vi.fn(), print: kind === 'frame-error' ? vi.fn(() => { throw new Error('unavailable') }) : vi.fn(),
    } }
    const win = { print: vi.fn() }
    const doc = { getElementById: (id) => id === 'print-preview' ? button : frame }
    runInNewContext(script, { document: doc, window: win })
    expect(button.addEventListener).toHaveBeenCalledOnce()
    const [event, listener] = button.addEventListener.mock.calls[0]
    expect(event).toBe('click')
    listener()
    if (frame) {
      expect(frame.contentWindow.focus).toHaveBeenCalledOnce()
      expect(frame.contentWindow.print).toHaveBeenCalledOnce()
    }
    expect(win.print).toHaveBeenCalledTimes(kind === 'iframe' ? 0 : 1)
  })
})
