import { Routes, Route, Navigate } from 'react-router-dom'
import { Logo, Button } from './design-system'

// Placeholder shell for the scaffold step. Subsequent steps replace this with
// DashboardShell + the Home/Pipeline/etc. screens converted from the design
// handoff. Exercises the design-system primitives so the build validates them.
function Placeholder() {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 18,
        textAlign: 'center',
        padding: 24,
      }}
    >
      <Logo size={48} />
      <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-base)' }}>
        React dashboard scaffold is live. Screens coming online next.
      </div>
      <Button variant="ghost" size="sm">
        Sign out
      </Button>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Placeholder />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
