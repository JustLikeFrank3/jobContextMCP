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
    """Blocking executor: run the golden suite with the configured provider.

    A partition that has authored its own golden set (evals/tenant.py) runs
    that set; otherwise the committed owner manifest is the fallback (the
    pre-tenant behavior, still correct for the owner partition). The judge
    likewise honors the partition's stored preference when one exists —
    tenant key and model apply to THEIR runs only, never the process env.
    """
    from evals.golden import load_golden  # noqa: PLC0415 — heavy imports stay off app startup
    from evals.ingest import store_results  # noqa: PLC0415
    from evals.runner import run_suite  # noqa: PLC0415
    from evals.tenant import build_judge_fn, load_tenant_golden  # noqa: PLC0415

    n = max(1, min(int(inputs.get("n", 5)), 10))
    tenant_entries = load_tenant_golden()
    entries = tenant_entries if tenant_entries is not None else load_golden()
    wanted = inputs.get("entries") or []
    if wanted:
        entries = [e for e in entries if e.id in set(wanted)]
    if not entries:
        return {"stored": "", "entries_scored": 0, "n_runs": n, "rows": [],
                "errors": ["no golden entries to run — add entries on the Evals page first"]}
    suite = run_suite(entries=entries, n=n, judge_fn=build_judge_fn(),
                      results_dir=_partition_results_dir())
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


# What the startup sweep writes when a restart killed an in-flight item
# (lib/work._sweep_partitions). Matched by prefix so the page can translate
# the operator-facing reason into what the user needs to know: the run is
# gone, it will not resume, and provider calls before the kill may have been
# billed. The 2026-08-24 report is the motivating incident — a deploy landed
# during a 1–3 hour run and the page later read "No eval run stored yet",
# indistinguishable from the run never having existed.
_ABANDONED_PREFIX = "abandoned:"
_ABANDONED_EXPLANATION = (
    "interrupted by a server restart (usually a deploy) before it finished — "
    "no results were stored, and provider calls made before the interruption "
    "may still have been billed. Run it again."
)


def latest_run_status() -> "dict | None":
    """The most recent run_evals work item in the CURRENT partition, shaped
    for the evals page.

    A launched run must always resolve to a state the user can see: stored
    results, a visible failure, or visibly in progress. The work row already
    carries the truth (the dispatcher and startup sweep keep it durable);
    this is the read path the page was missing.
    """
    items = [i for i in work.list_items(limit=50) if i["kind"] == KIND]
    if not items:
        return None
    item = items[0]  # list_items orders by id DESC
    error = str(item.get("error") or "")
    if error.startswith(_ABANDONED_PREFIX):
        error = _ABANDONED_EXPLANATION
    return {
        "work_id": item["id"],
        "status": item["status"],
        "error": error,
        "n": int((item.get("inputs") or {}).get("n") or 0) or None,
        "created_at": item.get("created_at") or "",
        "finished_at": item.get("finished_at") or "",
    }


# ── nightly schedule ──────────────────────────────────────────────────────────

# EVALS_NIGHTLY_DAYS_UTC values, UTC weekdays (datetime.weekday(): Mon=0).
_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_run_days(raw: str) -> "set[int] | None":
    """Parse EVALS_NIGHTLY_DAYS_UTC ("mon,wed,fri" or "0,2,4"); None = daily.

    An unparseable value degrades to DAILY with a warning, not to disabled:
    the failure mode of a typo should be "the suite ran more often than
    intended", never "the drift baseline silently stopped". Disabling stays
    what it always was — unsetting EVALS_NIGHTLY_HOUR_UTC.
    """
    raw = (raw or "").strip().lower()
    if not raw:
        return None
    days: set[int] = set()
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if token[:3] in _DAY_NAMES:
            days.add(_DAY_NAMES[token[:3]])
        elif token.isdigit() and 0 <= int(token) <= 6:
            days.add(int(token))
        else:
            _log.warning(
                "EVALS_NIGHTLY_DAYS_UTC=%r has unparseable entry %r; running daily",
                raw, token,
            )
            return None
    return days or None


def runs_today(days: "set[int] | None", now: "datetime.datetime | None" = None) -> bool:
    """Whether the schedule fires on *now*'s UTC weekday (None = every day)."""
    if days is None:
        return True
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.weekday() in days


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


async def _nightly_loop(hour: int, days: "set[int] | None" = None) -> None:
    while True:
        await asyncio.sleep(seconds_until_utc_hour(hour))
        # Checked after the sleep, against the day the run would happen on —
        # a filter applied at scheduling time would use the previous day's
        # weekday when the sleep crosses midnight (it always does for a
        # morning hour).
        if not runs_today(days):
            continue
        try:
            item_id = await asyncio.to_thread(_enqueue_nightly)
            if item_id is not None:
                _log.info("nightly evals enqueued (work id %s)", item_id)
        except Exception:  # noqa: BLE001 — the schedule must survive a bad night
            _log.exception("nightly evals enqueue failed")


def start_nightly_task() -> "asyncio.Task | None":
    """Start the nightly loop when EVALS_NIGHTLY_HOUR_UTC is set (0–23).

    EVALS_NIGHTLY_DAYS_UTC ("mon,wed,fri" or "0,2,4", UTC weekdays) restricts
    which days fire; unset runs every day. Cadence is a deployment-env choice,
    not a code change: regression signal only exists when something deployed,
    and drift is slow enough that the variance math (computed WITHIN a run,
    N=5) loses nothing at a lower frequency. The wallboard staleness panel
    tolerates up to 7 days before going amber.
    """
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
    days = parse_run_days(os.environ.get("EVALS_NIGHTLY_DAYS_UTC", ""))
    _log.info(
        "nightly evals scheduled at %02d:00 UTC (days=%s)",
        hour, "daily" if days is None else sorted(days),
    )
    return asyncio.get_running_loop().create_task(_nightly_loop(hour, days))
