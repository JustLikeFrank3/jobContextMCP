import { useEffect, useState } from 'react'
import { SectionHead } from '../_shared.jsx'
import { apiFetch, apiPost } from '../../auth/api.js'
import { Panel, Button } from '../../design-system'
import { INPUT_STYLE } from './inputStyles.js'

/* Desktop-only: AI provider + BYOK key entry.

   GET  /desktop/ai-provider — active provider, per-provider readiness
   POST /desktop/ai-provider — save provider/key/model to the app-data config

   Keys are write-only: the UI never sees a stored key back, only has_key.
   On the hosted product the GET 404s and the section renders nothing. */
export default function AiProviderSection() {
  const [info, setInfo] = useState(null)      // GET payload; null = hidden/probing
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)        // { tone: 'ok'|'err', text }

  const load = () =>
    apiFetch('/desktop/ai-provider')
      .then((data) => {
        setInfo(data)
        setProvider((current) => current || data.provider)
      })
      .catch(() => setInfo(null)) // hosted mode — section hides

  useEffect(() => {
    load()
  }, [])

  if (!info) return null
  const spec = info.providers[provider] || {}
  const needsKey = provider !== 'ollama'

  async function save() {
    setMsg(null)
    setBusy(true)
    try {
      const res = await apiPost('/desktop/ai-provider', {
        provider,
        api_key: apiKey.trim(),
        model: model.trim(),
      })
      setApiKey('')
      setMsg(
        res.configured
          ? { tone: 'ok', text: `Saved — chat and generation now use ${res.provider} · ${res.model}.` }
          : { tone: 'err', text: 'Saved, but no key is stored for this provider yet.' },
      )
      load()
    } catch (e) {
      const detail = e?.body?.detail || 'Could not save. Check the key and try again.'
      setMsg({ tone: 'err', text: typeof detail === 'string' ? detail : 'Could not save.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <SectionHead title="AI provider" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', lineHeight: 1.55, marginBottom: 14 }}>
          Powers chat, resume generation, and assessments. Your key is stored
          only in this machine{'’'}s config file and is never sent anywhere except
          the provider you choose.
        </div>
        <div style={{ display: 'grid', gap: 10, maxWidth: 460 }}>
          <select
            value={provider}
            onChange={(e) => { setProvider(e.target.value); setModel(''); setMsg(null) }}
            style={INPUT_STYLE}
          >
            {Object.entries(info.providers).map(([id, p]) => (
              <option key={id} value={id}>
                {p.label}
                {id === 'ollama' ? (p.running ? ' — detected' : ' — not running') : p.has_key ? ' — key saved' : ''}
              </option>
            ))}
          </select>
          {needsKey && (
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={spec.has_key ? 'Key saved — paste a new one to replace it' : `Paste your ${spec.label || provider} API key`}
              autoComplete="off"
              style={INPUT_STYLE}
            />
          )}
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder={`Model (default: ${spec.model || ''})`}
            style={INPUT_STYLE}
          />
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
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
          <Button size="sm" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </Panel>
    </>
  )
}
