import { useEffect, useState } from 'react'
import { useApi, Screen, SectionHead, Badge, fmtDate } from './_shared.jsx'
import { apiPost, ApiError } from '../auth/api.js'
import { Panel, Button } from '../design-system'

/* Settings: account integrations and the Oura Ring connection.

   Oura is a real OAuth integration. The user connects their actual Oura
   account (browser handshake in routes/dashboard/oura.py) and the server pulls
   readiness / sleep / HRV from the Oura Cloud API. There is no manual data
   entry here. Connect starts the login flow, Sync now pulls fresh data,
   Disconnect drops the stored tokens.

   Data:    GET  /api/dashboard/settings
   Actions: GET  /dashboard/oura/connect       (full-page nav)
            POST /api/dashboard/oura/sync
            POST /api/dashboard/oura/disconnect */

const CONNECT_URL = '/dashboard/oura/connect'

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

/* Reads the ?oura= outcome the OAuth callback redirects back with, then strips
   it from the URL so a refresh does not re-show the banner. */
function useOuraFlash() {
  const [flash, setFlash] = useState('')
  useEffect(() => {
    const loc = globalThis.location
    if (!loc) return
    const value = new URLSearchParams(loc.search).get('oura')
    if (!value) return
    setFlash(value)
    globalThis.history.replaceState({}, '', loc.pathname)
  }, [])
  return flash
}

const FLASH = {
  connected: { tone: 'green', text: 'Your Oura Ring is connected. Readiness now powers your Home dashboard.' },
  error: { tone: 'danger', text: 'Could not connect your Oura Ring. Please try again.' },
  unavailable: { tone: 'muted', text: 'Oura is not enabled on this server yet.' },
}

const FLASH_COLOR = { green: 'var(--green-300)', danger: 'var(--danger-soft)', muted: 'var(--muted)' }

function FlashBanner({ flash }) {
  const cfg = FLASH[flash]
  if (!cfg) return null
  const color = FLASH_COLOR[cfg.tone] || 'var(--muted)'
  const bg = cfg.tone === 'green' ? 'var(--tint-primary)' : 'var(--surface-sunken)'
  return (
    <div
      style={{
        padding: '11px 14px', marginBottom: 16, borderRadius: 'var(--radius-md)',
        background: bg, border: '1px solid var(--border-soft)', color, fontSize: 'var(--fs-sm)',
      }}
    >
      {cfg.text}
    </div>
  )
}

function NotConfigured({ isOwner }) {
  return (
    <Panel>
      <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55 }}>
        The Oura Ring integration is not enabled on this server yet, so there is
        nothing to connect to right now.
        {isOwner && (
          <span style={{ display: 'block', marginTop: 10, color: 'var(--faint)', fontSize: 'var(--fs-xs)' }}>
            Owner note: set <code style={{ color: 'var(--cyan-300)' }}>OURA_CLIENT_ID</code> and{' '}
            <code style={{ color: 'var(--cyan-300)' }}>OURA_CLIENT_SECRET</code> in the server secret
            (register an app at cloud.ouraring.com, redirect URI{' '}
            <code style={{ color: 'var(--cyan-300)' }}>/dashboard/oura/callback</code>) to turn on the
            connect flow.
          </span>
        )}
      </div>
    </Panel>
  )
}

function NotConnected() {
  return (
    <Panel>
      <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55, marginBottom: 16 }}>
        Connect your Oura account to pull your daily readiness, sleep, and HRV
        automatically. You will be sent to Oura to sign in and approve access,
        then brought right back here. Readiness drives the Home dashboard hero.
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button onClick={() => { globalThis.location.href = CONNECT_URL }}>
          Connect Oura Ring
        </Button>
      </div>
    </Panel>
  )
}

function Connected({ oura, lastSync, onReload }) {
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [okMsg, setOkMsg] = useState('')

  async function sync() {
    setErr(''); setOkMsg(''); setBusy('sync')
    try {
      const res = await apiPost('/api/dashboard/oura/sync', {})
      setOkMsg(res?.note === 'no_data'
        ? 'Connected, but Oura has no new readiness data in the last few days.'
        : 'Synced your latest Oura readiness.')
      onReload()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setErr('Your Oura connection needs to be re-established. Disconnect and connect again.')
        onReload()
      } else if (e instanceof ApiError) {
        setErr('Could not reach Oura just now. Please try again in a moment.')
      } else {
        setErr('Could not sync. Please try again.')
      }
    } finally {
      setBusy('')
    }
  }

  async function disconnect() {
    setErr(''); setOkMsg(''); setBusy('disconnect')
    try {
      await apiPost('/api/dashboard/oura/disconnect', {})
      onReload()
    } catch {
      setErr('Could not disconnect. Please try again.')
    } finally {
      setBusy('')
    }
  }

  return (
    <Panel>
      {oura ? (
        <OuraReading oura={oura} />
      ) : (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginBottom: 14 }}>
          Your ring is connected. No readings have synced yet. Click Sync now to
          pull your latest data from Oura.
        </div>
      )}

      {lastSync && (
        <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--faint)', marginBottom: 12 }}>
          Last synced: {fmtDate(lastSync) || lastSync}
        </div>
      )}

      {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>{err}</div>}
      {okMsg && <div style={{ color: 'var(--green-300)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>{okMsg}</div>}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
        <Button variant="ghost" size="sm" onClick={disconnect} disabled={Boolean(busy)}>
          {busy === 'disconnect' ? 'Disconnecting\u2026' : 'Disconnect'}
        </Button>
        <Button size="sm" onClick={sync} disabled={Boolean(busy)}>
          {busy === 'sync' ? 'Syncing\u2026' : 'Sync now'}
        </Button>
      </div>
    </Panel>
  )
}

function OuraSection({ data, reload }) {
  if (!data?.ouraConfigured) return <NotConfigured isOwner={Boolean(data?.isOwner)} />
  if (!data?.ouraConnected) return <NotConnected />
  return <Connected oura={data?.oura || null} lastSync={data?.ouraLastSync || ''} onReload={reload} />
}

export default function Settings() {
  const { data, loading, error, reload } = useApi('/api/dashboard/settings')
  const flash = useOuraFlash()

  return (
    <Screen loading={loading} error={error}>
      <FlashBanner flash={flash} />

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

      <SectionHead title="Oura Ring" />
      <OuraSection data={data} reload={reload} />
    </Screen>
  )
}
