import { useApi, Screen, SectionHead, Badge } from './_shared.jsx'
import { Panel } from '../design-system'

/* Settings — account status and integrations. Read-only summary; editing the
   OpenAI key and Oura connection happens on the classic settings page (which
   owns the tenant-config write path).
   Data: GET /api/dashboard/settings. */

function StatusRow({ label, ok, okText, offText, children }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        padding: '14px 16px', borderRadius: 'var(--radius-md)',
        background: 'var(--surface-sunken)', border: '1px solid var(--border-soft)',
      }}
    >
      <div>
        <div style={{ color: 'var(--text-strong)', fontWeight: 'var(--fw-semibold)', fontSize: 'var(--fs-base)' }}>
          {label}
        </div>
        {children && (
          <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 3 }}>{children}</div>
        )}
      </div>
      <Badge tone={ok ? 'green' : 'muted'}>{ok ? okText : offText}</Badge>
    </div>
  )
}

export default function Settings() {
  const { data, loading, error } = useApi('/api/dashboard/settings')

  return (
    <Screen loading={loading} error={error}>
      <SectionHead title="Account" />
      <Panel style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gap: 10 }}>
          <StatusRow label="Owner access" ok={data?.isOwner} okText="owner" offText="standard">
            {data?.isOwner ? 'You have owner-only features enabled.' : 'Standard user account.'}
          </StatusRow>
        </div>
      </Panel>

      <SectionHead title="Integrations" />
      <Panel>
        <div style={{ display: 'grid', gap: 10 }}>
          <StatusRow label="AI generation (OpenAI key)" ok={data?.openaiKeySet} okText="configured" offText="not set">
            Enables resume generation, cover letter drafting, and semantic search.
          </StatusRow>
          <StatusRow label="Oura Ring" ok={data?.ouraConnected} okText="connected" offText="not connected">
            Readiness data powers the Home dashboard hero.
          </StatusRow>
        </div>
        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <a
            href={data?.classicUrl || '/dashboard/settings'}
            style={{ color: 'var(--cyan-300)', fontSize: 'var(--fs-sm)', textDecoration: 'none' }}
          >
            Edit AI key and preferences {'\u2192'}
          </a>
        </div>
      </Panel>
    </Screen>
  )
}
