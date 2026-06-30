import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, Bars,
  List, Row, fmtDate,
} from './_shared.jsx'
import { Panel } from '../design-system'

/* Rejections — funnel analysis: where applications die and which companies.
   Data: GET /dashboard/rejections/data (_rejections_payload). */
export default function Rejections() {
  const { data, loading, error } = useApi('/dashboard/rejections/data')
  const recent = data?.recent || []
  const byStage = data?.by_stage || []
  const byCompany = data?.by_company || []
  const topStage = byStage[0]

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && (data?.total ?? 0) === 0}
      emptyLabel="No rejections logged. Keep going."
    >
      <StatGrid>
        <Stat label="Total" value={data?.total ?? 0} tone="danger" />
        <Stat label="Stages hit" value={byStage.length} />
        {topStage && (
          <Stat label="Most common stage" value={topStage.count} sub={String(topStage.stage).replace(/_/g, ' ')} tone="warn" />
        )}
        <Stat label="Companies" value={byCompany.length} tone="muted" />
      </StatGrid>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14, marginBottom: 20 }}>
        {byStage.length > 0 && (
          <Panel>
            <SectionHead title="By stage" />
            <Bars items={byStage} labelKey="stage" tone="danger" />
          </Panel>
        )}
        {byCompany.length > 0 && (
          <Panel>
            <SectionHead title="By company" />
            <Bars items={byCompany} labelKey="company" tone="muted" />
          </Panel>
        )}
      </div>

      <SectionHead title="Recent" right={`${recent.length}`} />
      <List>
        {recent.map((r, i) => (
          <Row
            key={`${r.company}-${i}`}
            title={r.company || 'Unknown'}
            subtitle={r.role}
            meta={r.date ? fmtDate(r.date) : ''}
            right={<Badge tone="danger">{String(r.stage || 'unknown').replace(/_/g, ' ')}</Badge>}
          >
            {r.reason && (
              <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.45 }}>
                {r.reason}
              </div>
            )}
          </Row>
        ))}
      </List>
    </Screen>
  )
}
