import { EYEBROW, fmtDate } from '../_shared.jsx'

/* Pipeline row — one job, styled per the desktop design handoff's 5-column
   table (COMPANY with 34px initial tile / ROLE / STAGE chip / FIT / NEXT
   STEP), followed by the full detail + action area the design omits: every
   assessment detail, action button, and AI-editor entry point is preserved. */

const CLOSED = new Set(['added', 'applied', 'dismissed'])

/* Shared column template so the header row in Pipeline.jsx lines up. */
export const ROW_GRID = 'minmax(0, 2fr) minmax(0, 2fr) minmax(0, 1.1fr) minmax(0, .7fr) minmax(0, 1.4fr)'

/* Real queue statuses mapped onto the handoff's stage palette by progress:
   applied = furthest along (OFFER green), added = ready to go out (ONSITE
   cyan), evaluated = mid-funnel (SCREEN amber), pending = neutral
   (APPLIED/INTERESTED grey), dismissed = closed (danger red). */
const STAGE = {
  applied: { c: '#6FD3A0', bg: 'rgba(111,211,160,.14)' },
  added: { c: '#6FE0EE', bg: 'rgba(0,181,200,.14)' },
  evaluated: { c: '#E0B77A', bg: 'rgba(224,183,122,.14)' },
  pending: { c: '#9BB0D0', bg: 'rgba(255,255,255,.06)' },
  dismissed: { c: '#E39393', bg: 'rgba(227,147,147,.12)' },
}

/* fitment_score is a free string ("7/10", "85"). Normalize to a 0–100 pct
   for the handoff's score coloring; display the raw value untouched. */
function scoreInfo(raw) {
  const text = String(raw || '').trim()
  if (!text) return null
  const m = text.match(/(\d+(?:\.\d+)?)\s*(?:\/\s*(\d+(?:\.\d+)?))?/)
  if (!m) return { text, color: '#9BB0D0' }
  const num = Number.parseFloat(m[1])
  const den = m[2] ? Number.parseFloat(m[2]) : (num <= 10 ? 10 : 100)
  const pct = den > 0 ? (num / den) * 100 : num
  const color = pct >= 85 ? '#6FE0EE' : pct >= 78 ? '#E0EAF7' : '#9BB0D0'
  return { text, color }
}

function nextStep(job) {
  switch (job.status) {
    case 'evaluated': return 'Queue apply or generate materials'
    case 'added': return 'Generate materials & apply'
    case 'applied': return 'Awaiting reply'
    case 'dismissed': return 'Closed'
    default: return 'Run assessment'
  }
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

export default function JobCard({ job, busy, isOwner, onAction, onOpenEditor }) {
  const closedEval = CLOSED.has(job.status)
  const canApply = job.status === 'evaluated'
  const appliedDone = job.status === 'applied' || job.status === 'dismissed'
  const evalLabel = job.assessed ? 'Re-run Assessment' : 'Run Assessment'
  const stage = STAGE[job.status] || STAGE.pending
  const score = scoreInfo(job.fitment_score)
  const initial = (job.company || '').trim().charAt(0).toUpperCase() || '?'

  return (
    <div style={{ borderTop: '1px solid rgba(255,255,255,.05)', padding: '14px 20px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: ROW_GRID, gap: 10, alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, minWidth: 0 }}>
          <div
            style={{
              width: 34, height: 34, borderRadius: 10, background: 'rgba(255,255,255,.06)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 'var(--fw-bold)', color: '#C9D6EC', flexShrink: 0,
            }}
          >
            {initial}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14.5, fontWeight: 'var(--fw-semibold)', color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {job.company || 'Unknown company'}
            </div>
            <div style={{ fontSize: 10.5, color: 'var(--faint)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              #{job.id} {'·'} {job.source || 'n/a'}{job.added_date ? ` · ${fmtDate(job.added_date)}` : ''}
            </div>
          </div>
        </div>
        <div style={{ fontSize: 13.5, color: 'var(--muted)', minWidth: 0 }}>{job.role || '—'}</div>
        <div>
          <span
            style={{
              fontSize: 10, fontWeight: 'var(--fw-semibold)', color: stage.c, background: stage.bg,
              padding: '4px 9px', borderRadius: 8, fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase', whiteSpace: 'nowrap',
            }}
          >
            {job.status || 'pending'}
          </span>
        </div>
        <div style={{ textAlign: 'center', fontSize: 16, fontWeight: 'var(--fw-bold)', fontFamily: 'var(--font-mono)', color: score ? score.color : 'var(--faint)' }}>
          {score ? score.text : '—'}
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>{nextStep(job)}</div>
      </div>

      {job.assessment_summary && <Detail label="Assessment">{job.assessment_summary}</Detail>}
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
    </div>
  )
}
