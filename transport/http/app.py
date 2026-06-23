"""FastAPI application factory.

Builds the FastAPI instance with CORS, attaches all route modules, and
logs a startup warning if API_KEY is not configured.

Tests import `create_app()` directly; the uvicorn entry point in main.py
calls the same factory.

Pass an initialised FastMCP instance as `mcp` to also mount the MCP
Streamable HTTP transport at /mcp (used in http / AKS mode so VS Code
can connect to the remote server via type:"http" in mcp.json).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from transport.http.config import get_settings
from transport.http.routes import context as context_routes
from transport.http.routes import health as health_routes
from transport.http.routes import jobs as jobs_routes
from transport.http.routes import oauth as oauth_routes
from transport.http.routes import personas as personas_routes
from transport.http.routes import resumes as resumes_routes
from transport.http.routes import workflows as workflows_routes
from transport.http.routes.dashboard import router as dashboard_router
from transport.http.routes.landing import landing_html
from transport.http.routes.login_page import login_html

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_logger = logging.getLogger(__name__)


class UserDataContextMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that routes each authenticated request to the
    requesting user's own data partition under DATA_FOLDER/users/{oid}/.

        Security model:
            - Any authenticated Entra user is routed to DATA_FOLDER/users/{oid}/,
                provisioned on first access.
            - API-key "admin" sessions are never mapped to an owner partition and
                cannot access tenant-scoped data endpoints.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        from transport.http.security import get_auth_provider
        from lib.user_context import set_data_folder, reset_data_folder, set_user_oid, reset_user_oid
        from lib.user_provisioning import provision_user_data
        import lib.config as _cfg_module

        provider = get_auth_provider()
        authorization = request.headers.get("Authorization")
        session = request.cookies.get("jc_session")
        user = provider.authenticate_request(authorization, session)

        # Diagnostic logging — helps trace auth failures in production.
        _logger.debug(
            "auth: path=%s has_bearer=%s has_session=%s authenticated=%s",
            request.url.path,
            bool(authorization),
            bool(session),
            user is not None,
        )

        _PUBLIC_PREFIXES = (
            "/.well-known/",
            "/health",
            "/oauth/",
            "/logout",
            "/logged-out",
            "/login",
            "/dashboard/login",
            "/dashboard/callback",
            "/dashboard/logout",
            "/favicon",
            "/apple-touch-icon",
        )

        if user and user.id and user.id != "admin":
            _logger.debug("auth: routing to tenant path=%s", request.url.path)
            data_dir = Path(str(_cfg_module.DATA_FOLDER)) / "users" / user.id
            provision_user_data(data_dir)
            oid_token = set_user_oid(user.id)
            token = set_data_folder(data_dir)
            try:
                return await call_next(request)
            finally:
                reset_data_folder(token)
                reset_user_oid(oid_token)

        if user and user.id == "admin":
            # API-key provider is single-tenant mode; keep historical behavior.
            # Tenant-scoped blocking is for Entra multi-user contexts only.
            if provider.__class__.__name__ == "ApiKeyAuthProvider" or not provider.auth_enabled:
                return await call_next(request)
            if request.url.path == "/" or any(request.url.path.startswith(p) for p in _PUBLIC_PREFIXES):
                return await call_next(request)
            from starlette.responses import JSONResponse as _JSONResponse
            return _JSONResponse(
                {
                    "error": "forbidden",
                    "message": "API-key sessions are not tenant-scoped; sign in with Entra to access user data.",
                },
                status_code=403,
            )

        # No authenticated identity resolved — block MCP and API endpoints.
        # Pass through public paths (well-known, health, oauth, dashboard login/callback)
        # so discovery and auth flows still work unauthenticated.
        if request.url.path == "/" or any(request.url.path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # Dashboard HTML pages: redirect expired/missing sessions to the root
        # Redirect unauthenticated *browser* navigations to the landing page
        # instead of returning a JSON 401 that the browser just renders as a
        # white page full of JSON.  API/fetch callers (Accept: application/json
        # or Sec-Fetch-Dest != document) still get the structured 401 so
        # automation, tooling, and dashboard JS can react to it correctly.
        is_document_nav = (
            "text/html" in request.headers.get("accept", "")
            or request.headers.get("sec-fetch-dest", "") == "document"
        )
        if is_document_nav and (
            request.url.path == "/dashboard"
            or request.url.path.startswith("/dashboard/")
        ):
            from starlette.responses import RedirectResponse as _Redirect
            return _Redirect(url="/", status_code=303)

        from starlette.responses import JSONResponse as _JSONResponse
        has_candidate = bool((authorization and authorization.strip()) or (session and session.strip()))
        detail = "Invalid credentials" if has_candidate else "Missing credentials"
        return _JSONResponse(
            {"error": "unauthorized", "message": "Authentication required", "detail": detail},
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="jobContextMCP"'},
        )


def create_app(mcp: "FastMCP | None" = None) -> FastAPI:
    """Build and return the FastAPI app for the HTTP transport.

    Args:
        mcp: Optional FastMCP instance. When provided, the MCP Streamable
             HTTP transport is mounted at /mcp so AI clients can connect
             via ``type: "http"`` in mcp.json.
    """
    settings = get_settings()

    # ── Build MCP Starlette sub-app first (lazy-inits the session manager) ───
    # Must happen before the lifespan closure captures it.
    mcp_starlette = mcp.streamable_http_app() if mcp is not None else None

    # ── Lifespan: drive MCP session manager alongside FastAPI startup ─────────
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if mcp_starlette is not None:
            # The Starlette sub-app carries its own lifespan that initialises
            # the StreamableHTTPSessionManager task group.  We must enter it
            # here; FastAPI does NOT propagate lifespan into mounted sub-apps.
            async with mcp_starlette.router.lifespan_context(mcp_starlette):
                yield
        else:
            yield

    app = FastAPI(
        title="jobContextMCP HTTP API",
        description=(
            "REST + SSE adapter for jobContextMCP. Exposes job evaluation, "
            "resume generation, and context retrieval for browser / iPad / "
            "Open WebUI clients. The stdio MCP server is unaffected."
        ),
        version="0.7.0-dev",
        lifespan=lifespan,
    )

    # Per-user data isolation for every authenticated request.
    # Registered first so it sits inside CORS (CORS must be outermost).
    app.add_middleware(UserDataContextMiddleware)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    if not settings.auth_enabled:
        _logger.warning(
            "API_KEY is not set — HTTP transport is running WITHOUT authentication. "
            "Do not enable remote bind (ENABLE_REMOTE=true) in this state."
        )

    app.include_router(oauth_routes.router)   # must be before MCP catch-all
    app.include_router(health_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(resumes_routes.router)
    app.include_router(context_routes.router)
    app.include_router(workflows_routes.router)
    app.include_router(personas_routes.router)
    app.include_router(dashboard_router)

    @app.get("/", include_in_schema=False)
    async def _root_landing() -> HTMLResponse:
        return HTMLResponse(landing_html())

    @app.get("/login", include_in_schema=False)
    async def _login_page(next: str = "/dashboard") -> HTMLResponse:
        return HTMLResponse(login_html(next))

    # Redirect /dashboard (no trailing slash) → /dashboard/ so the MCP
    # catch-all mount below doesn't intercept it before FastAPI can redirect.
    @app.get("/dashboard", include_in_schema=False)
    async def _dashboard_redirect() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/")

    # ── Static icon routes (suppress browser-auto 404s) ──────────────────────
    # Must be registered BEFORE the catch-all MCP mount below, or the mount
    # intercepts these paths first.
    _static = Path(__file__).parent / "static"

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(_static / "favicon.ico", media_type="image/x-icon")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon_svg():
        return FileResponse(_static / "favicon.svg", media_type="image/svg+xml")

    @app.get("/favicon-32.png", include_in_schema=False)
    async def favicon_32():
        return FileResponse(_static / "favicon-32.png", media_type="image/png")

    @app.get("/favicon-16.png", include_in_schema=False)
    async def favicon_16():
        return FileResponse(_static / "favicon-16.png", media_type="image/png")

    @app.get("/apple-touch-icon{_:path}.png", include_in_schema=False)
    async def apple_touch_icon(_: str):
        """Catch all apple-touch-icon variants iOS requests (sized, precomposed, etc.)."""
        return FileResponse(_static / "apple-touch-icon.png", media_type="image/png")

    # ── MCP Streamable HTTP transport (optional, catch-all — must be last) ────
    # The FastMCP Starlette app registers its handler at the path /mcp
    # internally.  Mounting at "" (no prefix stripping) passes the full
    # request path through so /mcp matches.  Registered last so all FastAPI
    # routes above take priority; unmatched paths fall through to the MCP app.
    if mcp_starlette is not None:
        app.mount("", mcp_starlette)
        _logger.info("MCP Streamable HTTP transport mounted at /mcp")

    return app
