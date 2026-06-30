import { useState } from 'react'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, statusTone,
  Bars, ExpandableCard, Chips, DetailLine, fmtDate,
} from './_shared.jsx'
import { Panel } from '../design-system'

/* Outreach — contacts, warm vs cold, and the follow-up queue.
   Data: GET /dashboard/people/data (_people_payload).

   Each contact is an expandable card matching the Posts pattern: collapsed
   shows name + relationship/company + outreach status; expanded reveals the
   context blurb, tags, contact info, notes, and last-touched date. */

function PersonCard({ person }) {
  const hasBody =
    person.context || person.notes || person.contact_info ||
    (Array.isArray(person.tags) && person.tags.length > 0) || person.last_updated

  return (
    <ExpandableCard
      title={person.name || 'Unknown'}
      subtitle={[person.relationship, person.company].filter(Boolean).join(' \u00b7 ')}
      right={<Badge tone={statusTone(person.outreach_status)}>{person.outreach_status || 'none'}</Badge>}
    >
      {hasBody && (
        <>
          {person.context && <DetailLine label="Context">{person.context}</DetailLine>}
          {person.contact_info && <DetailLine label="Contact">{person.contact_info}</DetailLine>}
          {person.notes && <DetailLine label="Notes">{person.notes}</DetailLine>}
          {Array.isArray(person.tags) && person.tags.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Chips items={person.tags} />
            </div>
          )}
          {person.last_updated && (
            <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', marginTop: 10 }}>
              Last touched {fmtDate(person.last_updated)}
            </div>
          )}
        </>
      )}
    </ExpandableCard>
  )
}

export default function People() {
  const { data, loading, error } = useApi('/dashboard/people/data')
  const [q, setQ] = useState('')
  const recent = data?.recent || []
  const followUp = data?.follow_up_queue || []
  const byStatus = data?.by_status || []

  const query = q.trim().toLowerCase()
  const match = (p) =>
    !query ||
    [p.name, p.company, p.relationship, p.outreach_status, p.context, ...(p.tags || [])]
      .join(' ').toLowerCase().includes(query)

  const shownRecent = recent.filter(match)
  const shownFollowUp = followUp.filter(match)

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

      {byStatus.length > 0 && (
        <Panel style={{ marginBottom: 20 }}>
          <SectionHead title="By outreach status" />
          <Bars items={byStatus} labelKey="status" tone="accent" />
        </Panel>
      )}

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter by name, company, relationship, tag\u2026'}
        style={{
          width: '100%', maxWidth: 440, marginBottom: 16, boxSizing: 'border-box',
          background: 'var(--surface-sunken)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', padding: '9px 11px',
          color: 'var(--text)', fontSize: 'var(--fs-sm)',
        }}
      />

      {shownFollowUp.length > 0 && (
        <>
          <SectionHead title="Follow-up queue" right={`${shownFollowUp.length}`} />
          <div style={{ display: 'grid', gap: 8, marginBottom: 20 }}>
            {shownFollowUp.map((p, i) => <PersonCard key={`fu-${p.name}-${i}`} person={p} />)}
          </div>
        </>
      )}

      <SectionHead title="Recent contacts" right={`${shownRecent.length}${query ? ` of ${recent.length}` : ''}`} />
      <div style={{ display: 'grid', gap: 8 }}>
        {shownRecent.map((p, i) => <PersonCard key={`re-${p.name}-${i}`} person={p} />)}
      </div>
    </Screen>
  )
}
