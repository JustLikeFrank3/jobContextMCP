import { useState, useEffect, useCallback } from 'react'
import { Panel, Button } from '../design-system'
import { apiFetch, apiPost } from '../auth/api.js'
import { Screen, EmptyState, EYEBROW, Badge } from './_shared.jsx'
import { parseProvenance, PROVENANCE_TONE, PROVENANCE_BADGE_LABEL } from './pipeline/provenance.js'
import { useToolbarSlot } from '../shell/toolbarSlot.jsx'
import { actionError } from './pipeline/shared.jsx'
import JobCard, { ROW_GRID } from './pipeline/JobCard.jsx'
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
   The card and modals live in ./pipeline/.

   Skin follows the desktop design handoff's PIPELINE page: "N active ·
   M applied" count line, segmented All/Active/Applied chips, and a
   5-column table (COMPANY / ROLE / STAGE / FIT / NEXT STEP) with mono
   headers — each row expands below its table line into the full detail +
   action area, so no functionality from the card era is lost. */

function personaOption(o) {
  if (typeof o === 'string') return { value: o, label: o }
  return { value: o.id || o.name || '', label: o.label || o.name || o.id || '' }
}

/* Statuses still moving through the funnel (design chips: All / Active / Applied). */
const ACTIVE_STATUSES = new Set(['pending', 'evaluated', 'added'])

/* Segmented chip per the handoff: cyan fill + deep-cyan ink when active. */
function Chip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        appearance: 'none', cursor: 'pointer', border: 'none',
        fontSize: 12.5, fontWeight: 'var(--fw-semibold)', fontFamily: 'var(--font-sans)',
        color: active ? '#04222A' : 'var(--muted)',
        background: active ? 'var(--cyan-500)' : 'rgba(255,255,255,.05)',
        padding: '7px 15px', borderRadius: 'var(--radius-pill)', whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  )
}

export default function Pipeline() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const [busy, setBusy] = useState(null)
  const [filter, setFilter] = useState('')
  const [stageFilter, setStageFilter] = useState('all')
  const [persona, setPersona] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [genResult, setGenResult] = useState(null) // { title, ok, provenance: parseProvenance() | null }
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

  // "+ Add Job" is the page's primary action — projected into the shell's
  // sticky toolbar per the desktop design's content-toolbar spec.
  useToolbarSlot(
    <Button size="sm" onClick={() => setAddOpen(true)}>{'＋'} Add Job</Button>,
    [],
  )

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
        setGenResult(null)
        const res = await apiPost('/dashboard/pipeline/generate-resume', { job_id: job.id, persona: activePersona })
        setGenResult({
          title: `Resume — ${job.company}`,
          ok: !!res?.ok,
          provenance: parseProvenance(res?.provenance),
        })
        if (!res?.ok) window.alert(`Resume generation did not produce files.\n\n${String(res?.content || res?.notes || '').slice(0, 500)}`)
      } else if (type === 'cl-latex' || type === 'cl-html') {
        const pipeline = type === 'cl-latex' ? 'latex' : 'html'
        setBusy(`Generating cover letter (${pipeline.toUpperCase()}) for ${job.company}…`)
        setGenResult(null)
        const res = await apiPost('/dashboard/pipeline/generate-cover-letter', { job_id: job.id, export_pipeline: pipeline, persona: activePersona })
        setGenResult({
          title: `Cover letter — ${job.company}`,
          ok: !!res?.ok,
          provenance: parseProvenance(res?.provenance),
        })
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
  const stageMatch = (j) =>
    stageFilter === 'all' ||
    (stageFilter === 'active' ? ACTIVE_STATUSES.has(j.status) : j.status === 'applied')
  const shown = jobs.filter((j) =>
    stageMatch(j) &&
    (!q || [j.company, j.role, j.status, j.source, j.decision_notes].join(' ').toLowerCase().includes(q)))

  const countBy = (s) => jobs.filter((j) => j.status === s).length
  const activeCount = jobs.filter((j) => ACTIVE_STATUSES.has(j.status)).length

  const fieldStyle = {
    flex: 1, minWidth: 220, maxWidth: 420, boxSizing: 'border-box',
    background: 'var(--surface-sunken)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', padding: '9px 11px',
    color: 'var(--text)', fontSize: 'var(--fs-sm)',
  }

  return (
    <Screen loading={state.loading} error={state.error} empty={false}>
      <div style={{ fontSize: 13.5, color: 'var(--muted)', marginBottom: 14 }}>
        {activeCount} active {'·'} {countBy('applied')} applied
      </div>

      {genResult && (
        <Panel pad="10px 14px" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 'var(--fw-semibold)', color: 'var(--text)' }}>
              {genResult.title}
            </span>
            {genResult.provenance ? (
              <>
                <Badge tone={PROVENANCE_TONE[genResult.provenance.status]}>
                  {PROVENANCE_BADGE_LABEL[genResult.provenance.status]}
                </Badge>
                <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--muted)' }}>
                  {genResult.provenance.text}
                </span>
              </>
            ) : (
              <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--faint)' }}>
                No provenance verdict returned (context-package generation).
              </span>
            )}
            <button
              onClick={() => setGenResult(null)}
              aria-label="Dismiss generation result"
              style={{
                marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--faint)', fontSize: 'var(--fs-sm)', lineHeight: 1, padding: 4,
              }}
            >
              {'✕'}
            </button>
          </div>
        </Panel>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <Chip active={stageFilter === 'all'} onClick={() => setStageFilter('all')}>All</Chip>
        <Chip active={stageFilter === 'active'} onClick={() => setStageFilter('active')}>Active</Chip>
        <Chip active={stageFilter === 'applied'} onClick={() => setStageFilter('applied')}>Applied</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 10.5, fontFamily: 'var(--font-mono)', fontWeight: 'var(--fw-semibold)', letterSpacing: '0.5px', color: 'var(--faint)', textTransform: 'uppercase' }}>
          {`${data?.total ?? 0} total · ${countBy('pending')} pending · ${countBy('evaluated')} evaluated · ${countBy('added')} added · ${countBy('applied')} applied`}
        </span>
      </div>

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
        <div style={{ borderRadius: 16, border: '1px solid var(--border)', overflow: 'hidden', background: 'var(--surface)' }}>
          <div
            style={{
              display: 'grid', gridTemplateColumns: ROW_GRID, gap: 10, padding: '12px 20px',
              background: 'rgba(255,255,255,.04)', fontSize: 10.5, fontWeight: 'var(--fw-semibold)',
              letterSpacing: '0.5px', color: 'var(--faint)', fontFamily: 'var(--font-mono)',
            }}
          >
            <div>COMPANY</div>
            <div>ROLE</div>
            <div>STAGE</div>
            <div style={{ textAlign: 'center' }}>FIT</div>
            <div>NEXT STEP</div>
          </div>
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
