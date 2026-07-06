import { useEffect, useState } from 'react'
import { useApi, Screen, SectionHead, Badge, fmtDate } from './_shared.jsx'
import { apiFetch, apiPost, ApiError } from '../auth/api.js'
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

/* Desktop-only: one-click MCP client connect.

   GET  /desktop/mcp-clients  — which clients are installed / already wired
   POST /desktop/mcp-connect  — write the jobcontext entry into that client

   These routes exist only when the backend runs as the desktop app
   (DEPLOY_MODE=desktop); on the hosted product the GET 404s and the whole
   section renders nothing. */
function useMcpClients() {
  const [state, setState] = useState({ clients: null, loading: true })
  useEffect(() => {
    let cancelled = false
    apiFetch('/desktop/mcp-clients')
      .then((data) => {
        if (!cancelled) setState({ clients: data?.clients || [], loading: false })
      })
      .catch(() => {
        if (!cancelled) setState({ clients: null, loading: false }) // not desktop mode
      })
    return () => {
      cancelled = true
    }
  }, [])
  const reload = () =>
    apiFetch('/desktop/mcp-clients')
      .then((data) => setState({ clients: data?.clients || [], loading: false }))
      .catch(() => setState({ clients: null, loading: false }))
  return { ...state, reload }
}

function McpClientRow({ client, onConnect, busy }) {
  const status = client.connected ? 'connected' : client.installed ? 'detected' : 'not detected'
  const tone = client.connected ? 'green' : client.installed ? 'muted' : 'muted'
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
          {client.label}
        </div>
        <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-2xs)', marginTop: 3 }}>
          {client.config_path}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        <Badge tone={tone}>{status}</Badge>
        <Button
          size="sm"
          variant={client.connected ? 'ghost' : undefined}
          onClick={() => onConnect(client.id)}
          disabled={Boolean(busy)}
        >
          {busy === client.id ? 'Connecting…' : client.connected ? 'Reconnect' : 'Connect'}
        </Button>
      </div>
    </div>
  )
}

function McpClientsSection() {
  const { clients, loading, reload } = useMcpClients()
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null) // { tone: 'ok'|'err', text }

  if (loading || clients === null) return null // hosted mode or still probing

  async function connect(id) {
    setMsg(null)
    setBusy(id)
    try {
      const res = await apiPost('/desktop/mcp-connect', { client: id })
      setMsg({ tone: 'ok', text: `Done — restart the app to pick up jobContext. Config written to ${res.config_path}.` })
      reload()
    } catch {
      setMsg({ tone: 'err', text: 'Could not write that client’s config. Is the app installed?' })
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <SectionHead title="AI clients (MCP)" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55, marginBottom: 14 }}>
          Give Claude Desktop, VS Code, or Cursor direct access to your job
          search tools. One click writes the MCP configuration; jobContext runs
          locally, so your data never leaves this machine.
        </div>
        <div style={{ display: 'grid', gap: 10 }}>
          {clients.map((c) => (
            <McpClientRow key={c.id} client={c} onConnect={connect} busy={busy} />
          ))}
        </div>
        {msg && (
          <div
            style={{
              marginTop: 12,
              color: msg.tone === 'ok' ? 'var(--green-300)' : 'var(--danger-soft)',
              fontSize: 'var(--fs-sm)',
            }}
          >
            {msg.text}
          </div>
        )}
      </Panel>
    </>
  )
}

/* Factual "works with" chip — the Oura name used descriptively, no Oura logo,
   never folded into the jobContext mark. Generic ring glyph in the brand cyan. */
function OuraCompatChip() {
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
        Oura and Oura Ring are trademarks of {'\u014C'}ura Health Oy. jobContext is not
        affiliated with, endorsed by, or sponsored by {'\u014C'}ura; the name is used
        solely to describe interoperability through the Oura API.
      </p>
    </div>
  )
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

      <McpClientsSection />

      <SectionHead title="Oura Ring" />
      <OuraCompatChip />
      <OuraSection data={data} reload={reload} />
    </Screen>
  )
}
