import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../design-system'

/* HomeScreen — the Oura-readiness redesign. Converted from the design
   handoff's home.jsx IIFE to ESM.

   Data: fetched from GET /api/dashboard/home (see transport/http/routes/
   dashboard/api.py). Until that responds it renders MOCK so the screen is
   never blank. The API shape mirrors MOCK exactly.

   Behavior:
   - Split / Card hero layout toggle (local UI state).
   - Oura toggle: when off (or no ring connected), the readiness panel becomes
     a Daily Digest in the same slot. hasOura is seeded from whether the API
     returned an oura payload — a null payload shows the digest, never a
     zeroed-out ring.
   - Animated gauge + bars on mount (skipped under prefers-reduced-motion). */

const ACCENT = 'var(--cyan-500)'

const DEFAULT_CARDS = [
  { key: 'pipeline', title: 'Pipeline', desc: 'Share-sheet intake, assessment, resume selection, cover letter, and apply queue' },
  { key: 'job-hunt', title: 'Job Hunt', desc: 'Applications, Kanban board, status breakdown' },
  { key: 'materials', title: 'Materials', desc: 'Resumes, cover letters, PDFs, and untracked files' },
  { key: 'rejections', title: 'Rejections', desc: 'Funnel analysis, patterns, company breakdown' },
  { key: 'posts', title: 'Posts', desc: 'LinkedIn pipeline: draft \u2192 written \u2192 approved \u2192 posted' },
  { key: 'people', title: 'Outreach', desc: 'Contacts, follow-up queue, warm vs cold' },
  { key: 'health', title: 'Wellbeing', desc: 'Mood & energy log, trend sparklines' },
  { key: 'interviews', title: 'Interviews', desc: 'Upcoming schedule, debrief log, verbatim quotes' },
]

const MOCK = {
  welcomeName: 'there',
  hasOura: false,
  oura: null,
  today: {
    active: 0,
    inflight: 0,
    overdue: 0,
    move: 'Start with your top priority action.',
    priorities: [],
  },
  digest: {
    date: '',
    items: [],
  },
  cards: DEFAULT_CARDS,
}

const EYEBROW = {
  font: 'var(--fw-semibold) var(--fs-2xs)/1.2 var(--font-sans)',
  textTransform: 'uppercase',
  letterSpacing: 'var(--ls-eyebrow)',
  color: 'var(--muted)',
}

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/* ---------- pieces ---------- */
function Gauge({ score, accent, size = 184, animate = true }) {
  const R = 78
  const C = 2 * Math.PI * R
  const [off, setOff] = useState(animate ? C : C * (1 - score / 100))
  useEffect(() => {
    if (!animate) {
      setOff(C * (1 - score / 100))
      return
    }
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => setOff(C * (1 - score / 100))),
    )
    return () => cancelAnimationFrame(id)
  }, [score, animate, C])
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 184 184"
        style={{ transform: 'rotate(-90deg)', display: 'block' }}
      >
        <circle cx="92" cy="92" r="78" fill="none" stroke="var(--ink-600)" strokeWidth="12" />
        <circle
          cx="92"
          cy="92"
          r="78"
          fill="none"
          stroke={accent}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={C}
          strokeDashoffset={off}
          style={{ transition: 'stroke-dashoffset 1.2s var(--ease-out)' }}
        />
      </svg>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 700,
            fontSize: size > 170 ? '2.7rem' : '2.3rem',
            lineHeight: 1,
            color: 'var(--text-strong)',
          }}
        >
          {score}
        </div>
        <div style={{ ...EYEBROW, marginTop: 5 }}>Score</div>
      </div>
    </div>
  )
}

function Bars({ bars, accent, animate, smallLabel }) {
  const [on, setOn] = useState(!animate)
  useEffect(() => {
    if (animate) requestAnimationFrame(() => requestAnimationFrame(() => setOn(true)))
  }, [animate])
  return (
    <div style={{ marginTop: 12 }}>
      {bars.map((b, i) => {
        const green = b.tone === 'green'
        const col = green ? 'var(--green-500)' : accent
        return (
          <div key={i} style={{ marginTop: 13 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: smallLabel ? '0.82rem' : '0.85rem', color: 'var(--muted)' }}>
                {b.label}
              </span>
              <span style={{ fontWeight: 700, fontSize: '0.95rem', color: col }}>
                {b.val}
                {b.unit}
              </span>
            </div>
            <div style={{ height: 6, borderRadius: 999, background: 'var(--ink-600)', overflow: 'hidden' }}>
              <div
                style={{
                  width: on ? b.pct + '%' : '0%',
                  height: '100%',
                  borderRadius: 999,
                  background: col,
                  transition: 'width 1s var(--ease-out)',
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Toggle({ on, onClick, accent }) {
  return (
    <div
      onClick={onClick}
      role="switch"
      aria-checked={on}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick()
      }}
      style={{
        width: 40,
        height: 22,
        borderRadius: 999,
        background: on ? accent : 'var(--ink-500)',
        position: 'relative',
        cursor: 'pointer',
        transition: 'background var(--dur-base)',
        flexShrink: 0,
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 3,
          left: on ? 21 : 3,
          width: 16,
          height: 16,
          borderRadius: 999,
          background: '#fff',
          transition: 'left var(--dur-base)',
          boxShadow: '0 1px 2px rgba(0,0,0,0.4)',
        }}
      />
    </div>
  )
}

function Digest({ digest, compact, withNote }) {
  const items = digest?.items || []
  return (
    <div>
      {digest?.date && (
        <div style={{ marginTop: 8, color: 'var(--muted)', fontSize: compact ? '0.82rem' : '0.85rem' }}>
          {digest.date}
        </div>
      )}
      <div style={{ marginTop: compact ? 10 : 12 }}>
        {items.length === 0 && (
          <div style={{ color: 'var(--faint)', fontSize: '0.85rem', padding: '8px 0' }}>
            Nothing pressing right now. Apply to 2 or 3 new roles today.
          </div>
        )}
        {items.map((d, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 12,
              padding: (compact ? 11 : 13) + 'px 0',
              borderTop: '1px solid var(--border-soft)',
            }}
          >
            <span
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                fontSize: compact ? '0.88rem' : '0.9rem',
                color: 'var(--text)',
              }}
            >
              <span style={{ width: 7, height: 7, borderRadius: 999, background: d.color, flexShrink: 0 }} />
              {d.label}
            </span>
            <span style={{ fontWeight: 700, fontSize: compact ? '0.9rem' : '0.92rem', color: d.color, whiteSpace: 'nowrap' }}>
              {d.value}
            </span>
          </div>
        ))}
      </div>
      {withNote && (
        <div style={{ marginTop: 16, fontSize: '0.8rem', color: 'var(--faint)', lineHeight: 1.5 }}>
          No Oura ring connected. Showing your daily digest. Connect a ring in Settings to see readiness.
        </div>
      )}
    </div>
  )
}

function PanelHead({ hasOura, setHasOura, accent }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
      <div style={{ ...EYEBROW, color: 'var(--cyan-300)' }}>{hasOura ? 'Oura \u00b7 Readiness' : 'Daily Digest'}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: '0.66rem', color: 'var(--faint)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Oura ring
        </span>
        <Toggle on={hasOura} onClick={() => setHasOura((v) => !v)} accent={accent} />
      </div>
    </div>
  )
}

function Overdue({ n }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        background: 'var(--tint-danger)',
        color: 'var(--danger-soft)',
        border: '1px solid color-mix(in srgb,var(--danger) 35%,transparent)',
        borderRadius: 999,
        padding: '6px 13px',
        fontSize: '0.8rem',
        fontWeight: 600,
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: 999, background: 'var(--danger)' }} />
      {n} overdue
    </div>
  )
}

function BigNum({ value, label }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '2.4rem', lineHeight: 1, color: 'var(--text-strong)' }}>
        {value}
      </div>
      <div style={{ ...EYEBROW, marginTop: 6 }}>{label}</div>
    </div>
  )
}

function Priorities({ priorities }) {
  if (!priorities || priorities.length === 0) {
    return (
      <div style={{ marginTop: 12, color: 'var(--faint)', fontSize: '0.9rem' }}>
        No priority actions queued.
      </div>
    )
  }
  return priorities.map((p) => (
    <div key={p.n} style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginTop: 12 }}>
      <span
        style={{
          width: 21,
          height: 21,
          borderRadius: 999,
          background: 'var(--tint-primary)',
          color: 'var(--cyan-300)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.7rem',
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          marginTop: 1,
        }}
      >
        {p.n}
      </span>
      <span style={{ fontSize: '0.92rem', color: 'var(--text)', lineHeight: 1.4 }}>{p.text}</span>
    </div>
  ))
}

/* ---------- hero variants ---------- */
function ReadinessOrDigest({ data, hasOura, setHasOura, accent, animate, size, compact }) {
  return (
    <>
      <PanelHead hasOura={hasOura} setHasOura={setHasOura} accent={accent} />
      {hasOura && data.oura ? (
        <>
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: compact ? 14 : 16 }}>
            <Gauge score={data.oura.score} accent={accent} size={size} animate={animate} />
          </div>
          <div style={{ textAlign: 'center', marginTop: compact ? 8 : 10, fontWeight: 600, fontSize: compact ? '0.95rem' : '0.98rem', color: accent }}>
            {data.oura.label}
          </div>
          <Bars bars={data.oura.bars} accent={accent} animate={animate} smallLabel={compact} />
        </>
      ) : (
        <Digest digest={data.digest} compact={compact} withNote={!compact} />
      )}
    </>
  )
}

function SplitHero({ data, hasOura, setHasOura, accent, animate }) {
  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-xl)',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-md)',
        marginBottom: 34,
      }}
    >
      <div style={{ height: 3, background: 'linear-gradient(90deg,var(--cyan-500) 0%,color-mix(in srgb,var(--cyan-500) 30%,transparent) 55%,transparent 100%)' }} />
      <div className="hero-split-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
        <div style={{ padding: '26px 30px' }}>
          <ReadinessOrDigest data={data} hasOura={hasOura} setHasOura={setHasOura} accent={accent} animate={animate} size={184} />
        </div>
        <div className="hero-split-right" style={{ padding: '26px 30px', borderLeft: '1px solid var(--border-soft)' }}>
          <div style={{ ...EYEBROW, color: 'var(--cyan-300)' }}>Pipeline \u00b7 Today</div>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 30, marginTop: 14 }}>
            <BigNum value={data.today.active} label="Active" />
            <BigNum value={data.today.inflight} label="In-flight" />
            {data.today.overdue > 0 && <div style={{ marginLeft: 'auto' }}><Overdue n={data.today.overdue} /></div>}
          </div>
          <div style={{ ...EYEBROW, marginTop: 24 }}>Priority actions</div>
          <div style={{ marginTop: 10 }}><Priorities priorities={data.today.priorities} /></div>
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '15px 30px',
          borderTop: '1px solid var(--border-soft)',
          background: 'color-mix(in srgb,var(--cyan-500) 5%,var(--surface))',
        }}
      >
        <span style={{ width: 8, height: 8, borderRadius: 999, background: 'var(--green-500)', flexShrink: 0 }} />
        <span style={{ ...EYEBROW, color: 'var(--green-300)', flexShrink: 0 }}>Today's move</span>
        <span style={{ color: 'var(--text-soft)', fontSize: '0.9rem', lineHeight: 1.4 }}>{data.today.move}</span>
        <span style={{ marginLeft: 'auto', color: 'var(--cyan-400)', fontSize: '1.1rem', flexShrink: 0 }}>{'\u2192'}</span>
      </div>
    </div>
  )
}

function CardsHero({ data, hasOura, setHasOura, accent, animate }) {
  const card = {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-xl)',
    padding: '22px 24px',
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(290px,1fr))', gap: 14, marginBottom: 34 }}>
      <div style={card}>
        <ReadinessOrDigest data={data} hasOura={hasOura} setHasOura={setHasOura} accent={accent} animate={animate} size={160} compact />
      </div>
      <div style={{ ...card, display: 'flex', flexDirection: 'column' }}>
        <div style={{ ...EYEBROW, color: 'var(--cyan-300)' }}>Pipeline \u00b7 Today</div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 26, marginTop: 16 }}>
          <BigNum value={data.today.active} label="Active" />
          <BigNum value={data.today.inflight} label="In-flight" />
        </div>
        {data.today.overdue > 0 && <div style={{ marginTop: 18 }}><Overdue n={data.today.overdue} /></div>}
        <div style={{ marginTop: 'auto', paddingTop: 18, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: 'var(--green-500)', flexShrink: 0, marginTop: 5 }} />
          <span style={{ color: 'var(--text-soft)', fontSize: '0.88rem', lineHeight: 1.45 }}>{data.today.move}</span>
        </div>
      </div>
      <div style={card}>
        <div style={EYEBROW}>Priority actions</div>
        <div style={{ marginTop: 12 }}><Priorities priorities={data.today.priorities} /></div>
      </div>
    </div>
  )
}

/* ---------- screen ---------- */
export default function Home() {
  const navigate = useNavigate()
  const [hero, setHero] = useState('split')
  const [data, setData] = useState(MOCK)
  const [hasOura, setHasOura] = useState(false)
  const [hover, setHover] = useState(null)
  const animate = useRef(!prefersReducedMotion()).current

  useEffect(() => {
    let cancelled = false
    fetch('/api/dashboard/home', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (cancelled || !json) return
        const merged = { ...MOCK, ...json, today: { ...MOCK.today, ...(json.today || {}) }, digest: { ...MOCK.digest, ...(json.digest || {}) } }
        setData(merged)
        setHasOura(Boolean(json.hasOura && json.oura))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const seg = (on) => ({
    padding: '6px 16px',
    borderRadius: 7,
    fontSize: '0.82rem',
    fontWeight: 600,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    transition: 'all var(--dur-base)',
    background: on ? 'var(--surface-raised)' : 'transparent',
    color: on ? 'var(--text-strong)' : 'var(--muted)',
    boxShadow: on ? 'inset 0 0 0 1px color-mix(in srgb,var(--cyan-500) 40%,transparent)' : 'none',
  })

  const cards = (data.cards || DEFAULT_CARDS).filter((c) => c.key !== 'digest')

  return (
    <div>
      <div
        style={{
          textAlign: 'center',
          fontFamily: 'var(--font-display)',
          fontSize: '1.55rem',
          fontWeight: 600,
          color: 'var(--text-strong)',
          margin: '2px 0 18px',
        }}
      >
        Welcome back, {data.welcomeName}.
      </div>

      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 18 }}>
        <div style={{ display: 'inline-flex', gap: 4, padding: 4, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}>
          <div onClick={() => setHero('split')} style={seg(hero === 'split')}>Split view</div>
          <div onClick={() => setHero('cards')} style={seg(hero === 'cards')}>Card view</div>
        </div>
      </div>

      {hero === 'split' ? (
        <SplitHero data={data} hasOura={hasOura} setHasOura={setHasOura} accent={ACCENT} animate={animate} />
      ) : (
        <CardsHero data={data} hasOura={hasOura} setHasOura={setHasOura} accent={ACCENT} animate={animate} />
      )}

      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 22 }}>
        <a
          href="/why"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 16px',
            border: '1px solid var(--border)',
            borderRadius: 999,
            color: 'var(--muted)',
            fontSize: '0.85rem',
            cursor: 'pointer',
          }}
        >
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="10" cy="10" r="7.5" />
            <path d="M10 9v4.5" strokeLinecap="round" />
            <circle cx="10" cy="6.5" r="0.8" fill="currentColor" stroke="none" />
          </svg>
          Why use jobContext?
        </a>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(248px, 1fr))', gap: 14 }}>
        {cards.map((c) => {
          const on = hover === c.key
          return (
            <a
              key={c.key}
              href={`/app/${c.key === 'home' ? '' : c.key}`}
              onClick={(e) => {
                e.preventDefault()
                navigate(c.key === 'home' ? '/' : `/${c.key}`)
              }}
              onMouseEnter={() => setHover(c.key)}
              onMouseLeave={() => setHover(null)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 7,
                textDecoration: 'none',
                background: on ? 'var(--surface-raised)' : 'var(--surface)',
                border: `1px solid ${on ? 'color-mix(in srgb, var(--cyan-500) 50%, transparent)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-xl)',
                padding: '20px 22px',
                boxShadow: on ? 'var(--glow-primary)' : 'none',
                transition: 'border-color var(--dur-base), background var(--dur-base), box-shadow var(--dur-base), transform var(--dur-base)',
                transform: on ? 'translateY(-2px)' : 'none',
              }}
            >
              <div style={{ color: 'var(--cyan-400)', height: 24 }}>
                <Icon name={c.key} size={24} />
              </div>
              <div style={{ fontWeight: 700, fontSize: 'var(--fs-h3)', color: 'var(--text-strong)' }}>{c.title}</div>
              <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.45 }}>{c.desc}</div>
              <div style={{ color: 'var(--cyan-400)', fontSize: 'var(--fs-sm)', fontWeight: 600, marginTop: 4 }}>Open {'\u2192'}</div>
            </a>
          )
        })}
      </div>
    </div>
  )
}
