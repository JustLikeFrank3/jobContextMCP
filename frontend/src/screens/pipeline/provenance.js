/* Provenance verdict parsing for generation results.

   The backend appends a one-line verdict from the deterministic truth gate
   (lib/provenance.format_provenance_line) to every generation confirmation
   and returns it as `provenance` on the generate-resume / generate-cover-letter
   responses. Three shapes:

     "Provenance: ✓ PASS — 6 claims traced to source, 0 unsourced"
     "Provenance: ⚠ 2 unsourced — \"47%\", \"$9M\""
     "Provenance: ⚠ check skipped — <reason>"

   Kept as a pure module so the classification is unit-testable without DOM. */

export function parseProvenance(line) {
  const text = (line || '').trim()
  if (!text.startsWith('Provenance:')) return null
  if (text.startsWith('Provenance: ✓')) return { status: 'pass', text }
  // Anchor on the FAIL shape — the PASS line also contains the word
  // "unsourced" ("0 unsourced"), and the skipped line also starts with ⚠.
  if (/^Provenance: ⚠ \d+ unsourced/u.test(text)) return { status: 'fail', text }
  return { status: 'skipped', text }
}

/* Badge tone (design-system _shared.jsx Badge) per verdict status. */
export const PROVENANCE_TONE = { pass: 'green', fail: 'warn', skipped: 'muted' }

export const PROVENANCE_BADGE_LABEL = {
  pass: '✓ provenance pass',
  fail: '⚠ unsourced claims',
  skipped: 'provenance skipped',
}
