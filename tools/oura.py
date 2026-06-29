"""tools/oura.py — Oura Ring readiness data integration.

Stores daily readiness snapshots in SQLite per user.  The dashboard home
page reads the most recent row to drive the Readiness + Pipeline hero card.

Tools exposed to MCP
--------------------
  log_oura_readiness(date?, readiness_score, sleep_score, hrv, recovery_index, raw_json?)
      Upserts today's (or a named date's) readiness data.  Call this once per
      day, or pass raw_json to store the full Oura API payload for later use.

  get_oura_readiness(days?)
      Returns the last N days of readiness records as a formatted string.
"""
from __future__ import annotations

import datetime
import json

from lib.db import get_connection
from lib.user_context import get_current_user_oid


# ── helpers ────────────────────────────────────────────────────────────────────
def _readiness_label(score: int) -> str:
    """Map a readiness score to its High / Good / Low band label."""
    if score >= 85:
        return "High"
    if score >= 70:
        return "Good"
    return "Low"

def _latest_oura_row() -> "dict | None":
    """Return the most recent oura_readiness row for the current user, or None.

    Always scoped to the current OID. In local/dev or API-key sessions the OID
    is the empty string, and rows are written with that same empty OID, so a
    WHERE oid = '' match still returns the local user's own data. On a shared
    database this guarantees an OID-less session can never read another user's
    rows (their rows carry a real OID, not '').
    """
    oid = get_current_user_oid()
    try:
        with get_connection() as con:
            row = con.execute(
                "SELECT date, readiness_score, sleep_score, hrv, recovery_index "
                "FROM oura_readiness WHERE oid = ? "
                "ORDER BY date DESC LIMIT 1",
                (oid,),
            ).fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    return None


# ── MCP tools ─────────────────────────────────────────────────────────────────

def log_oura_readiness(
    readiness_score: int,
    sleep_score: int,
    hrv: int,
    recovery_index: int,
    date: str = "",
    raw_json: str = "",
) -> str:
    """Log or update a daily Oura Ring readiness snapshot to SQLite.

    Call once per day (or whenever the Oura app syncs) with today's scores.
    Re-logging the same date overwrites the previous entry.

    Parameters
    ----------
    readiness_score : Oura readiness score 0-100.
    sleep_score     : Oura sleep score 0-100.
    hrv             : Heart rate variability in ms (rMSSD).
    recovery_index  : Oura recovery index 0-100.
    date            : ISO date string (YYYY-MM-DD). Defaults to today.
    raw_json        : Optional full Oura API response payload as a JSON string.
    """
    log_date = date or datetime.date.today().isoformat()
    oid = get_current_user_oid()

    with get_connection() as con:
        con.execute(
            """INSERT INTO oura_readiness
                   (oid, date, readiness_score, sleep_score, hrv, recovery_index, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(oid, date) DO UPDATE SET
                   readiness_score = excluded.readiness_score,
                   sleep_score     = excluded.sleep_score,
                   hrv             = excluded.hrv,
                   recovery_index  = excluded.recovery_index,
                   raw_json        = excluded.raw_json""",
            (oid, log_date, readiness_score, sleep_score, hrv, recovery_index, raw_json or None),
        )

    _label = _readiness_label(readiness_score)
    return (
        f"Oura readiness logged for {log_date}.\n"
        f"  Readiness: {readiness_score} ({_label})\n"
        f"  Sleep:     {sleep_score}\n"
        f"  HRV:       {hrv} ms\n"
        f"  Recovery:  {recovery_index}"
    )


def get_oura_readiness(days: int = 7) -> str:
    """Return recent Oura readiness records for the current user.

    Parameters
    ----------
    days : Number of days of history to return (default 7, max 90).
    """
    days = min(max(1, days), 90)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    oid = get_current_user_oid()

    try:
        with get_connection() as con:
            rows = con.execute(
                "SELECT date, readiness_score, sleep_score, hrv, recovery_index "
                "FROM oura_readiness WHERE oid = ? AND date >= ? "
                "ORDER BY date DESC",
                (oid, cutoff),
            ).fetchall()
    except Exception as exc:
        return f"Error reading oura_readiness: {exc}"

    if not rows:
        return f"No Oura data logged in the past {days} days. Use log_oura_readiness() to add entries."

    lines = [f"═══ OURA READINESS (last {days} days) ═══", ""]
    for r in rows:
        score = r["readiness_score"] or 0
        label = _readiness_label(score)
        lines.append(
            f"{r['date']}  Readiness {score:3d} ({label:<4})  "
            f"Sleep {r['sleep_score'] or '--':>3}  "
            f"HRV {r['hrv'] or '--':>3} ms  "
            f"Recovery {r['recovery_index'] or '--':>3}"
        )
    return "\n".join(lines)


# ── registration ───────────────────────────────────────────────────────────────

def register(mcp) -> None:
    mcp.tool()(log_oura_readiness)
    mcp.tool()(get_oura_readiness)
