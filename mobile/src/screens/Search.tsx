// Global search — one box over everything: jobs, companies, people,
// interviews, posts, check-ins. Grouped results with match highlighting,
// recent searches, and cross-cutting insights while the box is empty.
// Word-prefix scoring ("sta fa" finds "State Farm") with substring fallback.
import { useNavigation } from '@react-navigation/native'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { globalInsights } from '../lib/insights'
import { Datasets, allCompanies } from '../lib/store'
import { PressableScale } from '../ui/detail'
import { EmptyState, ErrorState, LoadingState } from '../ui/primitives'
import { fonts, t } from '../ui/tokens'
import { useDatasets } from '../ui/useDatasets'

// Session-scoped recent searches. Deliberately not persisted: search terms
// can name people/companies and the keychain is reserved for credentials.
let recentSearches: string[] = []

type Hit = {
  key: string
  group: string
  title: string
  sub?: string
  right?: string
  score: number
  go: (nav: any) => void
}

/** Every query word must prefix some word (or substring) of the haystack. */
function matchScore(query: string, haystack: string): number {
  const hay = haystack.toLowerCase()
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return 0
  let score = 0
  for (const w of words) {
    const idx = hay.indexOf(w)
    if (idx === -1) return 0
    // Word-boundary hits beat mid-word hits; early hits beat late ones.
    score += (idx === 0 || /[\s·,.-]/.test(hay[idx - 1] || '') ? 2 : 1) + 1 / (idx + 1)
  }
  return score
}

function buildHits(ds: Datasets, q: string): Hit[] {
  const hits: Hit[] = []
  const add = (h: Omit<Hit, 'score'>, haystack: string) => {
    const score = matchScore(q, haystack)
    if (score > 0) hits.push({ ...h, score })
  }

  allCompanies(ds).forEach((name) =>
    add(
      {
        key: `co:${name}`,
        group: 'Companies',
        title: name,
        go: (nav) => nav.push('CompanyDetail', { name }),
      },
      name,
    ),
  )
  ds.jobs.forEach((j) =>
    add(
      {
        key: `job:${j.id}`,
        group: 'Jobs',
        title: j.role || 'Untitled role',
        sub: j.company,
        right: Number(j.fitment_score) ? `${Number(j.fitment_score)} FIT` : undefined,
        go: (nav) => nav.push('JobDetail', { job: j }),
      },
      `${j.role} ${j.company} ${j.status}`,
    ),
  )
  ds.people.forEach((p) =>
    add(
      {
        key: `p:${p.id}`,
        group: 'People',
        title: p.name,
        sub: [p.relationship, p.company].filter(Boolean).join(' · '),
        go: (nav) => nav.push('PersonDetail', { person: p }),
      },
      `${p.name} ${p.company} ${p.relationship} ${p.context} ${p.notes}`,
    ),
  )
  ds.interviews.forEach((iv, i) =>
    add(
      {
        key: `iv:${iv.id ?? i}`,
        group: 'Interviews',
        title: [iv.company, (iv.interview_type || '').replace(/_/g, ' ')].filter(Boolean).join(' · '),
        sub: iv.upcoming ? 'upcoming' : 'debriefed',
        right: (iv.interview_date || '').slice(0, 10),
        go: (nav) => nav.push('InterviewDetail', { interview: iv }),
      },
      `${iv.company} ${iv.role} ${iv.interview_type} ${iv.interviewer}`,
    ),
  )
  ds.posts.forEach((p) =>
    add(
      {
        key: `post:${p.id}`,
        group: 'Posts',
        title: p.title || p.text.slice(0, 60),
        sub: (p.posted_date || '').slice(0, 10),
        go: (nav) => nav.push('PostDetail', { post: p }),
      },
      `${p.title} ${p.text} ${(p.hashtags || []).join(' ')}`,
    ),
  )
  ds.checkins.forEach((c, i) =>
    add(
      {
        key: `ci:${c.date}${i}`,
        group: 'Wellbeing',
        title: `${c.mood || 'Check-in'} · ${c.date.slice(0, 10)}`,
        sub: c.notes?.slice(0, 80),
        go: (nav) => nav.push('CheckinDetail', { entry: c }),
      },
      `${c.mood} ${c.notes} ${c.date}`,
    ),
  )
  return hits.sort((a, b) => b.score - a.score)
}

/** Bold the query-word matches inside a result line. */
function Highlight({ text, query, style }: { text: string; query: string; style: any }) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return <Text style={style}>{text}</Text>
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const splitter = new RegExp(`(${escaped.join('|')})`, 'ig')
  // Separate anchored tester — reusing the /g splitter for .test() would
  // carry lastIndex state between parts and mis-highlight.
  const tester = new RegExp(`^(?:${escaped.join('|')})$`, 'i')
  const parts = text.split(splitter)
  return (
    <Text style={style} numberOfLines={1}>
      {parts.map((part, i) =>
        tester.test(part) ? (
          <Text key={i} style={{ color: t.cyanBright, fontWeight: '700' }}>
            {part}
          </Text>
        ) : (
          part
        ),
      )}
    </Text>
  )
}

const GROUP_ORDER = ['Companies', 'Jobs', 'People', 'Interviews', 'Posts', 'Wellbeing']

export default function Search({ route }: any) {
  const nav = useNavigation<any>()
  const insets = useSafeAreaInsets()
  const [query, setQuery] = useState<string>(route.params?.initialQuery || '')
  const { data: ds, loading, error, refresh } = useDatasets()
  const inputRef = useRef<TextInput>(null)
  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 350) // after push animation
    return () => clearTimeout(timer)
  }, [])

  const hits = useMemo(() => (ds && query.trim() ? buildHits(ds, query.trim()) : []), [ds, query])
  const grouped = useMemo(() => {
    const map = new Map<string, Hit[]>()
    hits.forEach((h) => {
      if (!map.has(h.group)) map.set(h.group, [])
      map.get(h.group)!.push(h)
    })
    return GROUP_ORDER.filter((g) => map.has(g)).map((g) => ({ group: g, hits: map.get(g)!.slice(0, 5) }))
  }, [hits])

  const commit = (h: Hit) => {
    const q = query.trim()
    if (q) recentSearches = [q, ...recentSearches.filter((r) => r !== q)].slice(0, 8)
    h.go(nav)
  }

  return (
    <View style={[styles.root, { paddingTop: insets.top + 8 }]}>
      <View style={styles.searchRow}>
        <Pressable onPress={() => nav.goBack()} hitSlop={12} style={styles.backBtn}>
          <Text style={styles.backText}>‹</Text>
        </Pressable>
        <TextInput
          ref={inputRef}
          style={styles.input}
          value={query}
          onChangeText={setQuery}
          placeholder="Search jobs, people, companies, notes…"
          placeholderTextColor={t.faint}
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="search"
        />
        {query ? (
          <Pressable onPress={() => setQuery('')} hitSlop={10}>
            <Text style={styles.clear}>×</Text>
          </Pressable>
        ) : null}
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingHorizontal: 18, paddingBottom: 28 }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {loading && !ds ? <LoadingState /> : null}
        {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

        {ds && !query.trim() ? (
          <>
            {recentSearches.length ? (
              <>
                <Text style={styles.section}>RECENT</Text>
                <View style={styles.recentWrap}>
                  {recentSearches.map((r) => (
                    <Pressable key={r} onPress={() => setQuery(r)} style={styles.recentChip}>
                      <Text style={styles.recentText}>{r}</Text>
                    </Pressable>
                  ))}
                </View>
              </>
            ) : null}
            {globalInsights(ds).length ? (
              <>
                <Text style={styles.section}>WHILE YOU'RE HERE</Text>
                {globalInsights(ds).map((s) => (
                  <View key={s} style={styles.insightCard}>
                    <Text style={styles.insightText}>{s}</Text>
                  </View>
                ))}
              </>
            ) : null}
            <Text style={styles.hint}>
              One search covers your whole search: pipeline, contacts, interviews, posts, and journal.
            </Text>
          </>
        ) : null}

        {ds && query.trim() && !hits.length ? (
          <EmptyState
            message={`No matches for “${query.trim()}”.`}
            suggestions={['Try fewer words', 'Company names and people work best']}
          />
        ) : null}

        {grouped.map(({ group, hits: rows }) => (
          <View key={group}>
            <Text style={styles.section}>{group.toUpperCase()}</Text>
            {rows.map((h) => (
              <PressableScale key={h.key} onPress={() => commit(h)} style={styles.hitRow}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Highlight text={h.title} query={query} style={styles.hitTitle} />
                  {h.sub ? <Highlight text={h.sub} query={query} style={styles.hitSub} /> : null}
                </View>
                {h.right ? <Text style={styles.hitRight}>{h.right}</Text> : null}
                <Text style={styles.hitArrow}>›</Text>
              </PressableScale>
            ))}
          </View>
        ))}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: t.bg },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 18,
    paddingBottom: 12,
  },
  backBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: t.chipBg,
    borderWidth: 1,
    borderColor: t.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backText: { color: t.textBright, fontSize: 22, lineHeight: 24, fontWeight: '600' },
  input: {
    flex: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: t.chipBg,
    borderWidth: 1,
    borderColor: t.tintBorder,
    fontSize: 15,
    color: t.text,
  },
  clear: { color: t.muted, fontSize: 22, paddingHorizontal: 4 },
  section: {
    fontSize: 11.5,
    fontWeight: '600',
    letterSpacing: 1.2,
    color: t.muted2,
    fontFamily: fonts.mono,
    marginTop: 20,
    marginBottom: 4,
  },
  recentWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  recentChip: {
    backgroundColor: t.chipBg,
    borderRadius: 999,
    paddingHorizontal: 13,
    paddingVertical: 7,
    borderWidth: 1,
    borderColor: t.cardBorder,
  },
  recentText: { color: t.textSecondary, fontSize: 12.5 },
  insightCard: {
    marginTop: 8,
    borderRadius: 14,
    padding: 13,
    backgroundColor: t.tintFillLo,
    borderWidth: 1,
    borderColor: t.tintBorderLo,
  },
  insightText: { color: t.textBody, fontSize: 13, lineHeight: 18.5 },
  hint: { color: t.faint, fontSize: 12.5, lineHeight: 18, marginTop: 24, textAlign: 'center', paddingHorizontal: 20 },
  hitRow: {
    marginTop: 8,
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 14,
    backgroundColor: t.card,
    borderWidth: 1,
    borderColor: t.cardBorder,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  hitTitle: { fontSize: 14, fontWeight: '600', color: t.text },
  hitSub: { fontSize: 12, color: t.muted, marginTop: 1 },
  hitRight: { fontSize: 10.5, color: t.cyanBright, fontFamily: fonts.mono, fontWeight: '600' },
  hitArrow: { fontSize: 16, color: t.muted2 },
})
