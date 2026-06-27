"""Authentication primitives and provider abstraction for HTTP transport.

Routes should depend on `require_authenticated_user` / `require_api_key` rather
than hard-coding API key checks.

Providers:
  ApiKeyAuthProvider  — single shared API_KEY env var (default)
  EntraAuthProvider   — Entra ID PKCE; active when ENTRA_TENANT_ID +
                        ENTRA_CLIENT_ID are set.  Validates the jc_session
                        cookie as an Entra access JWT.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

from transport.http.config import get_settings


@dataclass(frozen=True)
class User:
    id: str
    name: str
    roles: tuple[str, ...] = ("admin",)


_SYSTEM_USER = User(id="admin", name="Admin", roles=("admin",))


def _normalize_bearer(raw: str | None) -> str | None:
    if not raw:
        return None
    token = raw.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


class AuthProvider(ABC):
    @property
    @abstractmethod
    def auth_enabled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def authenticate_request(self, authorization: str | None, session_token: str | None) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def authenticate_login(self, credential: str) -> tuple[User, str] | None:
        raise NotImplementedError


class ApiKeyAuthProvider(AuthProvider):
    """Auth provider backed by single shared API key.

    - Request auth accepts either Authorization bearer token or jc_session
      cookie token.
    - Login auth validates entered API key and returns cookie token.
    - If auth is disabled (no API_KEY configured), provider returns SYSTEM_USER
      to preserve local-dev ergonomics.
    """

    def __init__(self) -> None:
        # Intentionally do NOT snapshot settings here. get_settings() is cached
        # one layer down and is reset by tests (reset_settings_cache); reading
        # it fresh on each call keeps this provider correct even though the
        # provider instance itself is lru_cached.
        pass

    @property
    def auth_enabled(self) -> bool:
        return get_settings().auth_enabled

    def authenticate_request(self, authorization: str | None, session_token: str | None) -> User | None:
        settings = get_settings()
        if not settings.auth_enabled:
            return _SYSTEM_USER

        token = _normalize_bearer(authorization) or (session_token.strip() if session_token else None)
        if token and token == settings.api_key:
            return _SYSTEM_USER
        return None

    def authenticate_login(self, credential: str) -> tuple[User, str] | None:
        settings = get_settings()
        if not settings.auth_enabled:
            return (_SYSTEM_USER, "")
        if credential and credential.strip() == settings.api_key:
            # Session token is the same API key for the current provider.
            return (_SYSTEM_USER, settings.api_key or "")
        return None


class EntraAuthProvider(AuthProvider):
    """Auth provider backed by Entra ID (Azure AD).

    - authenticate_request: validates the jc_session cookie as an Entra
      access JWT using the shared PyJWT JWKS client in lib.auth.
    - authenticate_login: not used — browser flow handled in login.py routes.
    - auth_enabled: always True when this provider is active.
    """

    @property
    def auth_enabled(self) -> bool:
        return True

    def authenticate_request(
        self,
        authorization: str | None,
        session_token: str | None,
    ) -> User | None:
        from lib.auth import validate_token  # avoid circular at module load

        token = None
        if authorization:
            raw = authorization.strip()
            token = raw[7:].strip() if raw.lower().startswith("bearer ") else raw
        elif session_token:
            token = session_token.strip()

        if not token:
            return None

        # Per-user API keys (jcmcp_…) bypass Entra JWT validation.
        if token.startswith("jcmcp_"):
            from lib.api_keys import lookup_key
            oid = lookup_key(token)
            if oid:
                return User(id=oid, name="api-key")
            return None

        try:
            claims = validate_token(token)
            name = claims.get("name") or claims.get("preferred_username") or "user"
            uid = claims.get("oid") or claims.get("sub") or "unknown"
            return User(id=uid, name=name)
        except Exception:
            return None

    def authenticate_login(self, credential: str) -> tuple[User, str] | None:
        # Not used — PKCE flow sets the cookie directly in the callback route.
        return None


@lru_cache(maxsize=1)
def get_auth_provider() -> AuthProvider:
    """Return the active auth provider.

    Returns EntraAuthProvider when ENTRA_TENANT_ID + ENTRA_CLIENT_ID are set,
    otherwise falls back to ApiKeyAuthProvider.
    """
    if os.environ.get("ENTRA_TENANT_ID") and os.environ.get("ENTRA_CLIENT_ID"):
        return EntraAuthProvider()
    return ApiKeyAuthProvider()


def reset_auth_provider_cache() -> None:
    """Used by tests that mutate auth environment."""
    get_auth_provider.cache_clear()
