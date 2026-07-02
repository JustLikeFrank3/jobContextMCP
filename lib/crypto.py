"""Application-level encryption for secrets at rest.

Protects sensitive per-user values (OAuth access/refresh tokens, and any other
secret a tool chooses to wrap) before they are written to the per-user SQLite
DB. The encryption key is app-wide infrastructure: it lives only in the k8s
secret / Key Vault (env ``APP_ENCRYPTION_KEY``), never inside user data. This
gives application-level confidentiality on top of Azure's disk/blob
encryption-at-rest, so a leaked backup or DB file does not expose live tokens.

Design
------
* Algorithm: Fernet (AES-128-CBC + HMAC-SHA256), via the ``cryptography`` lib.
* Storage format: ciphertext is prefixed with ``enc:v1:`` so reads can tell
  encrypted values from legacy plaintext and migrate transparently on the next
  write. The version segment lets us rotate schemes later without ambiguity.
* Graceful degradation: when no key is configured (local dev), encryption is a
  no-op and values are stored as-is, matching the prior behaviour with zero
  breakage. Legacy plaintext (no prefix) is always returned unchanged on read.

Usage
-----
    from lib.crypto import encrypt_secret, decrypt_secret

    db_value = encrypt_secret(access_token)   # write path
    token    = decrypt_secret(db_value)       # read path
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

# Marker prepended to encrypted values. Reads use it to distinguish ciphertext
# from legacy plaintext; the version segment allows future scheme changes.
_PREFIX = "enc:v1:"


def _load_key() -> str:
    """Return the configured encryption key, or '' when none is set.

    Resolution order: APP_ENCRYPTION_KEY env var, then config.json
    ``app_encryption_key`` (via lib.config). Read fresh each call so tests and
    runtime config reloads are reflected without a stale module cache.
    """
    key = os.environ.get("APP_ENCRYPTION_KEY", "")
    if key:
        return key
    try:  # lazy import — avoids a hard dependency / import cycle at module load
        from lib import config

        return getattr(config, "APP_ENCRYPTION_KEY", "") or getattr(
            config, "_cfg", {}
        ).get("app_encryption_key", "")
    except Exception:  # pragma: no cover - config not importable
        return ""


def _fernet():
    """Build a Fernet instance from the configured key, or None when unset.

    Returns None (encryption disabled) both when no key is configured and when
    a configured key is malformed — the latter is logged so it is diagnosable
    without crashing the request path.
    """
    key = _load_key()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception:  # invalid key length/format
        _log.exception("APP_ENCRYPTION_KEY is set but invalid; storing in cleartext")
        return None


def encryption_enabled() -> bool:
    """True when a valid encryption key is configured."""
    return _fernet() is not None


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage.

    No-op for empty input or when no key is configured (returns the value
    unchanged). Idempotent: an already-encrypted value is returned as-is rather
    than double-wrapped.
    """
    if not plaintext or plaintext.startswith(_PREFIX):
        return plaintext
    fernet = _fernet()
    if fernet is None:
        return plaintext  # local dev / key unset: prior plaintext behaviour
    token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt_secret(value: str) -> str:
    """Decrypt a stored secret.

    Legacy plaintext (no ``enc:v1:`` prefix) and empty values are returned
    unchanged, so the read path works before, during, and after migration.
    Raises when a value is marked encrypted but cannot be decrypted (missing or
    wrong key), so callers fail closed rather than treating ciphertext as a
    valid secret.
    """
    if not value or not value.startswith(_PREFIX):
        return value
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError(
            "Encountered an encrypted secret but APP_ENCRYPTION_KEY is not configured"
        )
    from cryptography.fernet import InvalidToken

    try:
        return fernet.decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt secret (wrong key or corrupt data)") from exc
