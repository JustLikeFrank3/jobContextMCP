import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
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

const FOCUSABLE = 'button, a[href], input, select, textarea, [tabindex]'

function modalControls(dialog) {
  return [...dialog.querySelectorAll(FOCUSABLE)].filter((node) => (
    node.tabIndex >= 0 && !node.matches(':disabled, [type="hidden"]') && !node.closest('[hidden]') &&
    getComputedStyle(node).display !== 'none' && getComputedStyle(node).visibility !== 'hidden'
  ))
}

// The backdrop is a dialog container, not a button: Escape dismisses it,
// while Enter/Space remain available to its native inputs and buttons.
export function useModalKeyboard(onClose) {
  const dialogRef = useRef(null)
  useEffect(() => {
    const previous = document.activeElement
    const dialog = dialogRef.current
    ;(modalControls(dialog)[0] || dialog).focus()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [])

  function onKeyDown(event) {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onClose()
    } else if (event.key === 'Tab') {
      const controls = modalControls(event.currentTarget)
      const first = controls[0]
      const last = controls.at(-1)
      if (!first) {
        event.preventDefault()
        event.currentTarget.focus()
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  }
  return { ref: dialogRef, onKeyDown }
}

export function Modal({ title, onClose, children, maxWidth = 640 }) {
  const keyboard = useModalKeyboard(onClose)
  // Portal to <body>: .jc-page's enter animation animates `transform`,
  // which makes it the containing block for fixed descendants — a modal
  // rendered in-tree gets trapped (and clipped) inside the page wrapper,
  // visibly so when the page content is short (empty pipeline, qa).
  return createPortal(
    <div
      ref={keyboard.ref}
      onKeyDown={keyboard.onKeyDown}
      role="dialog"
      aria-modal="true"
      tabIndex={-1}
      aria-label={title}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 900, overflowY: 'auto', padding: '24px 14px' }}
    >
      <Panel pad="20px" style={{ maxWidth, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-lg)', color: 'var(--text-strong)' }}>{title}</span>
          <button type="button" aria-label="Close dialog" onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.3rem', cursor: 'pointer' }}>{'✕'}</button>
        </div>
        {children}
      </Panel>
    </div>,
    document.body,
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
