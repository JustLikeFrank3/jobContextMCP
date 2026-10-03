import { useState } from 'react'
import { useApi, Screen, SectionHead, EmptyState, fmtDate } from './_shared.jsx'
import { apiFetch } from '../auth/api.js'
import { Panel, Button } from '../design-system'

/* API Keys — personal access tokens for MCP clients (iOS Shortcut, CLI, etc.).
   List + create + revoke via /api/dashboard/api-keys. The plaintext token is
   shown exactly once, right after creation.

   Scope: "full" reaches everything; "badge" reaches only /api/badge/* (the
   GitHub Universe badge — search, queue a resume/cover letter, poll it). The
   badge's filesystem mounts as a USB drive with the token in plain text, so
   that is the only kind of key that should ever go on it. */

const SCOPES = {
  full: { label: 'Full access', hint: 'Can do everything your account can, including every MCP tool. Use for clients you control: Claude, Cursor, the CLI.' },
  badge: { label: 'Badge only \u2014 conference badge', hint: 'Can search your pipeline, queue a resume or cover letter, and check on it \u2014 nothing else. Use for any device you wear or might lose.' },
}

function ScopePill({ scope }) {
  const badge = scope === 'badge'
  return (
    <span
      style={{
        display: 'inline-block', borderRadius: 999, padding: '2px 8px', marginLeft: 8,
        fontSize: 'var(--fs-2xs)', fontWeight: 'var(--fw-semibold)', letterSpacing: 0.3,
        textTransform: 'uppercase', verticalAlign: 'middle',
        color: badge ? 'var(--warn)' : 'var(--cyan-300)',
        background: badge
          ? 'color-mix(in srgb, var(--warn) 18%, transparent)'
          : 'var(--tint-primary)',
      }}
    >
      {badge ? 'Badge only' : 'Full access'}
    </span>
  )
}

export default function ApiKeys() {
  const { data, loading, error, reload } = useApi('/api/dashboard/api-keys')
  const keys = data?.keys || []

  const [label, setLabel] = useState('')
  const [scope, setScope] = useState('full')
  const [busy, setBusy] = useState(false)
  const [newToken, setNewToken] = useState(null)
  const [actionError, setActionError] = useState('')

  const generate = async () => {
    setBusy(true)
    setActionError('')
    setNewToken(null)
    try {
      const res = await apiFetch('/api/dashboard/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label.trim(), scope }),
      })
      setNewToken(res?.token || '')
      setLabel('')
      await reload()
    } catch {
      setActionError('Could not create the key. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (id) => {
    if (typeof window !== 'undefined' &&
      !window.confirm('Revoke this key? Any tool using it stops working immediately.')) return
    setActionError('')
    try {
      await apiFetch(`/api/dashboard/api-keys/${id}/revoke`, { method: 'POST' })
      await reload()
    } catch {
      setActionError('Could not revoke the key. Try again.')
    }
  }

  return (
    <Screen loading={loading} error={error}>
      <SectionHead title="Generate a key" />
      <Panel style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Label (e.g. iPhone Shortcut)"
            style={{
              flex: 1, minWidth: 220, background: 'var(--surface-sunken)',
              color: 'var(--text)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)', padding: '10px 12px', fontSize: 'var(--fs-sm)',
            }}
          />
          <select
            aria-label="Key scope"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            disabled={busy}
            style={{
              background: 'var(--surface-sunken)', color: 'var(--text)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
              padding: '10px 12px', fontSize: 'var(--fs-sm)',
            }}
          >
            {Object.entries(SCOPES).map(([value, s]) => (
              <option key={value} value={value}>{s.label}</option>
            ))}
          </select>
          <Button onClick={generate} disabled={busy}>{busy ? 'Generating\u2026' : 'Generate key'}</Button>
        </div>
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', marginTop: 8, lineHeight: 1.5 }}>
          {SCOPES[scope].hint}
        </div>
        {actionError && (
          <div style={{ color: 'var(--warn)', fontSize: 'var(--fs-sm)', marginTop: 10 }}>{actionError}</div>
        )}
        {newToken != null && (
          <div
            style={{
              marginTop: 12, padding: '12px 14px', borderRadius: 'var(--radius-md)',
              background: 'var(--tint-primary)', border: '1px solid var(--line-strong)',
            }}
          >
            <div style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-xs)', fontWeight: 'var(--fw-semibold)', marginBottom: 6 }}>
              Copy this now. It is shown only once.
            </div>
            <code
              style={{
                display: 'block', fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-sm)',
                color: 'var(--text-strong)', wordBreak: 'break-all',
              }}
            >
              {newToken}
            </code>
          </div>
        )}
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-xs)', marginTop: 10, lineHeight: 1.5 }}>
          Send it as a bearer token on every request:{' '}
          <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-soft)' }}>
            Authorization: Bearer jcmcp_&lt;key&gt;
          </code>
        </div>
      </Panel>

      <SectionHead title="Your keys" right={`${keys.length}`} />
      {keys.length === 0 ? (
        <EmptyState label="No keys yet." hint="Generate one above to connect an MCP client." />
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {keys.map((k) => (
            <Panel key={k.id} pad="12px 14px">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
                    {k.label || 'unlabeled'}
                    <ScopePill scope={k.scope} />
                  </div>
                  <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-xs)', marginTop: 3 }}>
                    {`Created ${fmtDate(k.created_at) || '\u2014'}`}
                    {k.last_used_at ? ` \u00b7 Last used ${fmtDate(k.last_used_at)}` : ' \u00b7 Never used'}
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => revoke(k.id)}>Revoke</Button>
              </div>
            </Panel>
          ))}
        </div>
      )}
    </Screen>
  )
}
