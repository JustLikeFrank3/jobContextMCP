import { useState } from 'react'
import {
  useApi, Screen, StatGrid, Stat, Chips, EmptyState, fmtDate,
} from './_shared.jsx'

/* Outreach — contacts, warm vs cold, and the follow-up queue.
   Data: GET /dashboard/people/data (_people_payload).

   Design-handoff layout: pill filter chips (derived from the real outreach
   statuses in the payload) that filter live, a cyan hint bar (carries the
   follow-up queue summary), and a 2-col contact card grid — colored-initials
   avatar, name/title, mono status chip, then a divider with the contact
   synopsis and a mono last-touch line. */

/* Handoff palette (jobContext Desktop Import.dc.html lines 482-492). */
const AVATAR_BG = ['#6FE0EE', '#9BE0C0', '#E0C98A', '#C7A9E8', '#E8A9B4']

const STATUS_STYLES = [
  [/replied|responded|connected|referred|met|accepted|intro/, ['#6FD3A0', 'rgba(111,211,160,.15)']],
  [/warm|follow|active|scheduled/, ['#6FE0EE', 'rgba(0,181,200,.15)']],
  [/sent|await|pending|reached|outreach|waiting/, ['#E0B77A', 'rgba(224,183,122,.15)']],
]

function statusColors(status) {
  const s = (status || '').toLowerCase()
  for (const [re, colors] of STATUS_STYLES) {
    if (re.test(s)) return colors
  }
  return ['#9BB0D0', 'rgba(255,255,255,.06)']
}

const MONO_EYEBROW = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 'var(--fw-semibold)',
  letterSpacing: '1.2px',
  textTransform: 'uppercase',
  color: '#7C8AA6',
}

function initials(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  return parts.slice(0, 2).map((p) => p[0].toUpperCase()).join('')
}

/* Stable avatar color per contact so it survives filtering/reordering. */
function avatarBg(name) {
  let h = 0
  for (const c of String(name || '')) h = (h * 31 + c.codePointAt(0)) % 997
  return AVATAR_BG[h % AVATAR_BG.length]
}

/* "JUL 12"-style mono date for last-touch lines. */
function monoDate(iso) {
  if (!iso) return ''
  const d = new Date(String(iso).slice(0, 10) + 'T00:00:00')
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10).toUpperCase()
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()
}

function SectionLabel({ label, count, first }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        marginTop: first ? 0 : 22,
        marginBottom: 12,
      }}
    >
      <div style={MONO_EYEBROW}>{label}</div>
      <div style={{ ...MONO_EYEBROW, letterSpacing: 0 }}>{count}</div>
    </div>
  )
}

function PersonCard({ person }) {
  const [fg, bg] = statusColors(person.outreach_status)
  const status = person.outreach_status || 'none'
  const hasBody =
    person.context || person.notes || person.contact_info ||
    (Array.isArray(person.tags) && person.tags.length > 0) || person.last_updated

  return (
    <div
      style={{
        borderRadius: 14,
        padding: '15px 16px',
        background: 'rgba(255,255,255,.04)',
        border: '1px solid rgba(255,255,255,.07)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: '50%',
            background: avatarBg(person.name),
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 'var(--fw-bold)',
            fontSize: 15,
            color: '#04222A',
            flexShrink: 0,
          }}
        >
          {initials(person.name)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 'var(--fw-semibold)', color: '#F0F5FF' }}>
            {person.name || 'Unknown'}
          </div>
          <div style={{ fontSize: 12.5, color: '#8A99B5' }}>
            {[person.relationship, person.company].filter(Boolean).join(' · ')}
          </div>
        </div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            fontWeight: 'var(--fw-semibold)',
            textTransform: 'uppercase',
            color: fg,
            background: bg,
            padding: '4px 8px',
            borderRadius: 8,
            whiteSpace: 'nowrap',
          }}
        >
          {status}
        </div>
      </div>

      {hasBody && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,.06)' }}>
          {person.context && (
            <div style={{ fontSize: 12.5, color: '#B7C6E0', lineHeight: 1.45 }}>{person.context}</div>
          )}
          {person.contact_info && (
            <div style={{ fontSize: 12, color: '#8A99B5', lineHeight: 1.45, marginTop: person.context ? 6 : 0 }}>
              <span style={{ color: '#7C8AA6', fontWeight: 'var(--fw-semibold)' }}>Contact: </span>
              {person.contact_info}
            </div>
          )}
          {person.notes && (
            <div style={{ fontSize: 12, color: '#8A99B5', lineHeight: 1.45, marginTop: 6 }}>
              <span style={{ color: '#7C8AA6', fontWeight: 'var(--fw-semibold)' }}>Notes: </span>
              {person.notes}
            </div>
          )}
          {Array.isArray(person.tags) && person.tags.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Chips items={person.tags} />
            </div>
          )}
          {person.last_updated && (
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                color: '#6B7A96',
                textTransform: 'uppercase',
                marginTop: 8,
              }}
              title={`Last touched ${fmtDate(person.last_updated)}`}
            >
              {`${status} · ${monoDate(person.last_updated)}`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CardGrid({ people, keyPrefix }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
      {people.map((p, i) => <PersonCard key={`${keyPrefix}-${p.name}-${i}`} person={p} />)}
    </div>
  )
}

export default function People() {
  const { data, loading, error } = useApi('/dashboard/people/data')
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const recent = data?.recent || []
  const followUp = data?.follow_up_queue || []
  const byStatus = data?.by_status || []

  /* Filter chips from the real status values present in the payload. */
  const statuses = byStatus.length > 0
    ? byStatus.map((s) => ({ status: s.status, count: s.count }))
    : [...new Set([...recent, ...followUp].map((p) => p.outreach_status).filter(Boolean))]
      .map((status) => ({ status, count: null }))

  const query = q.trim().toLowerCase()
  const match = (p) =>
    (filter === 'all' || (p.outreach_status || 'none') === filter) &&
    (!query ||
      [p.name, p.company, p.relationship, p.outreach_status, p.context, ...(p.tags || [])]
        .join(' ').toLowerCase().includes(query))

  const shownRecent = recent.filter(match)
  const shownFollowUp = followUp.filter(match)
  const filtering = query || filter !== 'all'

  const fuNames = followUp.map((p) => p.name).filter(Boolean)
  const fuHint = fuNames.slice(0, 3).join(', ') + (fuNames.length > 3 ? ` +${fuNames.length - 3} more` : '')

  const chip = (active) => ({
    cursor: 'pointer',
    fontSize: 12.5,
    fontWeight: 'var(--fw-semibold)',
    color: active ? '#04222A' : '#A9B6CE',
    background: active ? '#00B5C8' : 'rgba(255,255,255,.05)',
    padding: '7px 15px',
    borderRadius: 'var(--radius-pill)',
    border: 'none',
    font: 'inherit',
    textTransform: 'capitalize',
    whiteSpace: 'nowrap',
  })

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && (data?.total ?? 0) === 0}
      emptyLabel="No contacts logged yet."
    >
      <StatGrid>
        <Stat label="Contacts" value={data?.total ?? 0} tone="accent" />
        <Stat label="Follow-up queue" value={followUp.length} tone={followUp.length ? 'warn' : 'muted'} />
        <Stat label="Relationships" value={(data?.by_relationship || []).length} />
        <Stat label="Statuses" value={byStatus.length} tone="muted" />
      </StatGrid>

      {statuses.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
          <button type="button" style={chip(filter === 'all')} onClick={() => setFilter('all')}>
            All
          </button>
          {statuses.map(({ status, count }) => (
            <button
              key={status}
              type="button"
              style={chip(filter === status)}
              onClick={() => setFilter(filter === status ? 'all' : status)}
            >
              {String(status).replace(/_/g, ' ')}
              {count != null && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, marginLeft: 6, opacity: 0.75 }}>
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {followUp.length > 0 && (
        <div
          style={{
            borderRadius: 14,
            padding: '13px 16px',
            background: 'rgba(0,181,200,.07)',
            border: '1px solid rgba(0,181,200,.18)',
            fontSize: 13,
            color: '#C9D6EC',
            marginBottom: 14,
          }}
        >
          <span style={{ color: '#6FE0EE', fontWeight: 'var(--fw-semibold)' }}>Follow-up queue: </span>
          {`${fuHint} ${fuNames.length === 1 ? 'needs' : 'need'} a follow-up`}
        </div>
      )}

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter by name, company, relationship, tag…'}
        style={{
          width: '100%', maxWidth: 440, marginBottom: 16, boxSizing: 'border-box',
          background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)',
          borderRadius: 12, padding: '9px 12px',
          color: '#E8EFFB', fontSize: 13,
        }}
      />

      {shownFollowUp.length > 0 && (
        <>
          <SectionLabel label="Follow-up queue" count={shownFollowUp.length} first />
          <CardGrid people={shownFollowUp} keyPrefix="fu" />
        </>
      )}

      <SectionLabel
        label="Recent contacts"
        count={`${shownRecent.length}${filtering ? ` of ${recent.length}` : ''}`}
        first={shownFollowUp.length === 0}
      />
      {shownRecent.length > 0 ? (
        <CardGrid people={shownRecent} keyPrefix="re" />
      ) : (
        <EmptyState label="No contacts match this filter." />
      )}
    </Screen>
  )
}
