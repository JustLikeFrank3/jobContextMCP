// Interviews — design layout: "Upcoming" cards (company · role, countdown
// chip, type/time line, debrief status) + "Recent debriefs" rows.
// Data: GET /dashboard/interviews/data → { total, upcoming[], recent[] }.
// The design's "Prep doc ready" slot has no per-interview field in the
// payload, so upcoming cards show a debrief-pending dot instead; recent rows
// surface the debrief signal that does exist (self_rating / what_landed /
// verbatim_quotes).
import { useNavigation } from '@react-navigation/native'
import { useCallback } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import { PressableScale } from '../ui/detail'
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  ScreenTitle,
  SectionLabel,
} from '../ui/primitives'
import { fonts, t } from '../ui/tokens'
import { countdownChip, interviewTimeLine } from '../ui/format'
import { useDashData } from '../ui/useDashData'

type Quote = string | { speaker?: string; quote?: string }
type Interview = {
  id?: number
  company?: string
  role?: string
  interview_date?: string
  interview_type?: string
  interviewer?: string
  interviewer_role?: string
  self_rating?: number | null
  what_landed?: string[]
  what_didnt?: string[]
  verbatim_quotes?: Quote[]
}

type Payload = { total: number; upcoming: Interview[]; recent: Interview[] }

function monoDate(dateStr?: string): string {
  const m = String(dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return ''
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return `${months[Number(m[2]) - 1]} ${Number(m[3])}`
}

function debriefLine(iv: Interview): string {
  const q = iv.verbatim_quotes?.[0]
  const quote = typeof q === 'string' ? q : q?.quote
  if (quote) return `“${quote}”`
  if (iv.what_landed?.[0]) return iv.what_landed[0]
  if (iv.self_rating != null) return `Self-rating ${iv.self_rating}/10`
  if (iv.what_didnt?.[0]) return iv.what_didnt[0]
  return (iv.interview_type || '').replace(/_/g, ' ')
}

export default function Interviews() {
  const nav = useNavigation<any>()
  const load = useCallback(() => api<Payload>('/dashboard/interviews/data'), [])
  const { data, loading, refreshing, error, refresh } = useDashData(load)
  const open = (iv: Interview, upcoming: boolean) =>
    nav.navigate('InterviewDetail', { interview: { ...iv, upcoming } })

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <ScreenTitle>Interviews</ScreenTitle>

      {loading && !data ? <LoadingState /> : null}
      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      {data ? (
        <>
          <SectionLabel style={{ marginTop: 20 } as any}>Upcoming</SectionLabel>
          {data.upcoming.length === 0 ? (
            <EmptyState
              message="You're interview-free."
              suggestions={['Practice STAR stories', 'Reach out to a recruiter', 'Review your pipeline']}
              actionLabel="Review pipeline"
              onAction={() => nav.navigate('Pipeline')}
            />
          ) : (
            data.upcoming.map((iv, i) => (
              <PressableScale key={iv.id ?? i} onPress={() => open(iv, true)}>
                <Card tint={i === 0 ? 'low' : undefined} raised={i !== 0} style={i === 0 ? styles.firstCard : undefined}>
                  <View style={styles.topRow}>
                    <Text style={styles.title} numberOfLines={1}>
                      {[iv.company, iv.role].filter(Boolean).join(' · ')}
                    </Text>
                    <Text style={[styles.countdown, { color: i === 0 ? t.cyanBright : t.textSecondary }]}>
                      {countdownChip(iv.interview_date)}
                    </Text>
                  </View>
                  <Text style={styles.meta}>{interviewTimeLine(iv)}</Text>
                  {iv.interviewer ? (
                    <Text style={styles.interviewer} numberOfLines={1}>
                      with {iv.interviewer}
                      {iv.interviewer_role ? ` · ${iv.interviewer_role}` : ''}
                    </Text>
                  ) : null}
                  <View style={styles.statusRow}>
                    <View style={[styles.dot, { backgroundColor: t.amber }]} />
                    <Text style={[styles.statusText, { color: t.amber }]}>Debrief pending</Text>
                  </View>
                </Card>
              </PressableScale>
            ))
          )}

          <SectionLabel>Recent debriefs</SectionLabel>
          {data.recent.length === 0 ? (
            <EmptyState message="No debriefs logged yet." />
          ) : (
            data.recent.map((iv, i) => (
              <PressableScale key={iv.id ?? `r${i}`} onPress={() => open(iv, false)}>
                <Card style={styles.debriefRow}>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.debriefTitle} numberOfLines={1}>
                      {[iv.company, (iv.interview_type || '').replace(/_/g, ' ')].filter(Boolean).join(' · ')}
                    </Text>
                    <Text style={styles.debriefSub} numberOfLines={1}>
                      {debriefLine(iv)}
                    </Text>
                  </View>
                  <Text style={styles.debriefDate}>{monoDate(iv.interview_date)}</Text>
                </Card>
              </PressableScale>
            ))
          )}
        </>
      ) : null}
    </Screen>
  )
}

const styles = StyleSheet.create({
  firstCard: { backgroundColor: 'rgba(0,181,200,.13)', borderColor: 'rgba(0,181,200,.26)' },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  title: { fontSize: 16, fontWeight: '700', color: t.text, flex: 1 },
  countdown: { fontSize: 11, fontWeight: '600', fontFamily: fonts.mono },
  meta: { fontSize: 13, color: t.muted, marginTop: 4, textTransform: 'capitalize' },
  interviewer: { fontSize: 12.5, color: t.faint, marginTop: 3 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  statusText: { fontSize: 12, fontWeight: '600' },
  debriefRow: {
    borderRadius: 14,
    paddingVertical: 13,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    backgroundColor: 'rgba(255,255,255,.035)',
    borderColor: t.hairline,
    marginTop: 8,
  },
  debriefTitle: { fontSize: 14.5, fontWeight: '600', color: t.textBright, textTransform: 'capitalize' },
  debriefSub: { fontSize: 12, color: t.muted, marginTop: 1 },
  debriefDate: { fontSize: 11, color: t.faint, fontFamily: fonts.mono },
})
