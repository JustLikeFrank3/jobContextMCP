import { useEffect, useState } from 'react'
import { fmtDate } from '../_shared.jsx'
import { apiPost, ApiError } from '../../auth/api.js'
import { Panel, Button } from '../../design-system'
import { INPUT_STYLE_FLEX } from './inputStyles.js'

/* The Oura Ring connection, in all its states.

   Oura is a real OAuth integration. The user connects their actual Oura
   account (browser handshake in routes/dashboard/oura.py) and the server pulls
   readiness / sleep / HRV from the Oura Cloud API. There is no manual data
   entry here. Connect starts the login flow, Sync now pulls fresh data,
   Disconnect drops the stored tokens.

   Actions: GET  /dashboard/oura/connect       (full-page nav)
            POST /api/dashboard/oura/sync
            POST /api/dashboard/oura/disconnect */

const CONNECT_URL = '/dashboard/oura/connect'

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
        Last reading: {fmtDate(oura.date) || oura.date || '—'}
      </div>
    </div>
  )
}

/* Reads the ?oura= outcome the OAuth callback redirects back with, then strips
   it from the URL so a refresh does not re-show the banner. */
export function useOuraFlash() {
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

export function FlashBanner({ flash }) {
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
          {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}
        </Button>
        <Button size="sm" onClick={sync} disabled={Boolean(busy)}>
          {busy === 'sync' ? 'Syncing…' : 'Sync now'}
        </Button>
      </div>
    </Panel>
  )
}

/* Desktop connect path: paste an Oura Personal Access Token. The OAuth flow
   needs server client credentials + a public HTTPS redirect URI registered
   with Oura — a local loopback app has neither. */
function PatConnect({ onReload }) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function connect() {
    const trimmed = token.trim()
    if (!trimmed || busy) return
    setErr(''); setBusy(true)
    try {
      await apiPost('/api/dashboard/oura/pat', { token: trimmed })
      setToken('')
      onReload()
    } catch (e) {
      setErr(e instanceof ApiError && e.body?.detail
        ? e.body.detail
        : 'Could not connect. Check the token and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel>
      <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55, marginBottom: 14 }}>
        <strong>Easiest path:</strong> connect your ring on the hosted dashboard
        (Settings {'→'} Oura {'→'} Connect) and enable Cloud sync above — readiness
        flows here automatically. Alternatively, if you have a legacy Oura{' '}
        <strong>Personal Access Token</strong> (Oura has deprecated creating new
        ones), paste it below — it stays on this machine.
      </div>
      {err && <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>{err}</div>}
      <div style={{ display: 'flex', gap: 10 }}>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') connect() }}
          placeholder="Personal access token"
          style={INPUT_STYLE_FLEX}
        />
        <Button size="sm" onClick={connect} disabled={busy || !token.trim()}>
          {busy ? 'Connecting…' : 'Connect'}
        </Button>
      </div>
    </Panel>
  )
}

/* Factual "works with" chip — the Oura name used descriptively, no Oura logo,
   never folded into the jobContext mark. Generic ring glyph in the brand cyan. */
export function OuraCompatChip() {
  return (
    <div style={{ marginBottom: 14 }}>
      <span
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '6px 12px', borderRadius: 999, whiteSpace: 'nowrap',
          border: '1px solid color-mix(in srgb, var(--cyan-500) 50%, transparent)',
          background: 'color-mix(in srgb, var(--cyan-500) 12%, transparent)',
          color: 'var(--text-soft)', fontSize: 'var(--fs-xs)', fontWeight: 600, lineHeight: 1,
        }}
      >
        <span
          aria-hidden="true"
          style={{ width: 12, height: 12, borderRadius: '50%', border: '2px solid var(--cyan-400)', boxSizing: 'border-box', flexShrink: 0 }}
        />{' '}
        Works with{' '}
        <strong style={{ color: 'var(--cyan-400)', fontWeight: 700 }}>Oura Ring</strong>
      </span>
      <p style={{ margin: '10px 0 0', color: 'var(--faint)', fontSize: 'var(--fs-2xs)', lineHeight: 1.5 }}>
        Oura and Oura Ring are trademarks of {'Ō'}ura Health Oy. jobContext is not
        affiliated with, endorsed by, or sponsored by {'Ō'}ura; the name is used
        solely to describe interoperability through the Oura API.
      </p>
    </div>
  )
}

export default function OuraSection({ data, reload, isDesktop }) {
  if (data?.ouraViaSync) {
    // Readiness arrives through cloud workspace sync (the ring is OAuth-
    // connected on the hosted product) — nothing to manage locally.
    return (
      <Panel>
        {data?.oura ? <OuraReading oura={data.oura} /> : null}
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55 }}>
          Synced from your cloud connection — your ring is connected on the hosted
          dashboard and readiness flows here automatically with Cloud sync. Nothing
          to configure on this machine.
        </div>
      </Panel>
    )
  }
  if (data?.ouraConnected) {
    return <Connected oura={data?.oura || null} lastSync={data?.ouraLastSync || ''} onReload={reload} />
  }
  if (isDesktop) return <PatConnect onReload={reload} />
  if (!data?.ouraConfigured) return <NotConfigured isOwner={Boolean(data?.isOwner)} />
  return <NotConnected />
}
