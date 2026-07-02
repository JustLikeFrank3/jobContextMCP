import { describe, it, expect } from 'vitest'
import { dayLabel } from './interviewUtils.js'

/* Build a "YYYY-MM-DD" string offset from today using LOCAL calendar
   components, so the test is stable regardless of the runner's timezone. */
function localDateStr(offsetDays) {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + offsetDays)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

describe('dayLabel badge', () => {
  it('reads "Today" for today\'s date', () => {
    expect(dayLabel(localDateStr(0))).toBe('Today')
  })

  it('reads "1d Ago" for yesterday', () => {
    expect(dayLabel(localDateStr(-1))).toBe('1d Ago')
  })

  it('reads "In 7d" for a date 7 days out', () => {
    expect(dayLabel(localDateStr(7))).toBe('In 7d')
  })

  it('returns empty string for missing/unparseable dates', () => {
    expect(dayLabel('')).toBe('')
    expect(dayLabel(null)).toBe('')
    expect(dayLabel('not-a-date')).toBe('')
  })
})
