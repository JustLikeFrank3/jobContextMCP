// Pipeline — design layout: segmented chips + application cards (initial
// tile, company, role, right-aligned fit score, stage chip, next step).
// Data: GET /dashboard/pipeline/data. The server's status vocabulary
// (pending | evaluated | added | applied | dismissed) maps onto the design's
// stage-chip palette in ui/tokens.stageStyle. Deep work (resumes, letters)
// stays on the desktop by design.
import { useCallback, useMemo, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import {
  Card,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  ScreenTitle,
  StatusChip,
} from '../ui/primitives'
import { fonts, stageStyle, t } from '../ui/tokens'
import { useDashData } from '../ui/useDashData'

type Job = {
  id: number
  company: string
  role: string
  status?: string
  fitment_score?: string | number | null
  assessed?: boolean
  assessment_summary?: string
  decision_notes?: string
  added_date?: string
}

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'applied', label: 'Applied' },
] as const
type FilterKey = (typeof FILTERS)[number]['key']

function scoreColor(score: number): string {
  if (score >= 85) return t.cyanBright
  if (score >= 78) return '#E0EAF7'
  return '#9BB0D0'
}

function nextStep(j: Job): string {
  if (j.status === 'applied') return 'Applied — awaiting reply'
  if (j.status === 'added') return 'Ready to apply'
  if (j.status === 'evaluated') return j.assessment_summary || 'Assessed — decide next'
  if (j.status === 'dismissed') return j.decision_notes || 'Dismissed'
  return 'Awaiting assessment'
}

export default function Pipeline() {
  const [filter, setFilter] = useState<FilterKey>('all')
  const load = useCallback(
    () => api<{ jobs: Job[] }>('/dashboard/pipeline/data').then((d) => [...(d.jobs || [])].sort((a, b) => b.id - a.id)),
    [],
  )
  const { data: jobs, loading, refreshing, error, refresh } = useDashData(load)

  const shown = useMemo(() => {
    if (!jobs) return []
    if (filter === 'active') return jobs.filter((j) => !['dismissed', 'applied'].includes(j.status || ''))
    if (filter === 'applied') return jobs.filter((j) => j.status === 'applied')
    return jobs
  }, [jobs, filter])

  const activeCount = jobs?.filter((j) => j.status !== 'dismissed').length ?? 0
  const appliedCount = jobs?.filter((j) => j.status === 'applied').length ?? 0

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <ScreenTitle sub={jobs ? `${activeCount} active · ${appliedCount} applied` : undefined}>
        Pipeline
      </ScreenTitle>

      <View style={styles.chipRow}>
        {FILTERS.map((f) => (
          <Chip key={f.key} label={f.label} active={filter === f.key} onPress={() => setFilter(f.key)} />
        ))}
      </View>

      {loading && !jobs ? <LoadingState /> : null}
      {error && !jobs ? <ErrorState message={error} onRetry={refresh} /> : null}
      {jobs && shown.length === 0 ? (
        <EmptyState
          message={
            filter === 'all'
              ? 'Queue is empty — share a job posting to jobContext to start one.'
              : 'Nothing in this stage right now.'
          }
        />
      ) : null}

      <View style={{ marginTop: 6 }}>
        {shown.map((job) => {
          const stage = stageStyle[job.status || 'pending'] || stageStyle.pending
          const score = Number(job.fitment_score) || 0
          return (
            <Card key={job.id} style={{ marginTop: 10 }}>
              <View style={styles.topRow}>
                <View style={styles.initialTile}>
                  <Text style={styles.initialText}>{(job.company || '?')[0].toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.company} numberOfLines={1}>
                    {job.company}
                  </Text>
                  <Text style={styles.role} numberOfLines={1}>
                    {job.role}
                  </Text>
                </View>
                {score > 0 ? (
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={[styles.score, { color: scoreColor(score) }]}>{score}</Text>
                    <Text style={styles.fitLabel}>FIT</Text>
                  </View>
                ) : (
                  <Text style={styles.unscored}>unscored</Text>
                )}
              </View>
              <View style={styles.bottomRow}>
                <StatusChip label={stage.label} color={stage.color} bg={stage.bg} />
                <Text style={styles.next} numberOfLines={1}>
                  {nextStep(job)}
                </Text>
              </View>
            </Card>
          )
        })}
      </View>
    </Screen>
  )
}

const styles = StyleSheet.create({
  chipRow: { flexDirection: 'row', gap: 8, marginTop: 16 },
  topRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  initialTile: {
    width: 38,
    height: 38,
    borderRadius: 11,
    backgroundColor: 'rgba(255,255,255,.06)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  initialText: { fontWeight: '700', color: t.textBody },
  company: { fontSize: 15.5, fontWeight: '600', color: t.text },
  role: { fontSize: 12.5, color: t.muted },
  score: { fontSize: 17, fontWeight: '700' },
  fitLabel: { fontSize: 9.5, color: t.faint, fontFamily: fonts.mono },
  unscored: { fontSize: 12, color: t.faint },
  bottomRow: { marginTop: 11, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  next: { fontSize: 12, color: t.textSecondary, flexShrink: 1 },
})
