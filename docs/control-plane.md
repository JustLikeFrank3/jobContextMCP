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

Kinds registered today: `capture_url` (mobile share → import → assess → push).

## Roadmap

- **P1 — document generation**: route assessment / interview-prep /
  cover-letter generation (MCP tools, dashboard, chat) through `enqueue`;
  stamp artifacts with work id + prompt/template version + model (provenance).
- **P2 — policy**: per-kind model routing, token budgets, fallbacks, retries
  as data; per-tenant quotas; token/cost accounting on the row.
- **P3 — scheduler**: cron-style enqueuers (Oura autosync, weekly digest,
  follow-up nudges) so recurring work gets the same durability and audit.
- **Deferred**: journaling work rows through sync (cross-device status),
  Career Inbox events for work transitions, cancellation endpoint.

## Non-goals

No external queue/broker, no workflow engine, no separate service. The same
table + loop runs inside the frozen desktop sidecar (single partition) and on
AKS (many partitions). Multi-step pipelines stay one executor per kind until
proven otherwise.
