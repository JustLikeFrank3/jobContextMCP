// Wellbeing — design layout: readiness card (big score), 7-day energy bars
// (last bar solid cyan), recent check-ins. Data:
//   GET /dashboard/health/data              check-ins (mood label, energy 1-10)
//   GET /api/dashboard/oura/history?days=14 readiness (optional — card omitted
//                                           when no ring data exists)
// The check-in form POSTs /dashboard/health/checkin (the same tool the web
// and MCP clients use), so all three surfaces write identical entries.
import { useNavigation } from '@react-navigation/native'
import { useCallback, useState } from 'react'
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native'
import { api, logCheckin } from '../api'
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
import { useDashData } from '../ui/useDashData'

type Entry = { date: string; mood?: string; energy?: number; notes?: string; productive?: boolean }
type HealthPayload = { total_entries: number; avg_mood: number | null; avg_energy: number | null; recent: Entry[] }
type OuraDay = { date: string; readiness?: number }

type Bundle = { health: HealthPayload; readiness: OuraDay | null }

function readinessNote(score: number): string {
  if (score >= 85) return 'High readiness — good day to push outreach'
  if (score >= 70) return 'Balanced — steady progress day'
  return 'Recovery day — keep the load light'
}

function dayLetter(dateStr: string): string {
  const m = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return ''
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return ['S', 'M', 'T', 'W', 'T', 'F', 'S'][d.getDay()]
}

const MOODS = [
  { emoji: '😔', word: 'low' },
  { emoji: '😕', word: 'drained' },
  { emoji: '🙂', word: 'steady' },
  { emoji: '😀', word: 'good' },
  { emoji: '🤩', word: 'great' },
]

// Check-in form — mood tiles, energy pills (1-10), notes, productive toggle.
// POSTs the same endpoint as web/MCP, then calls onSaved() to refresh.
function CheckinForm({ onSaved }: { onSaved: () => void }) {
  const [moodIdx, setMoodIdx] = useState(2)
  const [energy, setEnergy] = useState(5)
  const [notes, setNotes] = useState('')
  const [productive, setProductive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setErr(null)
    try {
      await logCheckin({ mood: MOODS[moodIdx].word, energy, notes: notes.trim(), productive })
      setNotes('')
      setProductive(false)
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not save check-in.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={styles.form}>
      <Text style={styles.formTitle}>How are you today?</Text>

      <Text style={styles.fieldLabel}>MOOD</Text>
      <View style={styles.moodRow}>
        {MOODS.map((m, i) => (
          <Pressable
            key={m.word}
            onPress={() => setMoodIdx(i)}
            style={[styles.moodTile, i === moodIdx && styles.moodTileOn]}
          >
            <Text style={styles.moodEmoji}>{m.emoji}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.fieldLabel}>{`ENERGY · ${energy}/10`}</Text>
      <View style={styles.pillRow}>
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <Pressable
            key={n}
            onPress={() => setEnergy(n)}
            style={[styles.pill, n <= energy && styles.pillOn]}
          >
            <Text style={[styles.pillText, n <= energy && styles.pillTextOn]}>{n}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.fieldLabel}>NOTES</Text>
      <TextInput
        value={notes}
        onChangeText={setNotes}
        placeholder="What’s on your mind today? (optional)"
        placeholderTextColor={t.faint}
        multiline
        maxLength={2000}
        style={styles.notesInput}
      />

      <View style={styles.toggleRow}>
        <Text style={styles.toggleLabel}>Productive day</Text>
        <Switch value={productive} onValueChange={setProductive} trackColor={{ true: t.cyan }} />
      </View>

      <Pressable onPress={submit} disabled={busy} style={[styles.submit, busy && styles.submitBusy]}>
        <Text style={styles.submitText}>{busy ? 'Saving…' : 'Check in'}</Text>
      </Pressable>
      {err ? <Text style={styles.formErr}>{err}</Text> : null}
    </Card>
  )
}

export default function Wellbeing() {
  const nav = useNavigation<any>()
  const load = useCallback(async (): Promise<Bundle> => {
    const health = await api<HealthPayload>('/dashboard/health/data')
    // Readiness is a bonus — older servers / no ring just omit the card.
    let readiness: OuraDay | null = null
    try {
      const h = await api<{ days: OuraDay[] }>('/api/dashboard/oura/history?days=14')
      const scored = (h.days || []).filter((d) => (d.readiness ?? 0) > 0)
      readiness = scored[scored.length - 1] || null
    } catch {
      readiness = null
    }
    return { health, readiness }
  }, [])
  const { data, loading, refreshing, error, refresh } = useDashData(load)

  // Oldest → newest, last 7 with an energy value, for the bar chart.
  const bars = (data?.health.recent || [])
    .filter((e) => typeof e.energy === 'number' && e.energy! > 0)
    .slice(0, 7)
    .reverse()

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <ScreenTitle sub={data ? `${data.health.total_entries} check-ins logged` : undefined}>
        Wellbeing
      </ScreenTitle>

      {loading && !data ? <LoadingState /> : null}
      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      {data ? (
        <>
          <CheckinForm onSaved={refresh} />

          {data.readiness ? (
            <Card tint="high" style={styles.readinessCard}>
              <Text style={styles.readinessScore}>{data.readiness.readiness}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.readinessTitle}>Oura readiness</Text>
                <Text style={styles.readinessNote}>{readinessNote(data.readiness.readiness || 0)}</Text>
              </View>
            </Card>
          ) : null}

          {bars.length > 1 && (
            <>
              <SectionLabel>{`${bars.length}-day energy`}</SectionLabel>
              <View style={styles.barRow}>
                {bars.map((e, i) => (
                  <View key={e.date + i} style={styles.barCol}>
                    <View
                      style={[
                        styles.bar,
                        {
                          height: Math.max(8, ((e.energy || 0) / 10) * 90),
                          backgroundColor: i === bars.length - 1 ? t.cyan : 'rgba(0,181,200,.35)',
                        },
                      ]}
                    />
                    <Text style={styles.barLabel}>{dayLetter(e.date)}</Text>
                  </View>
                ))}
              </View>
            </>
          )}

          <SectionLabel>Recent check-ins</SectionLabel>
          {data.health.recent.length === 0 ? (
            <EmptyState message="No check-ins yet — use the form above and your trends appear here." />
          ) : (
            data.health.recent.slice(0, 10).map((e, i) => (
              <PressableScale key={e.date + i} onPress={() => nav.navigate('CheckinDetail', { entry: e })}>
                <Card style={styles.entryCard}>
                  <View style={styles.entryTop}>
                    <Text style={styles.entryMood}>{e.mood || '—'}</Text>
                    <Text style={styles.entryDate}>{e.date?.slice(0, 10)}</Text>
                  </View>
                  {typeof e.energy === 'number' ? (
                    <View style={styles.meterRow}>
                      <Text style={styles.meterLabel}>ENERGY</Text>
                      <View style={styles.meterTrack}>
                        <View style={[styles.meterFill, { width: `${Math.min(e.energy, 10) * 10}%` }]} />
                      </View>
                      <Text style={styles.meterVal}>{e.energy}/10</Text>
                    </View>
                  ) : null}
                  {e.notes ? (
                    <Text style={styles.entryNotes} numberOfLines={2}>
                      {e.notes}
                    </Text>
                  ) : null}
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
  form: { borderRadius: 18, padding: 17, marginTop: 18 },
  formTitle: { fontSize: 14, fontWeight: '600', color: t.textSoft },
  fieldLabel: { fontSize: 10.5, color: t.muted2, fontFamily: fonts.mono, letterSpacing: 1, marginTop: 16 },
  moodRow: { flexDirection: 'row', gap: 8, marginTop: 8 },
  moodTile: {
    flex: 1, height: 52, borderRadius: 12, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,.05)', borderWidth: 1.5, borderColor: 'transparent',
  },
  moodTileOn: { backgroundColor: 'rgba(0,181,200,.18)', borderColor: t.cyan },
  moodEmoji: { fontSize: 22 },
  pillRow: { flexDirection: 'row', gap: 5, marginTop: 8 },
  pill: {
    flex: 1, height: 34, borderRadius: 8, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,.05)',
  },
  pillOn: { backgroundColor: 'rgba(0,181,200,.30)' },
  pillText: { fontSize: 11, color: t.muted2, fontFamily: fonts.mono },
  pillTextOn: { color: t.textBright, fontWeight: '600' },
  notesInput: {
    marginTop: 8, minHeight: 64, borderRadius: 12, padding: 11, fontSize: 13.5, lineHeight: 19,
    color: t.text, backgroundColor: 'rgba(255,255,255,.05)', borderWidth: 1.5, borderColor: t.hairline,
    textAlignVertical: 'top',
  },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 14 },
  toggleLabel: { fontSize: 13.5, color: t.textSoft },
  submit: {
    marginTop: 16, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center',
    backgroundColor: t.cyan,
  },
  submitBusy: { opacity: 0.6 },
  submitText: { fontSize: 14, fontWeight: '600', color: '#04141a' },
  formErr: { color: t.red, fontSize: 12.5, marginTop: 10 },
  readinessCard: {
    borderRadius: 18,
    padding: 17,
    marginTop: 18,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    backgroundColor: 'rgba(0,181,200,.14)',
    borderColor: 'rgba(0,181,200,.26)',
  },
  readinessScore: { fontSize: 40, fontWeight: '700', color: t.cyanBright, letterSpacing: -1 },
  readinessTitle: { fontSize: 14, fontWeight: '600', color: t.text },
  readinessNote: { fontSize: 12.5, color: t.cyanMuted, marginTop: 2 },
  barRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, height: 110, marginTop: 12 },
  barCol: { flex: 1, alignItems: 'center', justifyContent: 'flex-end', gap: 6 },
  bar: { width: '100%', borderRadius: 6 },
  barLabel: { fontSize: 9.5, color: t.faint, fontFamily: fonts.mono },
  entryCard: { borderRadius: 14, paddingVertical: 13, paddingHorizontal: 14, marginTop: 8 },
  entryTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  entryMood: { fontSize: 14.5, fontWeight: '600', color: t.textBright, textTransform: 'capitalize' },
  entryDate: { fontSize: 11, color: t.faint, fontFamily: fonts.mono },
  meterRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 10 },
  meterLabel: { fontSize: 9.5, color: t.muted2, fontFamily: fonts.mono, letterSpacing: 1 },
  meterTrack: { flex: 1, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,.07)', overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: 3, backgroundColor: t.cyan },
  meterVal: { fontSize: 11, fontWeight: '600', color: t.textSecondary, fontFamily: fonts.mono },
  entryNotes: { marginTop: 8, fontSize: 12.5, color: t.textSoft, lineHeight: 17.5 },
})
