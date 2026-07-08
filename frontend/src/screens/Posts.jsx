import { useState } from 'react'
import useDesktopMode from '../shell/useDesktopMode.js'
import { nativeAnchorHandler } from '../shell/nativeOpen.js'
import {
  useApi, Screen, SectionHead, StatGrid, Stat,
  ExpandableCard, Chips, DetailLine, EYEBROW, fmtDate, fmtNum,
} from './_shared.jsx'

/* Posts — LinkedIn content pipeline and engagement.
   Data: GET /dashboard/posts/data (_posts_payload).

   Each post is an expandable card: collapsed shows title + date + a compact
   metric line; expanded reveals the full metric grid, every hashtag, the
   source slug, and the LinkedIn link. A search filter narrows by title /
   source / hashtag. */

function MetricCell({ label, value, tone }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 'var(--fw-bold)', fontSize: 'var(--fs-lg)', color: tone }}>
        {fmtNum(value)}
      </span>
      <span style={EYEBROW}>{label}</span>
    </div>
  )
}

function PostCard({ post }) {
  const useDesktopModeValue = useDesktopMode()
  const hasMetrics = (post.impressions || 0) + (post.reactions || 0) + (post.comments || 0) > 0
  const compact = hasMetrics
    ? `${fmtNum(post.impressions)} views \u00b7 ${fmtNum(post.reactions)} reactions`
    : 'No metrics logged'

  return (
    <ExpandableCard
      title={post.title || post.source || 'Untitled post'}
      subtitle={post.posted_date ? fmtDate(post.posted_date) : ''}
      right={
        <span style={{ color: hasMetrics ? 'var(--green-300)' : 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', whiteSpace: 'nowrap' }}>
          {compact}
        </span>
      }
    >
      {hasMetrics && (
        <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', marginBottom: 4 }}>
          <MetricCell label="Impressions" value={post.impressions} tone="var(--green-300)" />
          <MetricCell label="Reactions" value={post.reactions} tone="var(--cyan-300)" />
          <MetricCell label="Comments" value={post.comments} tone="var(--text-strong)" />
        </div>
      )}

      {Array.isArray(post.hashtags) && post.hashtags.length > 0 && (
        <DetailLine label="Hashtags">
          <div style={{ marginTop: 6 }}>
            <Chips items={post.hashtags} prefix="#" />
          </div>
        </DetailLine>
      )}

      {post.source && <DetailLine label="Source">{post.source}</DetailLine>}

      {post.url ? (
        <div style={{ marginTop: 12 }}>
          <a href={post.url} target="_blank" rel="noreferrer" onClick={nativeAnchorHandler(useDesktopModeValue, post.url)} style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>
            View on LinkedIn {'\u2197'}
          </a>
        </div>
      ) : (
        <div style={{ marginTop: 12, color: 'var(--faint)', fontSize: 'var(--fs-xs)' }}>No public URL logged.</div>
      )}
    </ExpandableCard>
  )
}

export default function Posts() {
  const { data, loading, error } = useApi('/dashboard/posts/data')
  const [q, setQ] = useState('')
  const posts = data?.posts || []

  const query = q.trim().toLowerCase()
  const shown = query
    ? posts.filter((p) => [p.title, p.source, ...(p.hashtags || [])].join(' ').toLowerCase().includes(query))
    : posts

  return (
    <Screen
      loading={loading}
      error={error}
      empty={!loading && !error && posts.length === 0}
      emptyLabel="No LinkedIn posts logged yet."
    >
      <StatGrid>
        <Stat label="Posts" value={data?.total ?? 0} tone="accent" />
        <Stat label="Impressions" value={fmtNum(data?.total_impressions)} tone="green" />
        <Stat label="Reactions" value={fmtNum(data?.total_reactions)} />
        <Stat label="Comments" value={fmtNum(data?.total_comments)} tone="muted" />
      </StatGrid>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter by title, source, hashtag\u2026'}
        style={{
          width: '100%', maxWidth: 440, marginBottom: 14, boxSizing: 'border-box',
          background: 'var(--surface-sunken)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', padding: '9px 11px',
          color: 'var(--text)', fontSize: 'var(--fs-sm)',
        }}
      />

      <SectionHead title="Posts" right={`${shown.length}${query ? ` of ${posts.length}` : ''}`} />
      <div style={{ display: 'grid', gap: 8 }}>
        {shown.map((p, i) => (
          <PostCard key={`${p.source || p.title}-${i}`} post={p} />
        ))}
      </div>
    </Screen>
  )
}
