import { useEffect, useState } from 'react'
import { SectionHead, fmtDate } from '../_shared.jsx'
import { apiFetch, apiPost } from '../../auth/api.js'
import { Panel, Button } from '../../design-system'
import { INPUT_STYLE_FLEX } from './inputStyles.js'

/* Desktop-only: bidirectional cloud sync. PAT from the hosted dashboard's
   API Keys tab; rows merge last-writer-wins, files newest-wins with conflict
   copies. Runs automatically every 15 min + on demand. */
export default function CloudSyncSection() {
  const [status, setStatus] = useState(null)
  const [pat, setPat] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)

  const load = () => apiFetch('/desktop/sync').then(setStatus).catch(() => setStatus(null))
  useEffect(() => { load() }, [])

  async function save() {
    setBusy('save'); setMsg(null)
    try {
      await apiPost('/desktop/sync/config', { url: url.trim(), pat: pat.trim(), auto: true })
      setPat(''); setUrl('')
      await load()
      setMsg({ tone: 'ok', text: 'Saved. Syncing…' })
      await runNow(true)
    } catch (e) {
      setMsg({ tone: 'err', text: e.message || 'Could not save.' })
    } finally {
      setBusy('')
    }
  }

  async function runNow(quiet) {
    setBusy('sync'); if (!quiet) setMsg(null)
    try {
      const res = await apiPost('/desktop/sync/run', {})
      if (res.status === 'ok') {
        setMsg({ tone: 'ok', text: `Synced — ${res.rows_pulled ?? 0} pulled, ${res.rows_pushed ?? 0} pushed, files ↓${res.files?.pull ?? 0} ↑${res.files?.push ?? 0}${res.files?.conflict ? ` (${res.files.conflict} conflict copies)` : ''}.` })
      } else {
        setMsg({ tone: 'err', text: res.error || 'Sync failed.' })
      }
      await load()
    } catch (e) {
      setMsg({ tone: 'err', text: e?.body?.detail || e.message || 'Sync failed.' })
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <SectionHead title="Cloud sync" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55, marginBottom: 14 }}>
          Keep this app and your cloud workspace in sync both ways — interviews you
          debrief here show up for Claude mobile, and cloud changes flow back. Create
          an API key on the hosted dashboard (API Keys tab) and paste it below.
          Syncs automatically every 15 minutes.
        </div>
        {status?.configured && (
          <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--faint)', marginBottom: 12 }}>
            Connected to {status.url}
            {status.last?.finished ? ` · last sync ${fmtDate(status.last.finished) || status.last.finished}` : ''}
            {status.last?.status === 'error' ? ' · last sync failed' : ''}
          </div>
        )}
        {msg && (
          <div style={{ color: msg.tone === 'ok' ? 'var(--green-300)' : 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>
            {msg.text}
          </div>
        )}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={status?.url || 'https://app.jobcontext.ai'}
            style={{ ...INPUT_STYLE_FLEX, minWidth: 200 }}
          />
          <input
            type="password"
            value={pat}
            onChange={(e) => setPat(e.target.value)}
            placeholder={status?.has_pat ? 'API key saved — paste to replace' : 'Cloud API key'}
            style={{ ...INPUT_STYLE_FLEX, minWidth: 200 }}
          />
          <Button size="sm" onClick={save} disabled={Boolean(busy) || (!pat.trim() && !status?.has_pat)}>
            {busy === 'save' ? 'Saving…' : 'Save & sync'}
          </Button>
          {status?.configured && (
            <Button variant="ghost" size="sm" onClick={() => runNow(false)} disabled={Boolean(busy)}>
              {busy === 'sync' ? 'Syncing…' : 'Sync now'}
            </Button>
          )}
        </div>
      </Panel>
    </>
  )
}
