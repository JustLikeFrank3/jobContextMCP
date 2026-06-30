import { useState } from 'react'
import { useApi, Screen, SectionHead, Badge, fmtDate } from './_shared.jsx'
import { apiPost, ApiError } from '../auth/api.js'
import { Panel, Button } from '../design-system'

/* Settings — account status, integrations, and the Oura connect/upload control.
   Editing the OpenAI key still happens on the classic settings page (it owns
   the tenant-config write path), but Oura readiness can be entered here: the
   first reading is what "connects" the ring and unlocks the Home hero.
   Data: GET /api/dashboard/settings, POST /api/dashboard/oura. */

function StatusRow({ label, ok, okText, offText, children }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        padding: '14px 16px', borderRadius: 'var(--radius-md)',
        background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
      }}
    >
      <div>
        <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
          {label}
        </div>
        {children && (
          <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 3 }}>{children}</div>
        )}
      </div>
      <Badge tone={ok ? 'green' : 'muted'}>{ok ? okText : offText}</Badge>
    </div>
  )
}

const fieldStyle = {
  width: '100%', boxSizing: 'border-box', background: 'var(--surface-sunken)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  padding: '9px 11px', color: 'var(--text)', fontSize: 'var(--fs-sm)',
}
const labelStyle = { display: 'block', fontSize: 'var(--fs-xs)', color: 'var(--muted)', marginBottom: 5 }

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function NumberField({ label, hint, value, onChange, min, max }) {
  return (
    <label style={{ display: 'block' }}>
      <span style={labelStyle}>{label}</span>
      <input
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={fieldStyle}
      />
      {hint && <span style={{ display: 'block', fontSize: 'var(--fs-2xs)', color: 'var(--faint)', marginTop: 4 }}>{hint}</span>}
    </label>
  )
}

function OuraReading({ oura }) {
  const cells = [
    ['Readiness', oura.readiness_score],
    ['Sleep', oura.sleep_score],
    ['HRV', `${oura.hrv} ms`],
    ['Recovery', oura.recovery_index],
  ]
  return (
    <div
      style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: 10,
        padding: '12px 14px', marginBottom: 14, borderRadius: 'var(--radius-md)',
        background: 'var(--tint-primary)', border: '1px solid var(--line-strong)',
      }}
    >
      {cells.map(([k, v]) => (
        <div key={k}>
          <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{k}</div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '1.4rem', color: 'var(--text-strong)', lineHeight: 1.1 }}>{v}</div>
        </div>
      ))}
      <div style={{ gridColumn: '1 / -1', fontSize: 'var(--fs-2xs)', color: 'var(--faint)' }}>
        Last reading: {fmtDate(oura.date) || oura.date || '\u2014'}
      </div>
    </div>
  )
}

function OuraControl({ oura, onSaved }) {
  const connected = Boolean(oura)
  const [readiness, setReadiness] = useState(oura?.readiness_score ?? '')
  const [sleep, setSleep] = useState(oura?.sleep_score ?? '')
  const [hrv, setHrv] = useState(oura?.hrv ?? '')
  const [recovery, setRecovery] = useState(oura?.recovery_index ?? '')
  const [date, setDate] = useState(todayIso())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [okMsg, setOkMsg] = useState('')

  async function submit() {
    setErr(''); setOkMsg('')
    const r = Number(readiness)
    if (!Number.isFinite(r) || r < 0 || r > 100) {
      setErr('Readiness is required and must be between 0 and 100.')
      return
    }
    setBusy(true)
    try {
      await apiPost('/api/dashboard/oura', {
        readiness_score: r,
        sleep_score: Number(sleep) || 0,
        hrv: Number(hrv) || 0,
        recovery_index: Number(recovery) || 0,
        date: date || '',
      })
      setOkMsg(connected ? 'Reading updated. The Home hero now reflects it.' : 'Ring connected. Readiness is now live on Home.')
      onSaved()
    } catch (e) {
      if (e instanceof ApiError) {
        setErr(e.body ? `Could not save (${e.status}): ${e.body.slice(0, 200)}` : `Could not save (${e.status}).`)
      } else {
        setErr('Could not save the reading. Try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel>
      {connected && <OuraReading oura={oura} />}
      <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.5, marginBottom: 14 }}>
        {connected
          ? 'Update today\u2019s scores below, or log a different date. Re-logging the same date overwrites it.'
          : 'Enter your latest Oura scores to connect the ring. Readiness drives the Home dashboard hero; without it Home shows the Daily Digest instead.'}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 12 }}>
        <NumberField label="Readiness *" hint="0\u2013100" value={readiness} onChange={setReadiness} min={0} max={100} />
        <NumberField label="Sleep score" hint="0\u2013100" value={sleep} onChange={setSleep} min={0} max={100} />
        <NumberField label="HRV" hint="ms (rMSSD)" value={hrv} onChange={setHrv} min={0} max={400} />
        <NumberField label="Recovery index" hint="0\u2013100" value={recovery} onChange={setRecovery} min={0} max={100} />
      </div>

      <label style={{ display: 'block', maxWidth: 220, marginBottom: 16 }}>
        <span style={labelStyle}>Date</span>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={fieldStyle} />
      </label>

      {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12, whiteSpace: 'pre-wrap' }}>{err}</div>}
      {okMsg && <div style={{ color: 'var(--green-300)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>{okMsg}</div>}

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button size="sm" onClick={submit} disabled={busy}>
          {busy ? 'Saving\u2026' : connected ? 'Update reading' : 'Connect ring'}
        </Button>
      </div>
    </Panel>
  )
}

export default function Settings() {
  const { data, loading, error, reload } = useApi('/api/dashboard/settings')

  return (
    <Screen loading={loading} error={error}>
      <SectionHead title="Account" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gap: 10 }}>
          <StatusRow label="Owner access" ok={data?.isOwner} okText="owner" offText="standard">
            {data?.isOwner ? 'You have owner-only features enabled.' : 'Standard user account.'}
          </StatusRow>
        </div>
      </Panel>

      <SectionHead title="Integrations" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gap: 10 }}>
          <StatusRow label="AI generation (OpenAI key)" ok={data?.openaiKeySet} okText="configured" offText="not set">
            Enables resume generation, cover letter drafting, and semantic search.
          </StatusRow>
          <StatusRow label="Oura Ring" ok={data?.ouraConnected} okText="connected" offText="not connected">
            Readiness data powers the Home dashboard hero.
          </StatusRow>
        </div>
        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <a
            href={data?.classicUrl || '/dashboard/settings'}
            style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}
          >
            Edit AI key and preferences {'\u2192'}
          </a>
        </div>
      </Panel>

      <SectionHead title="Oura Ring readiness" />
      <OuraControl oura={data?.oura || null} onSaved={reload} />
    </Screen>
  )
}
