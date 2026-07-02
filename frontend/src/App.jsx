import { Routes, Route, Navigate } from 'react-router-dom'
import DashboardShell from './shell/DashboardShell.jsx'
import Home from './screens/Home.jsx'
import Pipeline from './screens/Pipeline.jsx'
import JobHunt from './screens/JobHunt.jsx'
import Materials from './screens/Materials.jsx'
import Rejections from './screens/Rejections.jsx'
import Posts from './screens/Posts.jsx'
import People from './screens/People.jsx'
import Health from './screens/Health.jsx'
import Interviews from './screens/Interviews.jsx'
import Settings from './screens/Settings.jsx'
import ApiKeys from './screens/ApiKeys.jsx'
import { ProtectedRoute } from './auth/AuthContext.jsx'

// All dashboard screens render inside DashboardShell (header + tab bar) via
// react-router's <Outlet>. The whole shell is gated behind ProtectedRoute so an
// expired/missing session redirects to login before any screen renders.
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
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/job-hunt" element={<JobHunt />} />
        <Route path="/materials" element={<Materials />} />
        <Route path="/rejections" element={<Rejections />} />
        <Route path="/posts" element={<Posts />} />
        <Route path="/people" element={<People />} />
        <Route path="/health" element={<Health />} />
        <Route path="/interviews" element={<Interviews />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/api-keys" element={<ApiKeys />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
