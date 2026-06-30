/* Shared building blocks for the dashboard screens.

   Every ported screen fetches a JSON endpoint and renders tables / stat cards /
   breakdown bars. These primitives keep that consistent and lean so each screen
   file stays small and declarative. All visual values reference design tokens —
   never hard-code color/spacing here. */
import { useState, useEffect } from 'react'
import { Panel } from '../design-system'
import { apiFetch } from '../auth/api.js'

/* ---------- data hook ---------- */
/**
 * Fetch a JSON endpoint once on mount.
 * Returns { data, loading, error, reload }. apiFetch handles 401 -> login.
 */
export function useApi(path) {
  const [state, setState] = useState({ data: null, loading: true, error: null })

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, error: null })
    apiFetch(path)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((err) => {
        if (!cancelled) setState({ data: null, loading: false, error: err })
      })
    return () => {
      cancelled = true
    }
  }, [path])

  const reload = () =>
    apiFetch(path)
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((error) => setState((s) => ({ ...s, error })))

  return { ...state, reload }
}

/* ---------- layout ---------- */
export const EYEBROW = {
  font: 'var(--fw-semibold) var(--fs-2xs)/1.2 var(--font-sans)',
  textTransform: 'uppercase',
  letterSpacing: 'var(--ls-eyebrow)',
  color: 'var(--muted)',
}

/** Wraps a screen body with loading / error / empty fallbacks. */
export function Screen({ loading, error, empty, emptyLabel, children }) {
  if (loading) return <Centered>{'Loading\u2026'}</Centered>
  if (error) {
    const code = error.status ? ` (${error.status})` : ''
    return <Centered tone="var(--warn)">{`Couldn\u2019t load this data.${code} Try refreshing.`}</Centered>
  }
  if (empty) return <EmptyState label={emptyLabel} />
  return children
}

function Centered({ children, tone = 'var(--muted)' }) {
  return (
    <Panel pad="48px 28px" style={{ textAlign: 'center', color: tone, fontSize: 'var(--fs-sm)' }}>
      {children}
    </Panel>
  )
}

export function EmptyState({ label = 'Nothing here yet.', hint }) {
  return (
    <Panel pad="40px 28px" style={{ textAlign: 'center' }}>
      <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-base)', fontWeight: 'var(--fw-medium)' }}>
        {label}
      </div>
      {hint && (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 6 }}>{hint}</div>
      )}
    </Panel>
  )
}

/** Section heading + optional right-aligned slot. */
export function SectionHead({ title, right }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        gap: 12,
        margin: '4px 2px 12px',
      }}
    >
      <h2
        style={{
          margin: 0,
          font: 'var(--fw-semibold) var(--fs-lg)/1.2 var(--font-display)',
          color: 'var(--text-strong)',
        }}
      >
        {title}
      </h2>
      {right != null && <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>{right}</div>}
    </div>
  )
}

/* ---------- stat cards ---------- */
export function StatGrid({ children, min = 150 }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
        gap: 12,
        marginBottom: 20,
      }}
    >
      {children}
    </div>
  )
}

const TONE_COLOR = {
  default: 'var(--text-strong)',
  accent: 'var(--cyan-300)',
  green: 'var(--green-300)',
  warn: 'var(--warn)',
  danger: 'var(--danger-soft)',
  muted: 'var(--muted)',
}

export function Stat({ label, value, tone = 'default', sub }) {
  return (
    <Panel pad="14px 16px">
      <div style={EYEBROW}>{label}</div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 'var(--fw-bold)',
          fontSize: 'var(--fs-xl)',
          lineHeight: 1.1,
          color: TONE_COLOR[tone] || TONE_COLOR.default,
          marginTop: 6,
        }}
      >
        {value}
      </div>
      {sub && <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', marginTop: 4 }}>{sub}</div>}
    </Panel>
  )
}

/* ---------- badges ---------- */
const BADGE_TONE = {
  default: ['var(--surface-chip)', 'var(--text-soft)'],
  accent: ['color-mix(in srgb, var(--cyan-500) 18%, transparent)', 'var(--cyan-300)'],
  green: ['color-mix(in srgb, var(--green-500) 16%, transparent)', 'var(--green-300)'],
  warn: ['color-mix(in srgb, var(--warn) 18%, transparent)', 'var(--warn)'],
  danger: ['color-mix(in srgb, var(--danger) 16%, transparent)', 'var(--danger-soft)'],
  muted: ['var(--surface-sunken)', 'var(--muted)'],
}

export function Badge({ children, tone = 'default' }) {
  const [bg, fg] = BADGE_TONE[tone] || BADGE_TONE.default
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        background: bg,
        color: fg,
        borderRadius: 'var(--radius-pill)',
        padding: '3px 10px',
        fontSize: 'var(--fs-2xs)',
        fontWeight: 'var(--fw-semibold)',
        textTransform: 'capitalize',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

/** Map common status strings to a badge tone. */
export function statusTone(status) {
  const s = (status || '').toLowerCase()
  if (/offer|accepted|hired|posted|approved|applied|evaluated|sent/.test(s)) return 'green'
  if (/reject|dismiss|declin|closed|withdrawn|ghost/.test(s)) return 'danger'
  if (/interview|screen|onsite|phone|final|follow/.test(s)) return 'accent'
  if (/draft|pending|new|none|waiting|paused/.test(s)) return 'warn'
  return 'default'
}

/* ---------- breakdown bars ---------- */
/** Horizontal count bars for a {label,count}[] breakdown. */
export function Bars({ items, tone = 'accent', labelKey = 'label', max }) {
  const top = max || Math.max(1, ...items.map((i) => i.count || 0))
  const color = TONE_COLOR[tone] || TONE_COLOR.accent
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {items.map((it, i) => {
        const pct = Math.round(((it.count || 0) / top) * 100)
        return (
          <div key={`${it[labelKey]}-${i}`}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 'var(--fs-xs)',
                marginBottom: 4,
              }}
            >
              <span style={{ color: 'var(--text-soft)', textTransform: 'capitalize' }}>
                {String(it[labelKey] || '\u2014').replace(/_/g, ' ')}
              </span>
              <span style={{ color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>{it.count}</span>
            </div>
            <div
              style={{
                height: 7,
                borderRadius: 'var(--radius-pill)',
                background: 'var(--ink-600)',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: '100%',
                  background: color,
                  borderRadius: 'var(--radius-pill)',
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ---------- list rows ---------- */
/** A flexible list of rows inside a Panel. Each child is one row. */
export function List({ children }) {
  return <div style={{ display: 'grid', gap: 8 }}>{children}</div>
}

export function Row({ title, subtitle, meta, right, children }) {
  return (
    <Panel pad="12px 14px">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          {title && (
            <div
              style={{
                color: 'var(--text-strong)',
                fontWeight: 'var(--fw-semibold)',
                fontSize: 'var(--fs-base)',
              }}
            >
              {title}
            </div>
          )}
          {subtitle && (
            <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 3, lineHeight: 1.4 }}>
              {subtitle}
            </div>
          )}
          {children}
          {meta && (
            <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', marginTop: 6 }}>{meta}</div>
          )}
        </div>
        {right != null && <div style={{ flexShrink: 0, textAlign: 'right' }}>{right}</div>}
      </div>
    </Panel>
  )
}

/* ---------- formatting ---------- */
export function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(String(iso).slice(0, 10) + 'T00:00:00')
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtNum(n) {
  const v = Number(n || 0)
  return v.toLocaleString()
}
