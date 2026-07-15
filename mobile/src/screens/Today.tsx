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

export default function Today() {
  const [data, setData] = useState<HomeData | null>(null)
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
})
