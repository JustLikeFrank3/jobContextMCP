/* Markdown rendering for the Materials preview window.
 *
 * Assessments and prep docs are agent-written Markdown; the preview should
 * read as a document, not as raw source. Rendering happens client-side
 * (marked) and the output is ALWAYS passed through DOMPurify before it
 * touches a same-origin document: the content comes from LLM/agent output,
 * which makes unsanitized markdown→HTML a stored-XSS vector, not a
 * hypothetical.
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

export function renderMarkdownDoc(mdText) {
  const raw = marked.parse(String(mdText ?? ''), { gfm: true, async: false })
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
}

/* Document styling for the rendered markdown, matching the preview window's
 * dark chrome on screen and flipping to ink-on-paper for print. */
export const MARKDOWN_DOC_CSS = `
  .doc { max-width: 760px; margin: 0 auto; padding: 28px 32px 64px;
    color: #e6edf6; line-height: 1.6; font-size: 15px; }
  .doc h1, .doc h2, .doc h3, .doc h4 { color: #f2f7ff; line-height: 1.25;
    margin: 1.6em 0 0.6em; }
  .doc h1 { font-size: 26px; border-bottom: 1px solid #223049; padding-bottom: 8px; }
  .doc h2 { font-size: 20px; border-bottom: 1px solid #1a2740; padding-bottom: 6px; }
  .doc h3 { font-size: 16px; }
  .doc h1:first-child { margin-top: 0.2em; }
  .doc p { margin: 0.7em 0; }
  .doc ul, .doc ol { padding-left: 1.5em; margin: 0.7em 0; }
  .doc li { margin: 0.3em 0; }
  .doc a { color: #00b5c8; }
  .doc strong { color: #f2f7ff; }
  .doc blockquote { margin: 0.9em 0; padding: 2px 14px; border-left: 3px solid #00b5c8;
    color: #b9c7dc; background: #0e1726; border-radius: 0 6px 6px 0; }
  .doc code { background: #0e1726; border: 1px solid #223049; border-radius: 5px;
    padding: 1px 6px; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .doc pre { background: #0e1726; border: 1px solid #223049; border-radius: 8px;
    padding: 12px 14px; overflow-x: auto; }
  .doc pre code { background: none; border: 0; padding: 0; }
  .doc table { border-collapse: collapse; margin: 0.9em 0; width: 100%; }
  .doc th, .doc td { border: 1px solid #223049; padding: 6px 10px; text-align: left; }
  .doc th { background: #0e1726; color: #f2f7ff; }
  .doc hr { border: 0; border-top: 1px solid #223049; margin: 1.6em 0; }
  @media print {
    html, body { background: #fff !important; color: #111 !important; }
    .bar { display: none !important; }
    .doc { color: #111; max-width: none; padding: 0; }
    .doc h1, .doc h2, .doc h3, .doc h4, .doc strong { color: #000; }
    .doc h1, .doc h2 { border-color: #ccc; }
    .doc a { color: #0a4ea3; }
    .doc blockquote { background: #f4f6f8; color: #333; border-left-color: #888; }
    .doc code, .doc pre { background: #f4f6f8; border-color: #ccc; }
    .doc th { background: #f4f6f8; color: #000; }
    .doc th, .doc td { border-color: #ccc; }
  }
`
