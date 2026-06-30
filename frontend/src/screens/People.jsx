import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, statusTone,
  Bars, List, Row, fmtDate,
} from './_shared.jsx'
import { Panel } from '../design-system'

/* Outreach — contacts, warm vs cold, and the follow-up queue.
   Data: GET /dashboard/people/data (_people_payload). */

function Person({ p, i }) {
  return (
    <Row
      key={`${p.name}-${i}`}
      title={p.name || 'Unknown'}
      subtitle={[p.relationship, p.company].filter(Boolean).join(' \u00b7 ')}
      meta={[
        Array.isArray(p.tags) && p.tags.length ? p.tags.join(', ') : '',
        p.last_contacted ? `Last contacted ${fmtDate(p.last_contacted)}` : '',
      ].filter(Boolean).join(' \u00b7 ')}
      right={<Badge tone={statusTone(p.outreach_status)}>{p.outreach_status || 'none'}</Badge>}
    >
      {p.context && (
        <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.45 }}>
          {p.context}
        </div>
      )}
    </Row>
  )
}

export default function People() {
  const { data, loading, error } = useApi('/dashboard/people/data')
  const recent = data?.recent || []
  const followUp = data?.follow_up_queue || []
  const byStatus = data?.by_status || []

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && (data?.total ?? 0) === 0}
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

      {followUp.length > 0 && (
        <>
          <SectionHead title="Follow-up queue" right={`${followUp.length}`} />
          <List>
            {followUp.map((p, i) => <Person key={`fu-${p.name}-${i}`} p={p} i={i} />)}
          </List>
          <div style={{ height: 18 }} />
        </>
      )}

      <SectionHead title="Recent contacts" right={`${recent.length}`} />
      <List>
        {recent.map((p, i) => <Person key={`re-${p.name}-${i}`} p={p} i={i} />)}
      </List>
    </Screen>
  )
}
