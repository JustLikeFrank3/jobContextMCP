# Alexa action transport

The custom-skill HTTPS transport now has an explicit policy for all 105 MCP
actions: 52 reads, 40 confirmed actions, and 13 handoffs. This is development
code targeting QA. Production remains frozen for the WebMCP challenge.
Native Alexa+ MCP toolkit onboarding remains a separate integration.

The [complete action reference](alexa-action-reference.md) lists every phrase,
its MCP target, available fields, and any handoff. The original fast briefing,
pipeline and upcoming-interview views remain available.

## Using a guided action

1. Say **Alexa, ask job context to update an application**.
2. It asks for the company. Say **my answer is Acme**.
3. It asks for the role. Say **my answer is engineer**.
4. It asks for the status. Say **my answer is applied**.
5. It reads back the request. Say **change notes** to add notes, then
   **my answer is the recruiter will call Monday**.
6. It reads back the revised request. Say **yes** to submit, or **cancel**.
7. Say **Alexa, ask job context to check my last request** to hear the result.

For read actions, say **run it** after choosing the fields. For mutations,
**run it** only repeats the review; **yes** after the read-back is required.
Field changes invalidate that review and return to collection. Empty or
overlong answers are rejected. Long confirmations are never silently clipped.
Optional fields use the underlying MCP defaults unless explicitly changed.
The reference lists those fields; say **change** followed by a field name.

Numbers use **the number is seven** and dates use **the date is September
tenth, twenty twenty-six**. Dates must resolve to a complete calendar date.
Lists are comma-separated in this first version; confirm the transcription.
Boolean fields use **my answer is yes** or **my answer is no**, so an ordinary
**no** remains cancellation. IDs and exact filenames can be supplied, but
there is no fuzzy company/person/file selection: inspect the read-back and
use the dashboard if voice recognition cannot reproduce the target.

Guided collection keeps the microphone open on both voice-only and APL
devices. After queuing work, use the full invocation to check status. Results
are paged for voice and screens; **read more** advances through the result.
No credentials, generated download URLs or clickable file links are placed
in the APL document. The original textual tools remain the source of the
result: the adapter strips markdown/box art, it does not invent an AI summary.
Context-building tools return context, not an automatically written message.

## Long work and document inputs

New actions run in the durable control plane rather than waiting for a
search, export, generation or sync inside Alexa's HTTP request deadline.
The queued acknowledgement means accepted for processing, not succeeded.
Failures are reported as failures; internal tracebacks remain in the dashboard.
Some underlying tools report a handled failure as text; that text is retained
instead of claiming the requested effect happened.

Resume/letter generation and full assessments use a saved job description
from the job queue. Company and role must match exactly one queue entry.
No job description is guessed from a company name. Missing/ambiguous entries
give a dashboard instruction and do not enqueue work. Submit-generation
aliases resolve through the same synchronous implementation inside the
background job, so Alexa's status points at its final result.

Operations needing entire file bodies, exact source edits, structured object
fields, credentials, URLs or local filesystem scans are handoffs with a
specific alternative. These are not claimed as executable voice actions.
Optional structured/exact-content fields on other actions are also excluded;
for example full JSON Oura payloads and post audience objects need the MCP
client or dashboard. Certification rules support get/set through a confirmed
request; search tools always force auto_queue off. To queue found jobs, use
the mobile/dashboard capture flow. Drafting context never sends a message.

## Isolation and confirmation guarantees

- Signed Alexa requests and account linking gate the transport. Only reviewed
  intents map to a dispatcher action; voice cannot choose an arbitrary function.
- Dialogues and replay receipts are in the linked tenant's SQLite database.
  Pending dialogues expire after five minutes of inactivity; receipts outlive
  the signed-request replay window. An unprompted yes cannot create work.
- The confirmation receipt, consumed dialogue and queued work row commit in
  one transaction. Concurrent duplicates return the original acknowledgement.
  This guarantees one queued action, not transactional rollback of all tool
  side effects if a tool crashes midway. New Alexa jobs have one attempt.
- Workers restore the partition from the work row and the verified OID from
  server-created inputs (needed for Oura). Alexa slots cannot set either.
- Cancel discards a pending dialogue; it does not cancel an already queued job.
  Existing control-plane recovery handles queued work after restart. Exhausted
  in-flight work is failed rather than silently replaying a write.
- Results can contain the private information explicitly requested, including
  wellbeing and compensation. They are never injected into unrelated views.

The control-plane changes also prevent simultaneous claims of one queued
item, avoid dispatching an inline generator twice, and wake the event loop
safely from request worker threads.

## Build and verification

The implementation passed 233 targeted tests spanning the signed Alexa
webhook, dialogue, views, work dispatcher/policies, tracked generation, MCP
facade, OAuth bridge and voice briefing. Measured coverage of the action
catalog, dialogue and Alexa route is 96.98%. The expanded model has not yet
been built in Amazon's console or tested on hardware.

Run `python scripts/build_alexa_model.py` after editing the reviewed catalog.
Coverage tests fail if an MCP action lacks a disposition or an executable
action gains a required parameter with no voice/input strategy.

After merging to QA and verifying the deploy, import
`packaging/alexa/en-US.json` in the development console and build. Keep the
existing QA endpoint, account-linking URLs and APL settings. Do not promote
to main or point Alexa at production during the freeze.

Before considering device rollout complete, exercise a read, a confirmed
write with cancellation, a queued generation with a saved JD, multi-page
results and a handoff on actual Echo hardware. Automated coverage does not
prove speech recognition for all 105 phrases or all parameter names.

The answer slot uses a carrier phrase and is the only slot in its utterance,
as required by [Amazon's phrase-slot guidance](https://www.developer.amazon.com/en-US/docs/alexa/interaction-model-design/tips-for-using-built-in-slots-for-your-skill.html).
