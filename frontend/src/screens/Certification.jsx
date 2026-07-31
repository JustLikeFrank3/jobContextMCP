import { useEffect, useState } from 'react'
import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, List, Row, fmtDate,
} from './_shared.jsx'
import { Panel } from '../design-system'
import { apiFetch, apiPost } from '../auth/api.js'

/* Certification — weekly work-search reports for the unemployment claim.
   Data: GET /dashboard/certification/data (index + live running-week
   progress), GET /dashboard/certification/report/{id} (frozen detail).
   The week dropdown selects a frozen report; the "required activities"
   dropdown writes the state profile (POST /dashboard/certification/profile).
   Entries only ever derive from logged events — the screen surfaces the
   under-target state loudly instead of padding. */

const SELECT_STYLE = {
  background: 'rgba(255,255,255,.06)',
  color: 'var(--text)',
  border: '1px solid rgba(255,255,255,.14)',
  borderRadius: 8,
  padding: '6px 10px',
  fontSize: 'var(--fs-sm)',
}

export default function Certification() {
  const { data, loading, error, reload } = useApi('/dashboard/certification/data')
  const reports = data?.reports || []
  const progress = data?.progress || null
  const profile = data?.profile || {}

  const [reportId, setReportId] = useState(null)
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  // Default the week dropdown to the newest frozen report.
  useEffect(() => {
    if (reportId === null && reports.length > 0) setReportId(reports[0].id)
  }, [reports, reportId])

  useEffect(() => {
    if (reportId === null) { setReport(null); return undefined }
    let live = true
    apiFetch(`/dashboard/certification/report/${reportId}`)
      .then((r) => { if (live) setReport(r) })
      .catch(() => { if (live) setReport(null) })
    return () => { live = false }
  }, [reportId])

  const setTarget = async (n) => {
    setBusy(true)
    try {
      await apiPost('/dashboard/certification/profile', { min_activities_per_week: n })
      setNotice(`Required activities set to ${n}/week.`)
      reload()
    } catch (e) {
      setNotice(e?.message || 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  const generate = async () => {
    setBusy(true)
    setNotice('Generating report — deriving activities and enriching employer addresses…')
    try {
      await apiPost('/dashboard/certification/generate', {})
      setNotice('Report frozen.')
      setReportId(null) // re-defaults to the newest after reload
      reload()
    } catch (e) {
      setNotice(e?.message || 'Generation failed')
    } finally {
      setBusy(false)
    }
  }

  const under = progress && progress.logged < progress.target

  return (
    <Screen loading={loading} error={error} empty={false}>
      <StatGrid>
        <Stat
          label="This week (live)"
          value={progress ? `${progress.logged}/${progress.target}` : '—'}
          sub={progress ? `week ending ${fmtDate(progress.weekEnding)}` : ''}
          tone={under ? 'warn' : 'green'}
        />
        <Stat label="Frozen reports" value={data?.total ?? 0} />
        <Stat label="State" value={profile.state || 'GA'} sub={`week ends ${profile.week_ends_on || 'Saturday'}`} tone="muted" />
      </StatGrid>

      <Panel style={{ marginBottom: 20 }}>
        <SectionHead title="Controls" />
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
          <label style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-soft)' }}>
            Required activities / week{' '}
            <select
              style={SELECT_STYLE}
              value={profile.min_activities_per_week || 3}
              disabled={busy}
              onChange={(e) => setTarget(Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-soft)' }}>
            Week{' '}
            <select
              style={SELECT_STYLE}
              value={reportId ?? ''}
              disabled={busy || reports.length === 0}
              onChange={(e) => setReportId(Number(e.target.value))}
            >
              {reports.length === 0 && <option value="">no frozen reports yet</option>}
              {reports.map((r) => (
                <option key={r.id} value={r.id}>
                  week ending {r.weekEnding} · v{r.version} ({r.entries} entries{r.gaps ? `, ${r.gaps} gaps` : ''})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={generate}
            disabled={busy}
            style={{ ...SELECT_STYLE, cursor: busy ? 'wait' : 'pointer', border: '1px solid rgba(0,181,200,.4)' }}
          >
            Freeze this week's report
          </button>
          {notice && <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-soft)' }}>{notice}</span>}
        </div>
      </Panel>

      {under && (
        <Panel style={{ marginBottom: 20, border: '1px solid rgba(255,180,0,.35)' }}>
          <div style={{ color: 'var(--warn)', fontSize: 'var(--fs-sm)', lineHeight: 1.5 }}>
            ⚠ {progress.logged}/{progress.target} qualifying activities so far this week — {progress.target - progress.logged} short.
            Apply, follow up, or complete a screen before {fmtDate(progress.weekEnding)}; reports are never padded.
          </div>
        </Panel>
      )}

      {report && (
        <>
          <SectionHead
            title={`Week ending ${report.weekEnding} — v${report.version}`}
            right={`generated ${report.generatedAt}`}
          />
          {report.gaps?.length > 0 && (
            <Panel style={{ marginBottom: 14, border: '1px solid rgba(255,180,0,.35)' }}>
              {report.gaps.map((g, i) => (
                <div key={i} style={{ color: 'var(--warn)', fontSize: 'var(--fs-sm)', lineHeight: 1.6 }}>⚠ {g}</div>
              ))}
            </Panel>
          )}
          <List>
            {(report.entries || []).map((e, i) => (
              <Row
                key={`${e.employer}-${i}`}
                title={`${i + 1}. ${e.employer}`}
                subtitle={e.position || '(position not recorded)'}
                meta={fmtDate(e.date)}
                right={
                  e.needs_address
                    ? <Badge tone="warn">needs address</Badge>
                    : <Badge tone="green">{String(e.kind || '').replace(/_/g, ' ')}</Badge>
                }
              >
                <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', marginTop: 8, lineHeight: 1.55 }}>
                  <div><strong>Address:</strong> {e.address || '— missing'}</div>
                  {e.website && <div><strong>Website:</strong> {e.website}</div>}
                  <div><strong>Method:</strong> {e.method}{e.contact ? ` · Contact: ${e.contact}` : ''}</div>
                  <div><strong>Result:</strong> {e.result}</div>
                  <div style={{ opacity: 0.6 }}>sources: {(e.source_event_ids || []).join(', ')}</div>
                </div>
              </Row>
            ))}
          </List>
          {report.alternates?.length > 0 && (
            <>
              <SectionHead title="Alternates" right={`${report.alternates.length}`} />
              <List>
                {report.alternates.map((a, i) => (
                  <Row
                    key={`${a.employer}-alt-${i}`}
                    title={`${String.fromCharCode(97 + i)}. ${a.employer}`}
                    subtitle={a.position}
                    meta={fmtDate(a.date)}
                    right={<Badge tone="muted">{String(a.kind || '').replace(/_/g, ' ')}</Badge>}
                  />
                ))}
              </List>
            </>
          )}
        </>
      )}
      {!report && reports.length === 0 && (
        <Panel>
          <div style={{ color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', lineHeight: 1.6 }}>
            No frozen reports yet. Your activities are already being tracked from
            applications and interviews — freeze this week's report to get a
            portal-ready summary, or ask the assistant:
            {' '}<code>certification(action="weekly_report")</code>.
          </div>
        </Panel>
      )}
    </Screen>
  )
}
