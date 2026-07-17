import { Badge } from '../_shared.jsx'

export default function StatusRow({ label, ok, okText, offText, children }) {
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
