# Contact and voice retrieval

This change is intended for QA during the production freeze.

Examples for the consolidated MCP tools (also exposed through WebMCP):

```json
{"action": "tone_profile", "sample_id": 187}
{"action": "tone_profile", "query": "Randy Milliken", "limit": 5}
{"action": "tone_profile", "source": "outreach_randy_milliken", "offset": 5}
```

Use these with `stories`. Results default to the five newest samples, with
source labels, sample IDs, and logging timestamps. Query terms must all occur
in the source, context, or body, ignoring case. Source matching is exact.
Bodies longer than 2,000 characters have labeled previews; `sample_id` retrieves
the entire original body. Limit is 1–20; offset is zero-based.

For a contact, use `people` with:

```json
{"action": "get", "name": "Randy Milliken", "include_context": true}
```

The response combines the contact record, stories whose people list contains
that exact full name, and recent outreach samples under its legacy source label.
Ambiguous contact names return a choice of names rather than combined records.
This does not prove delivery or consult Gmail. A sample timestamp records when
it was logged, not when an email was sent.

`people/log` accepts `sent_subject` alongside `sent_message`. The subject is
preserved as a labeled line in the tone sample's existing context field; the body
is preserved verbatim. There is no new database schema or retrospective subject
recovery. Subject without body is rejected before any write.

Non-job outreach can be logged against a contact without creating an application.

Alexa uses the existing contact lookup and writing-style actions. The generated
development model adds field names for the new options; it must be imported and
built after a QA deployment before voice field changes are available. No live
skill or production deployment is part of this change.

## Remaining work

- Semantic indexing of sent messages and tone samples in materials search.
- Stable contact associations for stories/messages and explicit alias resolution.
- A structured message history with provider thread IDs and delivery provenance.
- Contact lookup by ID (currently name-based) and pagination for linked stories.

Exact legacy source/name matching deliberately avoids inventing these links.
