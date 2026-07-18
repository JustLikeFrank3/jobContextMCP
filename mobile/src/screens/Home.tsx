// Home — the design's "Daily Digest" (variant 1a): greeting + date,
// today's priorities (cyan-tinted card), follow-ups due with status chips,
// next interview card, and a wellbeing nudge. All real data:
//   GET /api/dashboard/home           greeting, priorities, move text, oura
//   GET /dashboard/people/data        follow-up queue (optional — omitted on error)
//   GET /dashboard/interviews/data    next interview (optional — omitted on error)
// The avatar opens Settings; the activity row opens the Inbox feed —
// both live as chromeless tab routes so no functionality is lost.
import { useNavigation } from '@react-navigation/native'
import { useCallback } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import { countdownChip, interviewTimeLine } from '../ui/format'
import {
  Card,
  ErrorState,
  LoadingState,
  Screen,
  SectionLabel,
  StatusChip,
} from '../ui/primitives'
import { fonts, t } from '../ui/tokens'
import { useDashData } from '../ui/useDashData'

type HomeData = {
  welcomeName: string
  hasOura: boolean
  oura?: { score: number; label: string } | null
  today: {
    active: number
    inflight: number
    overdue: number
    move: string
    priorities: { n: string; text: string }[]
  }
}

type Person = { id: number; name: string; company?: string; outreach_status?: string; last_updated?: string }
type Interview = {
  id?: number
  company?: string
  role?: string
  interview_date?: string
  interview_type?: string
  interviewer?: string
}

type Bundle = {
  home: HomeData
  followups: Person[]
  nextInterview: Interview | null
}

function dateLine(): string {
  const d = new Date()
  const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return `${days[d.getDay()]} · ${months[d.getMonth()]} ${d.getDate()}`
}

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

// outreach_status → follow-up chip. "responded" means they replied and the
// ball is in our court (design's red/overdue slot); "sent" is waiting on them.
function followupChip(status?: string): { label: string; color: string; bg: string } {
  const s = (status || '').toLowerCase()
  if (s === 'responded') return { label: 'NEEDS REPLY', color: t.red, bg: 'rgba(227,147,147,.14)' }
  if (s === 'follow-up') return { label: 'DUE', color: t.amber, bg: 'rgba(224,183,122,.13)' }
  if (s === 'sent') return { label: 'AWAITING', color: t.amber, bg: 'rgba(224,183,122,.13)' }
  return { label: 'DRAFTED', color: t.textSecondary, bg: 'rgba(255,255,255,.06)' }
}

export default function Home() {
  const nav = useNavigation<any>()
  const load = useCallback(async (): Promise<Bundle> => {
    const home = await api<HomeData>('/api/dashboard/home')
    // Side sections are best-effort: a failure omits the section, not Home.
    const [people, interviews] = await Promise.allSettled([
      api<{ follow_up_queue: Person[] }>('/dashboard/people/data'),
      api<{ upcoming: Interview[] }>('/dashboard/interviews/data'),
    ])
    return {
      home,
      followups:
        people.status === 'fulfilled' ? (people.value.follow_up_queue || []).slice(0, 3) : [],
      nextInterview:
        interviews.status === 'fulfilled' ? interviews.value.upcoming?.[0] || null : null,
    }
  }, [])
  const { data, loading, refreshing, error, refresh } = useDashData(load)

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      {/* Greeting + avatar */}
      <View style={styles.headerRow}>
        <View>
          <Text style={styles.date}>{dateLine()}</Text>
          <Text style={styles.greeting}>
            {greeting()}
            {data?.home.welcomeName && data.home.welcomeName !== 'there'
              ? `, ${data.home.welcomeName}`
              : ''}
          </Text>
        </View>
        <Pressable style={styles.avatar} onPress={() => nav.navigate('Settings')}>
          <Text style={styles.avatarText}>{(data?.home.welcomeName || '·')[0].toUpperCase()}</Text>
        </Pressable>
      </View>

      {loading && !data ? <LoadingState /> : null}
      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      {data ? (
        <>
          {/* Today's priorities — cyan tint card */}
          {data.home.today.priorities.length > 0 && (
            <Card tint="high" style={{ borderRadius: 20, padding: 18, marginTop: 18 }}>
              <Text style={styles.prioLabel}>
                TODAY'S {data.home.today.priorities.length} PRIORIT
                {data.home.today.priorities.length === 1 ? 'Y' : 'IES'}
              </Text>
              <View style={{ marginTop: 12, gap: 11 }}>
                {data.home.today.priorities.map((p, i) => (
                  <View key={p.n} style={styles.prioRow}>
                    <View style={[styles.checkbox, i === 0 && { borderColor: t.cyan }]} />
                    <Text style={styles.prioText}>{p.text}</Text>
                  </View>
                ))}
              </View>
            </Card>
          )}

          {/* Follow-ups due */}
          {data.followups.length > 0 && (
            <>
              <SectionLabel>Follow-ups due</SectionLabel>
              <View style={{ marginTop: 4 }}>
                {data.followups.map((p) => {
                  const chip = followupChip(p.outreach_status)
                  return (
                    <Card key={p.id} style={styles.followRow}>
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={styles.followName}>{p.company || p.name}</Text>
                        <Text style={styles.followSub} numberOfLines={1}>
                          {p.company ? p.name : p.outreach_status || ''}
                        </Text>
                      </View>
                      <StatusChip {...chip} />
                    </Card>
                  )
                })}
              </View>
            </>
          )}

          {/* Next interview */}
          {data.nextInterview && (
            <>
              <SectionLabel>Next interview</SectionLabel>
              <Card raised style={{ marginTop: 4 }}>
                <View style={styles.ivTop}>
                  <Text style={styles.ivTitle} numberOfLines={1}>
                    {[data.nextInterview.company, data.nextInterview.role]
                      .filter(Boolean)
                      .join(' · ')}
                  </Text>
                  <Text style={styles.ivCountdown}>{countdownChip(data.nextInterview.interview_date)}</Text>
                </View>
                <Text style={styles.ivMeta}>{interviewTimeLine(data.nextInterview)}</Text>
                <Pressable onPress={() => nav.navigate('Interviews')}>
                  <Text style={styles.ivLink}>View in Interviews →</Text>
                </Pressable>
              </Card>
            </>
          )}

          {/* Wellbeing nudge — Today's Move text in the design's nudge card */}
          {data.home.today.move ? (
            <Card tint="low" style={styles.nudge}>
              <Text style={styles.nudgeEmoji}>🌿</Text>
              <Text style={styles.nudgeText}>{data.home.today.move}</Text>
            </Card>
          ) : null}

          {/* Recent activity → Inbox feed (kept from the previous app) */}
          <Pressable onPress={() => nav.navigate('Activity')}>
            <Card style={styles.activityRow}>
              <Text style={styles.activityText}>Recent activity</Text>
              <Text style={styles.activityArrow}>→</Text>
            </Card>
          </Pressable>
        </>
      ) : null}
    </Screen>
  )
}

const styles = StyleSheet.create({
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  date: { fontSize: 13, fontWeight: '500', color: t.cyanBright, fontFamily: fonts.mono, letterSpacing: 1 },
  greeting: { fontSize: 27, fontWeight: '700', color: t.text, letterSpacing: -0.6, marginTop: 3 },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: t.tintFillHi,
    borderWidth: 1,
    borderColor: 'rgba(0,181,200,.4)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { fontWeight: '700', color: t.cyanBright },
  prioLabel: { fontSize: 11, fontWeight: '600', letterSpacing: 1.5, color: t.cyanBright, fontFamily: fonts.mono },
  prioRow: { flexDirection: 'row', alignItems: 'center', gap: 11 },
  checkbox: { width: 18, height: 18, borderRadius: 6, borderWidth: 2, borderColor: 'rgba(215,227,248,.35)' },
  prioText: { fontSize: 14.5, color: t.textBright, flex: 1 },
  followRow: {
    borderRadius: 14,
    paddingVertical: 13,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    marginTop: 8,
  },
  followName: { fontSize: 15, fontWeight: '600', color: t.text },
  followSub: { fontSize: 12.5, color: t.muted, marginTop: 1 },
  ivTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  ivTitle: { fontSize: 16, fontWeight: '700', color: t.text, flex: 1 },
  ivCountdown: { fontSize: 11, fontWeight: '600', color: t.cyanBright, fontFamily: fonts.mono },
  ivMeta: { fontSize: 13, color: t.muted, marginTop: 4, textTransform: 'capitalize' },
  ivLink: { marginTop: 11, fontSize: 12, fontWeight: '600', color: t.cyanBright },
  nudge: { flexDirection: 'row', alignItems: 'center', gap: 13, marginTop: 18 },
  nudgeEmoji: { fontSize: 22 },
  nudgeText: { fontSize: 13.5, color: t.textBody, lineHeight: 18, flex: 1 },
  activityRow: {
    borderRadius: 14,
    paddingVertical: 13,
    paddingHorizontal: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 14,
  },
  activityText: { fontSize: 14, fontWeight: '600', color: t.textSecondary },
  activityArrow: { fontSize: 14, color: t.cyanBright },
})
