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
import logging
import sqlite3

import lib.config as _cfg


_logger = logging.getLogger(__name__)


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
_DB_FILENAME = "jobcontextmcp.db"


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
    return Path(str(_cfg.DATA_FOLDER)) / "db" / _DB_FILENAME


def global_db_path() -> Path:
    """Always return the GLOBAL database path regardless of per-request user context.

    Use this for tables that must be queryable before a user is identified
    (e.g. user_api_keys lookup during auth).
    """
    return Path(str(_cfg.DATA_FOLDER)) / "db" / _DB_FILENAME


# ── Schema migrations ──────────────────────────────────────────────────────────
# Applied lazily on first connection to ensure existing DBs stay up to date
# without requiring a full migration script re-run.
_MIGRATIONS = [
    # v1 — per-user API keys for programmatic access (iOS Shortcuts, CLI tools)
    """CREATE TABLE IF NOT EXISTS user_api_keys (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        key_hash     TEXT    NOT NULL UNIQUE,
        oid          TEXT    NOT NULL,
        label        TEXT,
        created_at   TEXT    NOT NULL,
        last_used_at TEXT
    )""",
    # v2 — resume template + style selection per job card
    "ALTER TABLE job_queue ADD COLUMN resume_template TEXT",
    "ALTER TABLE job_queue ADD COLUMN resume_style TEXT",
    # v3 — cover letter template + style selection per job card
    "ALTER TABLE job_queue ADD COLUMN cl_template TEXT",
    "ALTER TABLE job_queue ADD COLUMN cl_style TEXT",
    # v4 — Oura Ring readiness data (per-user biometric integration)
    """CREATE TABLE IF NOT EXISTS oura_readiness (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        oid              TEXT    NOT NULL DEFAULT '',
        date             TEXT    NOT NULL,
        readiness_score  INTEGER,
        sleep_score      INTEGER,
        hrv              INTEGER,
        recovery_index   INTEGER,
        raw_json         TEXT,
        created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE(oid, date)
    )""",
    # v5 — Oura OAuth tokens (one row per user; populated by the connect flow).
    # Tokens live in the per-OID isolated DB, consistent with how the OpenAI
    # key is stored in each user's config.json. The access token is refreshed
    # in place via the refresh token when it expires.
    """CREATE TABLE IF NOT EXISTS oura_tokens (
        oid           TEXT    PRIMARY KEY,
        access_token  TEXT    NOT NULL,
        refresh_token TEXT    NOT NULL,
        expires_at    TEXT    NOT NULL,
        scope         TEXT,
        last_sync_at  TEXT,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    )""",
    # v6 — embedded chat (desktop Phase 5.5): conversations + messages.
    # Messages mirror the OpenAI chat shape so history rebuilds losslessly:
    # role ∈ user/assistant/tool; assistant rows may carry tool_calls JSON;
    # tool rows carry the tool_call_id + tool name they answer.
    """CREATE TABLE IF NOT EXISTS chat_sessions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        title      TEXT    NOT NULL DEFAULT '',
        created_at TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS chat_messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id   INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        role         TEXT    NOT NULL CHECK (role IN ('user','assistant','tool')),
        content      TEXT    NOT NULL DEFAULT '',
        tool_calls   TEXT,
        tool_call_id TEXT,
        tool_name    TEXT,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    )""",
    # v7 — generation provenance (lib/provenance.py): one row per pipeline
    # run recording which numeric claims the draft made, which source chunks
    # fed it, and whether the deterministic gate passed. The gate's verdict
    # trail — a rejected-then-regenerated document shows its own history.
    """CREATE TABLE IF NOT EXISTS generation_provenance (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT    NOT NULL,
        kind         TEXT    NOT NULL,
        company      TEXT    NOT NULL DEFAULT '',
        role         TEXT    NOT NULL DEFAULT '',
        jd_hash      TEXT    NOT NULL DEFAULT '',
        chunk_hashes TEXT    NOT NULL DEFAULT '[]',
        claims       TEXT    NOT NULL DEFAULT '[]',
        violations   TEXT    NOT NULL DEFAULT '[]',
        verdict      TEXT    NOT NULL,
        revisions    INTEGER NOT NULL DEFAULT 0
    )""",
]


# Substrings of sqlite3.OperationalError messages that are safe to ignore, but
# ONLY for the known-fragile ALTER TABLE job_queue migrations (see the guard in
# _apply_migrations). These occur when an ALTER targets job_queue before it has
# been created out-of-band by the SQLite seeder ("no such table") or a column
# that was already added by the seeder ("duplicate column name"). Scoping the
# tolerance to job_queue ALTERs keeps later migrations (e.g. the Oura tables)
# from being blocked on partially-provisioned DBs, while ensuring an unrelated
# broken migration (e.g. a typoed CREATE TABLE) still fails loudly instead of
# being silently marked applied.
_TOLERABLE_MIGRATION_ERRORS = ("duplicate column name", "no such table")


def _ledger_migration(con: sqlite3.Connection) -> None:
    """Record one migration as applied in the version ledger."""
    con.execute(
        "INSERT INTO applied_migrations (applied_at) VALUES (datetime('now'))"
    )


def _apply_migrations(con: sqlite3.Connection, is_global: bool = False) -> None:
    """Run any _MIGRATIONS statements that haven't been applied yet.

    Uses a simple applied_migrations table as a version ledger.
    Idempotent — safe to call on every connection open.

    Robustness: a single migration that fails with a tolerable error
    (missing target table for an ALTER, or a column that already exists) is
    logged and recorded as applied so the chain advances. This prevents an
    early fragile ALTER from permanently blocking later CREATE TABLE
    migrations (e.g. oura_readiness) on partially-provisioned databases.

    When *is_global* is True, only migrations that are safe for the global DB
    (i.e. don't reference per-user tables like job_queue) are applied.
    """
    con.execute(
        "CREATE TABLE IF NOT EXISTS applied_migrations "
        "(id INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = con.execute("SELECT COUNT(*) FROM applied_migrations").fetchone()[0]
    for i, sql in enumerate(_MIGRATIONS):
        if i < applied:
            continue
        # Skip per-user table migrations when running on the global DB
        if is_global and ("job_queue" in sql or "ALTER TABLE" in sql):
            _ledger_migration(con)
            continue
        try:
            con.execute(sql)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            # Only tolerate the known-fragile job_queue ALTERs; any other
            # migration failing with the same message is a real bug and must
            # abort so it isn't silently marked applied.
            is_job_queue_alter = "alter table job_queue" in sql.lower()
            if is_job_queue_alter and any(tol in msg for tol in _TOLERABLE_MIGRATION_ERRORS):
                _logger.warning(
                    "migration %d tolerated (%s): %s",
                    i, exc, sql.strip().splitlines()[0][:70],
                )
            else:
                raise
        _ledger_migration(con)
    # Sync journal + triggers (idempotent CREATE IF NOT EXISTS; owns its own
    # DDL in lib/sync.py so table specs and triggers stay colocated). Not
    # applicable to the global DB, which has none of the synced tables.
    if not is_global:
        from lib.sync import ensure_sync_schema

        ensure_sync_schema(con)
    con.commit()


@contextmanager
def get_connection(path: Path | None = None, is_global: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """
    Yield an open sqlite3 Connection with WAL mode and foreign keys enabled.

    Commits on clean exit, rolls back on exception.

    Parameters
    ----------
    path      : override the default db_path() — useful for tests pointing at data_dev/.
                When omitted, the per-request user context (lib.user_context) is
                checked first, then db_path() is used as the final fallback.
    is_global : when True, skip per-user table migrations (e.g. ALTER TABLE job_queue)
                that don't exist in the shared global DB.
    """
    if path is not None:
        resolved = path
    else:
        from lib.user_context import get_data_folder_override
        override = get_data_folder_override()
        resolved = (override / "db" / _DB_FILENAME) if override else db_path()
    # Ensure the directory exists (first run, new tenant, or global DB on fresh deploy)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    # Apply any pending schema migrations (idempotent, cheap when up to date).
    _apply_migrations(con, is_global=is_global)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
