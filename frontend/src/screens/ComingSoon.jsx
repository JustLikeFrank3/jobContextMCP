import { Panel } from '../design-system'

/* Temporary placeholder for screens not yet ported from the legacy
   server-rendered dashboard. Each renders inside DashboardShell via <Outlet>. */
export default function ComingSoon({ title }) {
  return (
    <Panel pad="40px 28px" style={{ textAlign: 'center' }}>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 'var(--fs-lg)',
          fontWeight: 'var(--fw-semibold)',
          color: 'var(--text-strong)',
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)' }}>
        This screen is being migrated to the new dashboard. Coming soon.
      </div>
    </Panel>
  )
}
