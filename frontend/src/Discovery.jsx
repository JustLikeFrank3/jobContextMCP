import React, { useEffect, useState } from 'react'
import './discovery.css'

const channels = ['network_free', 'linkedin_paid', 'discord', 'referral', 'other']
const segments = ['job searching', 'career change', 'coach', 'recruiter or hiring', 'school or workforce program', 'none of these']
const assistants = ['ChatGPT', 'Claude', 'Copilot', 'Gemini', 'other', 'none']
const thanks = "Thanks. I'll send the one-page consent form and a calendar link within a day."
const friendly = value => value.replaceAll('_', ' ')

async function api(path, payload) {
  const response = await fetch(`/api/discovery/${path}`, {
    credentials: path === 'signup' ? 'omit' : 'same-origin',
    ...(payload ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {}),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to save. Please check the fields and try again.')
  return data
}

function Field({ name, label, options, type = 'text', required = true, defaultValue, maxLength = 2000 }) {
  return <label>{label}{options ? <select name={name} required={required} defaultValue={defaultValue || ''}>
    {!defaultValue && <option value="" disabled>Select one</option>}
    {options.map(option => <option key={option} value={option}>{friendly(option)}</option>)}
  </select> : <input name={name} type={type} required={required} defaultValue={defaultValue} maxLength={maxLength} min={type === 'number' ? 0 : undefined} />}</label>
}

const isBetaSignup = () => window.location.pathname === '/discovery/beta' || new URLSearchParams(window.location.search).get('program') === 'beta'
const betaThanks = "Thanks for your interest in the jobContext beta. I'll email you within a day with next steps and details about testing."
function Signup() {
  const beta = isBetaSignup()
  const channel = new URLSearchParams(window.location.search).get('c')
  const alternate = `${beta ? '/discovery' : '/discovery/beta'}${channels.includes(channel) ? `?c=${encodeURIComponent(channel)}` : ''}`
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    const values = Object.fromEntries(new FormData(event.currentTarget))
    const query = new URLSearchParams(window.location.search)
    values.channel = channels.includes(query.get('c')) ? query.get('c') : 'other'
    values.program = beta ? 'beta' : 'interview'
    try { await api('signup', values); setDone(true) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  if (done) return <p role="status" className="discovery-thanks">{beta ? betaThanks : thanks}</p>
  return <>
    <p className="discovery-eyebrow">jobContext / {beta ? 'Beta signup' : 'Customer discovery'}</p>
    <h1>{beta ? 'Help test jobContext.' : 'Help shape a better job search.'}</h1>
    <p className="discovery-intro">{beta ? "Try jobContext with your own workflow and tell me what works, what gets confusing, and what breaks. Sign up below and I'll email you with access details and testing expectations. This is beta interest, not an interview booking or automatic account creation." : "I'm doing customer discovery for jobContext. This is a conversation, not a demo. $25 gift card for 30 minutes, or a year of jobContext Pro if you'd rather. You can stop at any point. Nothing that identifies you gets published, ever."}</p>
    <p><a href={alternate}>{beta ? 'Prefer a 30-minute research conversation? Interview signup' : 'Want to try the product? Beta signup'}</a></p>
    <form onSubmit={submit}>
      <Field name="segment_answer" label="Are you actively job searching, or do you coach people who are?" options={segments} />
      <label>What do you use today to keep track of applications, résumés, and interviews?<textarea name="current_tools" maxLength={2000} required rows={3} /></label>
      <Field name="ai_assistant" label="Which AI assistant do you use most, if any?" options={assistants} />
      <div className="discovery-grid"><Field name="name" label="Name" maxLength={160} /><Field name="email" label="Email" type="email" maxLength={254} /></div>
      <Field name="best_window" label={beta ? "When could you start testing? (optional)" : "Best 30-minute window (include your time zone)"} required={!beta} maxLength={500} />
      {!beta && <fieldset><legend>Which thank-you would you prefer?</legend>
        <label className="discovery-check"><input type="radio" name="incentive_preference" value="gift_card" required /> $25 gift card</label>
        <label className="discovery-check"><input type="radio" name="incentive_preference" value="pro_access" required /> 12 months of jobContext Pro</label>
      </fieldset>}
      <div className="discovery-trap" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" /></label></div>
      {error && <p role="alert" className="discovery-error">{error}</p>}
      <button disabled={busy}>{busy ? 'Sending…' : beta ? 'Join the beta list' : 'Count me in'}</button>
      <p className="discovery-note">Signing up expresses interest. Recording and quote permissions are collected separately.</p>
    </form>
  </>
}

const actionLabels = { consent: 'Record consent', schedule: 'Schedule session', complete: 'Complete session', quote: 'Add quote', incentive: 'Record incentive', status: 'Set status' }

function ActionForm({ participant, sessions, onSaved }) {
  const [action, setAction] = useState('consent')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event) {
    event.preventDefault(); setError(''); setBusy(true)
    const fields = Object.fromEntries(new FormData(event.currentTarget))
    if (['consent', 'schedule', 'incentive', 'status'].includes(action)) fields.participant = participant.id
    for (const key of ['session', 'minutes', 'amount']) if (key in fields) fields[key] = Number(fields[key])
    for (const key of ['recording_ok', 'quote_ok', 'public', 'pending', 'no_show']) if (key in fields) fields[key] = fields[key] === 'on'
    if (action === 'schedule') fields.when = new Date(fields.when).toISOString()
    if (action === 'incentive' && !('pending' in fields)) fields.pending = false
    try { await api(action, fields); await onSaved() } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <div className="discovery-actions">
    <label>Update this participant<select value={action} onChange={e => { setAction(e.target.value); setError('') }}>{Object.entries(actionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <form key={action} onSubmit={submit}>
      {['complete', 'quote'].includes(action) && <label>Session<select name="session" required defaultValue=""><option value="" disabled>Select a session</option>{sessions.map(s => <option key={s.id} value={s.id}>#{s.id}: {friendly(s.kind)} / {s.scheduled_for || 'unscheduled'} / {s.status}</option>)}</select></label>}
      {action === 'consent' && <><Field name="version" label="Signed consent version" defaultValue="2026-09" /><label className="discovery-check"><input type="checkbox" name="recording_ok" /> Recording permission granted</label><label className="discovery-check"><input type="checkbox" name="quote_ok" /> Quote permission granted</label></>}
      {action === 'schedule' && <><Field name="kind" label="Session kind" options={['interview', 'beta_session']} defaultValue={participant.program === 'beta' ? 'beta_session' : 'interview'} /><Field name="when" label="Date and time (your local time)" type="datetime-local" /></>}
      {action === 'complete' && <><Field name="minutes" label="Duration in minutes" type="number" defaultValue="30" /><Field name="themes" label="Themes (comma separated)" required={false} /><Field name="notes" label="Private notes reference" required={false} maxLength={1000} /><label className="discovery-check"><input type="checkbox" name="no_show" /> Participant did not attend</label></>}
      {action === 'quote' && <><label>Quote<textarea name="text" required maxLength={4000} rows={3} /></label><label className="discovery-check"><input type="checkbox" name="public" /> Reviewed for identifying details and approved for publication (requires quote consent)</label></>}
      {action === 'incentive' && <><Field name="earned_by" label="Completed interview session ID, or beta_complete" maxLength={80} /><Field name="type" label="Incentive" options={['gift_card', 'pro_access', 'none']} defaultValue="gift_card" /><Field name="amount" label="Amount in USD" type="number" defaultValue="25" /><Field name="reference" label="Payment or access reference (required when sent)" required={false} maxLength={300} /><label className="discovery-check"><input type="checkbox" name="pending" defaultChecked /> Pending delivery</label></>}
      {action === 'status' && <Field name="status" label="Status" options={['dropped', 'declined']} />}
      {error && <p role="alert" className="discovery-error">{error}</p>}
      <button disabled={busy}>{busy ? 'Saving…' : actionLabels[action]}</button>
    </form>
  </div>
}

function Review() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [snapshot, setSnapshot] = useState('')
  const [busy, setBusy] = useState(false)
  const [filters, setFilters] = useState({ status: '', segment: '', channel: '' })
  const refresh = async () => setData(await api('review'))
  useEffect(() => { refresh().catch(err => setError(err.message)) }, [])
  async function freeze() {
    setBusy(true); setError('')
    try { const result = await api('snapshot', {}); setSnapshot(`${result.filename}\nSHA-256: ${result.ledger_sha256}`) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  if (!data) return <p role="status">{error || 'Loading discovery ledger…'}</p>
  const { ledger, report } = data
  const people = ledger.participants.filter(p => Object.entries(filters).every(([key, value]) => !value || p[key] === value)).sort((a, b) => b.id - a.id)
  return <>
    <p className="discovery-eyebrow">jobContext / Founder review</p><h1>Customer discovery ledger</h1>
    <p>Signups are interest. Consent and completed sessions establish the counts.</p>
    <a href="/discovery">Interview signup</a> · <a href="/discovery/beta">Beta signup</a>
    {report.errors.map((text, i) => <p key={i} role="alert" className="discovery-error">{text}</p>)}
    {report.errors.length > 0 && <p className="discovery-error">Figures below are provisional. Publishing and snapshots are blocked until these errors are resolved.</p>}
    {report.warnings.map((text, i) => <p key={i} className="discovery-warning">{text}</p>)}
    <div className="discovery-stats">{Object.entries(report.numbers).map(([key, value]) => <div key={key}><strong>{key === 'consent_on_file_rate' ? `${Math.round(value * 100)}%` : value}</strong><span>{friendly(key)}</span></div>)}</div>
    <button onClick={freeze} disabled={busy || report.errors.length > 0}>{busy ? 'Saving snapshot…' : 'Snapshot'}</button>
    {snapshot && <pre role="status">{snapshot}</pre>}{error && <p role="alert" className="discovery-error">{error}</p>}
    <div className="discovery-grid">{Object.keys(filters).map(key => <label key={key}>{friendly(key)}<select value={filters[key]} onChange={e => setFilters({ ...filters, [key]: e.target.value })}><option value="">All</option>{[...new Set(ledger.participants.map(p => p[key]))].sort().map(v => <option key={v}>{v}</option>)}</select></label>)}</div>
    <p>{people.length} participant{people.length === 1 ? '' : 's'}</p>
    {people.map(p => { const sessions = ledger.sessions.filter(s => s.participant_id === p.id); const incentives = ledger.incentives.filter(i => i.participant_id === p.id); return <details key={p.id} className="discovery-person">
      <summary><strong>{p.name}</strong> · {p.contact} <span>#{p.id} / {p.status} / {p.program}</span></summary>
      <p>{p.created_at} · {friendly(p.segment)} · {friendly(p.channel)}</p>
      <dl>{Object.entries(p.screener || {}).map(([k, v]) => <React.Fragment key={k}><dt>{friendly(k)}</dt><dd>{Array.isArray(v) ? v.join(', ') : v}</dd></React.Fragment>)}</dl>
      <p>Consent: {p.consent.recorded_at || 'Not recorded'} · Version: {p.consent.version || 'none'} · Recording: {p.consent.recording_ok ? 'yes' : 'no'} · Quotes: {p.consent.quote_ok ? 'yes' : 'no'}</p>
      <h3>Sessions ({sessions.length})</h3>{sessions.map(s => <div key={s.id}><p>#{s.id} · {s.kind} · {s.status} · {s.scheduled_for} · {s.duration_minutes || 0} minutes</p><p>{s.themes.join(', ')} {s.notes_path}</p>{s.quotes.map((q, i) => <blockquote key={i}>{q.text} ({q.public ? 'public requested' : 'private'})</blockquote>)}</div>)}
      <h3>Incentives ({incentives.length})</h3>{incentives.map(i => <p key={i.id}>#{i.id} · {i.type} · ${i.amount_usd} · {i.status} · Earned by {i.earned_by} · {i.reference}</p>)}
      <ActionForm participant={p} sessions={sessions} onSaved={refresh} />
    </details> })}
  </>
}

export default function Discovery() {
  const review = window.location.pathname === '/discovery/review'
  const beta = !review && isBetaSignup()
  useEffect(() => { document.title = review ? 'jobContext: Discovery review' : beta ? 'jobContext: Beta signup' : 'jobContext: Customer discovery' }, [review, beta])
  return <main className={`discovery ${review ? 'discovery-review' : ''}`}>{review ? <Review /> : <Signup />}</main>
}
