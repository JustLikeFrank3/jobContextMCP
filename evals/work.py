"""Server-side eval runs — the ``run_evals`` control-plane work kind.

The suite runs where the partition data and provider credentials already
live: inside the server process, dispatched by lib/work with the partition
context taken from the work row. Results persist to the partition
(``eval_runs/`` history + the live results store feeding eval_* gauges),
so the dashboards update with no external pusher.

Nightly automation: ``start_nightly_task`` (called from the app lifespan)
enqueues one ``run_evals`` item per day for the owner partition when
``EVALS_NIGHTLY_HOUR_UTC`` is set — giving a fixed-model drift baseline
from an always-on machine instead of whoever's workstation happens to be
awake.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from pathlib import Path

from lib import work
from lib.user_context import get_data_folder_override, reset_data_folder, set_data_folder

_log = logging.getLogger(__name__)

KIND = "run_evals"


def _partition_results_dir() -> Path:
    from lib import config  # noqa: PLC0415 — late bind: constants re-pointed at runtime

    override = get_data_folder_override()
    base = Path(str(override)) if override is not None else Path(str(config.DATA_FOLDER))
    return base / "eval_runs"


def run_evals_executor(inputs: dict) -> dict:
    """Blocking executor: run the golden suite with the configured provider."""
    from evals.golden import load_golden  # noqa: PLC0415 — heavy imports stay off app startup
    from evals.ingest import store_results  # noqa: PLC0415
    from evals.runner import run_suite  # noqa: PLC0415

    n = max(1, min(int(inputs.get("n", 5)), 10))
    entries = load_golden()
    wanted = inputs.get("entries") or []
    if wanted:
        entries = [e for e in entries if e.id in set(wanted)]
    suite = run_suite(entries=entries, n=n, results_dir=_partition_results_dir())
    payload = suite.to_dict()
    kind, scored = store_results(payload)
    errors = [e.error for e in suite.entries if e.error]
    return {
        "stored": kind,
        "entries_scored": scored,
        "n_runs": n,
        "rows": payload.get("rows", []),
        "errors": errors,
    }


work.register_kind(KIND, run_evals_executor)


def enqueue_run(n: int = 5, entries: "list[str] | None" = None, origin: str = "api") -> int:
    """Enqueue a run in the CURRENT partition context; returns the work id."""
    return work.enqueue(KIND, {"n": n, "entries": entries or []}, origin=origin)


# ── nightly schedule ──────────────────────────────────────────────────────────

def seconds_until_utc_hour(hour: int, now: "datetime.datetime | None" = None) -> float:
    """Seconds from *now* until the next HH:00 UTC (never 0; a full day when
    called exactly on the hour)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def _owner_partition() -> "str | None":
    """The owner's partition path (multi-tenant), or None (desktop/dev)."""
    from lib import config  # noqa: PLC0415

    oid = str(os.environ.get("ENTRA_OWNER_OID", "") or "").strip()
    if not oid:
        return None
    candidate = Path(str(config.DATA_FOLDER)) / "users" / oid
    return str(candidate) if candidate.is_dir() else None


def _enqueue_nightly() -> "int | None":
    """Enqueue the nightly run in the owner partition unless one is already
    queued/running there."""
    partition = _owner_partition()
    token = set_data_folder(partition) if partition else None
    try:
        pending = [
            i for i in work.list_items(limit=20)
            if i["kind"] == KIND and i["status"] in ("queued", "running")
        ]
        if pending:
            _log.info("nightly evals: run already pending (id=%s), skipping", pending[0]["id"])
            return None
        return enqueue_run(origin="nightly")
    finally:
        if token is not None:
            reset_data_folder(token)


async def _nightly_loop(hour: int) -> None:
    while True:
        await asyncio.sleep(seconds_until_utc_hour(hour))
        try:
            item_id = await asyncio.to_thread(_enqueue_nightly)
            if item_id is not None:
                _log.info("nightly evals enqueued (work id %s)", item_id)
        except Exception:  # noqa: BLE001 — the schedule must survive a bad night
            _log.exception("nightly evals enqueue failed")


def start_nightly_task() -> "asyncio.Task | None":
    """Start the nightly loop when EVALS_NIGHTLY_HOUR_UTC is set (0–23)."""
    raw = str(os.environ.get("EVALS_NIGHTLY_HOUR_UTC", "") or "").strip()
    if not raw:
        return None
    try:
        hour = int(raw)
        if not 0 <= hour <= 23:
            raise ValueError(raw)
    except ValueError:
        _log.warning("EVALS_NIGHTLY_HOUR_UTC=%r is not an hour 0-23; nightly evals disabled", raw)
        return None
    _log.info("nightly evals scheduled at %02d:00 UTC", hour)
    return asyncio.get_running_loop().create_task(_nightly_loop(hour))
