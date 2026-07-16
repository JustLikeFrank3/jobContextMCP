// Networking — the relationship surface. Filter by where the conversation
// stands (needs reply / awaiting reply / drafted), search everything, act
// with one tap: call, email, LinkedIn. Follow-ups float to the top.
import { useCallback, useEffect, useState } from 'react'
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
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

type PeopleData = { total: number; follow_up_queue: Person[]; recent: Person[]; people?: Person[] }

// outreach_status vocabulary: none | drafted | sent | responded
const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'responded', label: 'Needs reply' },
  { key: 'sent', label: 'Awaiting reply' },
  { key: 'drafted', label: 'Drafted' },
] as const
type FilterKey = (typeof FILTERS)[number]['key']

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

export default function Networking() {
  const [data, setData] = useState<PeopleData | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<FilterKey>('all')

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

  useEffect(() => {
    load()
  }, [load])

  return (
    <ScrollView
      style={styles.root}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.cyan} />}
    >
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.filterRow}>
        {FILTERS.map((f) => (
          <Pressable
            key={f.key}
            style={[styles.filterChip, filter === f.key && styles.filterChipActive]}
            onPress={() => setFilter(f.key)}
          >
            <Text style={[styles.filterText, filter === f.key && styles.filterTextActive]}>
              {f.label}
            </Text>
          </Pressable>
        ))}
      </View>
      <TextInput
        style={styles.search}
        value={query}
        onChangeText={setQuery}
        placeholder="Search people, companies, context…"
        placeholderTextColor={colors.faint}
        autoCapitalize="none"
      />
      {(() => {
        const q = query.trim().toLowerCase()
        const match = (p: Person) => {
          if (filter !== 'all' && (p.outreach_status || 'none').toLowerCase() !== filter) return false
          return !q || `${p.name} ${p.company} ${p.relationship} ${p.context} ${p.notes}`.toLowerCase().includes(q)
        }
        // Prefer the full roster (newer API); fall back to the recent slice.
        const roster = data?.people?.length ? data.people : (data?.recent || [])
        const followupIds = new Set((data?.follow_up_queue || []).map((p) => p.id))
        const followups = (data?.follow_up_queue || []).filter(match)
        const rest = roster.filter((p) => match(p) && !followupIds.has(p.id))
        // Group by relationship so the list reads like a network, not a log.
        const groups = new Map<string, Person[]>()
        for (const p of rest) {
          const key = (p.relationship || 'other').toLowerCase()
          groups.set(key, [...(groups.get(key) || []), p])
        }
        return (
          <>
            {followups.length > 0 && (
              <>
                <Text style={styles.section}>Follow-ups due</Text>
                {followups.map((p) => <PersonCard key={`f${p.id}`} p={p} highlight />)}
              </>
            )}
            {[...groups.entries()].map(([rel, people]) => (
              <View key={rel}>
                <Text style={styles.section}>{rel} ({people.length})</Text>
                {people.map((p) => <PersonCard key={p.id} p={p} />)}
              </View>
            ))}
            {(q || filter !== 'all') && followups.length === 0 && groups.size === 0 && (
              <Text style={styles.empty}>
                {q ? `No matches for “${query}”.` : 'Nobody in this state right now.'}
              </Text>
            )}
          </>
        )
      })()}
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
  search: {
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 10, color: colors.text, paddingHorizontal: 14, paddingVertical: 10,
    fontSize: 14, marginHorizontal: 12, marginTop: 12,
  },
  empty: { color: colors.muted, textAlign: 'center', marginTop: 40 },
  filterRow: { flexDirection: 'row', gap: 8, marginHorizontal: 12, marginTop: 12 },
  filterChip: {
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 999, paddingHorizontal: 13, paddingVertical: 7,
  },
  filterChipActive: { borderColor: colors.cyan, backgroundColor: colors.surfaceRaised },
  filterText: { color: colors.muted, fontSize: 13 },
  filterTextActive: { color: colors.cyan, fontWeight: '600' },
})
