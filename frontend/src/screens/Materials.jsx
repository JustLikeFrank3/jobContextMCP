import {
  useApi, Screen, SectionHead, StatGrid, Stat, Badge, EmptyState,
} from './_shared.jsx'
import { Panel } from '../design-system'

/* Materials — generated resumes, cover letters, PDFs, and prep docs.
   Data: GET /dashboard/materials/data (_materials_payload). */

const FOLDER_LABEL = {
  optimized_resumes: 'Optimized resumes',
  cover_letters: 'Cover letters',
  resume_pdfs: 'Resume PDFs',
  cover_letter_pdfs: 'Cover letter PDFs',
  job_assessments: 'Job assessments',
  interview_prep: 'Interview prep docs',
}
const FOLDER_ORDER = [
  'optimized_resumes', 'cover_letters', 'resume_pdfs',
  'cover_letter_pdfs', 'job_assessments', 'interview_prep',
]

export default function Materials() {
  const { data, loading, error } = useApi('/dashboard/materials/data')
  const folders = data?.folders || {}
  const totalFiles = Object.values(folders).reduce((n, f) => n + (f.count || 0), 0)

  return (
    <Screen loading={loading} error={error} empty={!loading && !error && totalFiles === 0}
      emptyLabel="No materials generated yet."
      emptyHint="Resumes and cover letters you generate will appear here."
    >
      <StatGrid>
        <Stat label="Resumes" value={data?.optimized_resumes ?? 0} tone="accent" />
        <Stat label="Cover letters" value={data?.cover_letters ?? 0} />
        <Stat label="PDFs" value={(data?.resume_pdfs ?? 0) + (data?.cover_letter_pdfs ?? 0)} tone="green" />
        <Stat label="Untracked" value={data?.gap ?? 0} tone={data?.gap ? 'warn' : 'muted'}
          sub={data?.gap ? 'resumes with no application' : 'all tracked'} />
      </StatGrid>

      {FOLDER_ORDER.filter((k) => folders[k]?.count > 0).map((key) => {
        const f = folders[key]
        return (
          <Panel key={key} style={{ marginBottom: 14 }}>
            <SectionHead title={FOLDER_LABEL[key] || key} right={`${f.count}`} />
            <div style={{ display: 'grid', gap: 6 }}>
              {f.files.map((file) => (
                <a
                  key={file.name}
                  href={file.href}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
                    padding: '9px 12px', borderRadius: 'var(--radius-md)',
                    background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
                    color: 'var(--text-soft)', fontSize: 'var(--fs-sm)', textDecoration: 'none',
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {file.name}
                  </span>
                  <Badge tone="muted">{(file.ext || '').replace('.', '') || 'file'}</Badge>
                </a>
              ))}
            </div>
          </Panel>
        )
      })}

      {totalFiles === 0 && <EmptyState label="No files in any folder yet." />}
    </Screen>
  )
}
