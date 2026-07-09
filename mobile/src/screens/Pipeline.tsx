// Pipeline glance — the queue at phone altitude: score, status, summary.
// Deep work (resumes, letters) stays on the desktop by design.
import { useCallback, useEffect, useState } from 'react'
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import { colors } from '../theme'

type Job = {
  id: number
  company: string
  role: string
  fitment_score?: string | number | null
  assessed?: boolean
  assessment_summary?: string
  added_date?: string
}

export default function Pipeline() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setRefreshing(true)
    try {
      const data = await api<{ jobs: Job[] }>('/dashboard/pipeline/data')
      setJobs([...(data.jobs || [])].sort((a, b) => b.id - a.id))
      setError('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <View style={styles.root}>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <FlatList
        data={jobs}
        keyExtractor={(j) => String(j.id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.cyan} />}
        ListEmptyComponent={!refreshing ? <Text style={styles.empty}>Queue is empty — share a job posting to jobContext to start one.</Text> : null}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.company} numberOfLines={1}>{item.company}</Text>
              {item.fitment_score ? (
                <Text style={styles.score}>{String(item.fitment_score)}</Text>
              ) : (
                <Text style={styles.pending}>unscored</Text>
              )}
            </View>
            <Text style={styles.role} numberOfLines={1}>{item.role}</Text>
            {item.assessment_summary ? (
              <Text style={styles.summary} numberOfLines={2}>{item.assessment_summary}</Text>
            ) : null}
          </View>
        )}
      />
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  card: {
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 14, marginHorizontal: 12, marginTop: 10,
  },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  company: { color: colors.text, fontWeight: '700', fontSize: 15, flex: 1 },
  score: { color: colors.green, fontWeight: '700', fontSize: 14 },
  pending: { color: colors.faint, fontSize: 12 },
  role: { color: colors.muted, fontSize: 13, marginTop: 2 },
  summary: { color: colors.faint, fontSize: 12, marginTop: 8, lineHeight: 17 },
  empty: { color: colors.muted, textAlign: 'center', marginTop: 60, paddingHorizontal: 40, lineHeight: 20 },
  error: { color: colors.danger, padding: 12, textAlign: 'center' },
})
