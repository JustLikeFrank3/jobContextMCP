"""Control-plane wiring for weekly certification snapshots.

Kind ``certification.weekly``: runs Sunday morning (UTC) after the
certification week closes, generates the frozen weekly report for the
just-closed week, and surfaces it via the Home card and daily digest.
Zero-touch by default — the user opens a finished report and exports.

The loop itself is a no-op until certification is configured (a saved
state_profile or a prior report), so unconfigured workspaces pay nothing.
Opt out entirely with CERTIFICATION_WEEKLY=0; override the fire hour with
CERTIFICATION_WEEKLY_HOUR_UTC (default 12).
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from pathlib import Path

from lib import config, work
from lib.user_context import reset_data_folder, set_data_folder

_log = logging.getLogger(__name__)

KIND = "certification.weekly"

_DEFAULT_HOUR_UTC = 12
_FIRE_WEEKDAY = 6  # Sunday — the morning after a Saturday week close


def certification_weekly_executor(inputs: dict) -> dict:
    """Generate the frozen report for the most recently closed week."""
    from tools import certification  # noqa: PLC0415 — keep startup cheap

    if not certification.is_configured():
        return {"skipped": "certification not configured"}

    profile = certification.get_state_profile()
    week_ending = str(inputs.get("week_ending", "") or "")
    if not week_ending:
        end = certification._week_ending_date(profile)  # most recent close
        week_ending = end.isoformat() if not isinstance(end, str) else ""
    if not week_ending:
        return {"skipped": "could not resolve week_ending"}

    from lib.db import get_connection  # noqa: PLC0415

    with get_connection() as con:
        row = con.execute(
            "SELECT id FROM certification_report WHERE week_ending = ? LIMIT 1",
            (week_ending,),
        ).fetchone()
    if row is not None:
        return {"skipped": f"report for {week_ending} already exists", "report_id": row[0]}

    summary = certification.weekly_certification_report(week_ending=week_ending)
    return {"week_ending": week_ending, "summary": summary[:2000]}


work.register_kind(KIND, certification_weekly_executor)


def enqueue_weekly(week_ending: str = "", origin: str = "schedule") -> int:
    return work.enqueue(KIND, {"week_ending": week_ending}, origin=origin)


def seconds_until_utc_weekday_hour(weekday: int, hour: int, now=None) -> float:
    """Seconds until the next occurrence of (weekday, hour:00) UTC."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    days_ahead = (weekday - target.weekday()) % 7
    target += datetime.timedelta(days=days_ahead)
    if target <= now:
        target += datetime.timedelta(days=7)
    return (target - now).total_seconds()


def _owner_partition() -> "str | None":
    oid = str(os.environ.get("ENTRA_OWNER_OID", "") or "").strip()
    if not oid:
        return None
    candidate = Path(str(config.DATA_FOLDER)) / "users" / oid
    return str(candidate) if candidate.is_dir() else None


def _enqueue_weekly() -> "int | None":
    partition = _owner_partition()
    token = set_data_folder(partition) if partition else None
    try:
        from tools import certification  # noqa: PLC0415

        if not certification.is_configured():
            _log.info("weekly certification: not configured, skipping")
            return None
        pending = [
            i for i in work.list_items(limit=20)
            if i["kind"] == KIND and i["status"] in ("queued", "running")
        ]
        if pending:
            _log.info(
                "weekly certification: run already pending (id=%s), skipping",
                pending[0]["id"],
            )
            return None
        return enqueue_weekly()
    finally:
        if token is not None:
            reset_data_folder(token)


async def _weekly_loop(hour: int) -> None:
    while True:
        await asyncio.sleep(seconds_until_utc_weekday_hour(_FIRE_WEEKDAY, hour))
        try:
            item_id = await asyncio.to_thread(_enqueue_weekly)
            if item_id is not None:
                _log.info("weekly certification enqueued (work item %s)", item_id)
        except Exception:  # noqa: BLE001 — the schedule must survive a bad week
            _log.exception("weekly certification enqueue failed")


def start_weekly_task() -> "asyncio.Task | None":
    """Start the Sunday-morning loop unless explicitly disabled."""
    if str(os.environ.get("CERTIFICATION_WEEKLY", "") or "").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return None
    raw = str(os.environ.get("CERTIFICATION_WEEKLY_HOUR_UTC", "") or "").strip()
    hour = _DEFAULT_HOUR_UTC
    if raw:
        try:
            hour = int(raw)
        except ValueError:
            _log.warning("CERTIFICATION_WEEKLY_HOUR_UTC=%r is not an int; using %s", raw, _DEFAULT_HOUR_UTC)
            hour = _DEFAULT_HOUR_UTC
    if not 0 <= hour <= 23:
        _log.warning("CERTIFICATION_WEEKLY_HOUR_UTC=%s out of range; using %s", hour, _DEFAULT_HOUR_UTC)
        hour = _DEFAULT_HOUR_UTC
    return asyncio.get_running_loop().create_task(_weekly_loop(hour))
