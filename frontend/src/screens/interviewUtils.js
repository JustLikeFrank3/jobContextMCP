/* Pure helpers for the Interviews screen — kept framework-free so they can be
   unit-tested without rendering React. */

/* Parse an interview date to LOCAL start-of-day.

   A bare "YYYY-MM-DD" string passed to `new Date()` is interpreted as UTC
   midnight, which resolves to the *previous* calendar day in any timezone west
   of UTC — that is why a same-day interview used to read "1d Ago". We parse the
   date components explicitly into a local Date so the today boundary is stable.
   Returns null for empty/unparseable input. */
export function startOfDayLocal(dateStr) {
  if (!dateStr) return null
  const s = String(dateStr).trim()
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const d = new Date(s.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return null
  d.setHours(0, 0, 0, 0)
  return d
}

/* Relative-day badge label computed from local start-of-day:
   "Today" for today, "Nd Ago" for past dates, "In Nd" for future dates. */
export function dayLabel(dateStr) {
  const d = startOfDayLocal(dateStr)
  if (!d) return ''
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((d - today) / 86400000)
  if (diff === 0) return 'Today'
  if (diff > 0) return `In ${diff}d`
  return `${Math.abs(diff)}d Ago`
}
