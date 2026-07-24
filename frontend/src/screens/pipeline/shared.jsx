import { Panel } from '../../design-system'
import { ApiError } from '../../auth/api.js'
import { Badge } from '../_shared.jsx'
import { parseProvenance, PROVENANCE_TONE, PROVENANCE_BADGE_LABEL } from './provenance.js'

/* Shared primitives for the Pipeline card actions and editor modals. */

/* Renders the backend's one-line provenance verdict as a badge + line.
   Renders nothing when the response carried no verdict (e.g. older server). */
export function ProvenanceNote({ line }) {
  const parsed = parseProvenance(line)
  if (!parsed) return null
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '0 0 8px' }}>
      <Badge tone={PROVENANCE_TONE[parsed.status]}>{PROVENANCE_BADGE_LABEL[parsed.status]}</Badge>
      <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--muted)' }}>{parsed.text}</span>
    </div>
  )
}

export function actionError(e) {
  if (e instanceof ApiError) {
    const body = (e.body || '').slice(0, 400)
    return `Request failed (${e.status}).${body ? `\n\n${body}` : ''}`
  }
  return String(e?.message || e)
}

export const modalField = {
  width: '100%', boxSizing: 'border-box', background: 'var(--surface-sunken)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  padding: '9px 11px', color: 'var(--text)', fontSize: 'var(--fs-sm)',
}
export const modalLabel = { display: 'block', fontSize: 'var(--fs-xs)', color: 'var(--muted)', marginBottom: 5 }

export function Modal({ title, onClose, children, maxWidth = 640 }) {
  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 900, overflowY: 'auto', padding: '24px 14px' }}
    >
      <Panel pad="20px" style={{ maxWidth, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-lg)', color: 'var(--text-strong)' }}>{title}</span>
          <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.3rem', cursor: 'pointer' }}>{'✕'}</button>
        </div>
        {children}
      </Panel>
    </div>
  )
}

export function ResultLine({ children }) {
  return (
    <pre style={{
      whiteSpace: 'pre-wrap', margin: '0 0 8px', padding: '9px 11px',
      background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
      borderRadius: 'var(--radius-sm)', color: 'var(--text-soft)',
      fontSize: 'var(--fs-xs)', lineHeight: 1.5, fontFamily: 'var(--font-mono)',
    }}>{children}</pre>
  )
}

export function EmptyEditorState({ what }) {
  return (
    <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.5 }}>
      No {what} are available to edit yet. Generate one first, then come back to refine it with AI.
    </div>
  )
}
