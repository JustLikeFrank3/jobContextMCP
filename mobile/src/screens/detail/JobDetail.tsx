// Job detail — every pipeline card opens here. Surfaces the assessment
// detail, materials, and company relationships the list card has no room
// for, plus the company's activity timeline.
import { useNavigation } from '@react-navigation/native'
import { Linking, Text, View } from 'react-native'
import { jobSummary } from '../../lib/insights'
import { Job, companyBundle, daysSince } from '../../lib/store'
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
import { stageStyle, t } from '../../ui/tokens'
import { useDatasets } from '../../ui/useDatasets'

export default function JobDetail({ route }: any) {
  const seed: Job = route.params.job
  const nav = useNavigation<any>()
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  const job = ds?.jobs.find((j) => j.id === seed.id) || seed
  const stage = stageStyle[(job.status || 'pending').toLowerCase()] || stageStyle.pending
  const score = Number(job.fitment_score) || 0
  const co = ds ? companyBundle(ds, job.company) : null
  const age = daysSince(job.added_date)
  const sourceUrl = /^https?:\/\//i.test(job.source || '') ? job.source : undefined

  const actions = [
    ...(sourceUrl
      ? [{ label: 'Open posting', onPress: () => Linking.openURL(sourceUrl).catch(() => {}), primary: true }]
      : []),
    { label: 'View company', onPress: () => nav.push('CompanyDetail', { name: job.company }) },
  ]

  return (
    <DetailShell
      kicker="Job"
      title={job.role || 'Untitled role'}
      subtitle={job.company}
      shareText={`${job.role} at ${job.company}${score ? ` — fit score ${score}` : ''}${sourceUrl ? `\n${sourceUrl}` : ''}`}
      refreshing={refreshing}
      onRefresh={refresh}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <StatusChip label={stage.label} color={stage.color} bg={stage.bg} />
        {score > 0 ? <Text style={{ color: t.cyanBright, fontWeight: '700', fontSize: 15 }}>{score} FIT</Text> : null}
      </View>

      {loading && !ds ? <LoadingState /> : null}
      {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

      {ds ? <SummaryBlock sentences={jobSummary(job, ds)} /> : null}

      <Section label="Overview">
        <MetaGrid
          rows={[
            { label: 'Company', value: job.company },
            { label: 'Status', value: stage.label },
            { label: 'Fit score', value: score || undefined },
            { label: 'Added', value: (job.added_date || '').slice(0, 10) },
            { label: 'In pipeline', value: age != null && age >= 0 ? `${age} day${age === 1 ? '' : 's'}` : undefined },
            { label: 'Source', value: sourceUrl ? undefined : job.source },
          ]}
        />
      </Section>

      {job.assessment_detail || job.assessment_summary ? (
        <Section label="Assessment">
          <View style={cardStyle}>
            <Text style={{ color: t.textBody, fontSize: 13.5, lineHeight: 20 }}>
              {job.assessment_detail || job.assessment_summary}
            </Text>
            {job.decision_notes ? (
              <Text style={{ color: t.muted, fontSize: 12.5, lineHeight: 18, marginTop: 10 }}>
                Decision: {job.decision_notes}
              </Text>
            ) : null}
          </View>
        </Section>
      ) : null}

      {job.selected_resume || job.recommended_resume || job.last_edited_cover_letter ? (
        <Section label="Materials" initiallyOpen={false}>
          <MetaGrid
            rows={[
              { label: 'Resume', value: job.selected_resume || job.recommended_resume },
              { label: 'Tailored', value: job.last_edited_resume },
              { label: 'Cover letter', value: job.last_edited_cover_letter },
            ]}
          />
          <Text style={{ color: t.faint, fontSize: 11.5, marginTop: 8, lineHeight: 16 }}>
            Generate and edit materials from the desktop — they sync here.
          </Text>
        </Section>
      ) : null}

      {co && (co.people.length || co.interviews.length || co.jobs.length > 1) ? (
        <Section label={`At ${job.company}`}>
          {co.interviews.slice(0, 3).map((iv, i) => (
            <RelatedRow
              key={`iv${iv.id ?? i}`}
              title={`${(iv.interview_type || 'interview').replace(/_/g, ' ')}${iv.upcoming ? ' · upcoming' : ''}`}
              sub={iv.interviewer ? `with ${iv.interviewer}` : undefined}
              right={(iv.interview_date || '').slice(0, 10)}
              onPress={() => nav.push('InterviewDetail', { interview: iv })}
            />
          ))}
          {co.people.slice(0, 3).map((p) => (
            <RelatedRow
              key={`p${p.id}`}
              title={p.name}
              sub={p.relationship}
              right={(p.outreach_status || '').toUpperCase()}
              onPress={() => nav.push('PersonDetail', { person: p })}
            />
          ))}
          {co.jobs
            .filter((j) => j.id !== job.id)
            .slice(0, 3)
            .map((j) => (
              <RelatedRow
                key={`j${j.id}`}
                title={j.role}
                sub={(stageStyle[(j.status || 'pending').toLowerCase()] || stageStyle.pending).label}
                right={Number(j.fitment_score) ? `${Number(j.fitment_score)} FIT` : undefined}
                onPress={() => nav.push('JobDetail', { job: j })}
              />
            ))}
        </Section>
      ) : null}

      {co && co.events.length ? (
        <Section label="Timeline" initiallyOpen={false} count={co.events.length}>
          <TimelineList
            items={co.events.slice(0, 10).map((e) => ({ title: e.title, sub: e.subtitle, ts: e.ts }))}
          />
        </Section>
      ) : null}

      <Section label="Quick actions">
        <ActionRow actions={actions} />
      </Section>
    </DetailShell>
  )
}

const cardStyle = {
  marginTop: 10,
  borderRadius: 16,
  borderWidth: 1,
  borderColor: t.cardBorder,
  backgroundColor: t.card,
  padding: 15,
} as const
