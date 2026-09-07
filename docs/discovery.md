# Customer discovery ledger

jobContext's product claims are gated by provenance: a number in a generated
résumé must trace to a source record or the run is flagged. This document
applies the same rule to the company's own traction claims. Any figure quoted
on a pitch application, an investor email, or a conference form ("customer
interviews completed", "beta testers", "consent on file") is derived from
`data/discovery.db` (a standalone SQLite file, `lib/discovery.py`) by
`scripts/discovery_report.py`, and the snapshot the script writes records
which rows stand behind each number. If it can't
be recomputed from the ledger, it isn't quoted.

## What lives where

| Artifact | Committed? | Contents |
|---|---|---|
| `lib/discovery.py` | yes | the DDL, `add_signup()`, `load_ledger()`, the counting rules, snapshot and findings writers |
| `data/discovery.db` | **no** (`*.db` is git-ignored) | participants, sessions, quotes, incentives — names, contacts, quotes. Override the path with `DISCOVERY_DB`; never inside a tenant partition |
| `data/discovery/*.md` | **no** (`/data/discovery/` is git-ignored) | per-session notes and transcripts |
| `data/discovery_snapshot_<date>_<uuid>.json` | **no** | frozen numbers + record ids + ledger sha256 at the moment a form was filled in |
| `docs/discovery-findings.md` | yes | aggregates and consented, unattributed quotes only |
| `templates/discovery/` | yes | screener, consent, interview guide, session-notes template |
| `scripts/discovery_report.py` | yes | the CLI: `init`, `import-signups`, `consent`, `session add/done`, `quote`, `incentive`, `report`, `check`, `snapshot`, `findings` |
| `tests/test_discovery_report.py` | yes | pins every counting rule, the schema constraints, the CSV import, and the CLI flow |

The split is deliberate: the *method* is public and reviewable, the *people*
are not. Nothing in the committed tree can identify a participant.

## Records

Five tables, created on first open by `lib/discovery.connect()`: `program`
(one row of settings), `participants`, `sessions`, `quotes`, `incentives`.
CHECK constraints enforce the enums below and FOREIGN KEYs stop a session or
incentive from pointing at nobody; the report re-checks both anyway so a
hand-edited row can't slip past.

**Participant** — one row per human. `segment` is who they are to the product
(`job_seeker`, `career_changer`, `coach`, `school`, `workforce_program`,
`employer`, `other`, or `internal` for the founder and anyone who never
counts). `channel` is how they arrived (`network_free`, `linkedin_paid`,
`discord`, `referral`, `other`). `program` is `interview` or `beta`.
The `consent_*` columns record the consent-form version, when it was
recorded, and two booleans the report enforces: `recording_ok` and
`quote_ok`. `screener_json` holds the three signup answers; `add_signup()`
fills it from a web form or a CSV row and maps the first answer to a
segment. `contact` is UNIQUE, which is what makes re-importing a form export
safe.

**Session** — one row per conversation. `kind` is `interview` or
`beta_session`; `status` is `scheduled`, `completed`, or `no_show`.
`duration_minutes` is real, not planned. `themes` is a comma-separated list of
short tags you assign after the call; they aggregate into the findings
page. Quotes live in their own table with a `public` flag; the report publishes a quote only when the participant's
consent says `quote_ok` and the quote is marked public, and it never
attributes beyond the segment. `notes_path` points at the private notes file.

**Incentive** — one row per payment or grant. `earned_by` names the session
id (for an interview) or the literal `beta_complete`. `status` is `pending`
or `sent`; a `sent` row must carry a `reference` (gift-card order id, or the
pro-access grant id). `type` is `gift_card`, `pro_access`, or `none`.

## Counting rules

These are the definitions behind every number. They live in the script's
docstring too; this is the human copy.

- A **customer interview** is a completed `interview` session of at least
  `program.interview_min_minutes` (default 20) with a participant who is not
  `internal` and whose consent is on file. Shorter calls are real
  conversations but are not counted; a completed session without consent is
  a hard error, not a silent exclusion.
- A **beta tester enrolled** is a `beta` participant in status `enrolled`,
  `active`, or `completed`, with consent on file.
- A **beta tester completed** has at least `program.beta_sessions_to_complete`
  (default 3) completed `beta_session` rows.
- **Incentives paid** sums `sent` rows. An incentive whose `earned_by` the
  participant has not actually earned is a hard error. An earned condition
  with no incentive row is a warning ("owed") unless the participant came in
  through `network_free`, where product access or nothing is the norm.
- The **consent rate** is participants with `consent.recorded_at` over all
  participants.

The report refuses to print numbers when any hard error exists. That is the
point: the badges script does the same for the README, and for the same
reason (a silently skipped check is how a number drifts).

## Workflow

```
python scripts/discovery_report.py init
```

1. Signup arrives (LinkedIn post, DM, referral). Either the web form writes
   the row through `add_signup()`, or you export the form's CSV and run
   `import-signups signups.csv`. Status `screened`.
2. Send the consent form (`templates/discovery/consent.md`). When it comes
   back: `consent <participant-id> [--recording-ok] [--quote-ok]`. No
   consent, no session gets counted, so do this before scheduling.
3. Schedule: `session add <participant-id> --when 2026-09-18T18:00`.
4. Run the call from `templates/discovery/interview_guide.md`; record if
   `recording_ok`. Afterwards write `data/discovery/<session-id>.md` from
   `templates/discovery/session_notes.md`, then
   `session done <session-id> --minutes 32 --themes "a,b" --notes data/discovery/7.md`
   and `quote <session-id> "..." --public` for anything quotable.
5. Send the incentive the same day:
   `incentive <participant-id> --earned-by <session-id> --amount 25 --reference <order-id>`.
6. `python scripts/discovery_report.py check`. The counting rules are pinned
   by `tests/test_discovery_report.py`, so they can't rot.

When a form asks for a traction number:

```
python scripts/discovery_report.py snapshot
python scripts/discovery_report.py findings docs/discovery-findings.md
```

Copy the numbers from the snapshot into the form, keep the snapshot file, and
commit the findings page. The snapshot's `ledger_sha256` is the answer to
"what did the ledger look like when you wrote that", and `provenance` lists
the session ids behind the interview count, one for one.

## What this is not

It is not a tool in the MCP surface and it is not tenant data. It is founder
operations: its own SQLite file, its own DDL, nothing in `lib/db.py`
migrations or the sync `TABLE_SPECS`, so the 12-tool surface stays
untouched. A public signup route and a founder-only review page can sit on
top of `lib/discovery.py` without changing any of that. If discovery ever needs to become a product
feature (coaches running their own interviews, say), it gets designed as one
then; this ledger is the evidence that would justify it.

## Web surface (permanently QA-only)

The public interview signup is https://qa.jobcontext.ai/discovery. For beta
interest use https://qa.jobcontext.ai/discovery?program=beta. Add `?c=referral`
(or `&c=referral` with another query) to attribute recruitment. Supported
channels: network_free, linkedin_paid, discord, referral, other; default other.
Both links record screened interest, not a completed interview or beta enrollment.

The founder review page is https://qa.jobcontext.ai/discovery/review. Sign in to
the QA dashboard first, then open this URL. Anonymous visitors and other tenants
receive 404. `DISCOVERY_ADMIN_OIDS` is an explicit comma-separated Entra OID
allowlist; QA uses its existing founder OID. API-key/no-auth identities cannot
open the page. Review POSTs require a same-origin Origin header and reject
cross-site browser requests. Pages and API responses are not cached or indexed.

`DISCOVERY_ENABLED=qa` enables these routes; absent that explicit setting they
return 404, including on production. `DISCOVERY_DB=/app/data/discovery/discovery.db`
keeps the ledger on QA's persistent volume outside all tenant partitions and
sync. The web form and ledger stay on QA after the production freeze ends.
No production settings, MCP tools or action schemas are changed.

Signup strips cookies before FastAPI routing and uses credential-free fetches.
Email duplicates and honeypots receive the same thank-you response. Signup is
limited to ten requests per ten minutes per ingress-supplied client IP; the
in-memory limiter is bounded and resets on restart. The body is limited to 8 KiB.
The confirmation promises manual follow-up within a day; no emails are sent by
this feature. Send the consent form and calendar link yourself.

`lib/discovery_ops.py` owns all founder mutations for both the CLI and HTTP API:
consent, schedule, complete/no-show, quote, incentive and dropped/declined status.
Recording and quote consent default to false. CLI opt-ins are `--recording-ok`
and `--quote-ok`; record only permissions actually granted on the consent form.

Review shows participant screener answers, consent, sessions, quotes and
incentives, with status/segment/channel filters and newest-first ordering.
Validation errors appear verbatim. Displayed figures are provisional when errors
exist; report publication and snapshots are blocked. Counts are always computed
by `build_report` from stored rows, with supporting row IDs in provenance.

Snapshots use SQLite backup to include committed WAL data and generate an
exclusive UUID filename. Each private JSON snapshot contains the frozen ledger,
its counts, provenance and SHA-256 of its canonical JSON, so the same records can
reproduce the numbers. Snapshots contain personal information: keep them private.
The PVC persists restarts; tenant sync does not back up this separate ledger.

Findings writes are restricted to `docs/discovery-findings.md`. Review all free
text themes and quotes for identifying details before sharing. A consent flag
permits a quote but cannot establish that the text itself is anonymous.
