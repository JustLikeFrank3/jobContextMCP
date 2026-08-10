"""Control plane P0: durable work items + in-process dispatcher.

Every background unit of work (share capture, and — in P1 — all document
generation) becomes a row in the per-user ``work_items`` table with a
lifecycle, instead of a fire-and-forget thread. The dispatcher is the only
thing that executes work, and it sets the partition context FROM THE ROW's
own home partition — workers can never run against the wrong tenant the way
ambient-context offloads could (see the 2026-07-09 capture incident).

Design constraints (docs/control-plane.md has the longer story):
  - No external queue/service. A table + an asyncio loop, so the identical
    code runs in the frozen desktop sidecar and on multi-tenant AKS.
  - Rows live in each user's own DB, like all tenant data. Cross-restart
    recovery sweeps partitions for orphaned queued/running rows.
  - Executors are plain blocking callables registered by kind; they run via
    asyncio.to_thread with bounded concurrency.

Public surface:
  register_kind(kind, fn)          — map a work kind to its executor
  enqueue(kind, inputs, ...)       — insert a queued row + wake the dispatcher
  get_item(item_id) / list_items() — status reads (current partition)
  start_dispatcher(app)/stop_...   — lifespan integration
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from lib import config, metrics, work_policy
from lib.db import get_connection
from lib.openai_calls import collect_usage
from lib.user_context import (
    get_data_folder_override,
    reset_data_folder,
    set_data_folder,
)

_log = logging.getLogger(__name__)

# kind -> blocking callable(inputs: dict) -> dict (artifacts; JSON-serializable)
_KINDS: dict[str, Callable[[dict], dict]] = {}

MAX_CONCURRENCY = 2

_SCHEMA = """CREATE TABLE IF NOT EXISTS work_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT    NOT NULL,
    inputs_json    TEXT    NOT NULL DEFAULT '{}',
    status         TEXT    NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    attempt        INTEGER NOT NULL DEFAULT 0,
    max_attempts   INTEGER NOT NULL DEFAULT 1,
    origin         TEXT    NOT NULL DEFAULT '',
    error          TEXT,
    artifacts_json TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at     TEXT,
    finished_at    TEXT
)"""


def register_kind(kind: str, fn: Callable[[dict], dict]) -> None:
    _KINDS[kind] = fn


# Columns added after work_items shipped. Applied here rather than through
# lib.db._MIGRATIONS on purpose: that ledger tolerates an ALTER whose target
# table doesn't exist yet and marks it applied anyway, and work_items is
# created lazily on first use — so a partition that had no work_items when the
# migration ran would burn the ledger entry and never get the column. A
# PRAGMA-guarded add here runs whenever the table is touched and cannot be
# skipped.
_ADDED_COLUMNS = {
    "llm_calls": "INTEGER NOT NULL DEFAULT 0",
    "tokens_prompt": "INTEGER NOT NULL DEFAULT 0",
    "tokens_completion": "INTEGER NOT NULL DEFAULT 0",
    "models_json": "TEXT",
}


def _ensure_schema() -> None:
    """Create work_items in the current partition's DB (idempotent)."""
    with get_connection() as con:
        con.execute(_SCHEMA)
        have = {r[1] for r in con.execute("PRAGMA table_info(work_items)")}
        for name, decl in _ADDED_COLUMNS.items():
            if name not in have:
                con.execute(f"ALTER TABLE work_items ADD COLUMN {name} {decl}")
        con.commit()


# ── enqueue / read (run inside a request's partition context) ─────────────────

def enqueue(kind: str, inputs: dict, origin: str = "", max_attempts: int = 0) -> int:
    """Insert a queued row in the CURRENT partition and wake the dispatcher.

    *max_attempts* defaults to the kind's policy (1 unless configured). It is
    stamped on the row rather than read at execution time so the startup sweep
    and the executor agree on the budget even if the policy changes between
    enqueue and run — an item that has already burned two of its two attempts
    must not become eligible again because someone edited a config file.
    """
    if kind not in _KINDS:
        raise ValueError(f"unknown work kind: {kind}")
    _ensure_schema()
    attempts = max_attempts if max_attempts > 0 else work_policy.for_kind(kind).max_attempts
    with get_connection() as con:
        cur = con.execute(
            "INSERT INTO work_items (kind, inputs_json, origin, max_attempts) "
            "VALUES (?, ?, ?, ?)",
            (kind, json.dumps(inputs), origin, max(1, attempts)),
        )
        con.commit()
        item_id = int(cur.lastrowid)
    _notify(get_data_folder_override(), item_id)
    return item_id


def run_now(kind: str, inputs: dict, origin: str = "") -> dict:
    """Create a work row and execute it INLINE, in the caller's thread.

    The interactive counterpart to :func:`enqueue`. Both produce the same
    durable row with the same lifecycle, artifacts, and failure capture — the
    difference is only who runs it and when.

    Use this when the caller is waiting for the result. Routing an interactive
    generation through the dispatcher would add latency without buying
    anything: MAX_CONCURRENCY is 2, so a user-facing request could sit behind
    two background evals, and the caller has to block for the answer either
    way. Use :func:`enqueue` for work nobody is waiting on (share capture,
    nightly evals, weekly reports).

    Durability is unaffected: the row is written before execution starts, so a
    process death mid-run leaves a 'running' row that the startup sweep fails
    as abandoned, exactly as for a dispatched item.

    Returns the finished row. Callers must check ``status`` — an executor that
    raises produces a 'failed' row with the traceback in ``error`` rather than
    propagating, so a caller that assumes success reads ``artifacts`` as None.
    """
    item_id = enqueue(kind, inputs, origin=origin)
    _execute(get_data_folder_override(), item_id)
    return get_item(item_id) or {"id": item_id, "status": "failed",
                                 "error": "work row vanished after execution"}


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["inputs"] = json.loads(d.pop("inputs_json") or "{}")
    d["artifacts"] = json.loads(d.pop("artifacts_json") or "null")
    d["models"] = json.loads(d.pop("models_json") or "[]")
    return d


def get_item(item_id: int) -> "dict | None":
    _ensure_schema()
    with get_connection() as con:
        row = con.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_items(status: str = "", limit: int = 50) -> list[dict]:
    _ensure_schema()
    limit = max(1, min(limit, 200))
    with get_connection() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM work_items WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM work_items ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── dispatcher ─────────────────────────────────────────────────────────────────

# Queue items are (partition_path_or_None, item_id). None = default partition
# (desktop single-tenant / dev).
_queue: "asyncio.Queue[tuple[str | None, int]] | None" = None
_workers: list[asyncio.Task] = []


def _notify(partition: "Path | str | None", item_id: int) -> None:
    """Hand a claimed-able item to the dispatcher; no-op when not running
    (tests / CLI): the startup sweep will find it later."""
    if _queue is not None:
        _queue.put_nowait((str(partition) if partition else None, item_id))


def _in_partition(partition: "str | None", fn: Callable[[], Any]) -> Any:
    """Run fn with the partition context taken from the WORK ROW's home, not
    from whatever context the dispatcher happens to hold."""
    if partition is None:
        return fn()
    token = set_data_folder(partition)
    try:
        return fn()
    finally:
        reset_data_folder(token)


def _tokens(usage: "list[dict]") -> int:
    return sum(int(u.get("prompt") or 0) + int(u.get("completion") or 0) for u in usage)


def _bump_attempt(item_id: int) -> int:
    """Record a retry on the row and return the new attempt number.

    Written before the retry runs, not after it finishes, so a process death
    mid-retry leaves the sweep an accurate attempt count instead of one that
    lets the item run more times than its policy allows.
    """
    with get_connection() as con:
        con.execute(
            "UPDATE work_items SET attempt = attempt + 1, status='running' WHERE id = ?",
            (item_id,),
        )
        con.commit()
        row = con.execute("SELECT attempt FROM work_items WHERE id = ?", (item_id,)).fetchone()
    return int(row["attempt"]) if row else 0


def _execute(partition: "str | None", item_id: int) -> None:
    """Blocking: claim, run the kind's executor, persist the outcome.

    Retries, model routing, per-run token budgets, and the tenant's daily quota
    all come from the kind's policy (lib/work_policy.py). Every default
    reproduces pre-P2 behavior: one attempt, no routing, no ceilings.
    """
    def _claim() -> "tuple[str, dict, int, int] | None":
        _ensure_schema()
        with get_connection() as con:
            row = con.execute(
                "SELECT * FROM work_items WHERE id = ? AND status IN ('queued','running')",
                (item_id,),
            ).fetchone()
            if row is None:
                return None
            con.execute(
                "UPDATE work_items SET status='running', attempt=attempt+1, "
                "started_at=datetime('now') WHERE id = ?",
                (item_id,),
            )
            con.commit()
            return (row["kind"], json.loads(row["inputs_json"] or "{}"),
                    int(row["attempt"]) + 1, int(row["max_attempts"]))

    claimed = _in_partition(partition, _claim)
    if claimed is None:
        return
    kind, inputs, attempt, max_attempts = claimed
    fn = _KINDS.get(kind)
    policy = _in_partition(partition, lambda: work_policy.for_kind(kind))

    def _finish(
        status: str,
        error: str = "",
        artifacts: "dict | None" = None,
        usage: "list[dict] | None" = None,
    ) -> None:
        # Tokens, not dollars. Prices move — Sonnet 5's introductory rate ends
        # 2026-08-31 — so a cost baked into a row is wrong the moment pricing
        # changes, and silently so. Tokens are the durable fact; dollars are a
        # view computed at read time against whatever the rate is then.
        calls = usage or []
        models = sorted({str(u.get("model") or "") for u in calls if u.get("model")})

        def _write() -> None:
            with get_connection() as con:
                con.execute(
                    "UPDATE work_items SET status=?, error=?, artifacts_json=?, "
                    "llm_calls=?, tokens_prompt=?, tokens_completion=?, models_json=?, "
                    "finished_at=datetime('now') WHERE id = ?",
                    (status, error or None,
                     json.dumps(artifacts) if artifacts is not None else None,
                     len(calls),
                     sum(int(u.get("prompt") or 0) for u in calls),
                     sum(int(u.get("completion") or 0) for u in calls),
                     json.dumps(models) if models else None,
                     item_id),
                )
                con.commit()
        _in_partition(partition, _write)

    if fn is None:
        _finish("failed", error=f"no executor registered for kind '{kind}'")
        metrics.inc("work_items_total", kind=kind, status="failed")
        return

    # Quota is checked once, before the first attempt: an exhausted tenant
    # should cost nothing at all, not one more call. Retries of an already
    # admitted run are not re-checked — the run was admitted.
    try:
        _in_partition(partition, lambda: work_policy.check_quota(policy))
    except Exception as exc:  # noqa: BLE001 — quota_exceeded is an outcome, not a crash
        _log.warning("work item %s (%s) blocked: %s", item_id, kind, exc)
        _finish("failed", error=str(exc))
        metrics.inc("work_items_total", kind=kind, status="blocked")
        return

    # Spend accumulates ACROSS attempts: the row's totals are what this unit of
    # work cost, and a retry that burns another 40k is part of that cost. It is
    # also why the budget passed to each attempt is the remainder — otherwise
    # `max_attempts` would quietly multiply `token_budget`.
    spent: list[dict] = []
    while True:
        remaining = policy.token_budget - _tokens(spent) if policy.token_budget else 0
        route = policy.model_for_attempt(attempt)
        route_token = config.route_llm_model(route) if route else None
        try:
            with collect_usage(budget=max(remaining, 0) if policy.token_budget else 0) as usage:
                try:
                    with metrics.timed("work_item_seconds", kind=kind):
                        artifacts = _in_partition(partition, lambda: fn(inputs))
                    spent.extend(usage)
                    _finish("succeeded",
                            artifacts=artifacts if isinstance(artifacts, dict) else None,
                            usage=spent)
                    metrics.inc("work_items_total", kind=kind, status="succeeded")
                    return
                except Exception as exc:  # noqa: BLE001 — outcome is the record, never a crash
                    spent.extend(usage)
                    retry = attempt < max_attempts and policy.is_retryable(exc)
                    _log.warning(
                        "work item %s (%s) attempt %s/%s failed (retry=%s): %s",
                        item_id, kind, attempt, max_attempts, retry, exc,
                    )
                    if not retry:
                        _log.exception("work item %s (%s) failed", item_id, kind)
                        _finish("failed",
                                error=f"{exc}\n{traceback.format_exc(limit=8)}", usage=spent)
                        metrics.inc("work_items_total", kind=kind, status="failed")
                        return
        finally:
            if route_token is not None:
                config.reset_llm_model_route(route_token)

        metrics.inc("work_items_total", kind=kind, status="retried")
        backoff = policy.backoff_for_attempt(attempt)
        if backoff:
            # Slept in this thread, holding a dispatcher slot (there are two).
            # A scheduler that re-queued the row instead would be the right
            # answer for minute-scale waits; it is P3's job, and until it
            # exists a policy with long backoffs starves the queue. Keep them
            # in seconds.
            time.sleep(backoff)
        attempt = _in_partition(partition, lambda: _bump_attempt(item_id))


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        partition, item_id = await _queue.get()
        try:
            await asyncio.to_thread(_execute, partition, item_id)
        except Exception:  # noqa: BLE001
            _log.exception("dispatcher worker error on item %s", item_id)
        finally:
            _queue.task_done()


def _sweep_partitions() -> list[tuple["str | None", int]]:
    """Find queued/running rows abandoned by a previous process. Running rows
    are re-run: executors must stay idempotent-ish or bounded by max_attempts."""
    import lib.config as cfg

    found: list[tuple[str | None, int]] = []

    def _scan(partition: "str | None") -> None:
        def _q() -> list[int]:
            with get_connection() as con:
                try:
                    rows = con.execute(
                        "SELECT id, attempt, max_attempts FROM work_items "
                        "WHERE status IN ('queued','running') ORDER BY id"
                    ).fetchall()
                except Exception:  # noqa: BLE001 — table may not exist yet
                    return []
                ids: list[int] = []
                for r in rows:
                    if r["attempt"] >= r["max_attempts"]:
                        con.execute(
                            "UPDATE work_items SET status='failed', "
                            "error='abandoned: attempts exhausted (process restart)', "
                            "finished_at=datetime('now') WHERE id = ?",
                            (r["id"],),
                        )
                    else:
                        ids.append(int(r["id"]))
                con.commit()
                return ids
        for item_id in _in_partition(partition, _q):
            found.append((partition, item_id))

    _scan(None)  # default partition (desktop / dev / admin)
    users_root = Path(str(cfg.DATA_FOLDER)) / "users"
    if users_root.is_dir():
        for child in sorted(users_root.iterdir()):
            if (child / "db").is_dir():
                _scan(str(child))
    return found


async def start_dispatcher() -> None:
    global _queue
    if _queue is not None:
        return
    _queue = asyncio.Queue()
    for _ in range(MAX_CONCURRENCY):
        _workers.append(asyncio.create_task(_worker_loop()))
    try:
        for partition, item_id in await asyncio.to_thread(_sweep_partitions):
            _queue.put_nowait((partition, item_id))
    except Exception:  # noqa: BLE001 — recovery is best-effort at startup
        _log.exception("work sweep failed")
    _log.info("work dispatcher started (concurrency=%d)", MAX_CONCURRENCY)


async def stop_dispatcher() -> None:
    global _queue
    for t in _workers:
        t.cancel()
    _workers.clear()
    _queue = None
