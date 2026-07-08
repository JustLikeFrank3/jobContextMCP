// Career Inbox — the home screen. One chronological feed of everything that
// changed (derived server-side from the sync journal): open the app, know
// instantly what happened since you last looked.
import { useCallback, useEffect, useState } from 'react'
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native'
import { fetchEvents, InboxEvent } from '../api'
import { colors } from '../theme'

const ICONS: Record<string, string> = {
  assessment_done: '📊',
  job_imported: '📥',
  interview_logged: '🎙️',
  application_update: '📌',
  activity: '🗒️',
  rejection: '📕',
}

function timeAgo(ts: string): string {
  const then = new Date(ts).getTime()
  if (Number.isNaN(then)) return ''
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (mins < 60) return `${mins}m`
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h`
  return `${Math.round(mins / 60 / 24)}d`
}

export default function Inbox() {
  const [events, setEvents] = useState<InboxEvent[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setRefreshing(true)
    try {
      const data = await fetchEvents()
      setEvents(data.events)
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
        data={events}
        keyExtractor={(e) => String(e.id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.cyan} />}
        ListEmptyComponent={
          !refreshing ? (
            <Text style={styles.empty}>
              Nothing yet. Share a job posting to jobContext and watch this feed light up.
            </Text>
          ) : null
        }
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.icon}>{ICONS[item.type] || '•'}</Text>
            <View style={styles.body}>
              <Text style={styles.title}>{item.title}</Text>
              {item.subtitle ? <Text style={styles.subtitle}>{item.subtitle}</Text> : null}
            </View>
            <Text style={styles.time}>{timeAgo(item.ts)}</Text>
          </View>
        )}
      />
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  card: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 14, marginHorizontal: 12, marginTop: 10,
  },
  icon: { fontSize: 20 },
  body: { flex: 1 },
  title: { color: colors.text, fontWeight: '600', fontSize: 15 },
  subtitle: { color: colors.muted, fontSize: 13, marginTop: 2 },
  time: { color: colors.faint, fontSize: 12 },
  empty: { color: colors.muted, textAlign: 'center', marginTop: 60, paddingHorizontal: 40, lineHeight: 20 },
  error: { color: colors.danger, padding: 12, textAlign: 'center' },
})
