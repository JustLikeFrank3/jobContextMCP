// Wellbeing check-in detail — one entry with its journal text in full,
// energy vs your recent average, and the surrounding week's trend.
import { useNavigation } from '@react-navigation/native'
import { Text, View } from 'react-native'
import { checkinSummary } from '../../lib/insights'
import { Checkin } from '../../lib/store'
import { ActionRow, DetailShell, MetaGrid, Meter, Section, SummaryBlock } from '../../ui/detail'
import { ErrorState, LoadingState } from '../../ui/primitives'
import { fonts, t } from '../../ui/tokens'
import { useDatasets } from '../../ui/useDatasets'

export default function CheckinDetail({ route }: any) {
  const entry: Checkin = route.params.entry
  const nav = useNavigation<any>()
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  // The week around this entry, oldest first, for the mini trend.
  const idx = ds?.checkins.findIndex((c) => c.date === entry.date) ?? -1
  const week = idx >= 0 ? ds!.checkins.slice(idx, idx + 7).reverse() : []
  const energies = (ds?.checkins || []).map((c) => c.energy || 0).filter((e) => e > 0)
  const avg = energies.length ? energies.reduce((a, b) => a + b, 0) / energies.length : 0

  return (
    <DetailShell
      kicker="Check-in"
      title={(entry.mood || 'Check-in').replace(/^\w/, (c) => c.toUpperCase())}
      subtitle={(entry.date || '').slice(0, 10)}
      shareText={`Check-in ${entry.date?.slice(0, 10)}: ${entry.mood || ''}${entry.energy ? `, energy ${entry.energy}/10` : ''}`}
      refreshing={refreshing}
      onRefresh={refresh}
    >
      {loading && !ds ? <LoadingState /> : null}
      {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

      {ds ? <SummaryBlock sentences={checkinSummary(entry, ds)} /> : null}

      <Section label="Levels">
        <View style={card}>
          {typeof entry.energy === 'number' ? <Meter label="Energy" value={entry.energy} /> : null}
          {avg > 0 ? <Meter label="Your average" value={Number(avg.toFixed(1))} /> : null}
        </View>
      </Section>

      {entry.notes ? (
        <Section label="Journal">
          <View style={card}>
            <Text style={{ color: t.textBody, fontSize: 13.5, lineHeight: 20 }}>{entry.notes}</Text>
          </View>
        </Section>
      ) : null}

      <Section label="Details" initiallyOpen={false}>
        <MetaGrid
          rows={[
            { label: 'Date', value: (entry.date || '').slice(0, 10) },
            { label: 'Mood', value: entry.mood },
            { label: 'Productive', value: entry.productive == null ? undefined : entry.productive ? 'Yes' : 'No' },
          ]}
        />
      </Section>

      {week.length > 1 ? (
        <Section label="That week">
          <View style={[card, { flexDirection: 'row', alignItems: 'flex-end', gap: 8, height: 110 }]}>
            {week.map((c, i) => (
              <View key={c.date + i} style={{ flex: 1, alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                <View
                  style={{
                    width: '100%',
                    borderRadius: 6,
                    height: Math.max(6, ((c.energy || 0) / 10) * 64),
                    backgroundColor: c.date === entry.date ? t.cyan : 'rgba(0,181,200,.35)',
                  }}
                />
                <Text style={{ fontSize: 9, color: t.faint, fontFamily: fonts.mono }}>{c.date.slice(5, 10)}</Text>
              </View>
            ))}
          </View>
        </Section>
      ) : null}

      <Section label="Quick actions">
        <ActionRow
          actions={[{ label: 'New check-in', onPress: () => nav.navigate('Tabs', { screen: 'Wellbeing' }), primary: true }]}
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
