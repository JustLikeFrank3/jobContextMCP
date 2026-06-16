"""Environment-driven configuration for the HTTP transport.

Reads from process environment with safe defaults. Loaded once at app
startup via `get_settings()` and cached.

Recognized variables:
    HOST            Bind address (default 127.0.0.1).
    PORT            Bind port (default 8000).
    ENABLE_REMOTE   If "true", overrides HOST to 0.0.0.0 for LAN/Tailscale.
    API_KEY         Required bearer token. If unset, auth is DISABLED and a
                    warning is logged. Never deploy without an API_KEY.
    CORS_ORIGINS    Comma-separated origins for CORS (default: empty = same-origin only).
"""

from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class HttpSettings:
    """Resolved HTTP transport settings."""
    host: str
    port: int
    enable_remote: bool
    api_key: str | None
    cors_origins: tuple[str, ...]

    @property
    def bind_host(self) -> str:
        """The address actually passed to uvicorn (respects ENABLE_REMOTE)."""
        return "0.0.0.0" if self.enable_remote else self.host

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_port(default: int = 8000) -> int:
    """Read PORT from environment, ignoring empty or non-integer values."""
    raw = os.environ.get("PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    return default


@lru_cache(maxsize=1)
def get_settings() -> HttpSettings:
    """Build and cache HttpSettings from the current process environment."""
    cors_raw = os.environ.get("CORS_ORIGINS", "").strip()
    cors = tuple(o.strip() for o in cors_raw.split(",") if o.strip()) if cors_raw else ()
    return HttpSettings(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=_env_port(8000),
        enable_remote=_env_bool("ENABLE_REMOTE", False),
        api_key=os.environ.get("API_KEY") or None,
        cors_origins=cors,
    )


def reset_settings_cache() -> None:
    """Clear the cached settings. Used by tests that mutate the environment."""
    get_settings.cache_clear()
