import { useState } from 'react'
import { Button } from '../../design-system'
import { apiPost } from '../../auth/api.js'
import { Modal, ResultLine, EmptyEditorState, modalField, modalLabel, actionError } from './shared.jsx'

export default function EditResumeModal({ job, resumeOptions, onClose, onDone }) {
  const options = resumeOptions || []
  const [resumeName, setResumeName] = useState(job.suggested_edit_resume || options[0] || '')
  const [instructions, setInstructions] = useState('')
  const [exportPdf, setExportPdf] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState(null)

  async function submit() {
    if (!resumeName) { setErr('Pick a resume to edit.'); return }
    if (instructions.trim().length < 3) { setErr('Describe the edit in a few words.'); return }
    setSubmitting(true); setErr('')
    try {
      const res = await apiPost('/dashboard/pipeline/edit-resume', {
        job_id: job.id, resume_name: resumeName, instructions: instructions.trim(), export_pdf: exportPdf,
      })
      setResult(res)
    } catch (e) { setErr(actionError(e)) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={`Edit Resume — ${job.company}`} onClose={onClose}>
      {options.length === 0 ? (
        <EmptyEditorState what="optimized resumes" />
      ) : result ? (
        <div>
          <div style={{ padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'var(--tint-primary)', border: '1px solid var(--line-strong)', marginBottom: 12 }}>
            <div style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-xs)', fontWeight: 'var(--fw-semibold)', marginBottom: 6 }}>Resume edited</div>
            {result.edited_resume && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-sm)', color: 'var(--text-strong)', wordBreak: 'break-all' }}>{result.edited_resume}</div>
            )}
          </div>
          {result.save_result && <ResultLine>{result.save_result}</ResultLine>}
          {result.pdf_result && <ResultLine>{result.pdf_result}</ResultLine>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
            <Button size="sm" onClick={onDone}>Done</Button>
          </div>
        </div>
      ) : (
        <>
          <label style={{ display: 'block', marginBottom: 12 }}>
            <span style={modalLabel}>Resume to edit</span>
            <select style={modalField} value={resumeName} onChange={(e) => setResumeName(e.target.value)}>
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
              placeholder="e.g. Lead with the Azure migration. Tighten each GM bullet to one line. Add a metrics-forward summary up top."
            />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 'var(--fs-sm)', color: 'var(--text-soft)' }}>
            <input type="checkbox" checked={exportPdf} onChange={(e) => setExportPdf(e.target.checked)} />
            Also export a PDF using this job&rsquo;s selected template
          </label>
          {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
            <Button size="sm" onClick={submit} disabled={submitting}>{submitting ? 'Editing…' : 'Edit with AI'}</Button>
          </div>
        </>
      )}
    </Modal>
  )
}
