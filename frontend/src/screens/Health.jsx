import { useState } from 'react'
import { Panel } from '../design-system'
import { useApi, Screen, fmtDate } from './_shared.jsx'
import { apiPost } from '../auth/api.js'

/* Wellbeing — mood and energy check-ins, per the desktop design handoff.
   Data: GET /dashboard/health/data (_health_payload), plus the existing
   GET /api/dashboard/home payload for the Oura readiness card (same source
   Home.jsx already uses).

   Layout: a two-column grid with the check-in form (mood tiles, energy
   slider, notes, productive toggle) and a 7-DAY MOOD bar chart on the left;
   the Oura readiness card and RECENT CHECK-INS rows on the right.

   The form POSTs /dashboard/health/checkin, which delegates to the same
   log_mental_health_checkin tool the MCP and mobile clients use — all three
   surfaces write identical entries to the tenant's own partition. */

const SCALE = 10 // mood/energy are logged 1–10
const CYAN_DIM = 'color-mix(in srgb, var(--cyan-500) 35%, transparent)'

const MOODS = [
  { emoji: '\u{1F614}', word: 'Low' },
  { emoji: '\u{1F615}', word: 'Drained' },
  { emoji: '\u{1F642}', word: 'Steady' },
  { emoji: '\u{1F600}', word: 'Good' },
  { emoji: '\u{1F929}', word: 'Great' },
]

const MONO_LABEL = {
  fontSize: 11,
  fontWeight: 'var(--fw-semibold)',
  letterSpacing: '1.2px',
  color: 'var(--faint)',
  fontFamily: 'var(--font-mono)',
  textTransform: 'uppercase',
}

function toNum(v) {
  const n = Number.parseFloat(v)
  return Number.isFinite(n) ? n : null
}

/* 1–10 score -> one of the five emoji tiles (1-2, 3-4, 5-6, 7-8, 9-10). */
function bucket(v) {
  const n = toNum(v)
  if (n == null) return null
  return Math.max(0, Math.min(4, Math.ceil(n / 2) - 1))
}

function monoDate(iso) {
  if (!iso) return '—'
  const d = new Date(String(iso).slice(0, 10) + 'T00:00:00')
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10).toUpperCase()
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()
}

function dayLetter(iso) {
  const d = new Date(String(iso).slice(0, 10) + 'T00:00:00')
  return Number.isNaN(d.getTime()) ? '·' : 'SMTWTFS'[d.getDay()]
}

/* Check-in form — pick a mood tile, set energy on the slider, add optional
   notes, flag a productive day, submit. POSTs to /dashboard/health/checkin
   and calls onSaved() so the page reloads its data. */
function CheckinForm({ onSaved }) {
  const [moodIdx, setMoodIdx] = useState(2) // default Steady
  const [energy, setEnergy] = useState(5)
  const [notes, setNotes] = useState('')
  const [productive, setProductive] = useState(false)
  const [status, setStatus] = useState({ busy: false, error: null })

  async function submit() {
    setStatus({ busy: true, error: null })
    try {
      await apiPost('/dashboard/health/checkin', {
        mood: MOODS[moodIdx].word.toLowerCase(),
        energy,
        notes: notes.trim(),
        productive,
      })
      setNotes('')
      setProductive(false)
      setStatus({ busy: false, error: null })
      onSaved?.()
    } catch (err) {
      setStatus({ busy: false, error: err?.body?.detail || 'Could not save check-in.' })
    }
  }

  return (
    <Panel pad="20px" radius="18px">
      <div style={{ fontSize: 14, fontWeight: 'var(--fw-semibold)', color: 'var(--text-soft)' }}>
        {'How are you today?'}
      </div>

      <div style={{ ...MONO_LABEL, letterSpacing: '0.8px', marginTop: 16 }}>Mood</div>
      <div style={{ marginTop: 8, display: 'flex', gap: 10 }}>
        {MOODS.map((m, i) => (
          <button
            key={m.word}
            type="button"
            onClick={() => setMoodIdx(i)}
            aria-pressed={i === moodIdx}
            title={m.word}
            style={{
              flex: 1, height: 58, borderRadius: 13, fontSize: 22, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: i === moodIdx ? 'color-mix(in srgb, var(--cyan-500) 18%, transparent)' : 'rgba(255,255,255,.05)',
              border: i === moodIdx ? '1.5px solid var(--cyan-500)' : '1.5px solid transparent',
            }}
          >
            {m.emoji}
          </button>
        ))}
      </div>

      <div style={{ ...MONO_LABEL, letterSpacing: '0.8px', marginTop: 18 }}>
        {`Energy · ${energy}/${SCALE}`}
      </div>
      <input
        type="range" min="1" max={SCALE} step="1" value={energy}
        onChange={(e) => setEnergy(Number(e.target.value))}
        aria-label="Energy level"
        style={{ width: '100%', marginTop: 10, accentColor: 'var(--cyan-500)' }}
      />

      <div style={{ ...MONO_LABEL, letterSpacing: '0.8px', marginTop: 18 }}>Notes</div>
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="What’s on your mind today? (optional)"
        maxLength={2000}
        rows={3}
        style={{
          width: '100%', marginTop: 8, resize: 'vertical', boxSizing: 'border-box',
          background: 'rgba(255,255,255,.05)', color: 'var(--text)',
          border: '1.5px solid var(--border-soft)', borderRadius: 12,
          padding: '10px 12px', fontSize: 13.5, lineHeight: 1.5,
          fontFamily: 'var(--font-sans)',
        }}
      />

      <label style={{ display: 'flex', alignItems: 'center', gap: 9, marginTop: 14, cursor: 'pointer', fontSize: 13.5, color: 'var(--text-soft)' }}>
        <input
          type="checkbox" checked={productive}
          onChange={(e) => setProductive(e.target.checked)}
          style={{ width: 16, height: 16, accentColor: 'var(--cyan-500)' }}
        />
        {'Productive day'}
      </label>

      <button
        type="button"
        onClick={submit}
        disabled={status.busy}
        style={{
          width: '100%', marginTop: 16, height: 42, borderRadius: 12, border: 'none',
          cursor: status.busy ? 'default' : 'pointer',
          background: 'var(--cyan-500)', color: '#04141a',
          fontSize: 14, fontWeight: 'var(--fw-semibold)',
          opacity: status.busy ? 0.6 : 1,
        }}
      >
        {status.busy ? 'Saving…' : 'Check in'}
      </button>
      {status.error && (
        <div style={{ color: 'var(--warn)', fontSize: 12.5, marginTop: 10 }}>{status.error}</div>
      )}
    </Panel>
  )
}

/* 7-DAY MOOD — last 7 check-ins, oldest -> newest; the newest bar is solid
   cyan, earlier bars are dimmed, mono day letters underneath. */
function MoodChart({ entries }) {
  const points = entries.slice(0, 7).reverse()
  if (points.length === 0) return null
  return (
    <div>
      <div style={MONO_LABEL}>7-day mood</div>
      <div style={{ marginTop: 14, display: 'flex', alignItems: 'flex-end', gap: 12, height: 110 }}>
        {points.map((e, i) => {
          const mood = toNum(e.mood)
          const pct = mood == null ? 0 : Math.max(6, (mood / SCALE) * 100)
          return (
            <div
              key={`${e.date}-${i}`}
              title={`${fmtDate(e.date) || 'Undated'} · mood ${e.mood ?? '—'}/${SCALE}`}
              style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}
            >
              <div
                style={{
                  width: '100%', height: `${pct}%`, minHeight: mood == null ? 2 : 0, borderRadius: 7,
                  background: i === points.length - 1 ? 'var(--cyan-500)' : CYAN_DIM,
                }}
              />
              <div style={{ fontSize: 10, color: 'var(--faint)', fontFamily: 'var(--font-mono)' }}>{dayLetter(e.date)}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* Big-number gradient card. Shows Oura readiness when a ring is connected;
   otherwise falls back to the 30-check-in average energy so the slot never
   fabricates data. */
function ReadinessCard({ oura, move, avgEnergy }) {
  const big = oura ? oura.score : (avgEnergy ?? '—')
  const title = oura ? 'Oura readiness' : 'Avg energy'
  const sub = oura
    ? (move || oura.label || '')
    : `${SCALE}-point scale, last 30 check-ins · connect an Oura ring in Settings for readiness`
  return (
    <div
      style={{
        borderRadius: 18, padding: 20, display: 'flex', alignItems: 'center', gap: 18,
        background: 'linear-gradient(150deg, color-mix(in srgb, var(--cyan-500) 14%, transparent), color-mix(in srgb, var(--cyan-500) 3%, transparent))',
        border: '1px solid color-mix(in srgb, var(--cyan-500) 26%, transparent)',
      }}
    >
      <div style={{ fontSize: 46, fontWeight: 'var(--fw-bold)', color: 'var(--cyan-300)', letterSpacing: '-1px', lineHeight: 1 }}>
        {big}
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 'var(--fw-semibold)', color: 'var(--text)' }}>{title}</div>
        {sub && <div style={{ fontSize: 12.5, color: '#8AB6C4', marginTop: 3, lineHeight: 1.4 }}>{sub}</div>}
      </div>
    </div>
  )
}

function CheckinRow({ entry }) {
  const b = bucket(entry.mood)
  const face = b == null ? '·' : MOODS[b].emoji
  const word = entry.label || (b == null ? 'Check-in' : MOODS[b].word)
  return (
    <div style={{ borderRadius: 12, padding: '12px 14px', background: 'rgba(255,255,255,.035)', border: '1px solid rgba(255,255,255,.06)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
        <div style={{ fontSize: 13.5, color: 'var(--text-soft)', minWidth: 0 }}>
          {face} {word} {'·'} mood {entry.mood ?? '—'}/{SCALE} {'·'} energy {entry.energy ?? '—'}/{SCALE}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          {entry.productive != null && (
            <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 'var(--fw-semibold)', letterSpacing: '0.5px', color: entry.productive ? 'var(--green-300)' : 'var(--muted)' }}>
              {entry.productive ? 'PRODUCTIVE' : 'REST'}
            </span>
          )}
          <span style={{ fontSize: 11, color: 'var(--faint)', fontFamily: 'var(--font-mono)' }}>{monoDate(entry.date)}</span>
        </div>
      </div>
      {entry.notes && (
        <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 8, lineHeight: 1.5 }}>{entry.notes}</div>
      )}
    </div>
  )
}

export default function Health() {
  const { data, loading, error, reload } = useApi('/dashboard/health/data')
  const home = useApi('/api/dashboard/home') // readiness only; failures just hide the card
  const recent = data?.recent || []
  const oura = home.data?.oura || null

  // The check-in form is always shown (it's how the first entry gets made),
  // so this screen never hits the empty state — only loading/error gate it.
  return (
    <Screen loading={loading} error={error}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 18, alignItems: 'start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <CheckinForm onSaved={reload} />
          <MoodChart entries={recent} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <ReadinessCard oura={oura} move={home.data?.today?.move} avgEnergy={data?.avg_energy} />
          <div style={{ ...MONO_LABEL, letterSpacing: '0.8px' }}>
            {`${data?.total_entries ?? 0} check-ins · avg mood ${data?.avg_mood ?? '—'}/${SCALE} · avg energy ${data?.avg_energy ?? '—'}/${SCALE}`}
          </div>
          {recent.length > 0 && (
            <div>
              <div style={MONO_LABEL}>Recent check-ins</div>
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {recent.map((e, i) => (
                  <CheckinRow key={`${e.date}-${i}`} entry={e} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Screen>
  )
}
