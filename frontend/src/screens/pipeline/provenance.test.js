import { describe, it, expect } from 'vitest'
import { parseProvenance, PROVENANCE_TONE, PROVENANCE_BADGE_LABEL } from './provenance.js'

describe('parseProvenance', () => {
  it('classifies the PASS line as pass', () => {
    const out = parseProvenance('Provenance: ✓ PASS — 6 claims traced to source, 0 unsourced')
    expect(out).toEqual({
      status: 'pass',
      text: 'Provenance: ✓ PASS — 6 claims traced to source, 0 unsourced',
    })
  })

  it('classifies the FAIL line as fail, not tripped by "0 unsourced" in PASS', () => {
    const out = parseProvenance('Provenance: ⚠ 2 unsourced — "47%", "$9M"')
    expect(out.status).toBe('fail')
    // PASS line contains the word "unsourced" too — must stay pass.
    expect(parseProvenance('Provenance: ✓ PASS — 0 claims traced to source, 0 unsourced').status).toBe('pass')
  })

  it('classifies the check-skipped line as skipped, not fail', () => {
    const out = parseProvenance('Provenance: ⚠ check skipped — db unavailable')
    expect(out.status).toBe('skipped')
  })

  it('keeps a violation containing a quote char intact', () => {
    const out = parseProvenance('Provenance: ⚠ 1 unsourced — "5""')
    expect(out.status).toBe('fail')
    expect(out.text).toContain('5"')
  })

  it('returns null for absent or non-provenance input', () => {
    expect(parseProvenance(null)).toBeNull()
    expect(parseProvenance(undefined)).toBeNull()
    expect(parseProvenance('')).toBeNull()
    expect(parseProvenance('✓ Resume generated for R @ C')).toBeNull()
  })

  it('trims surrounding whitespace from the backend line', () => {
    expect(parseProvenance('  Provenance: ✓ PASS — 1 claims traced to source, 0 unsourced  ').status).toBe('pass')
  })
})

describe('badge mappings', () => {
  it('maps every status to a tone and label', () => {
    for (const status of ['pass', 'fail', 'skipped']) {
      expect(PROVENANCE_TONE[status]).toBeTruthy()
      expect(PROVENANCE_BADGE_LABEL[status]).toBeTruthy()
    }
  })
})
