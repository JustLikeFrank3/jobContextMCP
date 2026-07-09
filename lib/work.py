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
import traceback
from pathlib import Path
from typing import Any, Callable

from lib.db import get_connection
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


def _ensure_schema() -> None:
    """Create work_items in the current partition's DB (idempotent)."""
    with get_connection() as con:
        con.execute(_SCHEMA)
        con.commit()


# ── enqueue / read (run inside a request's partition context) ─────────────────

def enqueue(kind: str, inputs: dict, origin: str = "", max_attempts: int = 1) -> int:
    """Insert a queued row in the CURRENT partition and wake the dispatcher."""
    if kind not in _KINDS:
        raise ValueError(f"unknown work kind: {kind}")
    _ensure_schema()
    with get_connection() as con:
        cur = con.execute(
            "INSERT INTO work_items (kind, inputs_json, origin, max_attempts) "
            "VALUES (?, ?, ?, ?)",
            (kind, json.dumps(inputs), origin, max(1, max_attempts)),
        )
        con.commit()
        item_id = int(cur.lastrowid)
    _notify(get_data_folder_override(), item_id)
    return item_id


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["inputs"] = json.loads(d.pop("inputs_json") or "{}")
    d["artifacts"] = json.loads(d.pop("artifacts_json") or "null")
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


def _execute(partition: "str | None", item_id: int) -> None:
    """Blocking: claim, run the kind's executor, persist the outcome."""
    def _claim() -> "tuple[str, dict] | None":
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
            return row["kind"], json.loads(row["inputs_json"] or "{}")

    claimed = _in_partition(partition, _claim)
    if claimed is None:
        return
    kind, inputs = claimed
    fn = _KINDS.get(kind)

    def _finish(status: str, error: str = "", artifacts: "dict | None" = None) -> None:
        def _write() -> None:
            with get_connection() as con:
                con.execute(
                    "UPDATE work_items SET status=?, error=?, artifacts_json=?, "
                    "finished_at=datetime('now') WHERE id = ?",
                    (status, error or None,
                     json.dumps(artifacts) if artifacts is not None else None, item_id),
                )
                con.commit()
        _in_partition(partition, _write)

    if fn is None:
        _finish("failed", error=f"no executor registered for kind '{kind}'")
        return
    try:
        artifacts = _in_partition(partition, lambda: fn(inputs))
        _finish("succeeded", artifacts=artifacts if isinstance(artifacts, dict) else None)
    except Exception as exc:  # noqa: BLE001 — outcome is the record, never a crash
        _log.exception("work item %s (%s) failed", item_id, kind)
        _finish("failed", error=f"{exc}\n{traceback.format_exc(limit=8)}")


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
