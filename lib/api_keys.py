"""
lib/api_keys.py — Per-user API key management for programmatic access.

Keys are stored as SHA-256 hashes in the GLOBAL database so they can be looked
up during authentication before the per-request user context is established.
The plaintext key is shown only once at generation time and never stored.

Key format: jcmcp_<32 url-safe random chars>

Scopes
------
A key carries a *scope* that bounds what it can reach:

  SCOPE_FULL  ("full")   — the whole tenant API, as every key did before
                           scopes existed.  The default.
  SCOPE_BADGE ("badge")  — the conference-badge surface only (/api/badge/*):
                           search, enqueue a materials job, poll that job.

The badge scope exists because the hardware it lives on is not a secret.
Double-tapping reset on a Universe badge mounts it as a USB drive with its
``secrets.py`` in plain text, so a badge token is one careless hand-off away
from being public.  Scope enforcement is applied at the auth choke point
(transport/http/app.py middleware + require_authenticated_user), not here —
this module only records and reports what a key is allowed to be.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import NamedTuple

import lib.db as _db

_PREFIX = "jcmcp_"
_KEY_BODY_BYTES = 24  # 24 random bytes → 32 url-safe base64 chars (no padding)

SCOPE_FULL = "full"
SCOPE_BADGE = "badge"
VALID_SCOPES = (SCOPE_FULL, SCOPE_BADGE)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash(token: str) -> str:
    """Return the SHA-256 hex digest of the token string."""
    return hashlib.sha256(token.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _global_conn():
    """Context manager that always opens the global (non-tenant) database."""
    return _db.get_connection(path=_db.global_db_path(), is_global=True)


def _ensure_scope_column(con) -> None:
    """Add user_api_keys.scope if this database predates scopes.

    Deliberately NOT a _MIGRATIONS entry: _apply_migrations skips every
    statement containing "ALTER TABLE" when running against the global DB
    (it assumes ALTERs target per-user tables like job_queue), and
    user_api_keys is global — so a migration-list ALTER would be ledgered
    as applied without ever running.  Doing it here, lib/work.py style,
    keeps the column guaranteed present at the point of use.
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(user_api_keys)").fetchall()}
    if cols and "scope" not in cols:
        con.execute(
            f"ALTER TABLE user_api_keys ADD COLUMN scope TEXT NOT NULL DEFAULT '{SCOPE_FULL}'"
        )


# ── Public API ─────────────────────────────────────────────────────────────────

class ApiKeyInfo(NamedTuple):
    id: int
    label: str
    created_at: str
    last_used_at: str | None
    scope: str = SCOPE_FULL


class ResolvedKey(NamedTuple):
    """What authentication needs to know about a presented token."""
    oid: str
    scope: str


def create_key(oid: str, label: str = "", scope: str = SCOPE_FULL) -> tuple[int, str]:
    """Generate a new API key for *oid*.

    Returns ``(key_id, plaintext)`` where *plaintext* is the full
    ``jcmcp_…`` token.  The plaintext is NOT stored — callers must
    surface it to the user immediately and never again.

    *scope* must be one of VALID_SCOPES; an unknown scope is a programming
    error and raises rather than quietly minting a key with more reach than
    the caller asked for.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"unknown API key scope: {scope!r}")
    plaintext = _PREFIX + secrets.token_urlsafe(_KEY_BODY_BYTES)
    key_hash = _hash(plaintext)
    with _global_conn() as con:
        _ensure_scope_column(con)
        cur = con.execute(
            "INSERT INTO user_api_keys (key_hash, oid, label, created_at, scope) "
            "VALUES (?, ?, ?, ?, ?)",
            (key_hash, oid, label or "", _now_iso(), scope),
        )
        key_id: int = cur.lastrowid  # type: ignore[assignment]
    return key_id, plaintext


def resolve_key(token: str) -> ResolvedKey | None:
    """Return the OID + scope for *token*, or ``None`` if invalid/revoked.

    Also updates ``last_used_at`` on a successful lookup.
    """
    if not token.startswith(_PREFIX):
        return None
    key_hash = _hash(token)
    with _global_conn() as con:
        _ensure_scope_column(con)
        row = con.execute(
            "SELECT id, oid, scope FROM user_api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if row is None:
            return None
        con.execute(
            "UPDATE user_api_keys SET last_used_at = ? WHERE id = ?",
            (_now_iso(), row["id"]),
        )
    # A row written before scopes existed carries NULL — treat as full, which
    # is what it has always been able to do.
    return ResolvedKey(oid=row["oid"], scope=row["scope"] or SCOPE_FULL)


def lookup_key(token: str) -> str | None:
    """Return the OID associated with *token*, or ``None`` if invalid/revoked.

    Scope-blind; kept for callers that only need identity.  Anything making
    an authorization decision must use resolve_key() instead.
    """
    resolved = resolve_key(token)
    return resolved.oid if resolved else None


def list_keys(oid: str) -> list[ApiKeyInfo]:
    """Return all non-revoked API keys for *oid*.

    The ``key_hash`` is never included in the returned data.
    """
    with _global_conn() as con:
        _ensure_scope_column(con)
        rows = con.execute(
            "SELECT id, label, created_at, last_used_at, scope "
            "FROM user_api_keys WHERE oid = ? ORDER BY created_at DESC",
            (oid,),
        ).fetchall()
    return [
        ApiKeyInfo(
            id=r["id"],
            label=r["label"] or "",
            created_at=r["created_at"],
            last_used_at=r["last_used_at"],
            scope=r["scope"] or SCOPE_FULL,
        )
        for r in rows
    ]


def revoke_key(key_id: int, oid: str) -> bool:
    """Delete the key with *key_id* if it belongs to *oid*.

    Returns ``True`` if a row was deleted, ``False`` if not found / wrong owner.
    """
    with _global_conn() as con:
        cur = con.execute(
            "DELETE FROM user_api_keys WHERE id = ? AND oid = ?",
            (key_id, oid),
        )
    return cur.rowcount > 0
