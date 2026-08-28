// Detects whether the backend is the desktop app (DEPLOY_MODE=desktop).
//
// The mode comes from GET /api/dashboard/me, which exists in both
// deployments — probing a desktop-only route (the old approach) 404s in the
// cloud, and the browser logs that as a console error on every load. Result
// is module-cached: every consumer (nav tab, Chat screen, Settings sections)
// shares a single request per page load.
import { useEffect, useState } from 'react'

let probe = null

export function probeDesktopMode() {
  if (!probe) {
    probe = fetch('/api/dashboard/me', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((me) => Boolean(me?.desktop))
      .catch(() => false)
  }
  return probe
}

export default function useDesktopMode() {
  const [isDesktop, setIsDesktop] = useState(false)
  useEffect(() => {
    let live = true
    probeDesktopMode().then((value) => {
      if (live) setIsDesktop(value)
    })
    return () => {
      live = false
    }
  }, [])
  return isDesktop
}
