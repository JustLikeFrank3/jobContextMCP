# Job-board search and selected queuing

This increment targets QA during the production freeze. It adds a complete
search → details → confirmed queue flow to the classic Alexa skill, with
the same actions available through the consolidated `job_search` MCP tool
and its WebMCP bridge. It does not submit applications to employers.

## Voice walkthrough

After the QA PR is merged/deployed and the generated en-US development
model is built in Amazon's console:

1. **Alexa, launch the job context skill.**
2. **Find jobs for software engineer.** Alternatively say **find new jobs**,
   then **my answer is software engineer** when asked for the query.
3. Optionally say **change location**, then **my answer is remote**.
   **Change num results** and **the number is five** changes the result cap.
4. **Run it.** Search runs in the background so Alexa can acknowledge promptly.
5. **Alexa, ask job context to check my last request.**
6. **Tell me about job two.** Read the description excerpt, or tap a numbered
   result on an Echo Show. **Read more** while viewing search results reads
   the next three matches; result numbers stay stable.
7. **Queue job two.** Alexa reads back the exact company, role and location.
8. **Yes** to queue that posting, or **cancel**. **Run it** cannot confirm a write.
9. **Alexa, ask job context to check my last request.** This reports whether
   queuing succeeded. **Show my job queue**, then **run it**, lists the inbox.
   **Evaluate a queued job** starts the existing company/role assessment flow.

The search itself never queues jobs. The selected job retains its fetched
description and source link. Jobs already queued or tracked are excluded
by default; the optional `include_known` field can include them. Repeating
a queued company/role returns **Already queued**, preserving its original
description and evaluation state. SQLite insertion checks duplicates and
adds one row under a write lock rather than rewriting the entire queue.

## Saved boards

**List my job boards** shows configured boards and supported careers links
inferred from the existing job queue. **Save a job board** asks for a provider
and company slug; optionally set `company` to the display name. For example,
`jobs.ashbyhq.com/acme` uses provider `ashby` and slug `acme`.
**Remove a job board** excludes it from subsequent searches, including boards
inferred from queue links. Both changes require a read-back and **yes**.

The keyless search supports Greenhouse, Lever, Ashby and Recruitee. It searches
up to eight saved boards in parallel, defaults to five matches, and permits
1–20 results. Query words must occur in the title, location or description;
matches with more title hits rank first. This is keyword matching, not an
AI fitment score. Location filters use the board's location text. Individual
board failures are reported alongside any successful results; they are not
presented as proof that a company has no openings.

Public APIs return currently published postings, but a posting can close
after a search. Missing/short descriptions, invalid source links and unlisted
Ashby entries are excluded. No arbitrary source URL is fetched during selection.
Each board has a 12-second overall fetch limit and an 8 MB response cap.
Search snapshots expire after one hour and are isolated in the user's DB.
Expired or foreign-workspace IDs cannot queue jobs. Board configuration and
short-lived snapshots are local to that environment; they are not sync-journal
records and do not change the production workspace.

The existing individual-board tools remain available. The former generic
**search for jobs** phrase now opens saved-board discovery; **search Google
jobs** explicitly invokes the existing SerpAPI-backed web search, which still
requires its configured key.

## MCP examples

```json
{"action":"save_board","provider":"ashby","company_slug":"acme","company":"Acme"}
{"action":"discover","query":"software engineer","location":"remote","num_results":5}
{"action":"result","search_id":"<returned search_id>","result_number":2}
{"action":"queue_result","search_id":"<returned search_id>","result_number":2}
```

`discover` returns JSON with a `search_id`, numbered `results`, and `errors`.
`result` returns the stored description and URL. `queue_result` expresses an
explicit write request from the MCP client; Alexa adds the voice confirmation.
Alexa carries the search ID internally; users never dictate it. Device-bound
search context survives a new voice session. Touch opens details only and
invalidates an earlier voice confirmation on that device; it cannot queue.

## Verification and references

The targeted regression run passed 306 tests, with 97.34% combined coverage
of discovery, Alexa job views, and the dialogue handler. A read-only live
request to Osano's Greenhouse board returned four parseable postings.

Tests cover all four provider payloads, unavailable/malformed/oversized boards,
partial failure, filtering, exact selection, expiration, tenant isolation,
concurrent SQLite queue additions, voice cancellation/replay, device context,
APL token validation and escaped display text. Amazon's authoring preview
rendered the document on Show 2 and Show 5; the small display scrolled to the
last job and queue guidance. A tap on job two emitted exactly
`["job_detail", "preview-only", "2"]`. Content width reserves scrollbar space,
avoiding the previous horizontal scrollbar/footer clipping in the web preview.
Physical Echo Show behavior and speech recognition still require checking
after the QA deployment/model build.

- [Greenhouse public job-board API](https://docs.greenhouse.io/job-board.html)
- [Ashby public posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [Amazon APL UserEvent interface](https://developer.amazon.com/en-US/docs/alexa/alexa-presentation-language/apl-interface.html)
- [Amazon TouchWrapper example](https://developer.amazon.com/en-GB/blogs/alexa/alexa-skills-kit/2020/07/touchwrapper-implementation-and-best-practices-with-the-alexa-presentation-language)
