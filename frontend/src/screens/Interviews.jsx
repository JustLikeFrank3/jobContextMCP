import { Panel } from '../design-system'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, EmptyState, EYEBROW,
} from './_shared.jsx'
import { dayLabel } from './interviewUtils.js'

/* Interviews — upcoming schedule and debrief log.
   Data: GET /dashboard/interviews/data (_interviews_payload).

   Ports the legacy /dashboard/interviews two-column board: upcoming on the
   left, recent debriefs on the right, with day labels, type labels, what
   landed, verbatim quotes, and surfaced priorities. */

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

function ratingTone(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return 'muted'
  if (v >= 8) return 'green'
  if (v >= 5) return 'accent'
  return 'warn'
}

function quoteText(q) {
  return typeof q === 'string' ? q : q?.quote || ''
}

function BulletSection({ label, items }) {
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <>
      <div style={{ ...EYEBROW, marginTop: 10, marginBottom: 4 }}>{label}</div>
      <ul style={{ margin: 0, paddingLeft: 16, color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', lineHeight: 1.5 }}>
        {items.map((x, i) => (
          <li key={i} style={{ marginBottom: 2 }}>{x}</li>
        ))}
      </ul>
    </>
  )
}

function InterviewCard({ iv, upcoming }) {
  const date = (iv.interview_date || '').slice(0, 10)
  const rel = dayLabel(iv.interview_date)
  const isToday = rel === 'Today'
  const badgeTone = upcoming ? (isToday ? 'warn' : 'accent') : 'muted'
  const badgeText = upcoming ? rel || date : date || '\u2014'

  const meta = [
    typeLabel(iv.interview_type),
    iv.interview_format,
    iv.interviewer
      ? `with ${iv.interviewer}${iv.interviewer_role ? ` (${iv.interviewer_role})` : ''}`
      : '',
    iv.duration_minutes ? `${iv.duration_minutes} min` : '',
  ].filter(Boolean).join(' \u00b7 ')

  const quotes = Array.isArray(iv.verbatim_quotes) ? iv.verbatim_quotes.slice(0, 3) : []

  return (
    <Panel
      pad="14px 16px"
      style={upcoming ? { borderColor: 'color-mix(in srgb, var(--cyan-500) 45%, var(--border))' } : undefined}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
            {iv.company || 'Unknown'}
          </div>
          {iv.role && (
            <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 2 }}>{iv.role}</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Badge tone={badgeTone}>{badgeText}</Badge>
          {!upcoming && iv.self_rating != null && (
            <Badge tone={ratingTone(iv.self_rating)}>{`\u2605 ${iv.self_rating}/10`}</Badge>
          )}
        </div>
      </div>

      {meta && (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', marginTop: 6 }}>{meta}</div>
      )}

      {upcoming ? (
        iv.notes && (
          <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.45 }}>
            {iv.notes}
          </div>
        )
      ) : (
        <>
          <BulletSection label="What landed" items={iv.what_landed} />
          {quotes.map((q, i) => (
            <div
              key={i}
              style={{
                borderLeft: '3px solid var(--cyan-500)',
                paddingLeft: 10,
                margin: '8px 0 0',
                color: 'var(--text-soft)',
                fontSize: 'var(--fs-sm)',
                fontStyle: 'italic',
                lineHeight: 1.45,
              }}
            >
              {`\u201c${quoteText(q)}\u201d`}
            </div>
          ))}
          <BulletSection label="Surfaced priorities" items={iv.surfaced_priorities} />
        </>
      )}
    </Panel>
  )
}

function Column({ title, count, children }) {
  return (
    <div>
      <SectionHead title={title} right={`${count}`} />
      <div style={{ display: 'grid', gap: 10 }}>{children}</div>
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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 20 }}>
        <Column title="Upcoming interviews" count={upcoming.length}>
          {upcoming.length > 0
            ? upcoming.map((iv, i) => <InterviewCard key={`up-${i}`} iv={iv} upcoming />)
            : <EmptyState label="No upcoming interviews scheduled." />}
        </Column>

        <Column title="Recent debriefs" count={recent.length}>
          {recent.length > 0
            ? recent.map((iv, i) => <InterviewCard key={`re-${i}`} iv={iv} upcoming={false} />)
            : <EmptyState label="No debriefs logged yet." hint="Use log_interview() from your assistant." />}
        </Column>
      </div>
    </Screen>
  )
}
