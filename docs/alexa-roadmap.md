# jobContext voice and Echo Show integration

The broader implementation is documented in [Alexa action transport](alexa-action-transport.md),
with a [complete 111-action reference](alexa-action-reference.md). The
[job search flow](alexa-job-search.md) adds numbered results and confirmed queuing. The three
fast views below remain available alongside that guided transport.

## What is implemented

The classic custom skill uses signed HTTPS requests at `/alexa`. It calls
Python adapters over the same tenant storage used by the MCP tools; it is
not an MCP client and does not automatically expose all MCP actions.
Native Alexa+ MCP add-ons require separate Amazon onboarding.

| Experience | Existing MCP capability | Classic intent | Screen |
| --- | --- | --- | --- |
| Daily briefing | `insights.briefing` | Launch / BriefingIntent | Speakable summary |
| Active applications | `applications.status` data, with digest active/stale filtering | PipelineIntent | Company, role, status; first 10 |
| Next 14 days | `interviews.upcoming` data and date window | UpcomingInterviewsIntent | Date, company, role, interview type; first 10 |

Pipeline and interviews speak the count and first three items. They do not
read the MCP tools' markdown/box-art output aloud. The screen uses APL 1.0
core components, a scrollable content area, and escaped data sources. No
remote images or layout packages are required. Only requests advertising
`Alexa.Presentation.APL` get RenderDocument; voice-only devices keep their
existing response. Display sessions leave the microphone closed rather
than repeatedly prompting the user. Search results additionally support
read-only touch selection; the original three fast views do not have touch actions.

Unknown intents receive help. APL lifecycle events do not trigger reads.
All reads run in the linked user's partition in an AnyIO worker thread.
Linking is required before workspace visuals are returned. Application
notes, interviewer contact details and health information are omitted from
the new list views; briefing retains the existing urgent-action prose.

## Validation of this increment

The Alexa, view-adapter, voice-briefing, OAuth bridge and consolidated MCP
regression suites pass: 118 tests, with 96% combined coverage of the Alexa
handler and view adapters. Amazon's APL authoring preview rendered synthetic
pipeline data on Echo Show 2 and Show 5 profiles; vertical scrolling was
checked on Show 5. The later job-search increment reserves scrollbar space
and resolves the horizontal scrollbar/footer clipping in the web preview.
Physical-device layout verification remains required for that increment.

## Review of the wider MCP surface

The source of truth is `DOMAINS` in `tools/consolidated.py`: 12 domains,
105 actions on the reviewed QA revision. Each domain
mixes actions with different latency, sensitivity and side effects; exposing
a domain wholesale would make the voice interaction unpredictable.

| Domain | Useful next voice / Show experience | Work required before exposure |
| --- | --- | --- |
| applications | Queue count, assessment summary, company detail; stage cards | Add company/role disambiguation. Queue, update, event logging and decisions need a read-back and confirmed write; assessments may need background jobs. |
| job_search | Search results as selectable job cards | Board/web calls have network latency; cap results, handle timeouts and queue selected results explicitly. URLs are better captured from a phone. |
| documents | Resume/letter job progress, provenance badge, completed-document handoff | Use submit_resume / submit_cover_letter and generation_status. Synchronous generation takes 60–120 seconds. Avoid speaking full resumes; do not put bearer tokens into display URLs. |
| materials | Find an existing document and show a short excerpt | Resolve document names; distinguish retrieval from master-resume edits and deletion. Editing needs preview, confirmation and audit. |
| interviews | Company prep cards, existing prep recap, post-interview debrief capture | Select the exact company/role; truncate private interview notes thoughtfully. Read back dictated debriefs before saving. |
| people | Due outreach, referral paths, person lookup | Disambiguate names; minimize contact details on shared screens. Draft/review is separate from sending; existing tools do not authorize sending messages. |
| stories | Rehearse one STAR story, capture a new anecdote | Use specific retrieval rather than reading every story. Confirm transcription before ingest/log/update/delete. |
| wellbeing | Opt-in mood/energy check-in and recent readiness | Shared-room disclosure needs an explicit user request. Oura sync has network latency; stored readiness is the fast path. Do not treat HBDI as a short single-turn action. |
| brand | Stored portfolio metrics and recent post status | Cached reads suit voice; GitHub refresh and project scans are slower. Post logging/metrics updates need confirmed values. |
| insights | Weekly trends, overdue actions, eval status | Curate prose and screen summaries. Rejection history and compensation are explicitly requested views; compensation_update/rejection_log are writes. |
| workspace | Setup status and missing-data checklist | check is useful for diagnostics. setup creates files and belongs in a guided onboarding flow. |
| certification | List frozen reports and show report status | weekly_report freezes data; employer lookup can refresh; state_profile can update rules. Do not mistake these for pure reads. Export and mark_submitted require an explicit workflow. |

## Sequence after this increment

1. Validate the three views on an actual Echo Show and voice-only Echo.
2. Add company selection and read-only detail cards; carry stable internal
   identifiers through the session rather than guessing names from speech.
3. Add background document generation with a visible progress/status view.
4. Add confirmed capture flows for application events and interview debriefs.
   Use a one-time pending action and idempotency key so Yes/retries cannot
   duplicate a write; Yes without a pending action must do nothing.
5. Revisit native Alexa+ MCP onboarding when toolkit access is available.
   Verify discovery against the actual client; the current Amazon quickstart
   says WWW-Authenticate is unsupported, unlike the assumption in #361.

## Deploy and console setup

1. Merge the implementation PR into QA and wait for the QA deployment.
2. In Build → Interaction Model → JSON Editor, import
   `packaging/alexa/en-US.json`, save and build. Preserve additional locale
   models if any have been added independently.
3. Build → Interfaces: enable Alexa Presentation Language for screen devices.
4. Replace the Hello World listing examples with the real briefing, pipeline
   and interview phrases; this listing is separate from invocation routing.
5. In Development testing, launch with `launch the job context skill`.
   Verify the briefing, then invoke pipeline and upcoming interviews.
6. On a Show profile inspect RenderDocument and check landscape/small-screen
   scrolling. On a voice-only device verify there are no APL directives.
7. Confirm linked-account reads, unlinked LinkAccount behavior, Stop/Help,
   empty states, and a physical-device response. Tests alone are not visual QA.

### Amazon references

- [APL interface and RenderDocument](https://developer.amazon.com/en-US/docs/alexa/alexa-presentation-language/apl-interface.html)
- [Configure APL](https://developer.amazon.com/en-GB/docs/alexa/alexa-presentation-language/apl-support-for-your-skill.html)
- [Text markup escaping](https://developer.amazon.com/en-US/docs/alexa/alexa-presentation-language/apl-text-v2024-2.html)
- [Alexa+ MCP requirements](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html)
