import { Panel } from '../../design-system'
import { Badge, statusTone, EYEBROW, fmtDate } from '../_shared.jsx'

const CLOSED = new Set(['added', 'applied', 'dismissed'])

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

export default function JobCard({ job, busy, isOwner, onAction, onOpenEditor }) {
  const closedEval = CLOSED.has(job.status)
  const canApply = job.status === 'evaluated'
  const appliedDone = job.status === 'applied' || job.status === 'dismissed'
  const evalLabel = job.assessed ? 'Re-run Assessment' : 'Run Assessment'

  return (
    <Panel pad="14px 16px">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
            {job.company || 'Unknown company'} {job.role ? `— ${job.role}` : ''}
          </div>
          <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', marginTop: 3 }}>
            #{job.id} {'·'} {job.source || 'n/a'}{job.added_date ? ` · ${fmtDate(job.added_date)}` : ''}
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
