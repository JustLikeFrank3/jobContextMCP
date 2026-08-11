# Control Plane

Every background unit of work is a durable row with a lifecycle, executed by
one dispatcher — never a fire-and-forget thread inside a request handler.

## Why (the incident that motivated it)

2026-07-09: mobile share-capture handed scrape→assess→push to
`loop.run_in_executor`, which does not propagate contextvars. On multi-tenant
cloud the worker escaped the caller's partition, crashed on a missing table,
and the exception vanished into the executor. The user saw "Saved." and then
silence — for days. A control plane makes that failure mode structurally
impossible *and* visible when anything else goes wrong.

## Shape (P0, shipped)

Three pieces, no new infrastructure:

1. **`work_items` table** (`lib/work.py`) — per-user partition DB, like all
   tenant data: `kind, inputs_json, status (queued→running→succeeded/failed),
   attempt/max_attempts, origin, error (traceback), artifacts_json, timings`.
2. **Dispatcher** — an asyncio loop started in the FastAPI lifespan, bounded
   concurrency, executors run via `to_thread`. The worker sets partition
   context **from the work row's home partition**, never from ambient
   request context. On startup it sweeps partitions for rows orphaned by a
   restart: re-dispatches those with attempts left, fails the rest with
   `abandoned`.
3. **Status API** — `GET /api/work` and `GET /api/work/{id}`, partition-scoped
   like everything else.

Executors are blocking callables registered per kind:

```python
from lib import work
work.register_kind("capture_url", fn)          # fn(inputs: dict) -> artifacts dict
work_id = work.enqueue("capture_url", {"url": u}, origin="mobile-share")
```

An executor that raises fails the row with the traceback attached; success
stores its returned dict as artifacts. Pushes/notifications are signals the
executor sends; **the row is the system of record**.

Kinds registered today: `capture_url` (mobile share → import → assess → push), `run_evals` (server-side golden-suite eval runs, incl. the nightly schedule — see [evals.md](evals.md)), `certification.weekly` (Sunday-morning work-search report snapshots — `tools/certification_work.py`), and `generate.resume` / `generate.cover_letter` / `generate.assessment` (document generation — `tools/generate_work.py`; these run via `run_now` rather than the dispatcher, see P1 below).

`enqueue` hands the row to the dispatcher for work nobody is waiting on. **`run_now` creates the same row and executes it in the caller's thread** — for interactive work where the caller blocks for the answer regardless, so the queue would only add latency. Same lifecycle, same artifacts, same orphan sweep; only the dispatcher is skipped.

## Telemetry (P0, shipped alongside)

Two complementary layers, still zero new infrastructure (`lib/metrics.py`):

- **`GET /metrics`** — Prometheus text format from an in-process registry.
  Instrumented: every HTTP request (`http_requests_total` /
  `http_request_seconds`, labeled by route *template* to bound cardinality),
  every work item (`work_items_total` / `work_item_seconds` by kind/status),
  and every LLM call through the `create_chat_completion` funnel
  (`llm_calls_total` by label/model/outcome, `llm_call_seconds`,
  `llm_tokens_total` by direction). Aggregates only — no user data. The AKS
  pods carry `prometheus.io/*` annotations for Azure Monitor's managed
  Prometheus (enable pod-annotation scraping in
  ama-metrics-settings-configmap to activate collection).
- **`GET /api/work/stats`** — per-tenant JSON aggregates straight off the
  work_items table (counts + avg duration by kind/status, recent failures
  with error heads, and — since P2 — `tokens_by_kind`): the control plane
  doubling as its own telemetry source, consumable by the dashboard, mobile,
  or Claude in chat. Note the division of labour with `/metrics`: the
  Prometheus counters are cumulative and answer "what rate", the work rows are
  per-unit and answer "what did this job cost".

## Roadmap

- **P1 — document generation (shipped 2026-08-10)**: resume, cover-letter, and
  assessment generation now run as `generate.resume` / `generate.cover_letter` /
  `generate.assessment` rows for every caller — the MCP facade, the dashboard service, and the agent
  fallback alike. Artifacts carry the stamp P1 asked for: the row *is* the work
  id, plus `prompt_version` (a digest of the system prompt, not a
  hand-maintained constant that would silently go stale) and the `model` that
  produced the text. Two deviations from the original entry, both deliberate:
  **`run_now`, not `enqueue`** — the caller is waiting for the document, so the
  row is created and executed inline; queueing it behind `MAX_CONCURRENCY=2`
  background work would add latency and buy nothing, and durability is
  identical because the row is written before execution and swept on restart
  either way. And **the interception is a decorator** (`tools/generate_work.tracked`)
  rather than edits at each call site: there were three callers and a fourth
  that quietly bypassed the control plane would have been an easy mistake.
  `model` is resolved per kind — assessment reads `task="assessment"`, not the
  generator's model, and stamping one with the other's would be worse than not
  stamping at all.

  **The entry named more than it should have.** Of the three surfaces it
  listed, only assessment turned out to be a generator: `assess_job_fitment`
  and `generate_interview_prep_context` are context *packers* — they read the
  master resume and return a formatted prompt for the orchestrating agent to
  act on. No model is called and no document is produced, so there is no
  artifact to stamp and nothing to attribute; a row recording "we assembled a
  string" would be noise in the exact table you query to attribute a
  regression. They are deliberately untracked, and a test pins that so a later
  change doesn't wrap them by reflex.
- **P2 — accounting (shipped 2026-08-10)**: every row now carries what it
  spent — `llm_calls`, `tokens_prompt`, `tokens_completion`, and the set of
  models it called. Collection is a contextvar sink (`openai_calls.collect_usage`)
  wrapped around the executor, so LLM calls several frames down are attributed
  without threading a parameter through every generator; the sink is set and
  read in the same thread, so it does *not* depend on contextvar propagation
  across an offload (the 2026-07-09 trap). Aggregates surface at
  `GET /api/work/stats` as `tokens_by_kind`.

  Three deliberate choices. **Tokens, not dollars**: prices move — Sonnet 5's
  introductory rate ends 2026-08-31 — so a cost stored on a row is wrong the
  moment pricing changes, and wrong silently. Tokens are the durable fact;
  dollars are a view computed at read time. **Failed rows are counted too**:
  a run that burned 40k tokens and then blew up is exactly the spend worth
  seeing. And **the columns are added by a PRAGMA-guarded ALTER in
  `_ensure_schema`, not through `lib.db._MIGRATIONS`**: that ledger tolerates
  an ALTER whose target table doesn't exist and marks it applied anyway, and
  `work_items` is created lazily — so a partition with no work_items at
  migration time would burn the ledger entry and never get the columns.

  This exists because of a concrete misread: `llm_tokens_total` is cumulative
  since process start, and reading it as one night's spend overstated the
  nightly eval cost threefold. A per-row total cannot be misread that way.

- **P2 — policy (shipped 2026-08-10)**: per-kind model routing, retries and
  fallbacks as data, per-run token budgets, and per-tenant daily quotas, all
  resolved from configuration at execution time (`lib/work_policy.py`).

  **Every default reproduces pre-P2 behavior** — one attempt, no backoff, no
  routing, no ceilings. That is the load-bearing property: a policy engine
  whose defaults change how work runs is indistinguishable from a rewrite, and
  there would be no way to tell a policy bug from a regression in the work it
  governs.

  ```json
  "work_policy": {
    "defaults": {"max_attempts": 2, "backoff_seconds": [2, 8],
                 "daily_token_quota": 2000000},
    "kinds": {
      "generate.resume": {"model": "gpt-4.1",
                          "fallback_models": ["gpt-4o-mini"],
                          "token_budget": 60000}
    }
  }
  ```

  Layering is defaults → per-kind → env (`WORK_DAILY_TOKEN_QUOTA` only, for the
  cloud knob that must be settable without editing a tenant file). A malformed
  block degrades field by field instead of raising: a typo must not be able to
  stop work from running, only to fail to change how it runs.

  - **Routing** is a contextvar the executor sets and `_resolve_llm_settings`
    reads, so a generator several frames down needs no parameter. It reroutes
    the **model only, never the provider** — swapping vendors swaps which
    credential is required and who receives the prompt, which is a deployment
    change and should look like one. `task="eval_judge"` is exempt entirely:
    which model grades the golden suite has an MAE table behind it, and a
    tenant-editable file that could retarget it would invalidate that table
    silently.
  - **Retries** are classified, not blanket. Transient shapes (429, timeouts,
    5xx, dropped connections) retry; a `KeyError` or a bad prompt fails once,
    because it will fail identically on attempt two and retrying only doubles
    the cost of a bug. `max_attempts` is stamped on the row at enqueue, so an
    item cannot become eligible again because a config file changed while it
    sat in the queue. Backoff sleeps in the worker thread, which holds one of
    two dispatcher slots — fine for seconds, which is why the docs say seconds;
    minute-scale waits want P3's scheduler.
  - **Fallback models** advance with the attempt and stay on the last entry
    rather than snapping back to a primary that has already failed twice.
  - **Token budget** is a per-run stop-loss enforced in the call funnel: once a
    run has spent its budget the next request is not sent. It bounds a runaway
    loop, not a single oversized call — a request's cost is only knowable after
    it returns. Retries share the remainder, so `max_attempts` cannot quietly
    multiply the ceiling.
  - **Daily quota** is checked once, before a run is admitted, against the P2
    accounting columns (so it counts failed runs too). A run already in flight
    is never interrupted: that is the budget's job, and killing work mid-flight
    would leave a half-written document for a limit something else reached.
    Status at `GET /api/work/stats` → `quota`.
  Deliberately still absent: a *cost* figure anywhere. Tokens are the durable
  fact; dollars are a view computed at read time.
- **P3 — scheduler**: cron-style enqueuers (Oura autosync, weekly digest,
  follow-up nudges) so recurring work gets the same durability and audit.
- **Deferred**: journaling work rows through sync (cross-device status),
  Career Inbox events for work transitions, cancellation endpoint.

## Non-goals

No external queue/broker, no workflow engine, no separate service. The same
table + loop runs inside the frozen desktop sidecar (single partition) and on
AKS (many partitions). Multi-step pipelines stay one executor per kind until
proven otherwise.
