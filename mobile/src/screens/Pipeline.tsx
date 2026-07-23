// Pipeline — design layout: segmented chips + application cards (initial
// tile, company, role, right-aligned fit score, stage chip, next step).
// Data: GET /dashboard/pipeline/data. The server's status vocabulary
// (pending | evaluated | added | applied | dismissed) maps onto the design's
// stage-chip palette in ui/tokens.stageStyle. The "All" view groups cards
// by stage so the list reads as a funnel, and every card pushes JobDetail.
// Deep work (resumes, letters) stays on the desktop by design.
import { useNavigation } from '@react-navigation/native'
import { useCallback, useMemo, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import { Job } from '../lib/store'
import { PressableScale } from '../ui/detail'
import {
  Card,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  ScreenTitle,
  SectionLabel,
  StatusChip,
} from '../ui/primitives'
import { fonts, stageStyle, t } from '../ui/tokens'
import { useDashData } from '../ui/useDashData'

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

// Funnel order for the grouped "All" view — most actionable stages first.
const STAGE_ORDER = ['applied', 'added', 'evaluated', 'pending', 'dismissed']
const STAGE_HEADING: Record<string, string> = {
  applied: 'Applied',
  added: 'Ready to apply',
  evaluated: 'Assessed',
  pending: 'Awaiting assessment',
  dismissed: 'Dismissed',
}

function JobCard({ job, onPress }: { job: Job; onPress: () => void }) {
  const stage = stageStyle[job.status || 'pending'] || stageStyle.pending
  const score = Number(job.fitment_score) || 0
  return (
    <PressableScale onPress={onPress}>
      <Card style={{ marginTop: 10 }}>
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
    </PressableScale>
  )
}

export default function Pipeline() {
  const nav = useNavigation<any>()
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

  // Grouped "All" view: sections in funnel order, so the flat stack of
  // equally-weighted cards reads as stages of one process.
  const groups = useMemo(() => {
    if (filter !== 'all') return null
    return STAGE_ORDER.map((key) => ({
      key,
      heading: STAGE_HEADING[key],
      jobs: shown.filter((j) => (j.status || 'pending') === key),
    })).filter((g) => g.jobs.length > 0)
  }, [shown, filter])

  const activeCount = jobs?.filter((j) => j.status !== 'dismissed').length ?? 0
  const appliedCount = jobs?.filter((j) => j.status === 'applied').length ?? 0
  const open = (job: Job) => nav.navigate('JobDetail', { job })

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
          message={filter === 'all' ? 'Your pipeline is clear.' : 'Nothing in this stage right now.'}
          suggestions={
            filter === 'all'
              ? ['Share a job posting from any app to capture it', 'Browse roles your contacts posted about']
              : undefined
          }
          actionLabel={filter === 'all' ? 'See who could refer you' : undefined}
          onAction={filter === 'all' ? () => nav.navigate('People') : undefined}
        />
      ) : null}

      <View style={{ marginTop: 6 }}>
        {groups
          ? groups.map((g) => (
              <View key={g.key}>
                <SectionLabel>{g.heading}</SectionLabel>
                {g.jobs.map((job) => (
                  <JobCard key={job.id} job={job} onPress={() => open(job)} />
                ))}
              </View>
            ))
          : shown.map((job) => <JobCard key={job.id} job={job} onPress={() => open(job)} />)}
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
