import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Panel } from '../design-system'
import { loginUrl } from '../auth/api.js'
import { errorText, madeFrom, recentGenerations, request, terminal, wantedFor } from './conference/api.js'
import './conference/demo.css'

export default function ConferenceDemo() {
  const [online, setOnline] = useState(() => navigator.onLine)
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('pipeline')
  const [results, setResults] = useState(null)
  const [selected, setSelected] = useState(null)
  const [material, setMaterial] = useState('both')
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const [error, setError] = useState('')
  const [recent, setRecent] = useState([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [current, setCurrent] = useState(null)
  const [pollError, setPollError] = useState('')
  const [pollAttempt, setPollAttempt] = useState(0)

  const refreshRecent = useCallback(async () => {
    const rows = recentGenerations(await request('/api/work?limit=50'))
    setRecent(rows)
    setHistoryLoaded(true)
    return rows
  }, [])

  useEffect(() => {
    refreshRecent().catch(e => setError(errorText(e)))
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [refreshRecent])

  // Keep the handle in the URL: refresh/back/re-auth can resume the same work.
  // It is an ID, not a credential; the server still enforces the tenant boundary.
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get('work'))
    if (!Number.isSafeInteger(id) || id <= 0) return
    request(`/api/work/${id}`).then(item => {
      if (item.kind === 'badge_materials') setCurrent({ ...item, made: madeFrom(item) })
    }).catch(e => setError(errorText(e)))
  }, [])

  function track(item) {
    setPollError('')
    setCurrent({ ...item, made: madeFrom(item) })
    const url = new URL(window.location.href)
    url.searchParams.set('work', item.id)
    window.history.replaceState(null, '', url)
    setPollAttempt(n => n + 1)
  }

  const workId = current?.id
  const workStatus = current?.status
  useEffect(() => {
    if (!workId || terminal(workStatus) || !online) return
    let stopped = false
    let timer
    async function poll() {
      try {
        const item = await request(`/api/badge/work/${workId}`)
        if (stopped) return
        setPollError('')
        setCurrent(old => ({ ...old, ...item }))
        if (terminal(item.status)) {
          refreshRecent().catch(() => {})
        } else {
          timer = setTimeout(poll, 3000)
        }
      } catch (e) {
        if (!stopped) setPollError(errorText(e))
        // Pause on errors; an explicit check retries only the GET.
      }
    }
    poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [workId, workStatus, online, pollAttempt, refreshRecent])

  async function action(fn) {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setError('')
    try { await fn() } catch (e) { setError(errorText(e)) }
    finally { locked.current = false; setBusy(false) }
  }

  function search(event) {
    event.preventDefault()
    action(async () => {
      setSelected(null)
      setResults(null)
      const endpoint = source === 'pipeline' ? 'search' : 'jobs'
      const data = await request(`/api/badge/${endpoint}?q=${encodeURIComponent(query.trim())}&limit=12`)
      setResults({ ...data, source })
    })
  }

  function choose(job) {
    action(async () => {
      setSelected(null)
      const chosen = results.source === 'pipeline' ? job : await request('/api/badge/jobs/queue', {
        search_id: results.search_id, number: job.number,
      })
      setSelected(chosen)
    })
  }

  const active = recent.some(item => !terminal(item.status)) || (current && !terminal(current.status))

  function generate() {
    if (!selected || active || uncertain || !historyLoaded) return
    action(async () => {
      try {
        const inputs = { job_id: selected.job_id, material }
        const out = await request('/api/badge/materials', inputs)
        if (!Number.isSafeInteger(out?.work_id) || out.work_id <= 0) throw new Error('Missing work id')
        track({ id: out.work_id, inputs, status: 'queued', artifacts: {} })
        refreshRecent().catch(() => {})
      } catch (e) {
        // A missing response / 5xx does not prove the server rejected the POST.
        if (![401, 403, 410, 422, 429].includes(e?.status)) {
          setUncertain(true)
          setHistoryLoaded(false)
        }
        throw e
      }
    })
  }

  const missing = current?.status === 'succeeded'
    ? wantedFor(current.inputs?.material).filter(k => !current.made?.includes(k)) : []

  return <div className="conference-demo">
    <p>Find a role, select it, and create tailored documents. <Link to="/pipeline">Pipeline</Link> and <Link to="/materials">Materials</Link> remain available.</p>
    {!online && <p role="alert">You are offline. Switch to cellular or a hotspot. A queued generation can continue on the server; reconnect and check its status. For now, show the example PDFs saved on your device.</p>}
    {error && <p role="alert">{error} <a href={loginUrl('/app/conference-demo')} target="_blank" rel="noreferrer">Sign in in another tab</a></p>}
    <Panel>
      <form onSubmit={search}>
        <label>Search in<select value={source} onChange={e => { setSource(e.target.value); setResults(null); setSelected(null) }} disabled={busy}>
          <option value="pipeline">My pipeline</option><option value="open">Open positions</option>
        </select></label>
        <label>Company or role<input value={query} onChange={e => setQuery(e.target.value)} maxLength={120} placeholder="e.g. GitHub or platform engineer" required disabled={busy} /></label>
        <Button type="submit" disabled={busy || !online || !query.trim()}>Search</Button>
      </form>
      {results && <div aria-live="polite">
        <p>{results.count ? `Showing up to 12 results for ${query}. Select a role below.` : 'No matches. Try a more specific company or role, switch search source, or add a job in Pipeline.'}</p>
        {results.results.map((job, i) => <div className="conference-result" key={`${job.job_id || job.number}-${i}`}>
          <div><strong>{job.company}</strong><div>{job.role}</div><small>{job.location || job.status}</small></div>
          {results.source === 'pipeline' && !job.job_id
            ? <span>Employer only — search Open positions or add a job in Pipeline.</span>
            : <Button disabled={busy || !online} onClick={() => choose(job)}>{results.source === 'pipeline' ? 'Select' : 'Add & select'}</Button>}
        </div>)}
        <small>Long titles are shortened by the badge API. Review the full role in Pipeline before generating if needed.</small>
      </div>}
    </Panel>
    {selected && <Panel>
      <h2>Selected: {selected.company}</h2><p>{selected.role} · Job #{selected.job_id}</p>
      <label>Documents<select value={material} onChange={e => setMaterial(e.target.value)} disabled={busy}>
        <option value="both">Resume + cover letter</option><option value="resume">Resume only</option><option value="cover_letter">Cover letter only</option>
      </select></label>
      <Button onClick={generate} disabled={busy || !online || !!active || uncertain || !historyLoaded}>Generate documents</Button>
      {active && <p>A generation is already queued or running. Check it below before starting another.</p>}
    </Panel>}
    {current && <Panel>
      <h2>Generation #{current.id}</h2>
      <p role="status">{current.status === 'succeeded' ? (missing.length ? 'Partially completed' : 'Completed') : current.status}</p>
      <p>Created: {current.made?.join(', ').replaceAll('_', ' ') || 'none reported yet'}.</p>
      {missing.length > 0 && <p role="alert">Not created: {missing.join(', ').replaceAll('_', ' ')}. Open Materials to keep the completed document; select only the missing document to try again.</p>}
      {current.status === 'failed' && <p role="alert">Generation failed. {current.detail || 'Check Materials for any saved files, then try the failed document once or show your saved example.'}</p>}
      {pollError && <p role="alert">Status check paused. {pollError}</p>}
      {!terminal(current.status) && <><p>You can leave this page; generation continues on the server. Keep this URL or select the run below to resume. After a few minutes, switch to your saved example while checking this run.</p><Button disabled={!online || busy} onClick={() => { setPollError(''); setPollAttempt(n => n + 1) }}>Check status</Button></>}
      <p><Link to="/materials">Open Materials to preview or download</Link></p>
    </Panel>}
    <Panel>
      <h2>Recent generations</h2>
      <p>After a refresh or lost connection, select the existing run here. Refreshing this list never submits another generation.</p>
      <Button disabled={!online || busy} onClick={() => action(refreshRecent)}>Refresh recent generations</Button>
      {uncertain && <div role="alert"><p>The generation request may have reached the server. Refresh this list and check Materials before submitting again.</p><Button disabled={!historyLoaded || !!active || busy} onClick={() => setUncertain(false)}>I checked recent runs and Materials</Button></div>}
      {historyLoaded && recent.length === 0 && <p>No badge or conference generations among the latest 50 work items.</p>}
      {recent.map(item => <div className="conference-result" key={item.id}>
        <span>#{item.id} · {item.artifacts?.company || `Job #${item.inputs?.job_id}`} · {item.inputs?.material?.replaceAll('_', ' ')} · {item.status} · {item.created_at} UTC</span>
        <Button disabled={busy} onClick={() => track(item)}>View status #{item.id}</Button>
      </div>)}
    </Panel>
    <p>Before the conference, download one successful resume and cover letter from Materials to Files on your phone and to your laptop. They are your offline demonstration; new searches and generation require a connection.</p>
  </div>
}
