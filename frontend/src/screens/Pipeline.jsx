import { Panel } from '../design-system'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, statusTone,
  List, Row, fmtDate,
} from './_shared.jsx'

/* Pipeline — the share-sheet intake queue: jobs to assess, decide, and apply.
   Data: GET /dashboard/pipeline/data (_pipeline_payload). */
export default function Pipeline() {
  const { data, loading, error } = useApi('/dashboard/pipeline/data')
  const jobs = data?.jobs || []

  const count = (pred) => jobs.filter(pred).length
  const evaluated = count((j) => j.status === 'evaluated')
  const applied = count((j) => j.status === 'applied')
  const dismissed = count((j) => j.status === 'dismissed')

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && jobs.length === 0}
      emptyLabel="No jobs in the queue."
    >
      <StatGrid>
        <Stat label="In queue" value={data?.total ?? 0} tone="accent" />
        <Stat label="Evaluated" value={evaluated} />
        <Stat label="Applied" value={applied} tone="green" />
        <Stat label="Dismissed" value={dismissed} tone="muted" />
      </StatGrid>

      <SectionHead title="Queue" right={`${jobs.length} job${jobs.length === 1 ? '' : 's'}`} />
      <List>
        {jobs.map((j) => (
          <Row
            key={j.id}
            title={j.company || 'Unknown company'}
            subtitle={j.role}
            meta={[j.source, j.added_date ? fmtDate(j.added_date) : '']
              .filter(Boolean)
              .join(' \u00b7 ')}
            right={
              <div style={{ display: 'grid', gap: 6, justifyItems: 'end' }}>
                <Badge tone={statusTone(j.status)}>{j.status || 'pending'}</Badge>
                {j.fitment_score && (
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-sm)', color: 'var(--cyan-300)' }}>
                    {j.fitment_score}
                  </span>
                )}
              </div>
            }
          >
            {j.assessment_summary && (
              <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.45 }}>
                {j.assessment_summary}
              </div>
            )}
            {j.decision_notes && (
              <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', marginTop: 6, fontStyle: 'italic' }}>
                {j.decision_notes}
              </div>
            )}
          </Row>
        ))}
      </List>

      <Panel pad="12px 14px" style={{ marginTop: 16, textAlign: 'center' }}>
        <a href="/dashboard/pipeline" style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>
          Open the full pipeline workspace (assess, generate, apply) {'\u2192'}
        </a>
      </Panel>
    </Screen>
  )
}
