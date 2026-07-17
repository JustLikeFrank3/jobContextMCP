import { useState, useEffect, useCallback } from 'react'
import { Panel, Button } from '../design-system'
import { apiFetch, apiPost } from '../auth/api.js'
import { Screen, StatGrid, Stat, EmptyState, EYEBROW } from './_shared.jsx'
import { actionError } from './pipeline/shared.jsx'
import JobCard from './pipeline/JobCard.jsx'
import AddJobModal from './pipeline/AddJobModal.jsx'
import EditResumeModal from './pipeline/EditResumeModal.jsx'
import EditCoverLetterModal from './pipeline/EditCoverLetterModal.jsx'
import TemplateModal from './pipeline/TemplateModal.jsx'

/* Pipeline — the share-sheet intake queue: assess, generate, decide, apply.
   Data: GET /dashboard/pipeline/data (_pipeline_payload).

   Restores the interactive card actions from the legacy /dashboard/pipeline
   page: run/re-run assessment, generate resume, generate cover letter
   (HTML + LaTeX for owner), queue apply, mark applied, unqueue, remove —
   plus a search filter and the Add Job intake modal. The AI editor flows now
   live here too, in React: Edit Resume, Edit Cover Letter (draft → review →
   accept/discard), and the visual Template chooser with a live preview.
   The card and modals live in ./pipeline/. */

function personaOption(o) {
  if (typeof o === 'string') return { value: o, label: o }
  return { value: o.id || o.name || '', label: o.label || o.name || o.id || '' }
}

export default function Pipeline() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const [busy, setBusy] = useState(null)
  const [filter, setFilter] = useState('')
  const [persona, setPersona] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [editor, setEditor] = useState(null) // { type: 'edit-resume'|'edit-cl'|'templates', job }

  const load = useCallback(async ({ silent } = {}) => {
    if (!silent) setState((s) => ({ ...s, loading: !s.data, error: null }))
    try {
      const data = await apiFetch('/dashboard/pipeline/data')
      setState({ data, loading: false, error: null })
    } catch (error) {
      setState((s) => ({ ...s, loading: false, error }))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const data = state.data
  const jobs = data?.jobs || []
  const personaOptions = (data?.persona_options || []).map(personaOption)
  const activePersona = persona || data?.default_persona || 'default'

  async function onAction(job, type) {
    try {
      if (type === 'eval') {
        setBusy(`Running assessment for ${job.company}…`)
        await apiPost('/dashboard/pipeline/evaluate', { job_id: job.id })
      } else if (type === 'resume') {
        setBusy(`Generating resume for ${job.company}…`)
        const res = await apiPost('/dashboard/pipeline/generate-resume', { job_id: job.id, persona: activePersona })
        if (!res?.ok) window.alert(`Resume generation did not produce files.\n\n${String(res?.content || res?.notes || '').slice(0, 500)}`)
      } else if (type === 'cl-latex' || type === 'cl-html') {
        const pipeline = type === 'cl-latex' ? 'latex' : 'html'
        setBusy(`Generating cover letter (${pipeline.toUpperCase()}) for ${job.company}…`)
        const res = await apiPost('/dashboard/pipeline/generate-cover-letter', { job_id: job.id, export_pipeline: pipeline, persona: activePersona })
        if (!res?.ok) window.alert(`Cover letter generation did not produce files (likely an API rate limit or provider error).\n\n${String(res?.content || res?.notes || '').slice(0, 500)}`)
      } else if (type === 'apply') {
        setBusy(`Queueing application for ${job.company}…`)
        await apiPost('/dashboard/pipeline/queue-apply', { job_id: job.id })
      } else if (type === 'applied') {
        const note = window.prompt('Optional application note:', 'Applied manually from dashboard.')
        if (note === null) return
        setBusy(`Marking ${job.company} applied…`)
        await apiPost('/dashboard/pipeline/mark-applied', { job_id: job.id, notes: note })
      } else if (type === 'unqueue') {
        setBusy(`Resetting ${job.company} to pending…`)
        await apiPost('/dashboard/pipeline/unqueue', { job_id: job.id })
      } else if (type === 'remove') {
        if (!window.confirm(`Remove ${job.company} — ${job.role} from the pipeline? This deletes the entry.`)) return
        setBusy(`Removing ${job.company}…`)
        await apiPost('/dashboard/pipeline/remove', { job_id: job.id })
      }
      await load({ silent: true })
    } catch (e) {
      window.alert(actionError(e))
    } finally {
      setBusy(null)
    }
  }

  const q = filter.trim().toLowerCase()
  const shown = q
    ? jobs.filter((j) => [j.company, j.role, j.status, j.source, j.decision_notes].join(' ').toLowerCase().includes(q))
    : jobs

  const countBy = (s) => jobs.filter((j) => j.status === s).length

  const fieldStyle = {
    flex: 1, minWidth: 220, maxWidth: 420, boxSizing: 'border-box',
    background: 'var(--surface-sunken)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', padding: '9px 11px',
    color: 'var(--text)', fontSize: 'var(--fs-sm)',
  }

  return (
    <Screen loading={state.loading} error={state.error} empty={false}>
      <StatGrid>
        <Stat label="Queue total" value={data?.total ?? 0} tone="accent" />
        <Stat label="Pending" value={countBy('pending')} tone="warn" />
        <Stat label="Evaluated" value={countBy('evaluated')} />
        <Stat label="Added" value={countBy('added')} tone="green" />
        <Stat label="Applied" value={countBy('applied')} tone="green" />
      </StatGrid>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={'Filter company / role / status…'}
          style={fieldStyle}
        />
        {personaOptions.length > 0 && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            <span style={{ ...EYEBROW }}>Persona</span>
            <select
              value={activePersona}
              onChange={(e) => setPersona(e.target.value)}
              style={{ ...fieldStyle, flex: '0 0 auto', minWidth: 150 }}
            >
              {personaOptions.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
        )}
        <Button size="sm" onClick={() => setAddOpen(true)}>{'＋'} Add Job</Button>
      </div>

      {busy && (
        <Panel pad="11px 14px" style={{ marginBottom: 14, borderColor: 'color-mix(in srgb, var(--cyan-500) 45%, var(--border))' }}>
          <div style={{ color: 'var(--cyan-200)', fontSize: 'var(--fs-sm)', marginBottom: 8 }}>{busy}</div>
          <div style={{ height: 4, borderRadius: 'var(--radius-pill)', background: 'var(--ink-600)', overflow: 'hidden' }}>
            <div style={{ width: '40%', height: '100%', background: 'var(--cyan-400)', borderRadius: 'var(--radius-pill)', animation: 'jcpulse 1.1s ease-in-out infinite' }} />
          </div>
        </Panel>
      )}
      <style>{'@keyframes jcpulse{0%{margin-left:-40%}100%{margin-left:100%}}'}</style>

      {shown.length === 0 ? (
        <EmptyState
          label={jobs.length === 0 ? 'No jobs in the queue.' : 'No jobs match your filter.'}
          hint={jobs.length === 0 ? 'Use Add Job, or share a posting from your phone.' : undefined}
        />
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {shown.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              busy={!!busy}
              isOwner={!!data?.is_owner}
              onAction={onAction}
              onOpenEditor={(j, type) => setEditor({ type, job: j })}
            />
          ))}
        </div>
      )}

      {addOpen && (
        <AddJobModal
          onClose={() => setAddOpen(false)}
          onSubmit={async (payload) => {
            await apiPost('/jobs/evaluate', { ...payload, source: 'dashboard_manual' })
            await load({ silent: true })
          }}
        />
      )}

      {editor?.type === 'edit-resume' && (
        <EditResumeModal
          job={editor.job}
          resumeOptions={data?.optimized_resume_options}
          onClose={() => setEditor(null)}
          onDone={() => { setEditor(null); load({ silent: true }) }}
        />
      )}
      {editor?.type === 'edit-cl' && (
        <EditCoverLetterModal
          job={editor.job}
          coverLetterOptions={data?.cover_letter_options}
          isOwner={!!data?.is_owner}
          onClose={() => setEditor(null)}
          onDone={() => { setEditor(null); load({ silent: true }) }}
        />
      )}
      {editor?.type === 'templates' && (
        <TemplateModal
          job={editor.job}
          resumeTemplates={data?.resume_templates}
          clTemplates={data?.cl_templates}
          styles={data?.template_styles}
          onClose={() => setEditor(null)}
          onSaved={() => load({ silent: true })}
        />
      )}
    </Screen>
  )
}
