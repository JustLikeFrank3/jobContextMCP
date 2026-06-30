import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge,
  List, Row, fmtDate, fmtNum,
} from './_shared.jsx'

/* Posts — LinkedIn content pipeline and engagement.
   Data: GET /dashboard/posts/data (_posts_payload). */
export default function Posts() {
  const { data, loading, error } = useApi('/dashboard/posts/data')
  const posts = data?.posts || []

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && posts.length === 0}
      emptyLabel="No LinkedIn posts logged yet."
    >
      <StatGrid>
        <Stat label="Posts" value={data?.total ?? 0} tone="accent" />
        <Stat label="Impressions" value={fmtNum(data?.total_impressions)} tone="green" />
        <Stat label="Reactions" value={fmtNum(data?.total_reactions)} />
        <Stat label="Comments" value={fmtNum(data?.total_comments)} tone="muted" />
      </StatGrid>

      <SectionHead title="Posts" right={`${posts.length}`} />
      <List>
        {posts.map((p, i) => (
          <Row
            key={`${p.source || p.title}-${i}`}
            title={p.title || p.source || 'Untitled post'}
            subtitle={Array.isArray(p.hashtags) && p.hashtags.length
              ? p.hashtags.map((h) => `#${h}`).join(' ')
              : ''}
            meta={p.posted_date ? fmtDate(p.posted_date) : ''}
            right={
              <div style={{ display: 'grid', gap: 4, justifyItems: 'end', fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)' }}>
                <span style={{ color: 'var(--green-300)' }}>{fmtNum(p.impressions)} views</span>
                <span style={{ color: 'var(--cyan-300)' }}>{fmtNum(p.reactions)} reactions</span>
                <span style={{ color: 'var(--muted)' }}>{fmtNum(p.comments)} comments</span>
              </div>
            }
          >
            {p.url && (
              <div style={{ marginTop: 8 }}>
                <a href={p.url} target="_blank" rel="noreferrer"
                  style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}>
                  View on LinkedIn {'\u2192'}
                </a>
              </div>
            )}
          </Row>
        ))}
      </List>
    </Screen>
  )
}
