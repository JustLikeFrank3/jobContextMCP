"""Per-request data folder isolation via contextvars.

Sets an override data folder on each authenticated HTTP request so that all
lib.io._load_json / _save_json and lib.db.get_connection() calls within that
request transparently read/write the requesting user's own data partition,
not the global /app/data/ directory.

Usage (handled automatically by UserDataContextMiddleware in transport/http/app.py):

    from lib.user_context import set_data_folder, reset_data_folder

    token = set_data_folder("/app/data/users/{oid}")
    try:
        ...  # all I/O within this call uses user's folder
    finally:
        reset_data_folder(token)

The feature is gated by the ENTRA_OWNER_OID env var.  When that var is not
set the middleware is a no-op and the existing single-user behaviour is
preserved — making it safe to deploy the code before wiring up the env var.
"""
from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

# Holds the absolute path of the current request's data folder override.
# Empty string means "no override — use the global lib.config.DATA_FOLDER".
_DATA_FOLDER_CTX: ContextVar[str] = ContextVar("data_folder_ctx", default="")


def get_data_folder_override() -> Path | None:
    """Return the active per-request data folder, or None to use the global default."""
    val = _DATA_FOLDER_CTX.get()
    return Path(val) if val else None


def set_data_folder(path: str | Path) -> object:
    """Activate a per-request data folder override.  Returns a reset token."""
    return _DATA_FOLDER_CTX.set(str(path))


def reset_data_folder(token: object) -> None:
    """Restore the previous context value using the token from set_data_folder()."""
    _DATA_FOLDER_CTX.reset(token)  # type: ignore[arg-type]
