import { useState } from 'react'
import { Button } from '../../design-system'
import { apiPost } from '../../auth/api.js'
import { Modal, modalField, modalLabel, actionError } from './shared.jsx'

/* Template chooser (resume + cover letter, live preview) */
export default function TemplateModal({ job, resumeTemplates, clTemplates, styles, onClose, onSaved }) {
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
  // Restrict tpl/sty to safe alphanumeric-and-hyphen slugs before embedding in URL paths.
  const safeTpl = tpl.replace(/[^a-z0-9-]/gi, '')
  const safeSty = sty.replace(/[^a-z0-9-]/gi, '')
  const previewUrl = isResume
    ? `/dashboard/pipeline/preview-template/${safeTpl}/${safeSty}`
    : `/dashboard/pipeline/preview-cl/${safeTpl}/${safeSty}`

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
    <Modal title={`Templates — ${job.company}`} onClose={onClose} maxWidth={760}>
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
        <Button size="sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : `Use this ${isResume ? 'resume' : 'cover letter'} template`}</Button>
      </div>
    </Modal>
  )
}
