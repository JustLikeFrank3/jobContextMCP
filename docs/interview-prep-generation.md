# Interview preparation for any saved job

The existing `interviews/prep_context` action returns source material and writing
instructions. It remains available. The new `interviews/prepare` action generates
and saves a finished practice document in a background work item.

## MCP and WebMCP

1. Call `interviews` with `action=prepare`, `company`, optional `role` and `stage`.
2. If multiple saved roles match, specify the exact role before retrying. No
   work is queued for ambiguous or missing jobs.
3. Poll `documents/generation_status` with the returned work ID.
4. Read the latest result with `interviews/read_prepared` for that company/role.

The job must exist in applications or the evaluation queue. No application or
interview is created by preparation. A model provider and a master resume are
required. Missing configuration, malformed output or generation failure do not
produce a pretend completed document. Prior documents have unique filenames and
are retained; the role-specific pointer selects the latest successful result.

Source records are limited to that saved company/role, plus the master resume and
up to three exact-company historical interviews. Historical interviews are
explicitly marked in the generator instructions as potentially different roles.
Long source excerpts retain their start and end to preserve later corrections.
The saved JSON record retains the evidence supplied to generation. This is
AI-generated practice with source labels, not independently verified claims or a
confirmed interview schedule. The model's factual accuracy still needs review.

## Legacy Alexa and Echo Show

After QA deployment and importing/building the updated development model:

- “Prepare for an interview with Acme” selects the company.
- If multiple roles match, “my answer is Java Engineer” selects a role.
- The skill reads back the company/role. “Yes” queues document generation.
- “Ask job context to check my last request” retrieves the saved summary.
- “Read more” pages through the practice sections.
- “Read my interview prep” starts retrieval for a saved company/role.

Echo Show displays the role and five practice-section headings. Full source
notes are not embedded in the display rows. This transport does not resolve the
separate issue of the Echo failing to discover the legacy development skill.

## Native Alexa+

The same MCP actions and background worker are reusable; see
[native integration status](alexa-plus-native.md). Native account onboarding,
authentication compatibility, sub-500ms query measurements, MCP Apps visuals,
and actual device tests remain required. APL previews are not proof of native
Alexa+ compatibility. No production deployment is included in this work.
