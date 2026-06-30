import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, statusTone,
  List, Row, fmtDate,
} from './_shared.jsx'

/* Interviews — upcoming schedule and debrief log.
   Data: GET /dashboard/interviews/data (_interviews_payload). */

function ratingTone(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return 'muted'
  if (v >= 8) return 'green'
  if (v >= 5) return 'accent'
  return 'warn'
}

function Interview({ iv, i, showRating }) {
  const meta = [
    iv.interview_type ? String(iv.interview_type).replace(/_/g, ' ') : '',
    iv.interview_format,
    iv.interviewer ? `with ${iv.interviewer}` : '',
    iv.duration_minutes ? `${iv.duration_minutes} min` : '',
  ].filter(Boolean).join(' \u00b7 ')

  return (
    <Row
      key={`${iv.company}-${i}`}
      title={iv.company || 'Unknown'}
      subtitle={iv.role}
      meta={meta}
      right={
        <div style={{ display: 'grid', gap: 6, justifyItems: 'end' }}>
          {iv.interview_date && <Badge tone="accent">{fmtDate(iv.interview_date)}</Badge>}
          {showRating && iv.self_rating != null && (
            <Badge tone={ratingTone(iv.self_rating)}>{`self ${iv.self_rating}/10`}</Badge>
          )}
        </div>
      }
    >
      {Array.isArray(iv.what_landed) && iv.what_landed.length > 0 && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', lineHeight: 1.5 }}>
          {iv.what_landed.slice(0, 2).map((w, k) => <li key={k}>{w}</li>)}
        </ul>
      )}
    </Row>
  )
}

export default function Interviews() {
  const { data, loading, error } = useApi('/dashboard/interviews/data')
  const upcoming = data?.upcoming || []
  const recent = data?.recent || []

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && (data?.total ?? 0) === 0}
      emptyLabel="No interviews logged yet."
    >
      <StatGrid>
        <Stat label="Total" value={data?.total ?? 0} tone="accent" />
        <Stat label="Upcoming" value={upcoming.length} tone={upcoming.length ? 'green' : 'muted'} />
        <Stat label="Logged" value={recent.length} />
      </StatGrid>

      {upcoming.length > 0 && (
        <>
          <SectionHead title="Upcoming" right={`${upcoming.length}`} />
          <List>
            {upcoming.map((iv, i) => <Interview key={`up-${i}`} iv={iv} i={i} showRating={false} />)}
          </List>
          <div style={{ height: 18 }} />
        </>
      )}

      <SectionHead title="Recent debriefs" right={`${recent.length}`} />
      <List>
        {recent.map((iv, i) => <Interview key={`re-${i}`} iv={iv} i={i} showRating />)}
      </List>
    </Screen>
  )
}
