"""
Lazy Honcho client singleton.

Initialises only when honcho_api_key is set in config.json.
Falls back silently so all JSON-based code paths work unchanged when no key
is present (local dev, CI, fresh installs).

Usage from other modules:
    from lib import honcho_client
    if honcho_client.is_available():
        honcho_client.add_story("...", metadata={...})
    response = honcho_client.query_context("What are Frank's cloud strengths?")
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from honcho.client import Honcho as _HonchoClient
    from honcho.peer import Peer
    from honcho.session import Session

# Stable session ID — all personal-context stories live here
CONTEXT_SESSION_ID = "personal-context"

_client: "_HonchoClient | None" = None
_initialised: bool = False


def _get_client() -> "_HonchoClient | None":
    global _client, _initialised
    if _initialised:
        return _client
    _initialised = True
    try:
        from lib import config
        if not config.HONCHO_API_KEY:
            return None
        from honcho.client import Honcho
        _client = Honcho(
            api_key=config.HONCHO_API_KEY,
            workspace_id=config.HONCHO_WORKSPACE_ID,
        )
    except Exception:
        _client = None
    return _client


def is_available() -> bool:
    """Return True if a Honcho client is configured and initialised."""
    return _get_client() is not None


def _get_peer() -> "Peer | None":
    client = _get_client()
    if client is None:
        return None
    from lib import config
    try:
        return client.peer(config.HONCHO_PEER_ID)
    except Exception:
        return None


def _get_session() -> "Session | None":
    client = _get_client()
    if client is None:
        return None
    try:
        return client.session(CONTEXT_SESSION_ID)
    except Exception:
        return None


def add_story(content: str, metadata: dict | None = None) -> bool:
    """Write a story to Honcho as a peer message in the context session.

    Args:
        content: Full story text.
        metadata: Optional dict (tags, title, people, id, etc.).

    Returns:
        True on success, False if Honcho is unavailable or the call fails.
    """
    peer = _get_peer()
    session = _get_session()
    if peer is None or session is None:
        return False
    try:
        msg = peer.message(content, metadata=metadata)
        session.add_messages([msg])
        return True
    except Exception:
        return False


def query_context(query: str) -> str | None:
    """Ask Honcho to synthesise context for a natural-language query.

    Returns the model's response string, or None if Honcho is unavailable /
    the call fails (caller should fall back to JSON).
    """
    peer = _get_peer()
    if peer is None:
        return None
    try:
        return peer.chat(query)
    except Exception:
        return None


def reset() -> None:
    """Force re-initialisation of the cached client. Intended for tests."""
    global _client, _initialised
    _client = None
    _initialised = False
