// Person detail — every contact becomes a small CRM page: warmth status,
// tappable channels, relationship summary, notes, what's live at their
// company, and one-tap outreach actions.
import { useNavigation } from '@react-navigation/native'
import { Linking, Text, View } from 'react-native'
import { personSummary } from '../../lib/insights'
import { Person, companyBundle, contactChannels, daysSince } from '../../lib/store'
import {
  ActionRow,
  DetailShell,
  MetaGrid,
  RelatedRow,
  Section,
  SummaryBlock,
  TimelineList,
} from '../../ui/detail'
import { ErrorState, LoadingState, StatusChip } from '../../ui/primitives'
import { avatarPalette, t } from '../../ui/tokens'
import { useDatasets } from '../../ui/useDatasets'

const WARMTH: Record<string, { label: string; color: string; bg: string }> = {
  responded: { label: 'WARM · REPLIED', color: t.green, bg: 'rgba(111,211,160,.15)' },
  'follow-up': { label: 'FOLLOW-UP DUE', color: t.amber, bg: 'rgba(224,183,122,.15)' },
  sent: { label: 'AWAITING REPLY', color: t.amber, bg: 'rgba(224,183,122,.15)' },
  drafted: { label: 'DRAFTED', color: '#9BB0D0', bg: 'rgba(255,255,255,.06)' },
  none: { label: 'NOT CONTACTED', color: '#9BB0D0', bg: 'rgba(255,255,255,.06)' },
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
}

export default function PersonDetail({ route }: any) {
  const seed: Person = route.params.person
  const nav = useNavigation<any>()
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  const p = ds?.people.find((x) => x.id === seed.id) || seed
  const co = ds && p.company ? companyBundle(ds, p.company) : null
  const warmth = WARMTH[(p.outreach_status || 'none').toLowerCase()] || WARMTH.none
  const { email, phone, linkedin } = contactChannels(p)
  const open = (url: string) => Linking.openURL(url).catch(() => {})
  const gap = daysSince(p.last_contacted || p.last_updated)

  const actions = [
    ...(email
      ? [
          {
            label: 'Draft follow-up',
            onPress: () =>
              open(
                `mailto:${email}?subject=${encodeURIComponent('Following up')}&body=${encodeURIComponent(`Hi ${p.name.split(' ')[0]},\n\n`)}`,
              ),
            primary: true,
          },
        ]
      : []),
    ...(phone ? [{ label: 'Call', onPress: () => open(`tel:${phone.replace(/[^+\d]/g, '')}`) }] : []),
    ...(email ? [{ label: 'Email', onPress: () => open(`mailto:${email}`) }] : []),
    ...(linkedin
      ? [{ label: 'LinkedIn', onPress: () => open(linkedin.startsWith('http') ? linkedin : `https://${linkedin}`) }]
      : []),
    ...(p.company ? [{ label: 'View company', onPress: () => nav.push('CompanyDetail', { name: p.company }) }] : []),
  ]

  return (
    <DetailShell
      kicker={p.relationship || 'Contact'}
      title={p.name}
      subtitle={[p.relationship, p.company].filter(Boolean).join(' · ')}
      shareText={`${p.name}${p.company ? ` — ${p.company}` : ''}${linkedin ? `\n${linkedin}` : ''}`}
      refreshing={refreshing}
      onRefresh={refresh}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 12 }}>
        <View
          style={{
            width: 46,
            height: 46,
            borderRadius: 23,
            backgroundColor: avatarPalette[(p.id || 0) % avatarPalette.length],
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ fontWeight: '700', fontSize: 16, color: t.cyanInk }}>{initials(p.name)}</Text>
        </View>
        <View style={{ gap: 5, alignItems: 'flex-start' }}>
          <StatusChip {...warmth} />
          {gap != null && gap >= 0 ? (
            <Text style={{ fontSize: 11, color: gap > 14 ? t.amber : t.faint }}>
              Last touch {gap === 0 ? 'today' : `${gap} day${gap === 1 ? '' : 's'} ago`}
            </Text>
          ) : null}
        </View>
      </View>

      {loading && !ds ? <LoadingState /> : null}
      {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

      {ds ? <SummaryBlock sentences={personSummary(p, ds)} /> : null}

      {email || phone || linkedin ? (
        <Section label="Contact">
          {email ? <RelatedRow title={email} sub="Email" onPress={() => open(`mailto:${email}`)} /> : null}
          {phone ? <RelatedRow title={phone} sub="Phone" onPress={() => open(`tel:${phone.replace(/[^+\d]/g, '')}`)} /> : null}
          {linkedin ? (
            <RelatedRow
              title={linkedin.replace(/^https?:\/\/(www\.)?/, '')}
              sub="LinkedIn"
              onPress={() => open(linkedin.startsWith('http') ? linkedin : `https://${linkedin}`)}
            />
          ) : null}
        </Section>
      ) : null}

      {p.context || p.notes ? (
        <Section label="Notes">
          <View style={card}>
            {p.context ? (
              <Text style={{ color: t.textBody, fontSize: 13.5, lineHeight: 20 }}>{p.context}</Text>
            ) : null}
            {p.notes && p.notes !== p.context ? (
              <Text
                style={{ color: t.muted, fontSize: 13, lineHeight: 19, marginTop: p.context ? 10 : 0 }}
              >
                {p.notes}
              </Text>
            ) : null}
          </View>
        </Section>
      ) : null}

      <Section label="Status">
        <MetaGrid
          rows={[
            { label: 'Outreach', value: p.outreach_status || 'none' },
            { label: 'Last contact', value: (p.last_contacted || '').slice(0, 10) },
            { label: 'Updated', value: (p.last_updated || '').slice(0, 10) },
            { label: 'Tags', value: p.tags?.length ? p.tags.join(', ') : undefined },
          ]}
        />
      </Section>

      {co && (co.jobs.length || co.interviews.length) ? (
        <Section label={`Live at ${p.company}`}>
          {co.jobs.slice(0, 4).map((j) => (
            <RelatedRow
              key={`j${j.id}`}
              title={j.role}
              sub={j.status}
              right={Number(j.fitment_score) ? `${Number(j.fitment_score)} FIT` : undefined}
              onPress={() => nav.push('JobDetail', { job: j })}
            />
          ))}
          {co.interviews.slice(0, 3).map((iv, i) => (
            <RelatedRow
              key={`iv${iv.id ?? i}`}
              title={(iv.interview_type || 'interview').replace(/_/g, ' ')}
              sub={iv.upcoming ? 'upcoming' : 'debriefed'}
              right={(iv.interview_date || '').slice(0, 10)}
              onPress={() => nav.push('InterviewDetail', { interview: iv })}
            />
          ))}
        </Section>
      ) : null}

      {co && co.events.length ? (
        <Section label="Timeline" initiallyOpen={false} count={co.events.length}>
          <TimelineList items={co.events.slice(0, 8).map((e) => ({ title: e.title, sub: e.subtitle, ts: e.ts }))} />
        </Section>
      ) : null}

      <Section label="Suggested actions">
        <ActionRow actions={actions} />
        {!email && !phone && !linkedin ? (
          <Text style={{ color: t.faint, fontSize: 12, marginTop: 10, lineHeight: 17 }}>
            No channels on file — add contact info from the desktop to unlock one-tap outreach.
          </Text>
        ) : null}
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
