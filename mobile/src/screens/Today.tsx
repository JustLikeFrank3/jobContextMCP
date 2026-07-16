// Today — the 30-second glance: pipeline counts, today's move, priorities.
// Reads the same /api/dashboard/home payload the desktop hero uses.
import { useFocusEffect } from '@react-navigation/native'
import { useCallback, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import { colors } from '../theme'

type HomeData = {
  welcomeName: string
  today: { active: number; inflight: number; overdue: number; move: string; priorities: { n: string; text: string }[] }
  oura?: { readiness_score?: number } | null
}

type OuraDay = { date: string; readiness?: number; sleep?: number; hrv?: number; recovery?: number }

function readinessColor(score: number) {
  if (score >= 85) return colors.green
  if (score >= 70) return colors.cyan
  return colors.danger
}

function ReadinessGraph({ days }: { days: OuraDay[] }) {
  const scored = days.filter((d) => (d.readiness ?? 0) > 0)
  if (scored.length < 2) return null
  const max = 100
  const latest = scored[scored.length - 1]
  return (
    <View style={styles.card}>
      <View style={styles.graphHeader}>
        <Text style={styles.eyebrow}>Readiness — last {scored.length} days</Text>
        <Text style={[styles.graphNow, { color: readinessColor(latest.readiness!) }]}>
          {latest.readiness}
        </Text>
      </View>
      <View style={styles.graphRow}>
        {scored.map((d) => (
          <View key={d.date} style={styles.graphCol}>
            <View style={styles.graphTrack}>
              <View
                style={[
                  styles.graphBar,
                  { height: `${(d.readiness! / max) * 100}%`, backgroundColor: readinessColor(d.readiness!) },
                ]}
              />
            </View>
          </View>
        ))}
      </View>
      <View style={styles.graphLabels}>
        <Text style={styles.graphLabel}>{scored[0].date.slice(5)}</Text>
        <Text style={styles.graphLabel}>{latest.date.slice(5)}</Text>
      </View>
    </View>
  )
}

export default function Today() {
  const [data, setData] = useState<HomeData | null>(null)
  const [oura, setOura] = useState<OuraDay[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setRefreshing(true)
    try {
      setData(await api<HomeData>('/api/dashboard/home'))
      setError('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRefreshing(false)
    }
    // Graph is a bonus — older servers don't have the endpoint; stay quiet.
    try {
      const h = await api<{ days: OuraDay[] }>('/api/dashboard/oura/history?days=14')
      setOura(h.days || [])
    } catch {
      setOura([])
    }
  }, [])

  // Refetch on every tab focus — a screen mounted while signed out must not
  // keep its stale "Not signed in" error after the user signs in via Settings.
  useFocusEffect(
    useCallback(() => {
      load()
    }, [load]),
  )

  return (
    <ScrollView
      style={styles.root}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.cyan} />}
    >
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.statsRow}>
        <Stat label="Active" value={data?.today.active} />
        <Stat label="In-flight" value={data?.today.inflight} />
        <Stat label="Overdue" value={data?.today.overdue} tone={data?.today.overdue ? 'warn' : undefined} />
        {data?.oura?.readiness_score ? <Stat label="Readiness" value={data.oura.readiness_score} tone="good" /> : null}
      </View>
      <ReadinessGraph days={oura} />
      <View style={styles.card}>
        <Text style={styles.eyebrow}>Today's move</Text>
        <Text style={styles.move}>{data?.today.move || '—'}</Text>
      </View>
      {(data?.today.priorities?.length ?? 0) > 0 && (
        <View style={styles.card}>
          <Text style={styles.eyebrow}>Priorities</Text>
          {data!.today.priorities.map((p) => (
            <Text key={p.n} style={styles.priority}>
              {p.n}. {p.text}
            </Text>
          ))}
        </View>
      )}
    </ScrollView>
  )
}

function Stat({ label, value, tone }: { label: string; value?: number; tone?: 'warn' | 'good' }) {
  const color = tone === 'warn' ? colors.danger : tone === 'good' ? colors.green : colors.cyan
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color }]}>{value ?? '–'}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg, padding: 12 },
  statsRow: { flexDirection: 'row', gap: 10 },
  stat: {
    flex: 1, backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, paddingVertical: 14, alignItems: 'center',
  },
  statValue: { fontSize: 24, fontWeight: '700' },
  statLabel: { color: colors.muted, fontSize: 11, marginTop: 4, textTransform: 'uppercase', letterSpacing: 1 },
  card: {
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 14, marginTop: 12,
  },
  eyebrow: { color: colors.cyanSoft, fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
  move: { color: colors.text, fontSize: 15, lineHeight: 22 },
  priority: { color: colors.text, fontSize: 14, lineHeight: 24 },
  error: { color: colors.danger, paddingBottom: 8, textAlign: 'center' },
  graphHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  graphNow: { fontSize: 20, fontWeight: '700' },
  graphRow: { flexDirection: 'row', gap: 3, marginTop: 4 },
  graphCol: { flex: 1 },
  graphTrack: { height: 72, justifyContent: 'flex-end', backgroundColor: colors.surfaceRaised, borderRadius: 3, overflow: 'hidden' },
  graphBar: { borderRadius: 3 },
  graphLabels: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  graphLabel: { color: colors.faint, fontSize: 10 },
})
