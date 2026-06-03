"""Authentication primitives and provider abstraction for HTTP transport.

Routes should depend on `require_authenticated_user` / `require_api_key` rather
than hard-coding API key checks. Current provider is API-key backed, but this
module is intentionally shaped so future providers (OAuth, local users, SSO)
can be added without rewriting route protection logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

from transport.http.config import get_settings


@dataclass(frozen=True)
class User:
    id: str
    name: str
    roles: tuple[str, ...] = ("admin",)


_SYSTEM_USER = User(id="admin", name="Frank", roles=("admin",))


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


@lru_cache(maxsize=1)
def get_auth_provider() -> AuthProvider:
    """Return the active auth provider.

    Future extension point:
    switch on env/config and return OAuth / SSO provider instances.
    """
    return ApiKeyAuthProvider()


def reset_auth_provider_cache() -> None:
    """Used by tests that mutate auth environment."""
    get_auth_provider.cache_clear()
