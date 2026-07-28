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

/* Edit-flow instruction for fixing unsourced claims. Feeds the existing
   AI-edit modals (edit-resume / edit-cover-letter), whose pipeline re-runs
   the truth gate — so "Fix with AI" closes the loop with a fresh verdict.
   Pure so the exact contract with the edit prompt is unit-testable. */
export function buildFixInstruction(violations) {
  const vs = (violations || []).filter(Boolean)
  if (vs.length === 0) return ''
  const list = vs.map((v) => `"${v}"`).join(', ')
  const noun = vs.length === 1 ? 'claim' : 'claims'
  return (
    `The provenance gate flagged ${vs.length} unsourced ${noun}: ${list}. ` +
    'For each flagged claim, either rephrase it using only facts present in my source material, ' +
    'or remove it entirely. Do not invent or substitute any numbers, metrics, or named facts.'
  )
}
