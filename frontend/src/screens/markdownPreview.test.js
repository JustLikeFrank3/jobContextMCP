// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { renderMarkdownDoc, MARKDOWN_DOC_CSS } from './markdownPreview.js'

describe('renderMarkdownDoc', () => {
  it('renders headings, lists, and emphasis as HTML', () => {
    const html = renderMarkdownDoc('# Verdict\n\n**Strong** match\n\n- one\n- two')
    expect(html).toContain('<h1>Verdict</h1>')
    expect(html).toContain('<strong>Strong</strong>')
    expect(html).toMatch(/<li>one<\/li>/)
  })

  it('renders GFM tables', () => {
    const html = renderMarkdownDoc('| a | b |\n|---|---|\n| 1 | 2 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<td>1</td>')
  })

  // The content is agent-written — sanitization is the security boundary
  // between stored markdown and a same-origin document.
  it('strips script tags', () => {
    const html = renderMarkdownDoc('hello\n\n<script>window.pwned = 1</script>')
    expect(html).not.toContain('<script')
    expect(html).toContain('hello')
  })

  it('strips inline event handlers', () => {
    const html = renderMarkdownDoc('<img src="x" onerror="window.pwned=1">')
    expect(html).not.toContain('onerror')
  })

  it('strips javascript: links', () => {
    const html = renderMarkdownDoc('[click](javascript:alert(1))')
    expect(html).not.toContain('javascript:')
    expect(html).toContain('click')
  })

  it('empty and null input degrade to empty output', () => {
    expect(renderMarkdownDoc('')).toBe('')
    expect(renderMarkdownDoc(null)).toBe('')
  })
})

describe('MARKDOWN_DOC_CSS', () => {
  it('pairs screen colors and flips to ink-on-paper for print', () => {
    expect(MARKDOWN_DOC_CSS).toContain('.doc')
    expect(MARKDOWN_DOC_CSS).toContain('@media print')
    expect(MARKDOWN_DOC_CSS).toMatch(/print[^}]*background: #fff/s)
  })
})
