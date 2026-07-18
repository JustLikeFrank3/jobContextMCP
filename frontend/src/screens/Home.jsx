import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../auth/api.js'
import useDesktopMode from '../shell/useDesktopMode.js'

/* HomeScreen — re-skinned to the desktop design handoff's HOME page:
   mono date eyebrow + greeting, a 4-tile stat row, then a 1.35fr/1fr grid
   (cyan-tinted priorities card + daily-digest list on the left, readiness
   card + "today's move" nudge on the right). Workspace nav cards were
   dropped once the sidebar landed — navigation lives in the shell now.

   Data: fetched from GET /api/dashboard/home (see transport/http/routes/
   dashboard/api.py). Until that responds it renders MOCK so the screen is
   never blank. The API shape mirrors MOCK exactly.

   Behavior:
   - Oura toggle: when off (or no ring connected), the readiness card shows
     a note instead of the gauge. hasOura is seeded from whether the API
     returned an oura payload — a null payload never shows a zeroed ring.
   - The daily digest is always visible (left column) so enabling Oura
     augments the page rather than replacing the digest.
   - Animated gauge + bars on mount (skipped under prefers-reduced-motion).
   - The page title/subtitle come from DashboardShell — this screen renders
     content only. */

const ACCENT = 'var(--cyan-500)'

/* Handoff card recipe: rgba(255,255,255,.04) fill, .07 border, 14-18 radius */
const CARD_BG = 'rgba(255,255,255,.04)'
const CARD_BORDER = '1px solid rgba(255,255,255,.07)'

/* Mono uppercase section eyebrow (JetBrains Mono per the handoff) */
const MONO_EYEBROW = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '1.2px',
  textTransform: 'uppercase',
  color: '#7C8AA6',
}
const MONO_EYEBROW_CYAN = {
  ...MONO_EYEBROW,
  letterSpacing: '1.5px',
  color: 'var(--cyan-300)',
}

const MOCK = {
  welcomeName: 'there',
  welcomeIsDefault: false,
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
}

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

function dateEyebrow() {
  const d = new Date()
  const wd = d.toLocaleDateString('en-US', { weekday: 'short' }).toUpperCase()
  const mo = d.toLocaleDateString('en-US', { month: 'short' }).toUpperCase()
  return `${wd} · ${mo} ${d.getDate()}`
}

function timeGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

/* ---------- pieces ---------- */
function Gauge({ score, accent, size = 168, animate = true }) {
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
            fontSize: size > 160 ? '2.5rem' : '2.2rem',
            lineHeight: 1,
            color: 'var(--text)',
          }}
        >
          {score}
        </div>
        <div style={{ ...MONO_EYEBROW, fontSize: 9.5, marginTop: 5 }}>Score</div>
      </div>
    </div>
  )
}

function Bars({ bars, accent, animate }) {
  const [on, setOn] = useState(!animate)
  useEffect(() => {
    if (animate) requestAnimationFrame(() => requestAnimationFrame(() => setOn(true)))
  }, [animate])
  return (
    <div style={{ marginTop: 10 }}>
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
              <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>{b.label}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 12.5, color: col }}>
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

function Toggle({ on, onClick, accent, disabled = false }) {
  const fire = () => {
    if (!disabled) onClick()
  }
  return (
    <div
      onClick={fire}
      role="switch"
      aria-checked={on}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (!disabled && (e.key === 'Enter' || e.key === ' ')) onClick()
      }}
      title={disabled ? 'Connect an Oura ring in Settings to enable readiness' : undefined}
      style={{
        width: 40,
        height: 22,
        borderRadius: 999,
        background: on ? accent : 'var(--ink-500)',
        position: 'relative',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
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

function StatTile({ value, label, tint = false, valueColor }) {
  return (
    <div
      style={{
        flex: '1 1 150px',
        padding: 18,
        borderRadius: 16,
        background: tint ? 'rgba(0,181,200,.1)' : CARD_BG,
        border: tint ? '1px solid rgba(0,181,200,.24)' : CARD_BORDER,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 30,
          fontWeight: 700,
          lineHeight: 1.1,
          color: valueColor || (tint ? 'var(--cyan-300)' : 'var(--text)'),
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 12, color: tint ? '#8AB6C4' : 'var(--muted)', marginTop: 3 }}>{label}</div>
    </div>
  )
}

/* Digest rows styled like the handoff's FOLLOW-UPS DUE list — one card per
   item with a colored dot + label and a mono status chip on the right. */
function Digest({ digest }) {
  const items = digest?.items || []
  if (items.length === 0) {
    return (
      <div
        style={{
          borderRadius: 14,
          padding: '14px 16px',
          background: CARD_BG,
          border: CARD_BORDER,
          color: 'var(--faint)',
          fontSize: 13,
        }}
      >
        Nothing pressing right now. Apply to 2 or 3 new roles today.
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((d, i) => {
        const col = d.color || 'var(--cyan-300)'
        return (
          <div
            key={i}
            style={{
              borderRadius: 14,
              padding: '14px 16px',
              background: CARD_BG,
              border: CARD_BORDER,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, color: 'var(--text)' }}>
              <span style={{ width: 7, height: 7, borderRadius: 999, background: col, flexShrink: 0 }} />
              {d.label}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.5px',
                color: col,
                background: `color-mix(in srgb, ${col} 14%, transparent)`,
                padding: '4px 9px',
                borderRadius: 8,
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              {d.value}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* Numbered checkbox rows per the handoff's priorities card — the first
   (current) item gets the cyan box. */
function Priorities({ priorities }) {
  if (!priorities || priorities.length === 0) {
    return <div style={{ color: 'var(--faint)', fontSize: 13.5 }}>No priority actions queued.</div>
  }
  return priorities.map((p, i) => (
    <div key={p.n} style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: 6,
          border: `2px solid ${i === 0 ? 'var(--cyan-500)' : 'rgba(215,227,248,.35)'}`,
          color: i === 0 ? 'var(--cyan-300)' : 'var(--faint)',
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
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
      <span style={{ fontSize: 14.5, color: '#E8EFFB', lineHeight: 1.4 }}>{p.text}</span>
    </div>
  ))
}

function ReadinessCard({ data, hasOura, setHasOura, ouraConnected, accent, animate }) {
  const showReadiness = hasOura && data.oura
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={MONO_EYEBROW_CYAN}>{showReadiness ? 'Oura · Readiness' : 'Readiness'}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9.5,
              fontWeight: 600,
              color: 'var(--faint)',
              textTransform: 'uppercase',
              letterSpacing: '.8px',
            }}
          >
            {ouraConnected ? 'Oura ring' : 'Not connected'}
          </span>
          <Toggle on={hasOura} onClick={() => setHasOura((v) => !v)} accent={accent} disabled={!ouraConnected} />
        </div>
      </div>
      <div
        style={{
          marginTop: 10,
          borderRadius: 16,
          padding: 18,
          background: 'rgba(255,255,255,.045)',
          border: '1px solid rgba(255,255,255,.08)',
        }}
      >
        {showReadiness ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4 }}>
              <Gauge score={data.oura.score} accent={accent} animate={animate} />
            </div>
            <div style={{ textAlign: 'center', marginTop: 10, fontWeight: 600, fontSize: 14.5, color: accent }}>
              {data.oura.label}
            </div>
            <Bars bars={data.oura.bars} accent={accent} animate={animate} />
          </>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--faint)', lineHeight: 1.5 }}>
            {ouraConnected
              ? 'Readiness hidden — flip the toggle to bring it back.'
              : 'No Oura ring connected. Connect a ring in Settings to see readiness.'}
          </div>
        )}
      </div>
    </div>
  )
}

/* ---------- screen ---------- */
export default function Home() {
  const navigate = useNavigate()
  const isDesktop = useDesktopMode()
  const [data, setData] = useState(MOCK)
  const [hasOura, setHasOura] = useState(false)
  const [ouraConnected, setOuraConnected] = useState(false)
  const animate = useRef(!prefersReducedMotion()).current

  useEffect(() => {
    let cancelled = false
    apiFetch('/api/dashboard/home')
      .then((json) => {
        if (cancelled || !json) return
        const merged = { ...MOCK, ...json, today: { ...MOCK.today, ...(json.today || {}) }, digest: { ...MOCK.digest, ...(json.digest || {}) } }
        setData(merged)
        const connected = Boolean(json.hasOura && json.oura)
        setOuraConnected(connected)
        setHasOura(connected)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const readinessOn = hasOura && data.oura

  return (
    <div>
      {/* greeting — the 28px page title lives in DashboardShell; this is the
          handoff's mono date eyebrow + a smaller greeting line */}
      <div style={{ ...MONO_EYEBROW_CYAN, letterSpacing: '1px', fontSize: 13, fontWeight: 500 }}>
        {dateEyebrow()}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 20,
          fontWeight: 700,
          letterSpacing: '-0.4px',
          color: 'var(--text)',
          marginTop: 4,
        }}
      >
        {data.welcomeIsDefault ? timeGreeting() : `${timeGreeting()}, ${data.welcomeName}`}
      </div>

      {data.welcomeIsDefault && isDesktop && (
        <button
          onClick={() =>
            navigate('/chat', {
              state: {
                seed:
                  "I'm new here — check my workspace and walk me through setting it up.",
              },
            })
          }
          style={{
            marginTop: 14,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 7,
            fontSize: 13,
            fontWeight: 700,
            fontFamily: 'inherit',
            color: '#04222A',
            background: 'var(--cyan-500)',
            border: 'none',
            padding: '9px 16px',
            borderRadius: 10,
            boxShadow: '0 4px 14px rgba(0,181,200,.25)',
            cursor: 'pointer',
          }}
        >
          Set up your workspace with the assistant {'→'}
        </button>
      )}

      {/* stat tile row */}
      <div style={{ marginTop: 22, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <StatTile value={data.today.active} label="Active apps" />
        <StatTile value={data.today.inflight} label="In-flight" />
        <StatTile value={readinessOn ? data.oura.score : '—'} label="Readiness" tint={Boolean(readinessOn)} valueColor={readinessOn ? undefined : 'var(--faint)'} />
        <StatTile value={data.today.overdue} label="Overdue follow-ups" valueColor={data.today.overdue > 0 ? '#E0B77A' : 'var(--text)'} />
      </div>

      {/* two-column grid (collapses via .hero-split-grid at <=720px) */}
      <div
        className="hero-split-grid"
        style={{ marginTop: 22, display: 'grid', gridTemplateColumns: '1.35fr 1fr', gap: 18, alignItems: 'start' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {/* cyan-tinted priorities card */}
          <div
            style={{
              borderRadius: 18,
              padding: 20,
              background: 'linear-gradient(150deg, rgba(0,181,200,.15), rgba(0,181,200,.04))',
              border: '1px solid rgba(0,181,200,.26)',
            }}
          >
            <div style={MONO_EYEBROW_CYAN}>Today&rsquo;s priorities</div>
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Priorities priorities={data.today.priorities} />
            </div>
          </div>

          {/* daily digest list */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
              <div style={MONO_EYEBROW}>Daily digest</div>
              {data.digest.date && (
                <div style={{ ...MONO_EYEBROW, textTransform: 'none', letterSpacing: '.5px', fontWeight: 500, color: 'var(--faint)' }}>
                  {data.digest.date}
                </div>
              )}
            </div>
            <div style={{ marginTop: 10 }}>
              <Digest digest={data.digest} />
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <ReadinessCard
            data={data}
            hasOura={hasOura}
            setHasOura={setHasOura}
            ouraConnected={ouraConnected}
            accent={ACCENT}
            animate={animate}
          />

          {/* today's move — the handoff's nudge card */}
          <div
            style={{
              borderRadius: 16,
              padding: 18,
              background: 'rgba(0,181,200,.06)',
              border: '1px solid rgba(0,181,200,.16)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span style={{ width: 6, height: 6, borderRadius: 999, background: '#6FD3A0', flexShrink: 0 }} />
              <span style={{ ...MONO_EYEBROW, color: '#6FD3A0' }}>Today&rsquo;s move</span>
            </div>
            <div style={{ marginTop: 8, fontSize: 13.5, color: 'var(--text-soft)', lineHeight: 1.4 }}>
              {data.today.move}
            </div>
          </div>
        </div>
      </div>

    </div>
  )
}
