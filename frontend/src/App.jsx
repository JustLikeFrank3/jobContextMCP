import { Routes, Route, Navigate } from 'react-router-dom'
import DashboardShell from './shell/DashboardShell.jsx'
import Home from './screens/Home.jsx'
import ComingSoon from './screens/ComingSoon.jsx'
import { ProtectedRoute } from './auth/AuthContext.jsx'

// All dashboard screens render inside DashboardShell (header + tab bar) via
// react-router's <Outlet>. The whole shell is gated behind ProtectedRoute so an
// expired/missing session redirects to login before any screen renders. Home is
// the Oura-readiness redesign; the remaining tabs are placeholders until each
// legacy screen is ported.
export default function App() {
  return (
    <Routes>
      <Route
        element={
          <ProtectedRoute>
            <DashboardShell />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Home />} />
        <Route path="/pipeline" element={<ComingSoon title="Pipeline" />} />
        <Route path="/job-hunt" element={<ComingSoon title="Job Hunt" />} />
        <Route path="/materials" element={<ComingSoon title="Materials" />} />
        <Route path="/rejections" element={<ComingSoon title="Rejections" />} />
        <Route path="/posts" element={<ComingSoon title="Posts" />} />
        <Route path="/people" element={<ComingSoon title="Outreach" />} />
        <Route path="/health" element={<ComingSoon title="Wellbeing" />} />
        <Route path="/interviews" element={<ComingSoon title="Interviews" />} />
        <Route path="/settings" element={<ComingSoon title="Settings" />} />
        <Route path="/api-keys" element={<ComingSoon title="API Keys" />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
