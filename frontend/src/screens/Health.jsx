import { Panel } from '../design-system'
import {
  useApi, Screen, SectionHead, StatGrid, Stat,
  EYEBROW, fmtDate,
} from './_shared.jsx'

/* Wellbeing — mood and energy check-ins over time.
   Data: GET /dashboard/health/data (_health_payload).

   Ports the legacy /dashboard/health graphs: a paired mood (blue) + energy
   (teal) trend over the last 30 check-ins, plus per-entry meters. */

const MOOD_COLOR = '#3b82f6'
const ENERGY_COLOR = 'var(--cyan-400)'
const SCALE = 10 // mood/energy are logged 1–10

function toNum(v) {
  const n = Number.parseFloat(v)
  return Number.isFinite(n) ? n : null
}

function energyTone(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return 'muted'
  if (v >= 7) return 'green'
  if (v >= 4) return 'accent'
  return 'warn'
}

/* Twin-bar trend: one slot per check-in, oldest -> newest, mood + energy. */
function TrendChart({ entries }) {
  // entries arrive newest-first; reverse so the chart reads left (old) to right (new).
  const points = [...entries].reverse()
  if (points.length === 0) return null

  return (
    <Panel pad="16px 18px" style={{ marginBottom: 20 }}>
      <div style={{ ...EYEBROW, marginBottom: 12 }}>
        Mood &amp; energy {'\u2014'} last {points.length} check-ins
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 88 }}>
        {points.map((e, i) => {
          const mood = toNum(e.mood)
          const energy = toNum(e.energy)
          const moodH = mood == null ? 0 : (mood / SCALE) * 100
          const energyH = energy == null ? 0 : (energy / SCALE) * 100
          const title = `${fmtDate(e.date) || 'Undated'}\nMood: ${e.mood ?? '\u2014'}  Energy: ${e.energy ?? '\u2014'}`
          return (
            <div
              key={`${e.date}-${i}`}
              title={title}
              style={{ flex: 1, display: 'flex', alignItems: 'flex-end', gap: 2, height: '100%', minWidth: 4 }}
            >
              <div style={{ flex: 1, height: `${moodH}%`, background: MOOD_COLOR, borderRadius: '3px 3px 0 0', minHeight: moodH ? 2 : 0 }} />
              <div style={{ flex: 1, height: `${energyH}%`, background: ENERGY_COLOR, borderRadius: '3px 3px 0 0', minHeight: energyH ? 2 : 0 }} />
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', gap: 18, marginTop: 12 }}>
        <Legend color={MOOD_COLOR} label="Mood" />
        <Legend color={ENERGY_COLOR} label="Energy" />
      </div>
    </Panel>
  )
}

function Legend({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--muted)', fontSize: 'var(--fs-xs)' }}>
      <span style={{ width: 10, height: 10, borderRadius: 3, background: color }} />
      {label}
    </span>
  )
}

function Meter({ label, value, color }) {
  const n = toNum(value)
  const pct = n == null ? 0 : Math.max(0, Math.min(100, (n / SCALE) * 100))
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 50, fontSize: 'var(--fs-xs)', color: 'var(--muted)' }}>{label}</span>
      <div style={{ width: 104, height: 8, background: 'var(--ink-600)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 'var(--radius-pill)' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 'var(--fw-bold)', fontSize: 'var(--fs-sm)', color: 'var(--text-strong)' }}>
        {value ?? '\u2014'}
      </span>
    </div>
  )
}

function CheckinCard({ entry }) {
  return (
    <Panel pad="14px 16px">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
          {entry.date ? fmtDate(entry.date) : 'Undated'}
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {entry.mood != null && entry.mood !== '' && (
            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--muted)' }}>Mood: {entry.mood}</span>
          )}
          {entry.productive != null && (
            <span style={{ fontSize: 'var(--fs-xs)', color: entry.productive ? 'var(--green-300)' : 'var(--muted)' }}>
              {entry.productive ? 'Productive' : 'Rest'}
            </span>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 18, marginTop: 10, flexWrap: 'wrap' }}>
        <Meter label="Mood" value={entry.mood} color={MOOD_COLOR} />
        <Meter label="Energy" value={entry.energy} color={ENERGY_COLOR} />
      </div>
      {entry.notes && (
        <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 10, lineHeight: 1.5 }}>
          {entry.notes}
        </div>
      )}
    </Panel>
  )
}

export default function Health() {
  const { data, loading, error } = useApi('/dashboard/health/data')
  const recent = data?.recent || []

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && (data?.total_entries ?? 0) === 0}
      emptyLabel="No check-ins logged yet."
    >
      <StatGrid>
        <Stat label="Check-ins" value={data?.total_entries ?? 0} tone="accent" />
        <Stat label="Avg mood" value={data?.avg_mood != null ? `${data.avg_mood} / 10` : '\u2014'} tone="green" />
        <Stat label="Avg energy" value={data?.avg_energy != null ? `${data.avg_energy} / 10` : '\u2014'} tone={energyTone(data?.avg_energy)} />
        <Stat label="Recent window" value={recent.length} sub="entries shown" tone="muted" />
      </StatGrid>

      <TrendChart entries={recent} />

      <SectionHead title="Recent check-ins" right={`${recent.length}`} />
      <div style={{ display: 'grid', gap: 10 }}>
        {recent.map((e, i) => (
          <CheckinCard key={`${e.date}-${i}`} entry={e} />
        ))}
      </div>
    </Screen>
  )
}
