import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge,
  List, Row, fmtDate,
} from './_shared.jsx'

/* Wellbeing — mood and energy check-ins over time.
   Data: GET /dashboard/health/data (_health_payload). */

function energyTone(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return 'muted'
  if (v >= 7) return 'green'
  if (v >= 4) return 'accent'
  return 'warn'
}

export default function Health() {
  const { data, loading, error } = useApi('/dashboard/health/data')
  const recent = data?.recent || []

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && (data?.total_entries ?? 0) === 0}
      emptyLabel="No check-ins logged yet."
    >
      <StatGrid>
        <Stat label="Check-ins" value={data?.total_entries ?? 0} tone="accent" />
        <Stat label="Avg mood" value={data?.avg_mood ?? '\u2014'} tone="green" />
        <Stat label="Avg energy" value={data?.avg_energy ?? '\u2014'} tone={energyTone(data?.avg_energy)} />
        <Stat label="Recent window" value={recent.length} sub="entries shown" tone="muted" />
      </StatGrid>

      <SectionHead title="Recent check-ins" right={`${recent.length}`} />
      <List>
        {recent.map((e, i) => (
          <Row
            key={`${e.date}-${i}`}
            title={e.date ? fmtDate(e.date) : 'Undated'}
            subtitle={e.mood ? `Mood: ${e.mood}` : ''}
            right={
              <div style={{ display: 'grid', gap: 6, justifyItems: 'end' }}>
                {e.energy != null && <Badge tone={energyTone(e.energy)}>{`energy ${e.energy}`}</Badge>}
                {e.productive != null && (
                  <Badge tone={e.productive ? 'green' : 'muted'}>{e.productive ? 'productive' : 'rest'}</Badge>
                )}
              </div>
            }
          >
            {e.notes && (
              <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.45 }}>
                {e.notes}
              </div>
            )}
          </Row>
        ))}
      </List>
    </Screen>
  )
}
