import { useState } from 'react'
import { Button } from '../../design-system'
import { apiPost } from '../../auth/api.js'
import useDesktopMode from '../../shell/useDesktopMode.js'
import { nativeAnchorHandler } from '../../shell/nativeOpen.js'
import { EYEBROW } from '../_shared.jsx'
import { Modal, ResultLine, EmptyEditorState, ProvenanceNote, modalField, modalLabel, actionError } from './shared.jsx'

/* Edit Cover Letter (draft → review → accept/discard) */
export default function EditCoverLetterModal({ job, coverLetterOptions, isOwner, onClose, onDone }) {
  const isDesktop = useDesktopMode()
  const options = coverLetterOptions || []
  const [clName, setClName] = useState(job.suggested_edit_cover_letter || options[0] || '')
  const [instructions, setInstructions] = useState('')
  const [pipeline, setPipeline] = useState(isOwner ? 'latex' : 'html')
  const [exportPdf, setExportPdf] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')
  const [phase, setPhase] = useState('edit') // edit | review | done
  const [draft, setDraft] = useState(null)
  const [accepted, setAccepted] = useState(null)

  async function runEdit() {
    if (!clName) { setErr('Pick a cover letter to edit.'); return }
    if (instructions.trim().length < 3) { setErr('Describe the edit in a few words.'); return }
    setSubmitting(true); setErr('')
    try {
      const res = await apiPost('/dashboard/pipeline/edit-cover-letter', {
        job_id: job.id,
        cover_letter_name: clName,
        draft_name: draft?.draft_name || '',
        instructions: instructions.trim(),
        export_pdf: exportPdf,
        export_pipeline: pipeline,
      })
      setDraft(res)
      setPhase('review')
    } catch (e) { setErr(actionError(e)) } finally { setSubmitting(false) }
  }

  async function accept() {
    setSubmitting(true); setErr('')
    try {
      const res = await apiPost('/dashboard/pipeline/accept-cover-letter-edit', {
        cover_letter_name: clName, draft_name: draft.draft_name,
      })
      setAccepted(res); setPhase('done')
    } catch (e) { setErr(actionError(e)) } finally { setSubmitting(false) }
  }

  async function discard() {
    setSubmitting(true); setErr('')
    try {
      await apiPost('/dashboard/pipeline/cancel-cover-letter-edit', { cover_letter_name: clName })
    } catch { /* draft cleanup is best-effort */ } finally {
      setSubmitting(false); setDraft(null); setInstructions(''); setPhase('edit')
    }
  }

  let bodyContent
  if (options.length === 0) {
    bodyContent = <EmptyEditorState what="cover letters" />
  } else if (phase === 'done') {
    bodyContent = (
      <div>
        <div style={{ padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'var(--tint-success, var(--tint-primary))', border: '1px solid var(--line-strong)', marginBottom: 12 }}>
          <div style={{ color: 'var(--green-300)', fontSize: 'var(--fs-xs)', fontWeight: 'var(--fw-semibold)', marginBottom: 6 }}>Cover letter updated</div>
          <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)' }}>
            The draft was applied to {clName}. A .bak backup of the previous version was saved.
          </div>
        </div>
        {accepted?.href && (
          <a href={accepted.href} target="_blank" rel="noreferrer" onClick={nativeAnchorHandler(isDesktop, accepted.href, 'file')} style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>Open the updated file {'↗'}</a>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
          <Button size="sm" onClick={onDone}>Done</Button>
        </div>
      </div>
    )
  } else if (phase === 'review' && draft) {
    bodyContent = (
      <div>
        <div style={{ ...EYEBROW, marginBottom: 6 }}>Proposed draft</div>
        <pre style={{
          whiteSpace: 'pre-wrap', margin: '0 0 12px', padding: '12px 14px', maxHeight: 280, overflow: 'auto',
          background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-sm)',
          color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', lineHeight: 1.5,
        }}>{draft.draft_content}</pre>
        <ProvenanceNote line={draft.provenance} />
        {draft.save_result && <ResultLine>{draft.save_result}</ResultLine>}
        {draft.pdf_result && <ResultLine>{draft.pdf_result}</ResultLine>}
        {draft.pdf_href && (
          <a href={draft.pdf_href} target="_blank" rel="noreferrer" onClick={nativeAnchorHandler(isDesktop, draft.pdf_href, 'file')} style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>Open PDF preview {'↗'}</a>
        )}
        {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', margin: '12px 0', whiteSpace: 'pre-wrap' }}>{err}</div>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14, flexWrap: 'wrap' }}>
          <Button variant="ghost" size="sm" onClick={discard} disabled={submitting}>Discard draft</Button>
          <Button variant="ghost" size="sm" onClick={() => { setPhase('edit'); setInstructions('') }} disabled={submitting}>Revise again</Button>
          <Button size="sm" onClick={accept} disabled={submitting}>{submitting ? 'Applying…' : 'Accept & apply'}</Button>
        </div>
      </div>
    )
  } else {
    bodyContent = (
      <>
        {draft && (
          <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', marginBottom: 10 }}>
            Revising the current draft. Your new instructions build on the last AI pass.
          </div>
        )}
        <label style={{ display: 'block', marginBottom: 12 }}>
          <span style={modalLabel}>Cover letter to edit</span>
          <select style={modalField} value={clName} onChange={(e) => { setClName(e.target.value); setDraft(null) }}>
            {options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label style={{ display: 'block', marginBottom: 12 }}>
          <span style={modalLabel}>Edit instructions</span>
          <textarea
            style={{ ...modalField, resize: 'vertical', lineHeight: 1.45 }}
            rows={6}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="e.g. Open with a hook about their platform team. Cut the third paragraph. Make the tone warmer and more direct."
          />
        </label>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            <span style={modalLabel} >Export</span>
            <select style={{ ...modalField, width: 'auto' }} value={pipeline} onChange={(e) => setPipeline(e.target.value)}>
              <option value="html">HTML / PDF</option>
              {isOwner && <option value="latex">LaTeX</option>}
            </select>
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 'var(--fs-sm)', color: 'var(--text-soft)' }}>
            <input type="checkbox" checked={exportPdf} onChange={(e) => setExportPdf(e.target.checked)} />
            Export a PDF of the draft
          </label>
        </div>
        {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={runEdit} disabled={submitting}>{submitting ? 'Drafting…' : 'Draft edit with AI'}</Button>
        </div>
      </>
    )
  }

  return (
    <Modal title={`Edit Cover Letter — ${job.company}`} onClose={onClose} maxWidth={680}>
      {bodyContent}
    </Modal>
  )
}
