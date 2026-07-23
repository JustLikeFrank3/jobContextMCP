// People — design layout: search, filter chips that filter the list live,
// contact cards with colored-initial avatar, name, title, status chip, a
// contact-history synopsis, and a mono last-touch line. Quick actions
// (call / email / LinkedIn) are carried over from the previous Networking
// screen so no functionality is lost.
// Data: GET /dashboard/people/data → { people[], follow_up_queue[], recent[] }.
import { useNavigation } from '@react-navigation/native'
import { useCallback, useMemo, useState } from 'react'
import { Linking, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { api } from '../api'
import { PressableScale } from '../ui/detail'
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
import { avatarPalette, fonts, t } from '../ui/tokens'
import { useDashData } from '../ui/useDashData'

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
  last_contacted?: string
}

type Payload = { total: number; follow_up_queue: Person[]; recent: Person[]; people?: Person[] }

// outreach_status vocabulary: none | drafted | sent | responded (| follow-up)
type Filter = { key: 'all' | 'warm' | 'awaiting' | 'todo'; label: string; match: string[] | null }
const FILTERS: Filter[] = [
  { key: 'all', label: 'All', match: null },
  { key: 'warm', label: 'Warm', match: ['responded'] },
  { key: 'awaiting', label: 'Awaiting', match: ['sent', 'follow-up'] },
  { key: 'todo', label: 'To do', match: ['drafted', 'none', ''] },
]
type FilterKey = Filter['key']

const STATUS_CHIP: Record<string, { label: string; color: string; bg: string }> = {
  responded: { label: 'REPLIED', color: t.green, bg: 'rgba(111,211,160,.15)' },
  'follow-up': { label: 'DUE', color: t.amber, bg: 'rgba(224,183,122,.15)' },
  sent: { label: 'SENT', color: t.amber, bg: 'rgba(224,183,122,.15)' },
  drafted: { label: 'DRAFT', color: '#9BB0D0', bg: 'rgba(255,255,255,.06)' },
  none: { label: 'NEW', color: '#9BB0D0', bg: 'rgba(255,255,255,.06)' },
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
}

function lastTouch(p: Person): string {
  const status = (p.outreach_status || 'added').toUpperCase()
  const date = (p.last_contacted || p.last_updated || '').slice(0, 10)
  return date ? `${status} · ${date}` : status
}

function extractActions(p: Person) {
  const info = `${p.contact_info || ''} ${p.notes || ''} ${p.context || ''}`
  const email = info.match(/[\w.+-]+@[\w-]+\.[\w.]+/)?.[0]
  const phone = info.match(/\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/)?.[0]
  const linkedin = info.match(/(?:https?:\/\/)?(?:www\.)?linkedin\.com\/[^\s,)]+/i)?.[0]
  return { email, phone, linkedin }
}

function PersonCard({ p, index, onOpen }: { p: Person; index: number; onOpen: () => void }) {
  const chip = STATUS_CHIP[(p.outreach_status || 'none').toLowerCase()] || STATUS_CHIP.none
  const { email, phone, linkedin } = extractActions(p)
  const open = (url: string) => Linking.openURL(url).catch(() => {})
  const history = p.context || p.notes || ''
  return (
    <PressableScale onPress={onOpen}>
      <Card style={styles.personCard}>
      <View style={styles.personTop}>
        <View style={[styles.avatar, { backgroundColor: avatarPalette[index % avatarPalette.length] }]}>
          <Text style={styles.avatarText}>{initials(p.name)}</Text>
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={styles.name} numberOfLines={1}>
            {p.name}
          </Text>
          <Text style={styles.title} numberOfLines={1}>
            {[p.relationship, p.company].filter(Boolean).join(' · ')}
          </Text>
        </View>
        <StatusChip {...chip} />
      </View>
      {history ? (
        <View style={styles.historyRow}>
          <View style={[styles.historyDot, { backgroundColor: chip.color }]} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={styles.history} numberOfLines={2}>
              {history}
            </Text>
            <Text style={styles.last}>{lastTouch(p)}</Text>
          </View>
        </View>
      ) : (
        <Text style={[styles.last, { marginTop: 8 }]}>{lastTouch(p)}</Text>
      )}
      {(phone || email || linkedin) && (
        <View style={styles.actions}>
          {phone && (
            <Pressable style={styles.action} onPress={() => open(`tel:${phone.replace(/[^+\d]/g, '')}`)}>
              <Text style={styles.actionText}>Call</Text>
            </Pressable>
          )}
          {email && (
            <Pressable style={styles.action} onPress={() => open(`mailto:${email}`)}>
              <Text style={styles.actionText}>Email</Text>
            </Pressable>
          )}
          {linkedin && (
            <Pressable
              style={styles.action}
              onPress={() => open(linkedin.startsWith('http') ? linkedin : `https://${linkedin}`)}
            >
              <Text style={styles.actionText}>LinkedIn</Text>
            </Pressable>
          )}
        </View>
      )}
      </Card>
    </PressableScale>
  )
}

export default function People() {
  const nav = useNavigation<any>()
  const [filter, setFilter] = useState<FilterKey>('all')
  const [query, setQuery] = useState('')
  const load = useCallback(() => api<Payload>('/dashboard/people/data'), [])
  const { data, loading, refreshing, error, refresh } = useDashData(load)

  const shown = useMemo(() => {
    // Prefer the full roster (newer API); fall back to the recent slice.
    const roster = data?.people?.length ? data.people : data?.recent || []
    const def = FILTERS.find((f) => f.key === filter)!
    const q = query.trim().toLowerCase()
    return roster.filter((p) => {
      if (def.match && !def.match.includes((p.outreach_status || '').toLowerCase())) return false
      if (!q) return true
      return `${p.name} ${p.company} ${p.relationship} ${p.context} ${p.notes}`.toLowerCase().includes(q)
    })
  }, [data, filter, query])

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <ScreenTitle sub={data ? `${data.total} contacts` : undefined}>People</ScreenTitle>

      <TextInput
        style={styles.search}
        value={query}
        onChangeText={setQuery}
        placeholder="Search contacts…"
        placeholderTextColor={t.faint}
        autoCapitalize="none"
      />

      <View style={styles.chipRow}>
        {FILTERS.map((f) => (
          <Chip key={f.key} label={f.label} active={filter === f.key} onPress={() => setFilter(f.key)} />
        ))}
      </View>

      {loading && !data ? <LoadingState /> : null}
      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}
      {data && shown.length === 0 ? (
        <EmptyState
          message={query ? `No matches for “${query}”.` : 'Nobody in this state right now.'}
          suggestions={query ? undefined : ['Add contacts from the desktop', 'Search everything instead']}
          actionLabel={query ? undefined : 'Search everything'}
          onAction={query ? undefined : () => nav.navigate('Search')}
        />
      ) : null}

      <View style={{ marginTop: 6 }}>
        {shown.map((p, i) => (
          <PersonCard
            key={p.id ?? `${p.name}${i}`}
            p={p}
            index={i}
            onOpen={() => nav.navigate('PersonDetail', { person: p })}
          />
        ))}
      </View>
    </Screen>
  )
}

const styles = StyleSheet.create({
  search: {
    marginTop: 14,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: t.chipBg,
    borderWidth: 1,
    borderColor: t.cardBorder,
    fontSize: 14,
    color: t.text,
  },
  chipRow: { flexDirection: 'row', gap: 8, marginTop: 12, flexWrap: 'wrap' },
  personCard: { borderRadius: 14, paddingVertical: 13, paddingHorizontal: 14, marginTop: 8 },
  personTop: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontWeight: '700', fontSize: 15, color: t.cyanInk },
  name: { fontSize: 15, fontWeight: '600', color: t.text },
  title: { fontSize: 12.5, color: t.muted },
  historyRow: {
    marginTop: 11,
    paddingTop: 11,
    borderTopWidth: 1,
    borderTopColor: t.hairline,
    flexDirection: 'row',
    gap: 9,
  },
  historyDot: { width: 5, height: 5, borderRadius: 2.5, marginTop: 5 },
  history: { fontSize: 12.5, color: t.textSoft, lineHeight: 17.5 },
  last: { fontSize: 10.5, color: t.faint, fontFamily: fonts.mono, marginTop: 4, textTransform: 'uppercase' },
  actions: { flexDirection: 'row', gap: 8, marginTop: 10 },
  action: {
    backgroundColor: t.tintFillLo,
    borderColor: t.tintBorderLo,
    borderWidth: 1,
    borderRadius: 9,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  actionText: { color: t.cyanBright, fontSize: 12, fontWeight: '600' },
})
