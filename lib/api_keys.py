"""
lib/api_keys.py — Per-user API key management for programmatic access.

Keys are stored as SHA-256 hashes in the GLOBAL database so they can be looked
up during authentication before the per-request user context is established.
The plaintext key is shown only once at generation time and never stored.

Key format: jcmcp_<32 url-safe random chars>
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import NamedTuple

import lib.db as _db

_PREFIX = "jcmcp_"
_KEY_BODY_BYTES = 24  # 24 random bytes → 32 url-safe base64 chars (no padding)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash(token: str) -> str:
    """Return the SHA-256 hex digest of the token string."""
    return hashlib.sha256(token.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _global_conn():
    """Context manager that always opens the global (non-tenant) database."""
    return _db.get_connection(path=_db.global_db_path())


# ── Public API ─────────────────────────────────────────────────────────────────

class ApiKeyInfo(NamedTuple):
    id: int
    label: str
    created_at: str
    last_used_at: str | None


def create_key(oid: str, label: str = "") -> tuple[int, str]:
    """Generate a new API key for *oid*.

    Returns ``(key_id, plaintext)`` where *plaintext* is the full
    ``jcmcp_…`` token.  The plaintext is NOT stored — callers must
    surface it to the user immediately and never again.
    """
    plaintext = _PREFIX + secrets.token_urlsafe(_KEY_BODY_BYTES)
    key_hash = _hash(plaintext)
    with _global_conn() as con:
        cur = con.execute(
            "INSERT INTO user_api_keys (key_hash, oid, label, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key_hash, oid, label or "", _now_iso()),
        )
        key_id: int = cur.lastrowid  # type: ignore[assignment]
    return key_id, plaintext


def lookup_key(token: str) -> str | None:
    """Return the OID associated with *token*, or ``None`` if invalid/revoked.

    Also updates ``last_used_at`` on a successful lookup.
    """
    if not token.startswith(_PREFIX):
        return None
    key_hash = _hash(token)
    with _global_conn() as con:
        row = con.execute(
            "SELECT id, oid FROM user_api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if row is None:
            return None
        con.execute(
            "UPDATE user_api_keys SET last_used_at = ? WHERE id = ?",
            (_now_iso(), row["id"]),
        )
    return row["oid"]


def list_keys(oid: str) -> list[ApiKeyInfo]:
    """Return all non-revoked API keys for *oid*.

    The ``key_hash`` is never included in the returned data.
    """
    with _global_conn() as con:
        rows = con.execute(
            "SELECT id, label, created_at, last_used_at "
            "FROM user_api_keys WHERE oid = ? ORDER BY created_at DESC",
            (oid,),
        ).fetchall()
    return [
        ApiKeyInfo(
            id=r["id"],
            label=r["label"] or "",
            created_at=r["created_at"],
            last_used_at=r["last_used_at"],
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
