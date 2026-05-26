"""Bearer-token API key authentication.

Reads API_KEY from environment via transport.http.config. If API_KEY is
unset, authentication is bypassed entirely (LAN-only / local-dev mode); a
warning is logged at startup so this is not silent in production.

Use as a FastAPI dependency:

    from fastapi import APIRouter, Depends
    from transport.http.auth import require_api_key

    router = APIRouter(dependencies=[Depends(require_api_key)])
"""

import logging

from fastapi import Header, HTTPException, status

from transport.http.config import get_settings


_logger = logging.getLogger(__name__)


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """Validate the Authorization header against the configured API_KEY.

    Accepts both "Bearer <key>" and bare "<key>" formats for client
    convenience. Raises 401 if API_KEY is set and the header is missing or
    does not match. No-op when API_KEY is not configured.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if token != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
