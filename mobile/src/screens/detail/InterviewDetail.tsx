// Interview detail — overview, self-score, what landed / what didn't,
// verbatim quotes from the debrief, and the interview arc at this company.
import { useNavigation } from '@react-navigation/native'
import { Text, View } from 'react-native'
import { interviewSummary } from '../../lib/insights'
import { Interview, companyBundle, normName } from '../../lib/store'
import { countdownChip, interviewTimeLine } from '../../ui/format'
import {
  ActionRow,
  Bullets,
  DetailShell,
  MetaGrid,
  Meter,
  RelatedRow,
  Section,
  SummaryBlock,
  TimelineList,
} from '../../ui/detail'
import { ErrorState, LoadingState } from '../../ui/primitives'
import { fonts, t } from '../../ui/tokens'
import { useDatasets } from '../../ui/useDatasets'

function sameInterview(a: Interview, b: Interview): boolean {
  if (a.id != null && b.id != null) return a.id === b.id
  return normName(a.company) === normName(b.company) && a.interview_date === b.interview_date
}

export default function InterviewDetail({ route }: any) {
  const seed: Interview = route.params.interview
  const nav = useNavigation<any>()
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  const iv = ds?.interviews.find((i) => sameInterview(i, seed)) || seed
  const co = ds && iv.company ? companyBundle(ds, iv.company) : null
  const type = (iv.interview_type || 'interview').replace(/_/g, ' ')
  const others = (co?.interviews || []).filter((i) => !sameInterview(i, iv))
  const arc = co
    ? [...co.interviews].sort((a, b) => (a.interview_date || '').localeCompare(b.interview_date || ''))
    : []

  const quotes = (iv.verbatim_quotes || [])
    .map((q) => (typeof q === 'string' ? { quote: q } : q))
    .filter((q) => (q.quote || '').trim())

  return (
    <DetailShell
      kicker={iv.upcoming ? 'Upcoming interview' : 'Interview debrief'}
      title={[iv.company, type].filter(Boolean).join(' · ')}
      subtitle={iv.role}
      shareText={`${type} at ${iv.company}${iv.interview_date ? ` on ${iv.interview_date.slice(0, 10)}` : ''}`}
      refreshing={refreshing}
      onRefresh={refresh}
    >
      {iv.upcoming && iv.interview_date ? (
        <Text style={{ color: t.cyanBright, fontFamily: fonts.mono, fontWeight: '600', fontSize: 12, marginTop: 10 }}>
          {countdownChip(iv.interview_date)}
        </Text>
      ) : null}

      {loading && !ds ? <LoadingState /> : null}
      {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

      {ds ? <SummaryBlock sentences={interviewSummary(iv, ds)} /> : null}

      <Section label="Overview">
        <MetaGrid
          rows={[
            { label: 'Company', value: iv.company },
            { label: 'Role', value: iv.role },
            { label: 'Type', value: type },
            { label: 'When', value: interviewTimeLine(iv) || (iv.interview_date || '').slice(0, 10) },
            {
              label: 'Interviewer',
              value: iv.interviewer ? `${iv.interviewer}${iv.interviewer_role ? ` · ${iv.interviewer_role}` : ''}` : undefined,
            },
          ]}
        />
      </Section>

      {iv.self_rating != null ? (
        <Section label="Score">
          <View style={card}>
            <Meter label="Self-rating" value={iv.self_rating} />
          </View>
        </Section>
      ) : null}

      {iv.what_landed?.length ? (
        <Section label="What landed" count={iv.what_landed.length}>
          <Bullets items={iv.what_landed} color={t.green} />
        </Section>
      ) : null}

      {iv.what_didnt?.length ? (
        <Section label="What didn't" count={iv.what_didnt.length}>
          <Bullets items={iv.what_didnt} color={t.amber} />
        </Section>
      ) : null}

      {quotes.length ? (
        <Section label="Verbatim" count={quotes.length} initiallyOpen={false}>
          {quotes.map((q, i) => (
            <View key={i} style={[card, { borderLeftWidth: 3, borderLeftColor: t.cyan }]}>
              <Text style={{ color: t.textBody, fontSize: 13.5, lineHeight: 20, fontStyle: 'italic' }}>
                “{q.quote}”
              </Text>
              {q.speaker ? (
                <Text style={{ color: t.faint, fontSize: 11.5, marginTop: 6 }}>— {q.speaker}</Text>
              ) : null}
            </View>
          ))}
        </Section>
      ) : null}

      {arc.length > 1 ? (
        <Section label="Interview arc" count={arc.length}>
          <TimelineList
            items={arc.map((i) => ({
              title: (i.interview_type || 'interview').replace(/_/g, ' '),
              sub: sameInterview(i, iv) ? 'This interview' : i.interviewer ? `with ${i.interviewer}` : undefined,
              ts: i.interview_date,
              color: sameInterview(i, iv) ? t.cyanBright : i.upcoming ? t.amber : t.cyan,
            }))}
          />
        </Section>
      ) : null}

      {others.length || co?.jobs.length || co?.people.length ? (
        <Section label="Related" initiallyOpen={false}>
          {others.slice(0, 3).map((i, idx) => (
            <RelatedRow
              key={`iv${i.id ?? idx}`}
              title={(i.interview_type || 'interview').replace(/_/g, ' ')}
              sub={i.upcoming ? 'upcoming' : 'debriefed'}
              right={(i.interview_date || '').slice(0, 10)}
              onPress={() => nav.push('InterviewDetail', { interview: i })}
            />
          ))}
          {(co?.jobs || []).slice(0, 3).map((j) => (
            <RelatedRow
              key={`j${j.id}`}
              title={j.role}
              sub={j.status}
              right={Number(j.fitment_score) ? `${Number(j.fitment_score)} FIT` : undefined}
              onPress={() => nav.push('JobDetail', { job: j })}
            />
          ))}
          {(co?.people || []).slice(0, 3).map((p) => (
            <RelatedRow
              key={`p${p.id}`}
              title={p.name}
              sub={p.relationship}
              onPress={() => nav.push('PersonDetail', { person: p })}
            />
          ))}
        </Section>
      ) : null}

      <Section label="Quick actions">
        <ActionRow
          actions={[
            ...(iv.company
              ? [{ label: 'View company', onPress: () => nav.push('CompanyDetail', { name: iv.company }), primary: true }]
              : []),
            { label: 'All interviews', onPress: () => nav.navigate('Tabs', { screen: 'Interviews' }) },
          ]}
        />
      </Section>
    </DetailShell>
  )
}

const card = {
  marginTop: 10,
  borderRadius: 16,
  borderWidth: 1,
  borderColor: t.cardBorder,
  backgroundColor: t.card,
  padding: 15,
} as const
