import { useState } from 'react'
import { Button } from '../../design-system'
import { Modal, modalField, modalLabel, actionError } from './shared.jsx'

export default function AddJobModal({ onClose, onSubmit }) {
  const [company, setCompany] = useState('')
  const [role, setRole] = useState('')
  const [jd, setJd] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')

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
    <Modal title="Add Job" onClose={onClose} maxWidth={560}>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={modalLabel}>Company</span>
        <input style={modalField} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. Stripe" />
      </label>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={modalLabel}>Role</span>
        <input style={modalField} value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Senior Software Engineer" />
      </label>
      <label style={{ display: 'block', marginBottom: 16 }}>
        <span style={modalLabel}>Job description (paste full text)</span>
        <textarea style={{ ...modalField, resize: 'vertical', lineHeight: 1.45 }} rows={9} value={jd} onChange={(e) => setJd(e.target.value)} placeholder={'Paste the job description here…'} />
      </label>
      {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" onClick={submit} disabled={submitting}>{submitting ? 'Queueing…' : 'Queue & Assess'}</Button>
      </div>
    </Modal>
  )
}
