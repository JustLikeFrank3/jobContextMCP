// Detects whether the backend is the desktop app (DEPLOY_MODE=desktop).
//
// The desktop-only routes (/api/chat/*, /desktop/*) simply don't exist on
// the hosted product, so one cheap probe answers the question. Result is
// module-cached: every consumer (nav tab, Chat screen, Settings sections)
// shares a single request per page load.
import { useEffect, useState } from 'react'

let probe = null

export function probeDesktopMode() {
  if (!probe) {
    probe = fetch('/api/chat/sessions', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then((res) => res.ok)
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
