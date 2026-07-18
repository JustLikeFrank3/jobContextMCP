import { useState } from 'react'
import {
  useApi, Screen, StatGrid, Stat, EmptyState,
} from './_shared.jsx'
import { dayLabel, startOfDayLocal } from './interviewUtils.js'

/* Interviews — upcoming schedule and debrief log.
   Data: GET /dashboard/interviews/data (_interviews_payload).

   Design-handoff layout: mono UPCOMING eyebrow over a 2-col card grid — the
   next interview gets a cyan-tinted gradient card with a mono countdown chip,
   later ones get neutral cards — then RECENT DEBRIEFS as compact rows with
   mono dates. Debrief rows expand to reveal what landed, verbatim quotes, and
   surfaced priorities (payload detail the handoff rows don't show). */

const TYPE_LABELS = {
  recruiter_screen: 'Recruiter Screen',
  hiring_manager: 'Hiring Manager',
  technical: 'Technical',
  panel: 'Panel',
  onsite_loop: 'Onsite Loop',
  informational: 'Informational',
  team_match: 'Team Match',
  behavioral: 'Behavioral',
  system_design: 'System Design',
  coding: 'Coding',
  debrief: 'Debrief',
}

function typeLabel(t) {
  if (!t) return ''
  return TYPE_LABELS[t] || String(t).replaceAll('_', ' ')
}

/* Handoff palette (jobContext Desktop Import.dc.html, Interviews page). */
const MONO_EYEBROW = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 'var(--fw-semibold)',
  letterSpacing: '1.2px',
  textTransform: 'uppercase',
  color: '#7C8AA6',
}

const CHIP_MONO = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 'var(--fw-semibold)',
  whiteSpace: 'nowrap',
}

/* Self-rating chip colors, mapped onto the handoff status palette. */
function ratingColors(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return ['#9BB0D0', 'rgba(255,255,255,.06)']
  if (v >= 8) return ['#6FD3A0', 'rgba(111,211,160,.15)']
  if (v >= 5) return ['#6FE0EE', 'rgba(0,181,200,.15)']
  return ['#E0B77A', 'rgba(224,183,122,.15)']
}

function quoteText(q) {
  return typeof q === 'string' ? q : q?.quote || ''
}

/* "JUL 9"-style mono date for debrief rows. */
function monoDate(iso) {
  const d = startOfDayLocal(iso)
  if (!d) return '—'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()
}

function metaLine(iv) {
  return [
    typeLabel(iv.interview_type),
    iv.interview_format,
    iv.interviewer
      ? `with ${iv.interviewer}${iv.interviewer_role ? ` (${iv.interviewer_role})` : ''}`
      : '',
    iv.duration_minutes ? `${iv.duration_minutes} min` : '',
  ].filter(Boolean).join(' · ')
}

function BulletSection({ label, items }) {
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <>
      <div style={{ ...MONO_EYEBROW, fontSize: 10, marginTop: 12, marginBottom: 4 }}>{label}</div>
      <ul style={{ margin: 0, paddingLeft: 16, color: '#B7C6E0', fontSize: 12.5, lineHeight: 1.5 }}>
        {items.map((x, i) => (
          <li key={i} style={{ marginBottom: 2 }}>{x}</li>
        ))}
      </ul>
    </>
  )
}

function SectionLabel({ label, count, first }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginTop: first ? 4 : 26,
        marginBottom: 12,
      }}
    >
      <div style={MONO_EYEBROW}>{label}</div>
      <div style={{ ...MONO_EYEBROW, letterSpacing: 0 }}>{count}</div>
    </div>
  )
}

/* Upcoming interview card. The next one (featured) gets the cyan-tinted
   gradient treatment; later ones are neutral. */
function UpcomingCard({ iv, featured }) {
  const date = (iv.interview_date || '').slice(0, 10)
  const rel = dayLabel(iv.interview_date)
  const isToday = rel === 'Today'
  const chipText = (rel || date || '—').toUpperCase()
  const chipColor = featured ? '#6FE0EE' : isToday ? '#E0B77A' : '#A9B6CE'
  const meta = metaLine(iv)

  return (
    <div
      style={{
        borderRadius: 16,
        padding: 18,
        background: featured
          ? 'linear-gradient(150deg, rgba(0,181,200,.13), rgba(0,181,200,.03))'
          : 'rgba(255,255,255,.045)',
        border: featured ? '1px solid rgba(0,181,200,.26)' : '1px solid rgba(255,255,255,.08)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ fontSize: 16, fontWeight: 'var(--fw-bold)', color: '#F0F5FF', minWidth: 0 }}>
          {[iv.company || 'Unknown', iv.role].filter(Boolean).join(' · ')}
        </div>
        <div style={{ ...CHIP_MONO, color: chipColor }}>{chipText}</div>
      </div>
      {meta && (
        <div style={{ fontSize: 13, color: '#8A99B5', marginTop: 5 }}>{meta}</div>
      )}
      {iv.notes && (
        <div style={{ fontSize: 12.5, color: '#B7C6E0', marginTop: 12, lineHeight: 1.45 }}>
          {iv.notes}
        </div>
      )}
    </div>
  )
}

/* Recent debrief row: handoff-style compact row (title, synopsis, mono date)
   that expands to the full debrief detail. */
function DebriefRow({ iv }) {
  const [open, setOpen] = useState(false)

  const quotes = Array.isArray(iv.verbatim_quotes) ? iv.verbatim_quotes.slice(0, 3) : []
  const landed = Array.isArray(iv.what_landed) ? iv.what_landed : []
  const synopsis =
    landed[0] || (quotes[0] ? `“${quoteText(quotes[0])}”` : '') || iv.notes || metaLine(iv)
  const hasBody =
    landed.length > 0 || quotes.length > 0 ||
    (Array.isArray(iv.surfaced_priorities) && iv.surfaced_priorities.length > 0) || iv.notes
  const [ratingFg, ratingBg] = ratingColors(iv.self_rating)
  const meta = metaLine(iv)

  return (
    <div
      style={{
        borderRadius: 14,
        background: 'rgba(255,255,255,.035)',
        border: '1px solid rgba(255,255,255,.06)',
      }}
    >
      <button
        type="button"
        onClick={() => hasBody && setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          appearance: 'none',
          width: '100%',
          textAlign: 'left',
          background: 'transparent',
          border: 'none',
          cursor: hasBody ? 'pointer' : 'default',
          padding: '14px 16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          font: 'inherit',
          color: 'inherit',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14.5, fontWeight: 'var(--fw-semibold)', color: '#E8EFFB' }}>
            {[iv.company || 'Unknown', typeLabel(iv.interview_type)].filter(Boolean).join(' · ')}
          </div>
          {synopsis && (
            <div
              style={{
                fontSize: 12.5,
                color: '#8A99B5',
                marginTop: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: open ? 'normal' : 'nowrap',
              }}
            >
              {synopsis}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {iv.self_rating != null && (
            <span
              style={{
                ...CHIP_MONO,
                fontSize: 10,
                color: ratingFg,
                background: ratingBg,
                padding: '4px 8px',
                borderRadius: 8,
              }}
            >
              {`★ ${iv.self_rating}/10`}
            </span>
          )}
          <span style={{ ...CHIP_MONO, color: '#6B7A96' }}>{monoDate(iv.interview_date)}</span>
          {hasBody && (
            <span
              aria-hidden
              style={{
                color: '#6B7A96',
                fontSize: 'var(--fs-xs)',
                transition: 'transform var(--dur-base)',
                transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
              }}
            >
              {'▶'}
            </span>
          )}
        </div>
      </button>

      {open && hasBody && (
        <div style={{ padding: '0 16px 14px', borderTop: '1px solid rgba(255,255,255,.06)' }}>
          {meta && (
            <div style={{ fontSize: 12.5, color: '#8A99B5', marginTop: 12 }}>{meta}</div>
          )}
          <BulletSection label="What landed" items={landed} />
          {quotes.map((q, i) => (
            <div
              key={i}
              style={{
                borderLeft: '3px solid var(--cyan-500)',
                paddingLeft: 10,
                margin: '10px 0 0',
                color: '#B7C6E0',
                fontSize: 12.5,
                fontStyle: 'italic',
                lineHeight: 1.45,
              }}
            >
              {`“${quoteText(q)}”`}
            </div>
          ))}
          <BulletSection label="Surfaced priorities" items={iv.surfaced_priorities} />
          {iv.notes && (
            <div style={{ fontSize: 12.5, color: '#B7C6E0', marginTop: 12, lineHeight: 1.45 }}>
              {iv.notes}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Interviews() {
  const { data, loading, error } = useApi('/dashboard/interviews/data')
  const upcoming = data?.upcoming || []
  const recent = data?.recent || []

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && (data?.total ?? 0) === 0}
      emptyLabel="No interviews logged yet."
    >
      <StatGrid>
        <Stat label="Total logged" value={data?.total ?? 0} tone="accent" />
        <Stat label="Upcoming" value={upcoming.length} tone={upcoming.length ? 'green' : 'muted'} />
        <Stat label="Debriefs" value={recent.length} />
      </StatGrid>

      <SectionLabel label="Upcoming" count={upcoming.length} first />
      {upcoming.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
          {upcoming.map((iv, i) => (
            <UpcomingCard key={`up-${i}`} iv={iv} featured={i === 0} />
          ))}
        </div>
      ) : (
        <EmptyState label="No upcoming interviews scheduled." />
      )}

      <SectionLabel label="Recent debriefs" count={recent.length} />
      {recent.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {recent.map((iv, i) => <DebriefRow key={`re-${i}`} iv={iv} />)}
        </div>
      ) : (
        <EmptyState label="No debriefs logged yet." hint="Use log_interview() from your assistant." />
      )}
    </Screen>
  )
}
