// Post detail — full content (list cards clamp at 4 lines), metrics with
// performance-vs-average context, and the update/open/share actions.
import { useNavigation } from '@react-navigation/native'
import { Linking, Text, View } from 'react-native'
import { postSummary } from '../../lib/insights'
import { Post } from '../../lib/store'
import { ActionRow, DetailShell, MetaGrid, Meter, Section, SummaryBlock } from '../../ui/detail'
import { ErrorState, LoadingState, StatTile } from '../../ui/primitives'
import { fmtK, fonts, t } from '../../ui/tokens'
import { useDatasets } from '../../ui/useDatasets'

export default function PostDetail({ route }: any) {
  const seed: Post = route.params.post
  const nav = useNavigation<any>()
  const { data: ds, loading, refreshing, error, refresh } = useDatasets()

  const post = ds?.posts.find((p) => p.id === seed.id) || seed
  const n = ds?.posts.length || 0
  const avgImp = n ? (ds!.postTotals.impressions || 0) / n : 0
  const engagement = post.impressions > 0 ? ((post.reactions + post.comments) / post.impressions) * 100 : 0
  const vsAvg = avgImp > 0 ? Math.min(200, Math.round((post.impressions / avgImp) * 100)) : 0

  return (
    <DetailShell
      kicker="LinkedIn post"
      title={post.title || 'Post'}
      subtitle={(post.posted_date || '').slice(0, 10)}
      shareText={post.url || post.text}
      refreshing={refreshing}
      onRefresh={refresh}
    >
      {loading && !ds ? <LoadingState /> : null}
      {error && !ds ? <ErrorState message={error} onRetry={refresh} /> : null}

      {ds ? <SummaryBlock sentences={postSummary(post, ds)} /> : null}

      <View style={{ flexDirection: 'row', gap: 10, marginTop: 18 }}>
        <StatTile value={fmtK(post.impressions)} label="Impressions" />
        <StatTile value={fmtK(post.reactions)} label="Reactions" />
        <StatTile value={fmtK(post.comments)} label="Comments" accent />
      </View>

      {post.impressions > 0 ? (
        <Section label="Performance">
          <View style={card}>
            <Meter label="Engagement %" value={Number(engagement.toFixed(1))} max={Math.max(5, Math.ceil(engagement))} />
            {vsAvg > 0 ? <Meter label="vs your avg" value={vsAvg} max={200} /> : null}
            <Text style={{ color: t.faint, fontSize: 11, marginTop: 10, lineHeight: 15 }}>
              "vs your avg" caps at 2× — 100 means an average post.
            </Text>
          </View>
        </Section>
      ) : null}

      <Section label="Content">
        <View style={card}>
          <Text style={{ color: t.textBright, fontSize: 14, lineHeight: 21 }}>{post.text}</Text>
          {post.hashtags?.length ? (
            <Text style={{ marginTop: 12, fontSize: 12, color: t.cyanBright, fontFamily: fonts.mono }}>
              {post.hashtags.map((h) => (h.startsWith('#') ? h : `#${h}`)).join(' ')}
            </Text>
          ) : null}
        </View>
      </Section>

      <Section label="Details" initiallyOpen={false}>
        <MetaGrid
          rows={[
            { label: 'Published', value: (post.posted_date || '').slice(0, 10) },
            { label: 'Source', value: post.source },
            { label: 'Words', value: post.text ? post.text.trim().split(/\s+/).length : undefined },
          ]}
        />
      </Section>

      <Section label="Quick actions">
        <ActionRow
          actions={[
            ...(post.url
              ? [{ label: 'Open on LinkedIn', onPress: () => Linking.openURL(post.url!).catch(() => {}), primary: true }]
              : []),
            { label: 'Update metrics', onPress: () => nav.navigate('Tabs', { screen: 'Posts' }) },
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
