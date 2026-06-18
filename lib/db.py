"""
lib/db.py — SQLite connection helper for jobContextMCP.

Usage
-----
    from lib.db import get_connection

    with get_connection() as con:
        row = con.execute("SELECT * FROM applications WHERE id = ?", (1,)).fetchone()
        print(dict(row))

The context manager commits on clean exit and rolls back on any exception.
All rows are returned as sqlite3.Row objects (subscriptable by name).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator
import sqlite3

import lib.config as _cfg


# ── Canonical event type registry ─────────────────────────────────────────────
# Single source of truth for application event codes.
# Keys   = anything that may appear in historical JSON data.
# Values = the canonical code stored in SQLite (and used for new writes).

EVENT_TYPE_MAP: dict[str, str] = {
    # application submission
    "applied":                    "applied",
    "resume_submitted":           "applied",

    # Frank sent first contact
    "outreach":                   "outreach_sent",
    "outreach_sent":              "outreach_sent",
    "network_outreach":           "outreach_sent",
    "recruiter_outreach":         "outreach_sent",
    "outreach_plan_updated":      "outreach_sent",

    # Frank sent a follow-up (not first contact)
    "follow_up":                  "follow_up_sent",
    "follow_up_sent":             "follow_up_sent",
    "referral_update_sent":       "follow_up_sent",

    # inbound reply received
    "reply_received":             "reply_received",
    "recruiter_reply":            "reply_received",
    "referral_reply":             "reply_received",

    # Frank sent a reply
    "reply_sent":                 "reply_sent",

    # recruiter / HR interaction
    "recruiter_contact":          "recruiter_contact",
    "recruiter_inbound":          "recruiter_contact",
    "recruiter_call":             "recruiter_contact",
    "recruiter_reengaged":        "recruiter_contact",
    "recruiter_update":           "recruiter_contact",
    "hr_update":                  "recruiter_contact",

    # phone / video screen
    "phone_screen":               "phone_screen",
    "recruiter_screen_scheduled": "phone_screen",
    "recruiter_screen_completed": "phone_screen",

    # interview lifecycle
    "interview_scheduled":        "interview_scheduled",
    "meeting_scheduled":          "interview_scheduled",
    "onsite":                     "interview_completed",

    # referral lifecycle
    "referral_path_identified":   "referral_identified",
    "referral_path_confirmed":    "referral_confirmed",
    "referral_confirmed":         "referral_confirmed",
    "referral_submitted":         "referral_submitted",

    # rejection
    "rejection":                  "rejected",
    "rejection_received":         "rejected",
    "rejected":                   "rejected",
    "screened_out":               "rejected",

    # hiring manager interaction
    "hiring_manager_contact":     "hiring_manager_contact",

    # general note / intel / misc
    "note":                       "note",
    "logistics":                  "note",
    "intel":                      "note",
    "signal":                     "note",
    "peer_call":                  "note",

    # contact data updated
    "contact_update":             "contact_update",
}

# Ordered tuple used in the DDL CHECK constraint — keep in sync with map values.
EVENT_TYPE_CANONICAL: tuple[str, ...] = tuple(sorted(set(EVENT_TYPE_MAP.values())))


def normalize_event_type(raw: str) -> str:
    """
    Map a raw event type string to its canonical code.

    Unknown types fall back to 'note' so the INSERT never violates the CHECK
    constraint, but the original value is preserved in the raw_type column.
    """
    return EVENT_TYPE_MAP.get(raw, "note")


# ── Connection helper ──────────────────────────────────────────────────────────

def db_path() -> Path:
    """Return the path to the SQLite database, derived from config DATA_FOLDER."""
    return Path(str(_cfg.DATA_FOLDER)) / "jobcontextmcp.db"


@contextmanager
def get_connection(path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Yield an open sqlite3 Connection with WAL mode and foreign keys enabled.

    Commits on clean exit, rolls back on exception.

    Parameters
    ----------
    path : override the default db_path() — useful for tests pointing at data_dev/.
           When omitted, the per-request user context (lib.user_context) is
           checked first, then db_path() is used as the final fallback.
    """
    if path is not None:
        resolved = path
    else:
        from lib.user_context import get_data_folder_override
        override = get_data_folder_override()
        resolved = (override / "jobcontextmcp.db") if override else db_path()
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
