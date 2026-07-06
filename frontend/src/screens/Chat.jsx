import { useEffect, useRef, useState } from 'react'
import { apiFetch, apiPost } from '../auth/api.js'
import { Panel, Button } from '../design-system'
import { EmptyState } from './_shared.jsx'
import useDesktopMode from '../shell/useDesktopMode.js'

/* Chat: embedded assistant over the MCP tool registry (desktop only).

   Streams one turn at a time from POST /api/chat/sessions/{id}/stream —
   SSE over a fetch body (EventSource can't POST). Event types map 1:1 to
   thread items: tool_call/tool_result become activity chips, message is
   the assistant reply, error renders inline. Stop aborts the fetch, which
   cancels the server-side generator on disconnect.

   Data:    GET  /api/chat/sessions, GET /api/chat/sessions/{id}/messages
   Actions: POST /api/chat/sessions, POST /api/chat/sessions/{id}/stream */

/* Parse SSE frames out of a streamed body, invoking onEvent(type, data). */
async function readSseStream(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      let type = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) type = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) onEvent(type, JSON.parse(data))
    }
  }
}

/* Stored rows → thread items. Assistant rows that only carry tool_calls are
   skipped; their tool-result rows render as chips instead. */
function rowsToThread(rows) {
  const items = []
  for (const row of rows) {
    if (row.role === 'user') {
      items.push({ kind: 'user', content: row.content, id: `r${row.id}` })
    } else if (row.role === 'tool') {
      items.push({
        kind: 'tool', name: row.tool_name, content: row.content,
        running: false, id: `r${row.id}`,
      })
    } else if (row.role === 'assistant' && row.content) {
      items.push({ kind: 'assistant', content: row.content, id: `r${row.id}` })
    }
  }
  return items
}

function useChatStream() {
  const [items, setItems] = useState([])
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef(null)
  const nextId = useRef(0)

  const push = (item) => {
    nextId.current += 1
    const id = `l${nextId.current}`
    setItems((prev) => [...prev, { ...item, id }])
    return id
  }

  async function send(sessionId, text) {
    push({ kind: 'user', content: text })
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const response = await fetch(`/api/chat/sessions/${sessionId}/stream`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
      })
      if (!response.ok) {
        push({ kind: 'error', content: `Request failed (${response.status}).` })
        return
      }
      await readSseStream(response, (type, data) => {
        if (type === 'tool_call') {
          push({ kind: 'tool', name: data.name, content: '', running: true, callId: data.id })
        } else if (type === 'tool_result') {
          setItems((prev) =>
            prev.map((item) =>
              item.kind === 'tool' && item.callId === data.id
                ? { ...item, running: false, content: data.content }
                : item,
            ),
          )
        } else if (type === 'message') {
          push({ kind: 'assistant', content: data.content })
        } else if (type === 'error') {
          push({ kind: 'error', content: data.message })
        }
      })
    } catch (err) {
      if (err?.name !== 'AbortError') {
        push({ kind: 'error', content: 'Connection lost mid-reply. Try again.' })
      } else {
        push({ kind: 'error', content: 'Stopped.' })
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  const stop = () => abortRef.current?.abort()
  const reset = (thread) => setItems(thread)

  return { items, streaming, send, stop, reset }
}

const CHIP_STYLE = {
  display: 'inline-flex', alignItems: 'center', gap: 8, maxWidth: '100%',
  background: 'var(--surface-raised)', border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-md)', padding: '5px 10px',
  fontSize: 'var(--fs-xs)', color: 'var(--muted)', cursor: 'pointer',
}

function ToolChip({ item }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ alignSelf: 'flex-start', maxWidth: '85%' }}>
      <div style={CHIP_STYLE} onClick={() => setOpen((v) => !v)} role="button" tabIndex={0}>
        <span aria-hidden="true" style={{ color: 'var(--cyan-400)' }}>{'⚙'}</span>
        <code style={{ fontSize: 'var(--fs-2xs)' }}>{item.name}</code>
        {item.running
          ? <span style={{ color: 'var(--cyan-300)' }}>running{'…'}</span>
          : <span style={{ color: 'var(--green-300)' }}>{'✓'}</span>}
        {!item.running && <span style={{ color: 'var(--faint)' }}>{open ? '▴' : '▾'}</span>}
      </div>
      {open && !item.running && (
        <pre
          style={{
            margin: '6px 0 0', padding: '8px 10px', maxHeight: 180, overflow: 'auto',
            background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)', fontSize: 'var(--fs-2xs)',
            color: 'var(--muted)', whiteSpace: 'pre-wrap',
          }}
        >
          {item.content}
        </pre>
      )}
    </div>
  )
}

function ThreadItem({ item }) {
  if (item.kind === 'user') {
    return (
      <div
        style={{
          alignSelf: 'flex-end', maxWidth: '78%',
          background: 'var(--tint-primary)', border: '1px solid var(--line-strong)',
          borderRadius: '12px 12px 3px 12px', padding: '9px 13px',
          fontSize: 'var(--fs-sm)', color: 'var(--text-strong)', whiteSpace: 'pre-wrap',
        }}
      >
        {item.content}
      </div>
    )
  }
  if (item.kind === 'tool') return <ToolChip item={item} />
  if (item.kind === 'error') {
    return (
      <div style={{ alignSelf: 'flex-start', color: 'var(--danger-soft)', fontSize: 'var(--fs-sm)' }}>
        {item.content}
      </div>
    )
  }
  return (
    <div
      style={{
        alignSelf: 'flex-start', maxWidth: '85%', fontSize: 'var(--fs-sm)',
        color: 'var(--text-soft)', lineHeight: 1.6, whiteSpace: 'pre-wrap',
      }}
    >
      {item.content}
    </div>
  )
}

function SessionRail({ sessions, activeId, onSelect, onNew }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
      <Button size="sm" variant="ghost" onClick={onNew}>+ New chat</Button>
      {sessions.map((session) => (
        <div
          key={session.id}
          onClick={() => onSelect(session.id)}
          role="button"
          tabIndex={0}
          style={{
            padding: '7px 10px', borderRadius: 'var(--radius-md)', cursor: 'pointer',
            border: `1px solid ${session.id === activeId ? 'var(--cyan-400)' : 'var(--border-soft)'}`,
            background: session.id === activeId ? 'var(--surface-sunken)' : 'transparent',
          }}
        >
          <div
            style={{
              fontSize: 'var(--fs-xs)', whiteSpace: 'nowrap', overflow: 'hidden',
              textOverflow: 'ellipsis',
              color: session.id === activeId ? 'var(--text-strong)' : 'var(--muted)',
            }}
          >
            {session.title || 'Untitled'}
          </div>
        </div>
      ))}
    </div>
  )
}

function Composer({ streaming, onSend, onStop }) {
  const [text, setText] = useState('')
  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || streaming) return
    setText('')
    onSend(trimmed)
  }
  return (
    <div style={{ display: 'flex', gap: 9, alignItems: 'flex-end', marginTop: 12 }}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        rows={1}
        placeholder="Ask about your pipeline, queue a job, prep an interview…"
        style={{
          flex: 1, resize: 'none', minHeight: 40, maxHeight: 140, padding: '9px 13px',
          background: 'var(--surface)', border: '1px solid var(--surface-chip)',
          borderRadius: 'var(--radius-md)', color: 'var(--text-strong)',
          fontSize: 'var(--fs-sm)', fontFamily: 'inherit', outline: 'none',
        }}
      />
      {streaming ? (
        <Button size="sm" variant="ghost" onClick={onStop}>Stop</Button>
      ) : (
        <Button size="sm" onClick={submit}>Send</Button>
      )}
    </div>
  )
}

export default function Chat() {
  const isDesktop = useDesktopMode()
  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(null)
  const { items, streaming, send, stop, reset } = useChatStream()
  const scrollRef = useRef(null)

  const loadSessions = () =>
    apiFetch('/api/chat/sessions')
      .then((data) => setSessions(data?.sessions || []))
      .catch(() => setSessions([]))

  useEffect(() => {
    if (isDesktop) loadSessions()
  }, [isDesktop])

  useEffect(() => {
    if (activeId == null) {
      reset([])
      return
    }
    apiFetch(`/api/chat/sessions/${activeId}/messages`)
      .then((data) => reset(rowsToThread(data?.messages || [])))
      .catch(() => reset([]))
  }, [activeId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [items])

  async function handleSend(text) {
    let sessionId = activeId
    if (sessionId == null) {
      const created = await apiPost('/api/chat/sessions', {})
      sessionId = created.id
      setActiveId(sessionId)
    }
    await send(sessionId, text)
    loadSessions() // pick up auto-title / ordering
  }

  if (!isDesktop) {
    return (
      <EmptyState
        label="Chat is part of the desktop app."
        hint="Download jobContext Desktop to chat with your job search data locally — or connect Claude Desktop to the hosted MCP server."
      />
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '190px minmax(0, 1fr)', gap: 16 }}>
      <SessionRail
        sessions={sessions}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={() => setActiveId(null)}
      />
      <Panel>
        <div
          ref={scrollRef}
          style={{
            display: 'flex', flexDirection: 'column', gap: 12,
            minHeight: 380, maxHeight: '62vh', overflowY: 'auto', paddingRight: 4,
          }}
        >
          {items.length === 0 && (
            <div style={{ color: 'var(--faint)', fontSize: 'var(--fs-sm)', margin: 'auto', textAlign: 'center' }}>
              Ask anything about your job search.
              <br />
              Answers come from your local data via the same tools Claude uses.
            </div>
          )}
          {items.map((item) => <ThreadItem key={item.id} item={item} />)}
          {streaming && (
            <div style={{ alignSelf: 'flex-start', color: 'var(--faint)', fontSize: 'var(--fs-sm)' }}>
              thinking{'…'}
            </div>
          )}
        </div>
        <Composer streaming={streaming} onSend={handleSend} onStop={stop} />
      </Panel>
    </div>
  )
}
