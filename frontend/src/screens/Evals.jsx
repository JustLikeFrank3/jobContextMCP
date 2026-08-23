import { useState } from 'react'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, List, Row, EmptyState,
} from './_shared.jsx'
import { Panel } from '../design-system'
import { apiSend } from '../auth/api.js'

/* Evals — the tenant triage loop: run the truth suite on your own golden set,
   triage every flagged claim A/B/C/D, and choose a judge you can afford.
   Data: GET /dashboard/evals/data; mutations POST to /dashboard/evals/*.

   Honesty rules carried over from the wallboard: absent data renders as a
   gap, never a zero; flag bars normalize to flags/run (raw totals across
   mixed-N runs are not comparable); judge calibration labels name the corpus
   they were measured on. */

const RULING_TONES = { A: 'danger', B: 'warn', C: 'ok', D: 'accent' }
const RULING_COLORS = {
  A: 'var(--danger, #ef4444)', B: 'var(--warn, #f59e0b)',
  C: 'var(--ok, #22c55e)', D: 'var(--cyan-500, #00B5C8)',
}

/* ---------- scoring visuals (inline SVG) ---------- */

function perRun(r) {
  if (r.flags === null || r.flags === undefined) return null
  return r.n_runs ? r.flags / r.n_runs : r.flags
}

function TrendChart({ history }) {
  if (!history || history.length < 2) return null
  const w = 820; const h = 190; const pad = 34
  const step = (w - 2 * pad) / (history.length - 1)
  const yScore = (s) => h - pad - ((Math.max(1, Math.min(5, s)) - 1) / 4) * (h - 2 * pad)
  const maxRate = Math.max(...history.map((r) => perRun(r) ?? 0), 0.001)
  const barW = Math.max(4, Math.min(18, step * 0.4))
  const points = history.map((r, i) => `${pad + i * step},${yScore(r.mean)}`).join(' ')
  const last = history[history.length - 1]
  return (
    <Panel>
      <SectionHead title="Trend across stored runs" right="mean score (line) · flags per run (bars)" />
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: 'auto' }} role="img"
        aria-label="Mean score and hallucination flags per run">
        <line x1={pad} y1={yScore(4)} x2={w - pad} y2={yScore(4)}
          stroke="var(--ok, #22c55e)" strokeDasharray="5 5" strokeWidth="1" opacity=".7" />
        <text x={w - pad + 4} y={yScore(4) + 4} fill="var(--ok, #22c55e)" fontSize="11">4.0</text>
        {history.map((r, i) => {
          const rate = perRun(r)
          if (rate === null) return null /* absent stays absent — a gap, not a zero bar */
          const bh = Math.max((rate / maxRate) * (h - 2 * pad) * 0.85, 2)
          const tip = r.n_runs
            ? `${r.started_at}: ${r.flags} flags across N=${r.n_runs} (${rate.toFixed(1)}/run)`
            : `${r.started_at}: ${r.flags} flags (N unknown — raw count)`
          return (
            <rect key={`b${i}`} x={pad + i * step - barW / 2} y={h - pad - bh} width={barW}
              height={bh} fill={r.flags ? 'var(--danger, #ef4444)' : 'var(--ok, #22c55e)'} opacity=".45">
              <title>{tip}</title>
            </rect>
          )
        })}
        <polyline points={points} fill="none" stroke="var(--cyan-500, #00B5C8)" strokeWidth="2.5" />
        {history.map((r, i) => (
          <circle key={`c${i}`} cx={pad + i * step} cy={yScore(r.mean)} r="3.5"
            fill="var(--cyan-500, #00B5C8)">
            <title>{`${r.started_at}: mean ${r.mean.toFixed(2)}`}</title>
          </circle>
        ))}
        <text x={pad + (history.length - 1) * step + 6} y={yScore(last.mean) + 4}
          fill="var(--text, #f2f6fc)" fontSize="12" fontWeight="700">{last.mean.toFixed(2)}</text>
      </svg>
    </Panel>
  )
}

const DIM_LABELS = [
  ['keyword_coverage', 'keyword'], ['relevance', 'relevance'],
  ['accuracy', 'accuracy'], ['impact_language', 'impact'], ['ats_readiness', 'ats'],
]

function DimensionChart({ dims }) {
  const rows = DIM_LABELS.filter(([k]) => dims && dims[k] !== undefined)
  if (!rows.length) return null
  const w = 820; const rowH = 30; const padL = 90; const padR = 46
  const h = rows.length * rowH + 26
  const scale = (s) => padL + ((Math.max(1, Math.min(5, s)) - 1) / 4) * (w - padL - padR)
  return (
    <Panel>
      <SectionHead title="Latest run — per dimension" right="pass line 4.0" />
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: 'auto' }} role="img"
        aria-label="Per-dimension mean scores">
        <line x1={scale(4)} y1="8" x2={scale(4)} y2={h - 8}
          stroke="var(--ok, #22c55e)" strokeDasharray="5 5" strokeWidth="1" opacity=".7" />
        {rows.map(([key, label], i) => {
          const val = dims[key]
          const y = 18 + i * rowH
          const good = val >= 4
          return (
            <g key={key}>
              <text x={padL - 8} y={y + 13} fill="var(--text-muted, #9aa8bf)" fontSize="12"
                textAnchor="end">{label}</text>
              <rect x={padL} y={y} width={scale(val) - padL} height="18" rx="4"
                fill={good ? 'var(--ok, #22c55e)' : 'var(--cyan-500, #00B5C8)'}
                opacity={good ? 0.9 : 0.75}>
                <title>{`${label}: ${val.toFixed(2)}`}</title>
              </rect>
              <text x={scale(val) + 6} y={y + 13} fill="var(--text, #f2f6fc)"
                fontSize="12" fontWeight="700">{val.toFixed(2)}</text>
            </g>
          )
        })}
      </svg>
    </Panel>
  )
}

/* ---------- triage ---------- */

function TriageCard({ claim, meanings }) {
  const [ruling, setRuling] = useState(claim.ruling || '')
  const [note, setNote] = useState(claim.note || '')
  const [saving, setSaving] = useState(false)

  const send = async (nextRuling, nextNote) => {
    setSaving(true)
    try {
      await apiSend('/dashboard/evals/triage', {
        body: { gd_id: claim.gd_id, claim: claim.claim, ruling: nextRuling, note: nextNote },
      })
    } finally {
      setSaving(false)
    }
  }
  const pick = (r) => {
    const next = ruling === r ? '' : r
    setRuling(next)
    send(next, note)
  }

  return (
    <Row
      title={claim.claim}
      subtitle={`${claim.gd_id} · ${claim.source}`}
      right={ruling ? <Badge tone={RULING_TONES[ruling]}>{ruling}</Badge> : null}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 10 }}>
        {['A', 'B', 'C', 'D'].map((r) => (
          <button key={r} type="button" onClick={() => pick(r)} title={meanings?.[r] || r}
            style={{
              fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 13,
              padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
              border: '1px solid var(--line, #23324d)',
              background: ruling === r ? RULING_COLORS[r] : 'var(--well, #1b2a44)',
              color: ruling === r ? '#0a0f1c' : 'var(--text-muted, #9aa8bf)',
            }}>{r}</button>
        ))}
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => { if (ruling) send(ruling, note) }}
          placeholder="Note — for a D, tell the story: it becomes the master edit"
          style={{
            flex: 1, minWidth: 220, background: 'var(--well, #1b2a44)',
            border: '1px solid var(--line, #23324d)', borderRadius: 8,
            color: 'var(--text, #f2f6fc)', fontSize: 13, padding: '7px 10px',
          }}
        />
        {saving && <span style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 12 }}>saving…</span>}
      </div>
    </Row>
  )
}

/* ---------- golden set + judge + run ---------- */

const inputStyle = {
  background: 'var(--well, #1b2a44)', border: '1px solid var(--line, #23324d)',
  borderRadius: 8, color: 'var(--text, #f2f6fc)', fontSize: 13, padding: '9px 12px', width: '100%',
}

function GoldenSection({ golden, hasRun, reload }) {
  const [company, setCompany] = useState('')
  const [role, setRole] = useState('')
  const [jd, setJd] = useState('')
  const [kind, setKind] = useState('resume')
  const [status, setStatus] = useState('')

  const add = async () => {
    setStatus('saving…')
    try {
      await apiSend('/dashboard/evals/golden', {
        body: { company, role, jd_text: jd, output_kind: kind },
      })
      setCompany(''); setRole(''); setJd(''); setStatus('')
      reload()
    } catch (err) {
      setStatus(err?.body?.error || err.message)
    }
  }
  const remove = async (id) => {
    await apiSend('/dashboard/evals/golden/delete', { body: { entry_id: id } })
    reload()
  }

  return (
    <Panel>
      <SectionHead title="Your golden set" right={`${golden.length} entries`} />
      {golden.length === 0 && (
        <div style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 13, marginBottom: 12, lineHeight: 1.5 }}>
          {hasRun
            ? 'This partition runs the built-in golden set until you add your own entries — add one below to switch to your set.'
            : 'Pick 3–5 real job descriptions you care about — pasting the JD is all it takes. The suite generates against your master resume and judges the output.'}
        </div>
      )}
      {golden.length > 0 && (
        <List>
          {golden.map((e) => (
            <Row key={e.id} title={`${e.company} — ${e.role}`}
              subtitle={`${e.id} · ${e.output_kind || 'resume'}`}
              right={(
                <button type="button" onClick={() => remove(e.id)}
                  style={{ background: 'none', border: '1px solid var(--line, #23324d)', color: 'var(--text-muted, #9aa8bf)', borderRadius: 7, padding: '4px 10px', cursor: 'pointer', fontSize: 12 }}>
                  remove
                </button>
              )} />
          ))}
        </List>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12 }}>
        <input style={inputStyle} placeholder="Company" value={company} onChange={(e) => setCompany(e.target.value)} />
        <input style={inputStyle} placeholder="Role title" value={role} onChange={(e) => setRole(e.target.value)} />
      </div>
      <textarea style={{ ...inputStyle, minHeight: 130, marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 12 }}
        placeholder="Paste the full job description here" value={jd} onChange={(e) => setJd(e.target.value)} />
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 10 }}>
        <select style={{ ...inputStyle, width: 'auto' }} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="resume">resume</option>
          <option value="cover_letter">cover letter</option>
        </select>
        <button type="button" className="jc-btn-primary" onClick={add}
          style={{ background: 'var(--cyan-500, #00B5C8)', color: '#062330', border: 'none', borderRadius: 8, fontWeight: 700, padding: '9px 16px', cursor: 'pointer' }}>
          Add entry
        </button>
        {status && <span style={{ color: 'var(--warn, #f59e0b)', fontSize: 12 }}>{status}</span>}
      </div>
    </Panel>
  )
}

function JudgeSection({ judge, calMap, calDefault }) {
  const [provider, setProvider] = useState(judge.provider || '')
  const [model, setModel] = useState(judge.model || '')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(judge.base_url || '')
  const [status, setStatus] = useState('')

  const cal = !provider
    ? 'server default judge — the calibrated configuration the platform runs'
    : (calMap?.[model.trim()] || calDefault)

  const save = async () => {
    setStatus('saving…')
    try {
      const out = await apiSend('/dashboard/evals/judge', {
        body: { provider, model, api_key: apiKey, base_url: baseUrl },
      })
      setApiKey('')
      setStatus(out.warning ? `saved, but: ${out.warning}` : 'saved — applies to your next run')
    } catch (err) {
      setStatus(err?.body?.error || err.message)
    }
  }

  return (
    <Panel>
      <SectionHead title="Judge" />
      <div style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 13, marginBottom: 12, lineHeight: 1.5 }}>
        Judges are not interchangeable: scores are only comparable to the same judge&apos;s earlier
        runs. A cheaper judge is a fine drift signal for your own trend line — the calibration
        label tells you what has actually been measured, and on what.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
        <select style={inputStyle} value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">Server default (calibrated)</option>
          <option value="openai">OpenAI (your key)</option>
          <option value="anthropic">Anthropic (your key)</option>
          <option value="ollama">Ollama / local</option>
        </select>
        <input style={inputStyle} placeholder="Model (blank = provider default)" value={model}
          onChange={(e) => setModel(e.target.value)} />
        <input style={inputStyle} type="password" autoComplete="off"
          placeholder={judge.has_key ? 'API key (stored, unchanged)' : 'API key'}
          value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        <input style={inputStyle} placeholder="Base URL (Ollama only)" value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div style={{ color: cal.startsWith('calibrated') || !provider ? 'var(--ok, #22c55e)' : 'var(--text-muted, #9aa8bf)', fontSize: 12.5, margin: '10px 0' }}>
        {cal}
      </div>
      {judge.key_plaintext_at_rest && (
        <div style={{ color: 'var(--warn, #f59e0b)', fontSize: 12.5, marginBottom: 10 }}>
          ⚠ your key is stored WITHOUT encryption — this server has no APP_ENCRYPTION_KEY
          configured. It is never shown or sent back, but it sits in cleartext at rest; clear
          the provider to remove it if that is not acceptable.
        </div>
      )}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button type="button" onClick={save}
          style={{ background: 'var(--cyan-500, #00B5C8)', color: '#062330', border: 'none', borderRadius: 8, fontWeight: 700, padding: '9px 16px', cursor: 'pointer' }}>
          Save judge
        </button>
        {status && <span style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 12 }}>{status}</span>}
      </div>
    </Panel>
  )
}

function RunSection({ stamp, reload }) {
  const [n, setN] = useState('5')
  const [status, setStatus] = useState('')

  const run = async () => {
    setStatus('starting…')
    try {
      const out = await apiSend('/dashboard/evals/run', { body: { n: parseInt(n, 10) } })
      setStatus(`running (work #${out.work_id}) — a full run takes 1–3 hours; results appear here when stored`)
      const poll = setInterval(async () => {
        try {
          const s = await (await fetch('/dashboard/evals/stamp', { credentials: 'same-origin' })).json()
          if (s.updated_at && s.updated_at !== stamp) { clearInterval(poll); reload() }
        } catch { /* transient — next tick retries */ }
      }, 60000)
    } catch (err) {
      setStatus(err?.body?.error || err.message)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <select style={{ ...inputStyle, width: 'auto' }} value={n} onChange={(e) => setN(e.target.value)}>
          <option value="1">N=1 (quick)</option>
          <option value="3">N=3</option>
          <option value="5">N=5 (full variance)</option>
        </select>
        <button type="button" onClick={run}
          style={{ background: 'var(--cyan-500, #00B5C8)', color: '#062330', border: 'none', borderRadius: 8, fontWeight: 700, padding: '9px 16px', cursor: 'pointer' }}>
          Run evals
        </button>
        {status && <span style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 12.5 }}>{status}</span>}
      </div>
      <div style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 12.5, marginTop: 8, lineHeight: 1.5 }}>
        First runs usually flag a lot — most of it points at gaps in your master resume, not at
        the generator. Triage with <b>D</b>, document the true facts, and the count drains on the
        next run.
      </div>
      <div style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 12.5, marginTop: 4 }}>
        Cost scales with entries × N: on the default judge a 5-entry set at N=5 runs roughly
        $2.50–8. A cheaper judge (below) cuts this.
      </div>
    </div>
  )
}

/* ---------- screen ---------- */

export default function Evals() {
  const { data, loading, error, reload } = useApi('/dashboard/evals/data')
  const rows = data?.rows || []
  const claims = data?.claims || []
  const history = data?.history || []
  const summary = data?.summary || {}
  const ruled = claims.filter((c) => c.ruling).length
  const hasRun = rows.length > 0

  return (
    <Screen loading={loading} error={error}>
      {hasRun && (
        <StatGrid>
          <Stat label="Mean score" value={summary.mean != null ? summary.mean.toFixed(2) : '—'}
            tone={summary.mean >= 4 ? 'ok' : 'warn'} />
          <Stat label="Hallucination flags" value={summary.total_flags ?? '—'}
            tone={summary.total_flags === 0 ? 'ok' : 'danger'} sub={`N=${summary.n_runs ?? '?'}`} />
          <Stat label="Judge" value={summary.judge_model || 'unknown'} sub={summary.judge_calibration} />
          <Stat label="Stored" value={data?.stamp || '—'} tone="muted" />
        </StatGrid>
      )}

      {history.length >= 2 && (
        <div style={{ display: 'grid', gap: 14, marginBottom: 20 }}>
          <TrendChart history={history} />
          <DimensionChart dims={history[history.length - 1]?.dimensions} />
        </div>
      )}

      {hasRun ? (
        <>
          <SectionHead title="Latest run" />
          <List>
            {rows.map((r) => (
              <Row key={r.gd_id} title={`${r.gd_id} — ${r.role || ''}`}
                subtitle={r.error ? `errored: ${r.error}`
                  : `mean ${Number(r.mean).toFixed(2)} · accuracy ${r.accuracy} · CoV ${r.cov_pct}% · flips ${r.flip_rate_pct}%`}
                right={(
                  <Badge tone={(r.flags ?? 0) === 0 ? 'ok' : 'danger'}>
                    {r.flags ?? '—'} flags
                  </Badge>
                )} />
            ))}
          </List>
          <div style={{ margin: '14px 0 24px' }}>
            <RunSection stamp={data?.stamp} reload={reload} />
          </div>

          <SectionHead title="Triage flagged claims" right={`${ruled}/${claims.length} ruled`} />
          <div style={{ color: 'var(--text-muted, #9aa8bf)', fontSize: 12.5, margin: '0 0 12px', lineHeight: 1.5 }}>
            {Object.entries(data?.triage_meanings || {}).map(([k, v]) => (
              <div key={k}><b style={{ color: RULING_COLORS[k], fontFamily: 'var(--font-mono)' }}>{k}</b> — {v}</div>
            ))}
            <div style={{ marginTop: 6 }}>
              Rulings persist across runs. Every <b>D</b> is a to-do — document the fact in your
              master resume, and the flag converts to a citable strength on the next run.
            </div>
          </div>
          {claims.length === 0 ? (
            <EmptyState label="Nothing to triage — the stored run has no flagged claims." hint="That is the goal state; keep it." />
          ) : (
            <List>
              {claims.map((c) => <TriageCard key={c.key} claim={c} meanings={data?.triage_meanings} />)}
            </List>
          )}
          <div style={{ height: 24 }} />
        </>
      ) : (
        <div style={{ marginBottom: 20 }}>
          <EmptyState label="No eval run stored yet — nothing to triage or score."
            hint="Add golden entries below, then hit Run evals. Results land here when the run finishes." />
          <div style={{ marginTop: 14 }}>
            <RunSection stamp="" reload={reload} />
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gap: 14 }}>
        <GoldenSection golden={data?.golden || []} hasRun={hasRun} reload={reload} />
        <JudgeSection judge={data?.judge || {}} calMap={data?.calibration_map}
          calDefault={data?.calibration_default} />
      </div>
    </Screen>
  )
}
