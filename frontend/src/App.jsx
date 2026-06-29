import { Routes, Route, Navigate } from 'react-router-dom'

// Placeholder shell for the scaffold step. Subsequent steps replace this with
// DashboardShell + the Home/Pipeline/etc. screens converted from the design
// handoff. Kept intentionally minimal so `vite build` is green from day one.
function Placeholder() {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        textAlign: 'center',
        padding: 24,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: '2rem',
          fontWeight: 700,
          color: 'var(--text-strong)',
        }}
      >
        job<span style={{ color: 'var(--cyan-400)' }}>Context</span>
      </div>
      <div style={{ color: 'var(--muted)', fontSize: '0.95rem' }}>
        React dashboard scaffold is live. Screens coming online next.
      </div>
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
