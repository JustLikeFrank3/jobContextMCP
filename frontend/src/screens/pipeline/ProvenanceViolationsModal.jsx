import { useEffect, useState } from 'react'
import { Button } from '../../design-system'
import { Badge } from '../_shared.jsx'
import { apiFetch } from '../../auth/api.js'
import { Modal, actionError } from './shared.jsx'
import { buildFixInstruction } from './provenance.js'

/* Every violation from the last truth-gate run, listed in full and
   actionable. The generation responses carry only the one-line verdict
   (capped at 6 claims) — this modal reads the complete audit row via
   GET /dashboard/pipeline/provenance/latest and hands picked claims to
   the AI-edit flow (onFix), whose pipeline re-runs the gate.

   Auto-opened by the Pipeline screen when a generation fails the gate;
   re-openable from the result banner. */
export default function ProvenanceViolationsModal({ job, onClose, onFix }) {
  const [state, setState] = useState({ run: null, loading: true, error: '' })

  useEffect(() => {
    let alive = true
    const qs = new URLSearchParams({ company: job.company || '', role: job.role || '' })
    apiFetch(`/dashboard/pipeline/provenance/latest?${qs}`)
      .then((run) => { if (alive) setState({ run, loading: false, error: '' }) })
      .catch((e) => { if (alive) setState({ run: null, loading: false, error: actionError(e) }) })
    return () => { alive = false }
  }, [job.company, job.role])

  const run = state.run?.found ? state.run : null
  const violations = run?.violations || []

  return (
    <Modal title={`Provenance — ${job.company}`} onClose={onClose}>
      {state.loading ? (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>Loading gate record…</div>
      ) : state.error ? (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>{state.error}</div>
      ) : !run ? (
        <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>
          No provenance record found for this job.
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
            <Badge tone={violations.length ? 'warn' : 'green'}>
              {violations.length ? `⚠ ${violations.length} unsourced` : '✓ pass'}
            </Badge>
            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--muted)' }}>
              {run.kind} {'·'} {run.claims.length} claims checked {'·'} {new Date(run.ts).toLocaleString()}
            </span>
          </div>
          {violations.length === 0 ? (
            <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>
              Every claim traced to source material.
            </div>
          ) : (
            <>
              <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--muted)', marginBottom: 8 }}>
                These claims appear in the generated document but not in any source
                material shown to the model. Fix rephrases or removes them via the AI
                editor — which re-runs the gate.
              </div>
              <ol style={{ margin: '0 0 14px', paddingLeft: 22, display: 'grid', gap: 6 }}>
                {violations.map((v) => (
                  <li key={v} style={{ fontSize: 'var(--fs-sm)', color: 'var(--text)' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <code style={{
                        fontFamily: 'var(--font-mono)', background: 'var(--surface-sunken)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                        padding: '2px 7px', wordBreak: 'break-word',
                      }}>{v}</code>
                      <Button size="sm" variant="ghost" onClick={() => onFix(buildFixInstruction([v]))}>
                        Fix
                      </Button>
                    </div>
                  </li>
                ))}
              </ol>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <Button size="sm" variant="ghost" onClick={onClose}>Dismiss</Button>
                <Button size="sm" onClick={() => onFix(buildFixInstruction(violations))}>
                  Fix all {violations.length} with AI
                </Button>
              </div>
            </>
          )}
        </>
      )}
    </Modal>
  )
}
