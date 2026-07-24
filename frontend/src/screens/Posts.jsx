import { useState } from 'react'
import { createPortal } from 'react-dom'
import useDesktopMode from '../shell/useDesktopMode.js'
import { nativeAnchorHandler } from '../shell/nativeOpen.js'
import { useToolbarSlot } from '../shell/toolbarSlot.jsx'
import { apiPost } from '../auth/api.js'
import { useApi, Screen, fmtDate } from './_shared.jsx'
import ImportFlow, { StepIndicator } from './posts/ImportFlow.jsx'
import { fmtK } from './posts/csv.js'

/* Posts — LinkedIn content + engagement, per the desktop design handoff.
   Data: GET /dashboard/posts/data (_posts_payload).

   List mode: aggregate metric strip, post cards (text, cyan hashtag line,
   ◎/♥/💬 mono metrics, Update button → metrics sheet), search filter.
   Import mode: the 3-step LinkedIn CSV flow (ImportFlow); the toolbar slot
   carries the "Import from LinkedIn" action or the 1·2·3 step indicator. */

const MONO = { fontFamily: 'var(--font-mono)' }

function MetricSheet({ post, onClose, onSaved }) {
  const digits = (v) => v.replace(/[^0-9]/g, '')
  const [imp, setImp] = useState(String(post.impressions || ''))
  const [rx, setRx] = useState(String(post.reactions || ''))
  const [cm, setCm] = useState(String(post.comments || ''))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function save() {
    setBusy(true)
    setErr('')
    try {
      await apiPost('/dashboard/posts/metrics', {
        post_id: post.id,
        impressions: +imp || 0,
        reactions: +rx || 0,
        comments: +cm || 0,
      })
      onSaved()
    } catch (e) {
      setErr(e?.body?.detail || e.message || 'Could not save.')
      setBusy(false)
    }
  }

  const label = { fontSize: 11, fontWeight: 'var(--fw-semibold)', letterSpacing: 1, color: '#7C8AA6', ...MONO }
  const input = {
    marginTop: 6, width: '100%', boxSizing: 'border-box', background: 'rgba(255,255,255,.05)',
    border: '1px solid rgba(255,255,255,.12)', borderRadius: 12, padding: '11px 13px',
    color: 'var(--text)', fontSize: 15, fontFamily: 'var(--font-sans)', outline: 'none',
  }

  // Portal to <body> — same containing-block trap as pipeline's Modal:
  // .jc-page animates `transform`, which captures fixed descendants.
  return createPortal(
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{ position: 'fixed', inset: 0, zIndex: 90, background: 'rgba(4,7,14,.66)', backdropFilter: 'blur(3px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
    >
      <div style={{ width: 440, maxWidth: '100%', background: '#0E1524', borderRadius: 20, border: '1px solid rgba(255,255,255,.1)', padding: 24, boxShadow: '0 30px 80px rgba(0,0,0,.6)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 18, fontWeight: 'var(--fw-bold)', color: 'var(--text)' }}>Update metrics</div>
          <div onClick={onClose} style={{ cursor: 'pointer', color: '#8A99B5', fontSize: 24, lineHeight: 1 }}>×</div>
        </div>
        <div style={{ marginTop: 6, fontSize: '12.5px', color: '#8A99B5', lineHeight: 1.4, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {post.text || post.title}
        </div>
        <div style={{ marginTop: 18 }}>
          <div style={label}>IMPRESSIONS</div>
          <input type="text" inputMode="numeric" value={imp} onChange={(e) => setImp(digits(e.target.value))} style={input} />
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={label}>REACTIONS</div>
            <input type="text" inputMode="numeric" value={rx} onChange={(e) => setRx(digits(e.target.value))} style={input} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={label}>COMMENTS</div>
            <input type="text" inputMode="numeric" value={cm} onChange={(e) => setCm(digits(e.target.value))} style={input} />
          </div>
        </div>
        {err && <div style={{ marginTop: 12, color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)' }}>{err}</div>}
        <div onClick={busy ? undefined : save} style={{ marginTop: 22, textAlign: 'center', background: 'var(--cyan-500)', color: '#04222A', fontWeight: 'var(--fw-bold)', fontSize: 15, padding: 13, borderRadius: 14, cursor: busy ? 'wait' : 'pointer' }}>
          {busy ? 'Saving…' : 'Save metrics'}
        </div>
      </div>
    </div>,
    document.body,
  )
}

function PostCard({ post, isDesktop, onEdit }) {
  const tags = (post.hashtags || []).map((t) => `#${t}`).join(' ')
  return (
    <div style={{ borderRadius: 16, padding: '16px 18px', background: 'rgba(255,255,255,.045)', border: '1px solid rgba(255,255,255,.08)', display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: 14, color: '#E8EFFB', lineHeight: 1.4 }}>
          {post.text || post.title || post.source || 'Untitled post'}
        </div>
        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          {tags && <span style={{ fontSize: 12, color: 'var(--cyan-300)', ...MONO }}>{tags}</span>}
          {post.posted_date && <span style={{ fontSize: 11, color: '#6B7A96', ...MONO }}>{fmtDate(post.posted_date) || post.posted_date}</span>}
          {post.url && (
            <a href={post.url} target="_blank" rel="noreferrer" onClick={nativeAnchorHandler(isDesktop, post.url)} style={{ fontSize: 12, color: 'var(--cyan-300)', textDecoration: 'none' }}>
              View on LinkedIn ↗
            </a>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 20, fontSize: '12.5px', color: '#8A99B5', ...MONO, flexShrink: 0 }}>
        <span>◎ {fmtK(post.impressions)}</span>
        <span>♥ {fmtK(post.reactions)}</span>
        <span>💬 {fmtK(post.comments)}</span>
      </div>
      <div onClick={onEdit} style={{ cursor: 'pointer', fontSize: 12, fontWeight: 'var(--fw-semibold)', color: 'var(--cyan-300)', background: 'rgba(0,181,200,.12)', border: '1px solid rgba(0,181,200,.24)', padding: '7px 14px', borderRadius: 9, flexShrink: 0 }}>
        Update
      </div>
    </div>
  )
}

export default function Posts() {
  const { data, loading, error, reload } = useApi('/dashboard/posts/data')
  const isDesktop = useDesktopMode()
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('list') // list | import
  const [step, setStep] = useState(1)
  const [sheetPost, setSheetPost] = useState(null)

  const importing = mode === 'import'

  useToolbarSlot(
    importing ? (
      <StepIndicator step={step} />
    ) : (
      <div
        onClick={() => { setMode('import'); setStep(1) }}
        style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 'var(--fw-bold)', color: '#04222A', background: 'var(--cyan-500)', padding: '9px 16px', borderRadius: 10, boxShadow: '0 4px 14px rgba(0,181,200,.25)' }}
      >
        ↧ Import from LinkedIn
      </div>
    ),
    [importing, step],
  )

  if (importing) {
    return (
      <ImportFlow
        step={step}
        setStep={setStep}
        onDone={() => { setMode('list'); reload() }}
        onCancel={() => setMode('list')}
      />
    )
  }

  const posts = data?.posts || []
  const query = q.trim().toLowerCase()
  const shown = query
    ? posts.filter((p) => [p.text, p.title, p.source, ...(p.hashtags || [])].join(' ').toLowerCase().includes(query))
    : posts

  return (
    <Screen loading={loading} error={error} empty={false}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 150, padding: '16px 18px', borderRadius: 16, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.07)' }}>
          <div style={{ fontSize: 24, fontWeight: 'var(--fw-bold)', color: 'var(--text)' }}>{fmtK(data?.total_impressions)}</div>
          <div style={{ fontSize: '11.5px', color: '#8A99B5', marginTop: 2 }}>Impressions</div>
        </div>
        <div style={{ flex: 1, minWidth: 150, padding: '16px 18px', borderRadius: 16, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.07)' }}>
          <div style={{ fontSize: 24, fontWeight: 'var(--fw-bold)', color: 'var(--text)' }}>{fmtK(data?.total_reactions)}</div>
          <div style={{ fontSize: '11.5px', color: '#8A99B5', marginTop: 2 }}>Reactions</div>
        </div>
        <div style={{ flex: 1, minWidth: 150, padding: '16px 18px', borderRadius: 16, background: 'rgba(0,181,200,.1)', border: '1px solid rgba(0,181,200,.22)' }}>
          <div style={{ fontSize: 24, fontWeight: 'var(--fw-bold)', color: 'var(--cyan-300)' }}>{data?.total ?? 0}</div>
          <div style={{ fontSize: '11.5px', color: '#8AB6C4', marginTop: 2 }}>Posts logged</div>
        </div>
      </div>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={'Filter by text, source, hashtag…'}
        style={{
          width: '100%', maxWidth: 440, margin: '20px 0 0', boxSizing: 'border-box',
          background: 'var(--surface-sunken)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', padding: '9px 11px',
          color: 'var(--text)', fontSize: 'var(--fs-sm)',
        }}
      />

      <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {shown.length === 0 && (
          <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', padding: '30px 0', textAlign: 'center' }}>
            {posts.length === 0 ? 'No LinkedIn posts logged yet — import your Shares.csv to get started.' : 'No posts match your filter.'}
          </div>
        )}
        {shown.map((p, i) => (
          <PostCard key={p.id ?? `${p.source}-${i}`} post={p} isDesktop={isDesktop} onEdit={() => setSheetPost(p)} />
        ))}
      </div>

      {sheetPost && (
        <MetricSheet
          post={sheetPost}
          onClose={() => setSheetPost(null)}
          onSaved={() => { setSheetPost(null); reload() }}
        />
      )}
    </Screen>
  )
}
