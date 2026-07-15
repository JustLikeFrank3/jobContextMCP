// Contacts — phones are communication devices. Tap a person: call, email,
// LinkedIn, notes, follow-up state. Follow-up queue floats to the top.
import { useFocusEffect } from '@react-navigation/native'
import { useCallback, useState } from 'react'
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { api } from '../api'
import { colors } from '../theme'

type Person = {
  id: number
  name: string
  relationship?: string
  company?: string
  context?: string
  contact_info?: string
  outreach_status?: string
  notes?: string
  last_updated?: string
}

type PeopleData = { total: number; follow_up_queue: Person[]; recent: Person[] }

function extractActions(p: Person) {
  const info = `${p.contact_info || ''} ${p.notes || ''} ${p.context || ''}`
  const email = info.match(/[\w.+-]+@[\w-]+\.[\w.]+/)?.[0]
  const phone = info.match(/\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/)?.[0]
  const linkedin = info.match(/(?:https?:\/\/)?(?:www\.)?linkedin\.com\/[^\s,)]+/i)?.[0]
  return { email, phone, linkedin }
}

function PersonCard({ p, highlight }: { p: Person; highlight?: boolean }) {
  const { email, phone, linkedin } = extractActions(p)
  const open = (url: string) => Linking.openURL(url).catch(() => {})
  return (
    <View style={[styles.card, highlight && styles.cardHot]}>
      <View style={styles.row}>
        <Text style={styles.name}>{p.name}</Text>
        {p.outreach_status ? <Text style={styles.status}>{p.outreach_status}</Text> : null}
      </View>
      <Text style={styles.meta} numberOfLines={1}>
        {[p.relationship, p.company].filter(Boolean).join(' · ')}
      </Text>
      {p.context ? <Text style={styles.context} numberOfLines={2}>{p.context}</Text> : null}
      <View style={styles.actions}>
        {phone && (
          <Pressable style={styles.action} onPress={() => open(`tel:${phone.replace(/[^+\d]/g, '')}`)}>
            <Text style={styles.actionText}>📞 Call</Text>
          </Pressable>
        )}
        {email && (
          <Pressable style={styles.action} onPress={() => open(`mailto:${email}`)}>
            <Text style={styles.actionText}>✉️ Email</Text>
          </Pressable>
        )}
        {linkedin && (
          <Pressable style={styles.action} onPress={() => open(linkedin.startsWith('http') ? linkedin : `https://${linkedin}`)}>
            <Text style={styles.actionText}>💼 LinkedIn</Text>
          </Pressable>
        )}
      </View>
    </View>
  )
}

export default function Contacts() {
  const [data, setData] = useState<PeopleData | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setRefreshing(true)
    try {
      setData(await api<PeopleData>('/dashboard/people/data'))
      setError('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRefreshing(false)
    }
  }, [])

  // Refetch on every tab focus — see Today.tsx (stale pre-sign-in state).
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
      {(data?.follow_up_queue?.length ?? 0) > 0 && (
        <>
          <Text style={styles.section}>Follow-ups due</Text>
          {data!.follow_up_queue.map((p) => <PersonCard key={`f${p.id}`} p={p} highlight />)}
        </>
      )}
      <Text style={styles.section}>Recent {data ? `(${data.total} total)` : ''}</Text>
      {(data?.recent || []).map((p) => <PersonCard key={p.id} p={p} />)}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  section: {
    color: colors.cyanSoft, fontSize: 12, textTransform: 'uppercase', letterSpacing: 1,
    marginTop: 16, marginBottom: 4, marginHorizontal: 14,
  },
  card: {
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 14, marginHorizontal: 12, marginTop: 8,
  },
  cardHot: { borderColor: colors.cyan },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  name: { color: colors.text, fontWeight: '700', fontSize: 15 },
  status: { color: colors.cyanSoft, fontSize: 11, textTransform: 'uppercase' },
  meta: { color: colors.muted, fontSize: 13, marginTop: 2 },
  context: { color: colors.faint, fontSize: 12, marginTop: 6, lineHeight: 17 },
  actions: { flexDirection: 'row', gap: 8, marginTop: 10 },
  action: {
    backgroundColor: colors.surfaceRaised, borderColor: colors.border, borderWidth: 1,
    borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7,
  },
  actionText: { color: colors.text, fontSize: 13 },
  error: { color: colors.danger, padding: 12, textAlign: 'center' },
})
