// Global timeline — one chronological feed of the whole search: sync
// journal events, interviews, applications, posts, and check-ins, with
// type filters. Every row navigates to its detail page.
import { useNavigation } from '@react-navigation/native'
import { useMemo, useState } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'
import { Datasets } from '../lib/store'
import { PressableScale } from '../ui/detail'
import { Chip, EmptyState, ErrorState, LoadingState } from '../ui/primitives'
import { fonts, t } from '../ui/tokens'
import { useDatasets } from '../ui/useDatasets'

type Item = {
  key: string
  ts: string // ISO-ish, used for ordering + display
  kind: 'activity' | 'job' | 'interview' | 'post' | 'checkin'
  icon: string
  title: string
  sub?: string
  go?: (nav: any) => void
}

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'job', label: 'Jobs' },
  { key: 'interview', label: 'Interviews' },
  { key: 'post', label: 'Posts' },
  { key: 'checkin', label: 'Wellbeing' },
  { key: 'activity', label: 'Activity' },
] as const
type FilterKey = (typeof FILTERS)[number]['key']

function buildItems(ds: Datasets): Item[] {
  const items: Item[] = []
  ds.events.forEach((e) =>
    items.push({
      key: `ev${e.id}`,
      ts: e.ts || '',
      kind: 'activity',
      icon: '·',
      title: e.title,
      sub: e.subtitle,
      go: e.company ? (nav) => nav.push('CompanyDetail', { name: e.company }) : undefined,
    }),
  )
  ds.jobs.forEach((j) => {
    if (!j.added_date) return
    items.push({
      key: `job${j.id}`,
      ts: j.added_date,
      kind: 'job',
      icon: '▸',
      title: `Captured ${j.role} at ${j.company}`,
      sub: j.status,
      go: (nav) => nav.push('JobDetail', { job: j }),
    })
  })
  ds.interviews.forEach((iv, i) => {
    if (!iv.interview_date) return
    items.push({
      key: `iv${iv.id ?? i}`,
      ts: iv.interview_date,
      kind: 'interview',
      icon: '◆',
      title: `${(iv.interview_type || 'Interview').replace(/_/g, ' ')} · ${iv.company}`,
      sub: iv.upcoming ? 'upcoming' : 'debriefed',
      go: (nav) => nav.push('InterviewDetail', { interview: iv }),
    })
  })
  ds.posts.forEach((p) => {
    if (!p.posted_date) return
    items.push({
      key: `post${p.id}`,
      ts: p.posted_date,
      kind: 'post',
      icon: '◎',
      title: p.title || p.text.slice(0, 60),
      sub: 'LinkedIn post',
      go: (nav) => nav.push('PostDetail', { post: p }),
    })
  })
  ds.checkins.forEach((c, i) =>
    items.push({
      key: `ci${c.date}${i}`,
      ts: c.date,
      kind: 'checkin',
      icon: '♥',
      title: `Check-in · ${c.mood || '—'}`,
      sub: typeof c.energy === 'number' ? `energy ${c.energy}/10` : undefined,
      go: (nav) => nav.push('CheckinDetail', { entry: c }),
    }),
  )
  return items.filter((i) => i.ts).sort((a, b) => b.ts.localeCompare(a.ts))
}

const KIND_COLOR: Record<Item['kind'], string> = {
  activity: t.muted,
  job: t.cyanBright,
  interview: t.amber,
  post: t.green,
  checkin: '#C7A9E8',
}

// Rendered under a native stack header, so no manual safe-area inset.
export default function Timeline() {
  const nav = useNavigation<any>()
  const [filter, setFilter] = useState<FilterKey>('all')
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  const items = useMemo(() => (ds ? buildItems(ds) : []), [ds])
  const shown = useMemo(
    () => (filter === 'all' ? items : items.filter((i) => i.kind === filter)).slice(0, 120),
    [items, filter],
  )

  // Month headers ("JULY 2026") between groups.
  const withHeaders = useMemo(() => {
    const out: (Item | { header: string; key: string })[] = []
    let last = ''
    for (const it of shown) {
      const m = it.ts.slice(0, 7)
      if (m !== last) {
        last = m
        const [y, mo] = m.split('-')
        const months = ['JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE','JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER']
        out.push({ header: `${months[Number(mo) - 1] || m} ${y}`, key: `h${m}` })
      }
      out.push(it)
    }
    return out
  }, [shown])

  return (
    <View style={styles.root}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingHorizontal: 18, paddingBottom: 28, paddingTop: 10 }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.chipRow}>
          {FILTERS.map((f) => (
            <Chip key={f.key} label={f.label} active={filter === f.key} onPress={() => setFilter(f.key)} />
          ))}
        </View>

        {loading && !ds ? <LoadingState /> : null}
        {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}
        {ds && !shown.length ? (
          <EmptyState
            message="Nothing here yet."
            suggestions={['Share a job posting to start the pipeline', 'Log a check-in from Wellbeing']}
            actionLabel="Go to Wellbeing"
            onAction={() => nav.navigate('Tabs', { screen: 'Wellbeing' })}
          />
        ) : null}

        {withHeaders.map((row) =>
          'header' in row ? (
            <Text key={row.key} style={styles.monthHeader}>
              {row.header}
            </Text>
          ) : (
            <PressableScale
              key={row.key}
              onPress={row.go ? () => row.go!(nav) : undefined}
              disabled={!row.go}
              style={styles.row}
            >
              <Text style={[styles.icon, { color: KIND_COLOR[row.kind] }]}>{row.icon}</Text>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.title} numberOfLines={1}>
                  {row.title}
                </Text>
                {row.sub ? (
                  <Text style={styles.sub} numberOfLines={1}>
                    {row.sub}
                  </Text>
                ) : null}
              </View>
              <Text style={styles.ts}>{row.ts.slice(5, 10)}</Text>
              {row.go ? <Text style={styles.arrow}>›</Text> : null}
            </PressableScale>
          ),
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: t.bg },
  chipRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  monthHeader: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1.4,
    color: t.muted2,
    fontFamily: fonts.mono,
    marginTop: 20,
    marginBottom: 2,
  },
  row: {
    marginTop: 8,
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 14,
    backgroundColor: t.card,
    borderWidth: 1,
    borderColor: t.cardBorder,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
  },
  icon: { fontSize: 14, width: 16, textAlign: 'center' },
  title: { fontSize: 13.5, fontWeight: '600', color: t.textBright },
  sub: { fontSize: 11.5, color: t.muted, marginTop: 1, textTransform: 'capitalize' },
  ts: { fontSize: 10.5, color: t.faint, fontFamily: fonts.mono },
  arrow: { fontSize: 15, color: t.muted2 },
})
