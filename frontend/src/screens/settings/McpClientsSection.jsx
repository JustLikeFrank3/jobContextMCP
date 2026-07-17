import { useEffect, useState } from 'react'
import { SectionHead, Badge } from '../_shared.jsx'
import { apiFetch, apiPost } from '../../auth/api.js'
import { Panel, Button } from '../../design-system'

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

export default function McpClientsSection() {
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
