// Company detail — companies become first-class objects, assembled
// client-side by joining jobs, interviews, people, and events on the
// company name. Reached from any card that mentions a company.
import { useNavigation } from '@react-navigation/native'
import { Text, View } from 'react-native'
import { companySummary } from '../../lib/insights'
import { companyBundle } from '../../lib/store'
import {
  ActionRow,
  DetailShell,
  RelatedRow,
  Section,
  SummaryBlock,
  TimelineList,
} from '../../ui/detail'
import { EmptyState, ErrorState, LoadingState, StatTile } from '../../ui/primitives'
import { stageStyle, t } from '../../ui/tokens'
import { useDatasets } from '../../ui/useDatasets'

export default function CompanyDetail({ route }: any) {
  const name: string = route.params.name
  const nav = useNavigation<any>()
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  const co = ds ? companyBundle(ds, name) : null
  const upcoming = co?.interviews.filter((i) => i.upcoming) || []

  return (
    <DetailShell
      kicker="Company"
      title={name}
      subtitle={
        co
          ? `${co.jobs.length} jobs · ${co.interviews.length} interviews · ${co.people.length} contacts`
          : undefined
      }
      shareText={`${name} — tracked in jobContext`}
      refreshing={refreshing}
      onRefresh={refresh}
    >
      {loading && !ds ? <LoadingState /> : null}
      {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

      {co ? (
        <>
          <SummaryBlock sentences={companySummary(co)} />

          <View style={{ flexDirection: 'row', gap: 10, marginTop: 18 }}>
            <StatTile value={co.jobs.length} label="Jobs" />
            <StatTile value={co.interviews.length} label="Interviews" accent={upcoming.length > 0} />
            <StatTile value={co.people.length} label="Contacts" />
          </View>

          {co.jobs.length ? (
            <Section label="Open jobs" count={co.jobs.length}>
              {co.jobs.map((j) => (
                <RelatedRow
                  key={j.id}
                  title={j.role}
                  sub={(stageStyle[(j.status || 'pending').toLowerCase()] || stageStyle.pending).label}
                  right={Number(j.fitment_score) ? `${Number(j.fitment_score)} FIT` : undefined}
                  onPress={() => nav.push('JobDetail', { job: j })}
                />
              ))}
            </Section>
          ) : null}

          {co.interviews.length ? (
            <Section label="Interviews" count={co.interviews.length}>
              {co.interviews.map((iv, i) => (
                <RelatedRow
                  key={iv.id ?? i}
                  title={(iv.interview_type || 'interview').replace(/_/g, ' ')}
                  sub={iv.upcoming ? 'upcoming' : iv.interviewer ? `with ${iv.interviewer}` : 'debriefed'}
                  right={(iv.interview_date || '').slice(0, 10)}
                  onPress={() => nav.push('InterviewDetail', { interview: iv })}
                />
              ))}
            </Section>
          ) : null}

          {co.people.length ? (
            <Section label="People" count={co.people.length}>
              {co.people.map((p) => (
                <RelatedRow
                  key={p.id}
                  title={p.name}
                  sub={p.relationship}
                  right={(p.outreach_status || '').toUpperCase() || undefined}
                  onPress={() => nav.push('PersonDetail', { person: p })}
                />
              ))}
            </Section>
          ) : null}

          {co.events.length ? (
            <Section label="Timeline" count={co.events.length} initiallyOpen={false}>
              <TimelineList
                items={co.events.slice(0, 12).map((e) => ({ title: e.title, sub: e.subtitle, ts: e.ts }))}
              />
            </Section>
          ) : null}

          {!co.jobs.length && !co.interviews.length && !co.people.length ? (
            <EmptyState
              message={`Nothing tracked for ${name} yet.`}
              suggestions={['Share a job posting from this company', 'Add a contact from the desktop']}
            />
          ) : null}

          <Section label="Quick actions">
            <ActionRow
              actions={[
                { label: 'Search everything', onPress: () => nav.push('Search', { initialQuery: name }), primary: true },
                { label: 'Pipeline', onPress: () => nav.navigate('Tabs', { screen: 'Pipeline' }) },
              ]}
            />
          </Section>
        </>
      ) : null}
    </DetailShell>
  )
}
