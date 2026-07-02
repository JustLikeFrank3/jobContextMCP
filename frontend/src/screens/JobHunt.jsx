import { useState } from 'react'
import {
  useApi, Screen, StatGrid, Stat, Badge, statusTone,
  EmptyState, DetailLine, EYEBROW, fmtDate,
} from './_shared.jsx'

/* Job Hunt — every tracked application as a Kanban board.
   Data: GET /dashboard/job-hunt/data (_load_applications).

   Statuses in the data are free-form (dozens of one-off variants), so cards
   are bucketed into five lanes by substring matching. The Outreach lane sits
   first and captures the pre-application stage (networking, referral asks,
   warm intros, "interested" leads) before a formal application exists. Cards
   expand in place to show next steps, contact, notes, and the event count.
   A search filter narrows all lanes at once. */

const LANES = [
  { key: 'outreach', label: 'Outreach', tone: 'var(--cyan-200)' },
  { key: 'active', label: 'Active', tone: 'var(--cyan-400)' },
  { key: 'interview', label: 'Interviewing', tone: 'var(--cyan-300)' },
  { key: 'offer', label: 'Offer', tone: 'var(--green-400)' },
  { key: 'rejected', label: 'Rejected / Passed', tone: 'var(--danger)' },
]

function laneFor(status) {
  const s = (status || '').trim().toLowerCase()
  if (!s) return 'active'
  if (s.includes('offer') || s.includes('onboarding') || s.includes('accept')) return 'offer'
  if (s.includes('reject') || s.includes('pass') || s.includes('declin') || s.includes('no response') || s.includes('ghost')) return 'rejected'
  if (s.includes('interview') || s.includes('screen') || s.includes('onsite') || s.includes('panel')) return 'interview'
  // Pre-application stage: a relationship or lead exists, but nothing submitted yet.
  if (
    s.includes('outreach') || s.includes('interested') || s.includes('considering')
    || s.includes('networking') || s.includes('referral') || s.includes('handoff')
    || s.includes('pre-application') || s.includes('pre-app') || s.includes('pre-vetting')
    || s.includes('not submitted') || s.includes('not_submitted') || s.includes('no application')
    || s.includes('prospect') || s.includes('lead') || s.includes('researching')
    || s.includes('to apply') || s.includes('wishlist') || s.includes('saved')
    || s.includes('materials ready') || s.includes('warm')
  ) return 'outreach'
  return 'active'
}

function KanbanCard({ app }) {
  const [open, setOpen] = useState(false)
  const eventCount = Array.isArray(app.events) ? app.events.length : 0
  const hasBody = app.next_steps || app.contact || app.notes || eventCount > 0

  return (
    <div
      style={{
        background: 'var(--panel)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        onClick={() => hasBody && setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          appearance: 'none', width: '100%', textAlign: 'left',
          background: 'transparent', border: 'none', cursor: hasBody ? 'pointer' : 'default',
          padding: '9px 10px',
        }}
      >
        <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-sm)', lineHeight: 1.3 }}>
          {app.company || 'Unknown'}
        </div>
        {app.role && (
          <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', marginTop: 2, lineHeight: 1.35 }}>
            {app.role}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 7, flexWrap: 'wrap' }}>
          <Badge tone={statusTone(app.status)}>{(app.status || 'unknown').slice(0, 28)}</Badge>
          {eventCount > 0 && (
            <span style={{ color: 'var(--faint)', fontSize: 'var(--fs-2xs)' }}>
              {eventCount} event{eventCount === 1 ? '' : 's'}
            </span>
          )}
        </div>
      </button>

      {open && hasBody && (
        <div style={{ padding: '0 10px 10px', borderTop: '1px solid var(--border-soft)' }}>
          {app.next_steps && <DetailLine label="Next">{app.next_steps}</DetailLine>}
          {app.contact && <DetailLine label="Contact">{app.contact}</DetailLine>}
          {app.notes && <DetailLine label="Notes">{app.notes}</DetailLine>}
          {(app.applied_date || app.last_updated) && (
            <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-2xs)', marginTop: 8 }}>
              {app.applied_date ? `Applied ${fmtDate(app.applied_date)}` : ''}
              {app.applied_date && app.last_updated ? ' \u00b7 ' : ''}
              {app.last_updated ? `Updated ${fmtDate(app.last_updated)}` : ''}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Lane({ lane, apps }) {
  return (
    <div style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 10, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, paddingLeft: 4 }}>
        <span style={{ ...EYEBROW, color: lane.tone }}>{lane.label}</span>
        <span style={{ background: 'var(--surface-chip)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-pill)', padding: '2px 9px', fontSize: 'var(--fs-2xs)', color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
          {apps.length}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 8, alignContent: 'start' }}>
        {apps.length > 0
          ? apps.map((a, i) => <KanbanCard key={`${a.company}-${a.role}-${i}`} app={a} />)
          : <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', padding: '8px 4px' }}>No items</div>}
      </div>
    </div>
  )
}

export default function JobHunt() {
  const { data, loading, error } = useApi('/dashboard/job-hunt/data')
  const [q, setQ] = useState('')
  const apps = data?.applications || []

  const query = q.trim().toLowerCase()
  const shown = query
    ? apps.filter((a) => [a.company, a.role, a.status, a.next_steps, a.contact, a.notes].join(' ').toLowerCase().includes(query))
    : apps

  const buckets = { outreach: [], active: [], interview: [], offer: [], rejected: [] }
  shown.forEach((a) => buckets[laneFor(a.status)].push(a))

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && apps.length === 0}
      emptyLabel="No applications tracked yet."
    >
      <StatGrid>
        <Stat label="Applications" value={data?.total ?? 0} tone="accent" />
        <Stat label="Outreach" value={buckets.outreach.length} />
        <Stat label="Active" value={buckets.active.length} />
        <Stat label="Interviewing" value={buckets.interview.length} tone="accent" />
        <Stat label="Offers" value={buckets.offer.length} tone="green" />
        <Stat label="Rejected" value={buckets.rejected.length} tone="muted" />
      </StatGrid>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter by company, role, status, notes\u2026'}
        style={{
          width: '100%', maxWidth: 440, marginBottom: 16, boxSizing: 'border-box',
          background: 'var(--surface-sunken)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', padding: '9px 11px',
          color: 'var(--text)', fontSize: 'var(--fs-sm)',
        }}
      />

      {shown.length === 0 ? (
        <EmptyState label="No applications match your filter." />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, alignItems: 'start' }}>
          {LANES.map((lane) => (
            <Lane key={lane.key} lane={lane} apps={buckets[lane.key]} />
          ))}
        </div>
      )}

      <div style={{ marginTop: 16, textAlign: 'center' }}>
        <a href="/dashboard/job-hunt" target="_blank" rel="noreferrer" style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>
          Open the classic tracker {'\u2197'}
        </a>
      </div>
    </Screen>
  )
}
