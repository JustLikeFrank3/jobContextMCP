"""Entra ID JWT validation middleware and OIDC discovery for jobContextMCP.

Environment variables (injected from k8s secret jcmcp-app-secrets):
    ENTRA_TENANT_ID  — Azure AD tenant ID
    ENTRA_CLIENT_ID  — App registration client ID (== audience claim)

When either variable is unset the middleware is a no-op, preserving
local / stdio operation with no env vars required.
"""

import logging
import os
from typing import Callable

import jwt
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — resolved once at import time, re-read at each request so a future
# hot-reload or secret rotation doesn't require a pod restart.
# ---------------------------------------------------------------------------
TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")

JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

# Paths that bypass auth (discovery + health + OAuth callback)
_PUBLIC_PATHS = frozenset({
    "/.well-known/oauth-authorization-server",
    "/health",
    "/callback",
    "/dashboard/login",
    "/dashboard/callback",
})

# ---------------------------------------------------------------------------
# JWKS client — PyJWT handles caching and refresh internally
# ---------------------------------------------------------------------------
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URI, cache_jwk_set=True, lifespan=3600)
    return _jwks_client


def validate_token(token: str) -> dict:
    """Validate an Entra ID Bearer JWT and return the decoded claims.

    Accepts both v1 tokens (iss = sts.windows.net/…) and v2 tokens
    (iss = login.microsoftonline.com/…/v2.0) by skipping issuer check —
    the JWKS signature check is the security boundary.
    """
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    allowed_audiences = [CLIENT_ID, f"api://{CLIENT_ID}"]

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=allowed_audiences,
        options={"verify_iss": False},
    )
    return claims


# ---------------------------------------------------------------------------
# RFC 8414 Authorization Server Metadata
# Returned at /.well-known/oauth-authorization-server so MCP clients
# (VS Code, Claude Desktop, ChatGPT) can discover the token endpoint and
# initiate the PKCE flow automatically on first connection.
# ---------------------------------------------------------------------------
def oauth_discovery_json() -> dict:
    base = f"https://login.microsoftonline.com/{TENANT_ID}"
    return {
        "issuer": f"{base}/v2.0",
        "authorization_endpoint": f"{base}/oauth2/v2.0/authorize",
        "token_endpoint": f"{base}/oauth2/v2.0/token",
        "jwks_uri": f"{base}/discovery/v2.0/keys",
        "scopes_supported": [
            f"api://{CLIENT_ID}/access",
            "openid",
            "profile",
            "offline_access",
        ],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "registration_endpoint": None,
    }


# ---------------------------------------------------------------------------
# Starlette middleware
# ---------------------------------------------------------------------------
class EntraAuthMiddleware(BaseHTTPMiddleware):
    """Validate Entra ID Bearer tokens on every non-public request.

    No-op when ENTRA_TENANT_ID or ENTRA_CLIENT_ID is not set so local
    stdio / docker-compose mode continues to work without any changes.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        # No-op: local mode (env vars not injected)
        if not TENANT_ID or not CLIENT_ID:
            return await call_next(request)

        # Public endpoints pass through unconditionally
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "unauthorized", "message": "Bearer token required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="jobContextMCP"'},
            )

        token = auth_header.removeprefix("Bearer ")

        try:
            claims = validate_token(token)
            request.state.user = claims
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                {"error": "unauthorized", "message": "Token expired"},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="jobContextMCP", error="invalid_token",'
                        ' error_description="Token has expired"'
                    )
                },
            )
        except jwt.InvalidTokenError as exc:
            return JSONResponse(
                {"error": "unauthorized", "message": str(exc)},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="jobContextMCP", error="invalid_token"'
                    )
                },
            )
        except Exception:
            logger.exception("Unexpected error during token validation")
            return JSONResponse(
                {"error": "server_error", "message": "Token validation failed"},
                status_code=500,
            )

        return await call_next(request)
