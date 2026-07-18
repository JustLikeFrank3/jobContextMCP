// Date/label formatting shared by the design screens.

/** "IN 5D" / "TODAY" / "TOMORROW" countdown chip from an ISO-ish date. */
export function countdownChip(dateStr?: string): string {
  const m = String(dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return ''
  // Parse as a LOCAL calendar date — new Date('2026-07-02') is UTC midnight,
  // which is the previous day west of UTC.
  const then = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((then.getTime() - today.getTime()) / 86400000)
  if (diff === 0) return 'TODAY'
  if (diff === 1) return 'TOMORROW'
  if (diff > 1) return `IN ${diff}D`
  return `${-diff}D AGO`
}

/** "hiring manager · Tue 14:00" line from an interview record. */
export function interviewTimeLine(iv: {
  interview_type?: string
  interview_date?: string
}): string {
  const type = (iv.interview_type || '').replace(/_/g, ' ')
  const raw = String(iv.interview_date || '')
  const timePart = raw.includes(' ') ? raw.split(' ')[1]?.slice(0, 5) : ''
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  let dayName = ''
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    dayName = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()]
  }
  return [type, [dayName, timePart].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
}
