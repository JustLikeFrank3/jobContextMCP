import { useState, useEffect, useCallback } from 'react'
import { Panel, Button } from '../design-system'
import { apiFetch, apiPost, ApiError } from '../auth/api.js'
import {
  Screen, StatGrid, Stat, Badge, statusTone, EmptyState, EYEBROW, fmtDate,
} from './_shared.jsx'

/* Pipeline — the share-sheet intake queue: assess, generate, decide, apply.
   Data: GET /dashboard/pipeline/data (_pipeline_payload).

   Restores the interactive card actions from the legacy /dashboard/pipeline
   page: run/re-run assessment, generate resume, generate cover letter
   (HTML + LaTeX for owner), queue apply, mark applied, unqueue, remove —
   plus a search filter and the Add Job intake modal. The AI editor flows now
   live here too, in React: Edit Resume, Edit Cover Letter (draft → review →
   accept/discard), and the visual Template chooser with a live preview. */

const CLOSED = new Set(['added', 'applied', 'dismissed'])

function personaOption(o) {
  if (typeof o === 'string') return { value: o, label: o }
  return { value: o.id || o.name || '', label: o.label || o.name || o.id || '' }
}

function actionError(e) {
  if (e instanceof ApiError) {
    const body = (e.body || '').slice(0, 400)
    return `Request failed (${e.status}).${body ? `\n\n${body}` : ''}`
  }
  return String(e?.message || e)
}

/* compact action button with default / primary / danger tones */
function ActionBtn({ onClick, disabled, tone = 'default', title, children }) {
  const palette = {
    default: ['var(--surface-chip)', 'var(--text-soft)', 'var(--border)'],
    primary: ['color-mix(in srgb, var(--cyan-500) 20%, transparent)', 'var(--cyan-200)', 'color-mix(in srgb, var(--cyan-500) 45%, transparent)'],
    danger: ['color-mix(in srgb, var(--danger) 16%, transparent)', 'var(--danger-soft)', 'color-mix(in srgb, var(--danger) 40%, transparent)'],
  }[tone]
  const [bg, fg, bd] = palette
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        appearance: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        background: bg,
        color: fg,
        border: `1px solid ${bd}`,
        borderRadius: 'var(--radius-sm)',
        padding: '6px 11px',
        fontSize: 'var(--fs-xs)',
        fontWeight: 'var(--fw-medium)',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  )
}

function Detail({ label, children }) {
  return (
    <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-soft)', marginTop: 6, lineHeight: 1.45 }}>
      <span style={{ color: 'var(--muted)', fontWeight: 'var(--fw-semibold)' }}>{label}: </span>
      {children}
    </div>
  )
}

function JobCard({ job, busy, isOwner, onAction, onOpenEditor }) {
  const closedEval = CLOSED.has(job.status)
  const canApply = job.status === 'evaluated'
  const appliedDone = job.status === 'applied' || job.status === 'dismissed'
  const evalLabel = job.assessed ? 'Re-run Assessment' : 'Run Assessment'

  return (
    <Panel pad="14px 16px">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
            {job.company || 'Unknown company'} {job.role ? `\u2014 ${job.role}` : ''}
          </div>
          <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', marginTop: 3 }}>
            #{job.id} {'\u00b7'} {job.source || 'n/a'}{job.added_date ? ` \u00b7 ${fmtDate(job.added_date)}` : ''}
          </div>
        </div>
        <Badge tone={statusTone(job.status)}>{job.status || 'pending'}</Badge>
      </div>

      {job.assessment_summary && <Detail label="Assessment">{job.assessment_summary}</Detail>}
      {job.fitment_score && (
        <Detail label="Fitment">
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan-300)' }}>{job.fitment_score}</span>
        </Detail>
      )}
      {job.decision_notes && <Detail label="Notes">{job.decision_notes}</Detail>}
      {job.resume_template && (
        <Detail label="Resume template">{job.resume_template} / {job.resume_style || 'navy'}</Detail>
      )}
      {job.cl_template && (
        <Detail label="Cover letter template">{job.cl_template} / {job.cl_style || 'navy'}</Detail>
      )}

      {job.assessment_detail && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 'var(--fs-xs)' }}>
            Assessment details
          </summary>
          <pre
            style={{
              whiteSpace: 'pre-wrap', margin: '8px 0 0', padding: '10px 12px',
              background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-soft)',
              fontSize: 'var(--fs-xs)', lineHeight: 1.5, fontFamily: 'var(--font-mono)',
            }}
          >
            {job.assessment_detail}
          </pre>
        </details>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 12 }}>
        <ActionBtn tone="primary" disabled={busy || closedEval} onClick={() => onAction(job, 'eval')}>{evalLabel}</ActionBtn>
        <ActionBtn disabled={busy} onClick={() => onAction(job, 'resume')}>Generate Resume</ActionBtn>
        {isOwner && (
          <ActionBtn disabled={busy} onClick={() => onAction(job, 'cl-latex')}>Cover Letter (LaTeX)</ActionBtn>
        )}
        <ActionBtn disabled={busy} onClick={() => onAction(job, 'cl-html')}>Cover Letter (HTML)</ActionBtn>
        <ActionBtn disabled={busy || !canApply} onClick={() => onAction(job, 'apply')} title={canApply ? '' : 'Run assessment first'}>Queue Apply</ActionBtn>
        <ActionBtn disabled={busy || appliedDone} onClick={() => onAction(job, 'applied')}>Mark Applied</ActionBtn>
        <ActionBtn disabled={busy} onClick={() => onAction(job, 'unqueue')}>Unqueue</ActionBtn>
        <ActionBtn tone="danger" disabled={busy} onClick={() => onAction(job, 'remove')}>Remove</ActionBtn>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 8, paddingTop: 10, borderTop: '1px solid var(--border-soft)', alignItems: 'center' }}>
        <span style={{ ...EYEBROW, marginRight: 2 }}>AI editors</span>
        <ActionBtn disabled={busy} onClick={() => onOpenEditor(job, 'edit-resume')}>Edit Resume</ActionBtn>
        <ActionBtn disabled={busy} onClick={() => onOpenEditor(job, 'edit-cl')}>Edit Cover Letter</ActionBtn>
        <ActionBtn disabled={busy} onClick={() => onOpenEditor(job, 'templates')}>Templates</ActionBtn>
      </div>
    </Panel>
  )
}

function AddJobModal({ onClose, onSubmit }) {
  const [company, setCompany] = useState('')
  const [role, setRole] = useState('')
  const [jd, setJd] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')

  const field = {
    width: '100%', boxSizing: 'border-box', background: 'var(--surface-sunken)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    padding: '9px 11px', color: 'var(--text)', fontSize: 'var(--fs-sm)',
  }
  const lbl = { display: 'block', fontSize: 'var(--fs-xs)', color: 'var(--muted)', marginBottom: 5 }

  async function submit() {
    if (!company.trim() || !role.trim() || !jd.trim()) {
      setErr('Company, role, and job description are all required.')
      return
    }
    setSubmitting(true)
    setErr('')
    try {
      await onSubmit({ company: company.trim(), role: role.trim(), job_description: jd.trim() })
      onClose()
    } catch (e) {
      setErr(actionError(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 900, overflowY: 'auto', padding: '24px 14px' }}
    >
      <Panel pad="20px" style={{ maxWidth: 560, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-lg)', color: 'var(--text-strong)' }}>Add Job</span>
          <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.3rem', cursor: 'pointer' }}>{'\u2715'}</button>
        </div>
        <label style={{ display: 'block', marginBottom: 12 }}>
          <span style={lbl}>Company</span>
          <input style={field} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. Stripe" />
        </label>
        <label style={{ display: 'block', marginBottom: 12 }}>
          <span style={lbl}>Role</span>
          <input style={field} value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Senior Software Engineer" />
        </label>
        <label style={{ display: 'block', marginBottom: 16 }}>
          <span style={lbl}>Job description (paste full text)</span>
          <textarea style={{ ...field, resize: 'vertical', lineHeight: 1.45 }} rows={9} value={jd} onChange={(e) => setJd(e.target.value)} placeholder={'Paste the job description here\u2026'} />
        </label>
        {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={submit} disabled={submitting}>{submitting ? 'Queueing\u2026' : 'Queue & Assess'}</Button>
        </div>
      </Panel>
    </div>
  )
}

/* ---------- shared modal primitives for the editor flows ---------- */
const modalField = {
  width: '100%', boxSizing: 'border-box', background: 'var(--surface-sunken)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  padding: '9px 11px', color: 'var(--text)', fontSize: 'var(--fs-sm)',
}
const modalLabel = { display: 'block', fontSize: 'var(--fs-xs)', color: 'var(--muted)', marginBottom: 5 }

function Modal({ title, onClose, children, maxWidth = 640 }) {
  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 900, overflowY: 'auto', padding: '24px 14px' }}
    >
      <Panel pad="20px" style={{ maxWidth, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-lg)', color: 'var(--text-strong)' }}>{title}</span>
          <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.3rem', cursor: 'pointer' }}>{'\u2715'}</button>
        </div>
        {children}
      </Panel>
    </div>
  )
}

function ResultLine({ children }) {
  return (
    <pre style={{
      whiteSpace: 'pre-wrap', margin: '0 0 8px', padding: '9px 11px',
      background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
      borderRadius: 'var(--radius-sm)', color: 'var(--text-soft)',
      fontSize: 'var(--fs-xs)', lineHeight: 1.5, fontFamily: 'var(--font-mono)',
    }}>{children}</pre>
  )
}

function EmptyEditorState({ what }) {
  return (
    <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.5 }}>
      No {what} are available to edit yet. Generate one first, then come back to refine it with AI.
    </div>
  )
}

/* ---------- Edit Resume ---------- */
function EditResumeModal({ job, resumeOptions, onClose, onDone }) {
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
    <Modal title={`Edit Resume \u2014 ${job.company}`} onClose={onClose}>
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
            <Button size="sm" onClick={submit} disabled={submitting}>{submitting ? 'Editing\u2026' : 'Edit with AI'}</Button>
          </div>
        </>
      )}
    </Modal>
  )
}

/* ---------- Edit Cover Letter (draft \u2192 review \u2192 accept/discard) ---------- */
function EditCoverLetterModal({ job, coverLetterOptions, isOwner, onClose, onDone }) {
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
          <a href={accepted.href} target="_blank" rel="noreferrer" style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>Open the updated file {'\u2197'}</a>
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
        {draft.save_result && <ResultLine>{draft.save_result}</ResultLine>}
        {draft.pdf_result && <ResultLine>{draft.pdf_result}</ResultLine>}
        {draft.pdf_href && (
          <a href={draft.pdf_href} target="_blank" rel="noreferrer" style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>Open PDF preview {'\u2197'}</a>
        )}
        {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', margin: '12px 0', whiteSpace: 'pre-wrap' }}>{err}</div>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14, flexWrap: 'wrap' }}>
          <Button variant="ghost" size="sm" onClick={discard} disabled={submitting}>Discard draft</Button>
          <Button variant="ghost" size="sm" onClick={() => { setPhase('edit'); setInstructions('') }} disabled={submitting}>Revise again</Button>
          <Button size="sm" onClick={accept} disabled={submitting}>{submitting ? 'Applying\u2026' : 'Accept & apply'}</Button>
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
          <Button size="sm" onClick={runEdit} disabled={submitting}>{submitting ? 'Drafting\u2026' : 'Draft edit with AI'}</Button>
        </div>
      </>
    )
  }

  return (
    <Modal title={`Edit Cover Letter \u2014 ${job.company}`} onClose={onClose} maxWidth={680}>
      {bodyContent}
    </Modal>
  )
}

/* ---------- Template chooser (resume + cover letter, live preview) ---------- */
function TemplateModal({ job, resumeTemplates, clTemplates, styles, onClose, onSaved }) {
  const rTemplates = resumeTemplates?.length ? resumeTemplates : ['modern', 'executive', 'sidebar', 'portfolio']
  const cTemplates = clTemplates?.length ? clTemplates : rTemplates
  const sStyles = styles?.length ? styles : ['navy', 'slate', 'forest', 'warm', 'classic']

  const [tab, setTab] = useState('resume')
  const [rTpl, setRTpl] = useState(job.resume_template || 'modern')
  const [rSty, setRSty] = useState(job.resume_style || 'navy')
  const [cTpl, setCTpl] = useState(job.cl_template || 'modern')
  const [cSty, setCSty] = useState(job.cl_style || 'navy')
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')
  const [err, setErr] = useState('')

  const isResume = tab === 'resume'
  const tpl = isResume ? rTpl : cTpl
  const sty = isResume ? rSty : cSty
  const templates = isResume ? rTemplates : cTemplates
  const previewUrl = isResume
    ? `/dashboard/pipeline/preview-template/${tpl}/${sty}`
    : `/dashboard/pipeline/preview-cl/${tpl}/${sty}`

  async function save() {
    setSaving(true); setErr(''); setSavedMsg('')
    try {
      const endpoint = isResume ? '/dashboard/pipeline/select-template' : '/dashboard/pipeline/select-cl-template'
      await apiPost(endpoint, { job_id: job.id, template: tpl, style: sty })
      setSavedMsg(`${isResume ? 'Resume' : 'Cover letter'} template set: ${tpl} / ${sty}.`)
      onSaved()
    } catch (e) { setErr(actionError(e)) } finally { setSaving(false) }
  }

  const seg = (on) => ({
    padding: '6px 16px', borderRadius: 7, fontSize: 'var(--fs-xs)', fontWeight: 'var(--fw-semibold)',
    cursor: 'pointer', whiteSpace: 'nowrap', border: 'none',
    background: on ? 'var(--surface-raised)' : 'transparent',
    color: on ? 'var(--text-strong)' : 'var(--muted)',
    boxShadow: on ? 'inset 0 0 0 1px color-mix(in srgb,var(--cyan-500) 40%,transparent)' : 'none',
  })

  return (
    <Modal title={`Templates \u2014 ${job.company}`} onClose={onClose} maxWidth={760}>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
        <div style={{ display: 'inline-flex', gap: 4, padding: 4, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}>
          <button type="button" style={seg(isResume)} onClick={() => { setTab('resume'); setSavedMsg('') }}>Resume</button>
          <button type="button" style={seg(!isResume)} onClick={() => { setTab('cl'); setSavedMsg('') }}>Cover Letter</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
        <label style={{ flex: 1, minWidth: 180 }}>
          <span style={modalLabel}>Template</span>
          <select style={modalField} value={tpl} onChange={(e) => (isResume ? setRTpl : setCTpl)(e.target.value)}>
            {templates.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label style={{ flex: 1, minWidth: 180 }}>
          <span style={modalLabel}>Style</span>
          <select style={modalField} value={sty} onChange={(e) => (isResume ? setRSty : setCSty)(e.target.value)}>
            {sStyles.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>

      <iframe
        title="template-preview"
        src={previewUrl}
        style={{ width: '100%', height: 460, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: '#fff' }}
      />

      {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginTop: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
      {savedMsg && <div style={{ color: 'var(--green-300)', fontSize: 'var(--fs-sm)', marginTop: 12 }}>{savedMsg}</div>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14 }}>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        <Button size="sm" onClick={save} disabled={saving}>{saving ? 'Saving\u2026' : `Use this ${isResume ? 'resume' : 'cover letter'} template`}</Button>
      </div>
    </Modal>
  )
}

export default function Pipeline() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const [busy, setBusy] = useState(null)
  const [filter, setFilter] = useState('')
  const [persona, setPersona] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [editor, setEditor] = useState(null) // { type: 'edit-resume'|'edit-cl'|'templates', job }

  const load = useCallback(async ({ silent } = {}) => {
    if (!silent) setState((s) => ({ ...s, loading: !s.data, error: null }))
    try {
      const data = await apiFetch('/dashboard/pipeline/data')
      setState({ data, loading: false, error: null })
    } catch (error) {
      setState((s) => ({ ...s, loading: false, error }))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const data = state.data
  const jobs = data?.jobs || []
  const personaOptions = (data?.persona_options || []).map(personaOption)
  const activePersona = persona || data?.default_persona || 'default'

  async function onAction(job, type) {
    try {
      if (type === 'eval') {
        setBusy(`Running assessment for ${job.company}\u2026`)
        await apiPost('/dashboard/pipeline/evaluate', { job_id: job.id })
      } else if (type === 'resume') {
        setBusy(`Generating resume for ${job.company}\u2026`)
        const res = await apiPost('/dashboard/pipeline/generate-resume', { job_id: job.id, persona: activePersona })
        if (!res?.ok) window.alert(`Resume generation did not produce files.\n\n${String(res?.content || res?.notes || '').slice(0, 500)}`)
      } else if (type === 'cl-latex' || type === 'cl-html') {
        const pipeline = type === 'cl-latex' ? 'latex' : 'html'
        setBusy(`Generating cover letter (${pipeline.toUpperCase()}) for ${job.company}\u2026`)
        const res = await apiPost('/dashboard/pipeline/generate-cover-letter', { job_id: job.id, export_pipeline: pipeline, persona: activePersona })
        if (!res?.ok) window.alert(`Cover letter generation did not produce files (likely an API rate limit or provider error).\n\n${String(res?.content || res?.notes || '').slice(0, 500)}`)
      } else if (type === 'apply') {
        setBusy(`Queueing application for ${job.company}\u2026`)
        await apiPost('/dashboard/pipeline/queue-apply', { job_id: job.id })
      } else if (type === 'applied') {
        const note = window.prompt('Optional application note:', 'Applied manually from dashboard.')
        if (note === null) return
        setBusy(`Marking ${job.company} applied\u2026`)
        await apiPost('/dashboard/pipeline/mark-applied', { job_id: job.id, notes: note })
      } else if (type === 'unqueue') {
        setBusy(`Resetting ${job.company} to pending\u2026`)
        await apiPost('/dashboard/pipeline/unqueue', { job_id: job.id })
      } else if (type === 'remove') {
        if (!window.confirm(`Remove ${job.company} \u2014 ${job.role} from the pipeline? This deletes the entry.`)) return
        setBusy(`Removing ${job.company}\u2026`)
        await apiPost('/dashboard/pipeline/remove', { job_id: job.id })
      }
      await load({ silent: true })
    } catch (e) {
      window.alert(actionError(e))
    } finally {
      setBusy(null)
    }
  }

  const q = filter.trim().toLowerCase()
  const shown = q
    ? jobs.filter((j) => [j.company, j.role, j.status, j.source, j.decision_notes].join(' ').toLowerCase().includes(q))
    : jobs

  const countBy = (s) => jobs.filter((j) => j.status === s).length

  const fieldStyle = {
    flex: 1, minWidth: 220, maxWidth: 420, boxSizing: 'border-box',
    background: 'var(--surface-sunken)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', padding: '9px 11px',
    color: 'var(--text)', fontSize: 'var(--fs-sm)',
  }

  return (
    <Screen loading={state.loading} error={state.error} empty={false}>
      <StatGrid>
        <Stat label="Queue total" value={data?.total ?? 0} tone="accent" />
        <Stat label="Pending" value={countBy('pending')} tone="warn" />
        <Stat label="Evaluated" value={countBy('evaluated')} />
        <Stat label="Added" value={countBy('added')} tone="green" />
        <Stat label="Applied" value={countBy('applied')} tone="green" />
      </StatGrid>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={'Filter company / role / status\u2026'}
          style={fieldStyle}
        />
        {personaOptions.length > 0 && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            <span style={{ ...EYEBROW }}>Persona</span>
            <select
              value={activePersona}
              onChange={(e) => setPersona(e.target.value)}
              style={{ ...fieldStyle, flex: '0 0 auto', minWidth: 150 }}
            >
              {personaOptions.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
        )}
        <Button size="sm" onClick={() => setAddOpen(true)}>{'\uFF0B'} Add Job</Button>
      </div>

      {busy && (
        <Panel pad="11px 14px" style={{ marginBottom: 14, borderColor: 'color-mix(in srgb, var(--cyan-500) 45%, var(--border))' }}>
          <div style={{ color: 'var(--cyan-200)', fontSize: 'var(--fs-sm)', marginBottom: 8 }}>{busy}</div>
          <div style={{ height: 4, borderRadius: 'var(--radius-pill)', background: 'var(--ink-600)', overflow: 'hidden' }}>
            <div style={{ width: '40%', height: '100%', background: 'var(--cyan-400)', borderRadius: 'var(--radius-pill)', animation: 'jcpulse 1.1s ease-in-out infinite' }} />
          </div>
        </Panel>
      )}
      <style>{'@keyframes jcpulse{0%{margin-left:-40%}100%{margin-left:100%}}'}</style>

      {shown.length === 0 ? (
        <EmptyState
          label={jobs.length === 0 ? 'No jobs in the queue.' : 'No jobs match your filter.'}
          hint={jobs.length === 0 ? 'Use Add Job, or share a posting from your phone.' : undefined}
        />
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {shown.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              busy={!!busy}
              isOwner={!!data?.is_owner}
              onAction={onAction}
              onOpenEditor={(j, type) => setEditor({ type, job: j })}
            />
          ))}
        </div>
      )}

      {addOpen && (
        <AddJobModal
          onClose={() => setAddOpen(false)}
          onSubmit={async (payload) => {
            await apiPost('/jobs/evaluate', { ...payload, source: 'dashboard_manual' })
            await load({ silent: true })
          }}
        />
      )}

      {editor?.type === 'edit-resume' && (
        <EditResumeModal
          job={editor.job}
          resumeOptions={data?.optimized_resume_options}
          onClose={() => setEditor(null)}
          onDone={() => { setEditor(null); load({ silent: true }) }}
        />
      )}
      {editor?.type === 'edit-cl' && (
        <EditCoverLetterModal
          job={editor.job}
          coverLetterOptions={data?.cover_letter_options}
          isOwner={!!data?.is_owner}
          onClose={() => setEditor(null)}
          onDone={() => { setEditor(null); load({ silent: true }) }}
        />
      )}
      {editor?.type === 'templates' && (
        <TemplateModal
          job={editor.job}
          resumeTemplates={data?.resume_templates}
          clTemplates={data?.cl_templates}
          styles={data?.template_styles}
          onClose={() => setEditor(null)}
          onSaved={() => load({ silent: true })}
        />
      )}
    </Screen>
  )
}
