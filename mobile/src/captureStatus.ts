// Tiny observable for capture status — the share flow must NEVER use a
// modal Alert: alerts fired during the launch/foreground transition wedge
// touch handling on iOS ("app hangs after Saved…", source app frozen
// behind). A banner is state, not a modal — nothing can block on it.
import { useEffect, useState } from 'react'

export type CaptureStatus = { kind: 'busy' | 'ok' | 'error'; text: string } | null

let current: CaptureStatus = null
const listeners = new Set<(s: CaptureStatus) => void>()
let timer: ReturnType<typeof setTimeout> | null = null

export function setCaptureStatus(status: CaptureStatus, autoClearMs = 5000): void {
  current = status
  listeners.forEach((l) => l(status))
  if (timer) clearTimeout(timer)
  if (status && status.kind !== 'busy') {
    timer = setTimeout(() => setCaptureStatus(null), autoClearMs)
  } else if (status && status.kind === 'busy') {
    // A busy state must never outlive the work: if nothing resolves it
    // (dropped connection, crashed request), degrade to a gentle error
    // instead of an eternal spinner.
    timer = setTimeout(
      () =>
        setCaptureStatus({
          kind: 'error',
          text: 'Still working — check the Inbox in a minute.',
        }),
      45_000,
    )
  }
}

export function useCaptureStatus(): CaptureStatus {
  const [status, setStatus] = useState<CaptureStatus>(current)
  useEffect(() => {
    listeners.add(setStatus)
    return () => {
      listeners.delete(setStatus)
    }
  }, [])
  return status
}
