import { useRef, useState } from 'react'
import { apiPost } from '../../auth/api.js'
import { parseCSV, autoDetectMap, extractHashtags, numCell, fmtK } from './csv.js'

/* LinkedIn CSV import — the desktop design's 3-step flow.
   1 Upload: dashed drop zone (real drag-and-drop + file input).
   2 Map & preview: per-field column selects with MAPPED/REQUIRED/OPTIONAL
     tags, live 5-row preview, metrics note, footer bar with the count.
   3 Done: glow-check, stat tiles, and the summary of what was persisted.
   Confirm POSTs to /dashboard/posts/import (log_linkedin_post +
   update_post_metrics server-side) — unlike the prototype, it's real. */

const MONO = { fontFamily: 'var(--font-mono)' }
const EYEBROW = {
  fontSize: 11, fontWeight: 'var(--fw-semibold)', letterSpacing: 1.5,
  color: '#56637E', ...MONO,
}

export function StepIndicator({ step }) {
  const dot = (n) => ({
    width: 20, height: 20, borderRadius: '50%',
    background: step >= n ? 'var(--cyan-500)' : 'rgba(255,255,255,.14)',
    color: '#04222A', fontSize: 11, fontWeight: 'var(--fw-bold)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  })
  const lbl = (n) => ({ fontSize: 12, fontWeight: 'var(--fw-semibold)', color: step >= n ? 'var(--cyan-300)' : '#54627C' })
  const line = (n) => ({ width: 26, height: 2, borderRadius: 2, background: step >= n ? 'var(--cyan-500)' : 'rgba(255,255,255,.12)' })
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}><div style={dot(1)}>1</div><span style={lbl(1)}>Upload</span></div>
      <div style={line(2)} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}><div style={dot(2)}>2</div><span style={lbl(2)}>Map</span></div>
      <div style={line(3)} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}><div style={dot(3)}>3</div><span style={lbl(3)}>Done</span></div>
    </div>
  )
}

const SAMPLE_CSV = [
  'Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility',
  '2026-06-14,https://lnkd.in/a1,"Got laid off, so I built the tool I wished I had — persistent memory for my job search. #jobsearch #buildinpublic",,,MEMBER_NETWORK',
  '2026-06-22,https://lnkd.in/b2,"Your career has context. Your AI should too. Here is how I wired mine up with MCP. #AI #MCP #careers",,,PUBLIC',
  '2026-07-01,https://lnkd.in/c3,"Shipped v1.2: an offline desktop app that remembers your whole job hunt. #buildinpublic",,,PUBLIC',
  '2026-07-09,https://lnkd.in/d4,"Interview prep is just context assembly. A thread on how I automated mine. #interviews #jobsearch",,,PUBLIC',
].join('\n')

const FIELD_DEFS = [
  { key: 'text', title: 'Post text', req: true },
  { key: 'date', title: 'Date', req: false },
  { key: 'imp', title: 'Impressions', req: false },
  { key: 'rx', title: 'Reactions', req: false },
  { key: 'cm', title: 'Comments', req: false },
]

export default function ImportFlow({ step, setStep, onDone, onCancel }) {
  const [dragOver, setDragOver] = useState(false)
  const [fileName, setFileName] = useState('')
  const [headers, setHeaders] = useState([])
  const [rows, setRows] = useState([])
  const [map, setMap] = useState({ text: -1, date: -1, imp: -1, rx: -1, cm: -1 })
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const fileRef = useRef(null)

  function ingest(text, name) {
    const parsed = parseCSV(text)
    if (parsed.length < 2) { setErr('That CSV has no data rows.'); return }
    setErr('')
    setFileName(name)
    setHeaders(parsed[0].map((h) => h.trim()))
    setRows(parsed)
    setMap(autoDetectMap(parsed[0]))
    setStep(2)
  }

  function readFile(file) {
    const reader = new FileReader()
    reader.onload = () => ingest(String(reader.result), file.name)
    reader.readAsText(file)
  }

  const dataRows = rows.slice(1)
  const validRows = dataRows.filter((r) => map.text >= 0 && (r[map.text] || '').trim())
  const hasMetrics = map.imp >= 0 || map.rx >= 0 || map.cm >= 0
  const canImport = map.text >= 0 && validRows.length > 0 && !busy
  const metricRowCount = validRows.filter((r) =>
    [map.imp, map.rx, map.cm].some((idx) => idx >= 0 && numCell(r[idx]) != null)).length

  async function confirm() {
    if (!canImport) return
    setBusy(true)
    setErr('')
    try {
      const posts = validRows.map((r) => {
        const text = r[map.text].trim()
        const metric = (idx) => (idx >= 0 ? numCell(r[idx]) : null)
        return {
          text,
          posted_date: map.date >= 0 ? (r[map.date] || '').trim() : '',
          hashtags: extractHashtags(text),
          impressions: metric(map.imp),
          reactions: metric(map.rx),
          comments: metric(map.cm),
        }
      })
      const res = await apiPost('/dashboard/posts/import', { posts })
      setResult(res)
      setStep(3)
    } catch (e) {
      setErr(e?.body?.detail || e.message || 'Import failed.')
    } finally {
      setBusy(false)
    }
  }

  if (step === 1) {
    return (
      <div>
        <div style={{ fontSize: 27, fontWeight: 'var(--fw-bold)', color: 'var(--text)', letterSpacing: '-0.6px' }}>Import posts from LinkedIn</div>
        <div style={{ fontSize: '14.5px', color: '#A9B6CE', marginTop: 8, maxWidth: 600, lineHeight: 1.55 }}>
          Export your data from LinkedIn (Settings → Data Privacy → Get a copy of your data),
          then drop the CSV here. Everything is parsed locally and written to your workspace.
        </div>

        <label
          onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) readFile(f) }}
          onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true) }}
          onDragLeave={(e) => { e.preventDefault(); setDragOver(false) }}
          style={{
            marginTop: 24, position: 'relative', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 15, padding: 54,
            borderRadius: 24, border: `2px dashed ${dragOver ? 'var(--cyan-500)' : 'rgba(0,181,200,.4)'}`,
            background: dragOver ? 'rgba(0,181,200,.1)' : 'rgba(0,181,200,.03)',
            cursor: 'pointer', transition: 'all .18s', overflow: 'hidden',
          }}
        >
          <div style={{ position: 'absolute', width: 260, height: 260, borderRadius: '50%', background: 'radial-gradient(circle, rgba(0,181,200,.16), rgba(0,181,200,0) 68%)', animation: 'jc-glowRing 3.5s ease-in-out infinite', pointerEvents: 'none' }} />
          <div style={{ position: 'relative', width: 72, height: 72, borderRadius: 20, background: 'linear-gradient(150deg, rgba(0,181,200,.25), rgba(0,181,200,.06))', border: '1px solid rgba(0,181,200,.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'jc-float 3.5s ease-in-out infinite', boxShadow: '0 8px 30px rgba(0,181,200,.15)' }}>
            <svg width={32} height={32} viewBox="0 0 24 24" fill="none" stroke="var(--cyan-300)" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v13M7 8l5-5 5 5" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>
          </div>
          <div style={{ position: 'relative', fontSize: 18, fontWeight: 'var(--fw-semibold)', color: 'var(--text)' }}>Drag your CSV here</div>
          <div style={{ position: 'relative', fontSize: 13, color: '#8A99B5', ...MONO }}>Shares.csv · Engagement.csv · analytics export</div>
          <div style={{ position: 'relative', marginTop: 6, fontSize: '13.5px', fontWeight: 'var(--fw-bold)', color: '#04222A', background: 'var(--cyan-500)', padding: '10px 22px', borderRadius: 12, boxShadow: '0 6px 20px rgba(0,181,200,.3)' }}>Choose file…</div>
          <input ref={fileRef} type="file" accept=".csv,text/csv" style={{ display: 'none' }} onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = '' }} />
        </label>

        {err && <div style={{ marginTop: 14, color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)' }}>{err}</div>}
        <div style={{ marginTop: 18, display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#8A99B5' }}>
          <span onClick={() => ingest(SAMPLE_CSV, 'Shares.csv (sample)')} style={{ cursor: 'pointer', color: 'var(--cyan-300)', fontWeight: 'var(--fw-semibold)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            Use sample Shares.csv
          </span>
          <span>to preview the flow</span>
        </div>
      </div>
    )
  }

  if (step === 2) {
    const preview = validRows.slice(0, 5).map((r, i) => {
      const cell = (idx) => {
        if (idx < 0) return { v: '—', muted: true }
        const n = numCell(r[idx])
        return n == null ? { v: '—', muted: true } : { v: fmtK(n), muted: false }
      }
      return {
        text: (r[map.text] || '').replace(/\s+/g, ' ').trim() || '(empty)',
        imp: cell(map.imp), rx: cell(map.rx), cm: cell(map.cm),
        zebra: i % 2 ? 'rgba(255,255,255,.015)' : 'transparent',
      }
    })
    const cellColor = (c) => (c.muted ? '#54627C' : '#E8EFFB')

    return (
      <div style={{ paddingBottom: 90 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 24, fontWeight: 'var(--fw-bold)', color: 'var(--text)', letterSpacing: '-0.5px' }}>Map & preview</div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12, color: '#8A99B5', ...MONO, background: 'rgba(255,255,255,.04)', padding: '4px 10px', borderRadius: 8 }}>
            {fileName} · {Math.max(0, rows.length - 1)} rows
          </div>
        </div>
        <div style={{ display: 'flex', gap: 30, marginTop: 22, flexWrap: 'wrap' }}>
          <div style={{ width: 322, flexShrink: 0 }}>
            <div style={{ ...EYEBROW, marginBottom: 12 }}>COLUMN MAPPING</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
              {FIELD_DEFS.map((f) => {
                const mapped = map[f.key] >= 0
                const tag = mapped ? 'MAPPED' : f.req ? 'REQUIRED' : 'OPTIONAL'
                const tagColor = mapped ? '#6FD3A0' : f.req ? '#E39393' : '#56637E'
                const border = mapped ? 'rgba(0,181,200,.25)' : f.req ? 'rgba(227,147,147,.3)' : 'rgba(255,255,255,.07)'
                return (
                  <div key={f.key} style={{ padding: '13px 14px', borderRadius: 13, background: 'rgba(255,255,255,.035)', border: `1px solid ${border}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ fontSize: 12, fontWeight: 'var(--fw-semibold)', color: '#C9D6EC' }}>{f.title}</div>
                      <div style={{ fontSize: '9.5px', fontWeight: 'var(--fw-semibold)', letterSpacing: 0.5, color: tagColor, ...MONO }}>{tag}</div>
                    </div>
                    <select
                      value={String(map[f.key])}
                      onChange={(e) => setMap((m) => ({ ...m, [f.key]: parseInt(e.target.value, 10) }))}
                      style={{
                        marginTop: 9, width: '100%', background: 'rgba(255,255,255,.05)',
                        border: '1px solid rgba(255,255,255,.12)', borderRadius: 10,
                        padding: '9px 12px', color: 'var(--text)', fontSize: '13.5px',
                        fontFamily: 'var(--font-sans)', outline: 'none', cursor: 'pointer',
                      }}
                    >
                      <option value="-1" style={{ background: '#0E1524' }}>— none —</option>
                      {headers.map((h, i) => (
                        <option key={i} value={String(i)} style={{ background: '#0E1524' }}>{h || `Column ${i + 1}`}</option>
                      ))}
                    </select>
                  </div>
                )
              })}
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 320 }}>
            <div style={{ ...EYEBROW, marginBottom: 12 }}>PREVIEW · FIRST {preview.length} ROWS</div>
            <div style={{ borderRadius: 16, border: '1px solid rgba(255,255,255,.08)', overflow: 'hidden', background: 'rgba(255,255,255,.02)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 82px 68px 78px', background: 'rgba(0,181,200,.06)', padding: '11px 16px', fontSize: '10.5px', fontWeight: 'var(--fw-semibold)', letterSpacing: 0.5, color: 'var(--cyan-300)', ...MONO }}>
                <div>POST TEXT</div><div style={{ textAlign: 'right' }}>IMPR</div><div style={{ textAlign: 'right' }}>RX</div><div style={{ textAlign: 'right' }}>COMM</div>
              </div>
              {preview.map((row, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 82px 68px 78px', padding: '13px 16px', borderTop: '1px solid rgba(255,255,255,.05)', alignItems: 'center', background: row.zebra }}>
                  <div style={{ fontSize: 13, color: '#E8EFFB', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 14 }}>{row.text}</div>
                  <div style={{ textAlign: 'right', fontSize: 13, color: cellColor(row.imp), ...MONO }}>{row.imp.v}</div>
                  <div style={{ textAlign: 'right', fontSize: 13, color: cellColor(row.rx), ...MONO }}>{row.rx.v}</div>
                  <div style={{ textAlign: 'right', fontSize: 13, color: cellColor(row.cm), ...MONO }}>{row.cm.v}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14, display: 'flex', alignItems: 'flex-start', gap: 9, padding: '12px 14px', borderRadius: 12, background: hasMetrics ? 'rgba(111,211,160,.07)' : 'rgba(224,183,122,.07)', border: `1px solid ${hasMetrics ? 'rgba(111,211,160,.2)' : 'rgba(224,183,122,.2)'}` }}>
              <div style={{ color: hasMetrics ? '#6FD3A0' : '#E0B77A', flexShrink: 0, marginTop: 1 }}>{hasMetrics ? '✓' : '!'}</div>
              <div style={{ fontSize: '12.5px', color: '#B7C6E0', lineHeight: 1.45 }}>
                {hasMetrics
                  ? 'Engagement columns detected — metrics will be saved with each post.'
                  : 'No metric columns mapped — posts import with metrics at 0; fill them in later on the Posts screen.'}
              </div>
            </div>
            {err && <div style={{ marginTop: 12, color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)' }}>{err}</div>}
          </div>
        </div>

        <div style={{ position: 'sticky', bottom: 0, marginTop: 26, marginLeft: -36, marginRight: -36, padding: '16px 36px', background: 'rgba(10,15,28,.85)', backdropFilter: 'blur(18px)', borderTop: '1px solid rgba(255,255,255,.07)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontSize: '13.5px', color: '#C9D6EC' }}>
            <span style={{ color: 'var(--cyan-300)', fontWeight: 'var(--fw-bold)', fontSize: 16 }}>{validRows.length}</span> posts ready to import
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <div onClick={onCancel} style={{ cursor: 'pointer', fontSize: '13.5px', fontWeight: 'var(--fw-semibold)', color: '#C9D6EC', background: 'rgba(255,255,255,.06)', padding: '11px 18px', borderRadius: 11 }}>Cancel</div>
            <div
              onClick={confirm}
              style={{
                cursor: canImport ? 'pointer' : 'not-allowed',
                fontSize: '13.5px', fontWeight: 'var(--fw-bold)', color: '#04222A',
                background: canImport ? 'var(--cyan-500)' : '#455266',
                opacity: canImport ? 1 : 0.5, padding: '11px 22px', borderRadius: 11,
                boxShadow: canImport ? '0 6px 20px rgba(0,181,200,.3)' : 'none',
              }}
            >
              {busy ? 'Importing…' : `Import ${validRows.length} posts →`}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Step 3 — done
  const summary = [
    `${result?.logged ?? 0} posts logged via log_linkedin_post`,
    'Persisted to your workspace (SQLite + JSON fallback)',
    result?.with_metrics ? 'Engagement metrics saved per post' : 'Metrics left at 0 — editable anytime',
    'Reindexed as tone samples for cover-letter voice',
  ]
  return (
    <div style={{ minHeight: 480, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
      <div style={{ position: 'relative', width: 84, height: 84, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ position: 'absolute', inset: -14, borderRadius: '50%', background: 'radial-gradient(circle, rgba(111,211,160,.3), rgba(111,211,160,0) 70%)', animation: 'jc-glowRing 3s ease-in-out infinite' }} />
        <div style={{ width: 84, height: 84, borderRadius: '50%', background: 'rgba(111,211,160,.14)', border: '1.5px solid rgba(111,211,160,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'jc-checkPop .5s cubic-bezier(.34,1.56,.64,1) both' }}>
          <svg width={40} height={40} viewBox="0 0 24 24" fill="none" stroke="#7BD88F" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M4 12.5l5 5 11-11" /></svg>
        </div>
      </div>
      <div style={{ fontSize: 27, fontWeight: 'var(--fw-bold)', color: 'var(--text)', letterSpacing: '-0.5px', marginTop: 24 }}>Imported {result?.logged ?? 0} posts</div>
      <div style={{ fontSize: '14.5px', color: '#A9B6CE', marginTop: 8 }}>Written to your workspace and ready across every jobContext client.</div>
      <div style={{ marginTop: 26, display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
        <div style={{ width: 132, padding: 16, borderRadius: 16, background: 'rgba(0,181,200,.08)', border: '1px solid rgba(0,181,200,.2)' }}>
          <div style={{ fontSize: 28, fontWeight: 'var(--fw-bold)', color: 'var(--cyan-300)' }}>{result?.logged ?? 0}</div>
          <div style={{ fontSize: 11, color: '#8AB6C4', marginTop: 3 }}>posts logged</div>
        </div>
        <div style={{ width: 132, padding: 16, borderRadius: 16, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)' }}>
          <div style={{ fontSize: 28, fontWeight: 'var(--fw-bold)', color: 'var(--text)' }}>{result?.with_metrics ?? metricRowCount}</div>
          <div style={{ fontSize: 11, color: '#8A99B5', marginTop: 3 }}>with metrics</div>
        </div>
        <div style={{ width: 132, padding: 16, borderRadius: 16, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)' }}>
          <div style={{ fontSize: 15, fontWeight: 'var(--fw-bold)', color: 'var(--text)', marginTop: 8 }}>CSV</div>
          <div style={{ fontSize: 11, color: '#8A99B5', marginTop: 5 }}>source</div>
        </div>
      </div>
      <div style={{ marginTop: 22, width: 480, maxWidth: '100%', borderRadius: 16, background: 'rgba(255,255,255,.035)', border: '1px solid rgba(255,255,255,.07)', overflow: 'hidden', textAlign: 'left' }}>
        {summary.map((s) => (
          <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 18px', borderBottom: '1px solid rgba(255,255,255,.05)' }}>
            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="#6FD3A0" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round"><path d="M4 12.5l5 5 11-11" /></svg>
            <div style={{ fontSize: '13.5px', color: 'var(--text-soft)' }}>{s}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 26, display: 'flex', gap: 10 }}>
        <div onClick={onDone} style={{ cursor: 'pointer', fontSize: '13.5px', fontWeight: 'var(--fw-bold)', color: '#04222A', background: 'var(--cyan-500)', padding: '12px 24px', borderRadius: 12, boxShadow: '0 6px 20px rgba(0,181,200,.28)' }}>View in Posts</div>
        <div onClick={() => { setResult(null); setFileName(''); setHeaders([]); setRows([]); setMap({ text: -1, date: -1, imp: -1, rx: -1, cm: -1 }); setStep(1) }} style={{ cursor: 'pointer', fontSize: '13.5px', fontWeight: 'var(--fw-semibold)', color: '#C9D6EC', background: 'rgba(255,255,255,.06)', padding: '12px 20px', borderRadius: 12 }}>Import another</div>
      </div>
    </div>
  )
}
