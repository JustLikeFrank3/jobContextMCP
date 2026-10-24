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
