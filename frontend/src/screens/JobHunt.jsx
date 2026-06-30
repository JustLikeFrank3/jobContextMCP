import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, statusTone,
  Bars, List, Row, fmtDate,
} from './_shared.jsx'
import { Panel } from '../design-system'

/* Job Hunt — every tracked application and its current stage.
   Data: GET /dashboard/job-hunt/data (_load_applications). */
export default function JobHunt() {
  const { data, loading, error } = useApi('/dashboard/job-hunt/data')
  const apps = data?.applications || []
  const byStatus = data?.by_status || []
  const top = byStatus[0]

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && apps.length === 0}
      emptyLabel="No applications tracked yet."
    >
      <StatGrid>
        <Stat label="Applications" value={data?.total ?? 0} tone="accent" />
        <Stat label="Stages" value={byStatus.length} />
        {top && <Stat label="Most common" value={top.count} sub={String(top.status).replace(/_/g, ' ')} />}
        <Stat label="Updated" value={(data?.last_updated || '').slice(0, 10) || '\u2014'} tone="muted" />
      </StatGrid>

      {byStatus.length > 0 && (
        <Panel style={{ marginBottom: 20 }}>
          <SectionHead title="By status" />
          <Bars items={byStatus} labelKey="status" tone="accent" />
        </Panel>
      )}

      <SectionHead title="Applications" right={`${apps.length}`} />
      <List>
        {apps.map((a, i) => (
          <Row
            key={`${a.company}-${a.role}-${i}`}
            title={a.company || 'Unknown'}
            subtitle={a.role}
            meta={[
              a.contact ? `Contact: ${a.contact}` : '',
              a.applied_date ? `Applied ${fmtDate(a.applied_date)}` : '',
              Array.isArray(a.events) && a.events.length ? `${a.events.length} event${a.events.length === 1 ? '' : 's'}` : '',
            ].filter(Boolean).join(' \u00b7 ')}
            right={<Badge tone={statusTone(a.status)}>{a.status || 'unknown'}</Badge>}
          >
            {a.next_steps && (
              <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.45 }}>
                <span style={{ color: 'var(--muted)' }}>Next: </span>{a.next_steps}
              </div>
            )}
          </Row>
        ))}
      </List>

      <Panel pad="12px 14px" style={{ marginTop: 16, textAlign: 'center' }}>
        <a href="/dashboard/job-hunt" style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>
          Open the Kanban board {'\u2192'}
        </a>
      </Panel>
    </Screen>
  )
}
