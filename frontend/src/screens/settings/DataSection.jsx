import { useRef, useState } from 'react'
import { SectionHead } from '../_shared.jsx'
import { apiPost } from '../../auth/api.js'
import { Panel, Button } from '../../design-system'

/* Your data: export a zip of the whole workspace anywhere; import one on
   desktop (the "move my cloud workspace into the desktop app" path). Import
   swaps the local data dir (old one is kept as a timestamped backup) and
   requires an app restart. */
export default function DataSection({ isDesktop }) {
  const [state, setState] = useState({ phase: 'idle', detail: '' })
  const fileRef = useRef(null)

  async function importZip(file) {
    if (!file) return
    setState({ phase: 'busy', detail: '' })
    try {
      const res = await fetch('/desktop/import-workspace', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/zip' },
        body: file,
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body?.detail || `Import failed (${res.status})`)
      setState({ phase: 'done', detail: body?.backup || '' })
    } catch (e) {
      setState({ phase: 'error', detail: e.message })
    }
  }

  function quit() {
    apiPost('/desktop/shutdown', {}).catch(() => {})
  }

  return (
    <>
      <SectionHead title="Your data" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55, marginBottom: 14 }}>
          Everything lives in one folder: settings, the SQLite database, and your
          resume/materials files. <strong>Export</strong> downloads it all as a zip
          {isDesktop
            ? ' — and Import replaces this app’s data with a zip exported elsewhere (e.g. your cloud workspace). The current data is kept as a backup.'
            : ' you can import into the jobContext desktop app.'}
        </div>
        {state.phase === 'done' ? (
          <div>
            <div style={{ color: 'var(--green-300)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>
              Import complete{state.detail ? ` — previous data saved to ${state.detail}` : ''}. Quit and
              reopen jobContext to load the imported workspace.
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button size="sm" onClick={quit}>Quit jobContext</Button>
            </div>
          </div>
        ) : (
          <>
            {state.phase === 'error' && (
              <div style={{ color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>{state.detail}</div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, alignItems: 'center' }}>
              {isDesktop && (
                <>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".zip,application/zip"
                    style={{ display: 'none' }}
                    onChange={(e) => { importZip(e.target.files?.[0]); e.target.value = '' }}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={state.phase === 'busy'}
                    onClick={() => fileRef.current?.click()}
                  >
                    {state.phase === 'busy' ? 'Importing…' : 'Import from zip…'}
                  </Button>
                </>
              )}
              <Button
                size="sm"
                onClick={() => { globalThis.location.href = '/api/dashboard/export' }}
              >
                Export workspace (.zip)
              </Button>
            </div>
          </>
        )}
      </Panel>
    </>
  )
}
