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
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from lib.app_dirs import resource_root
from lib.version import __version__ as _APP_VERSION
from transport.http.config import get_settings
from transport.http.routes import context as context_routes
from transport.http.routes import health as health_routes
from transport.http.routes import jobs as jobs_routes
from transport.http.routes import oauth as oauth_routes
from transport.http.routes import personas as personas_routes
from transport.http.routes import resumes as resumes_routes
from transport.http.routes import workflows as workflows_routes
from transport.http.routes.dashboard import router as dashboard_router
from transport.http.routes.dashboard.api import router as dashboard_api_router
from transport.http.routes.architecture import architecture_html
from transport.http.routes.landing import landing_html
from transport.http.routes.login_page import login_html
from transport.http.routes.privacy import privacy_html
from transport.http.routes.setup import setup_html
from transport.http.routes.terms import terms_html
from transport.http.routes.why import why_html

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_logger = logging.getLogger(__name__)
_PNG_MEDIA_TYPE = "image/png"

# Vite build output for the React SPA. Module-level so tests can repoint it at
# a temporary build directory; only exists in prod after `npm run build`.
# resource_root() is sys._MEIPASS-aware so the SPA also resolves from inside
# a PyInstaller bundle (desktop app).
_SPA_DIST = resource_root() / "frontend" / "dist"


def _mount_spa(app: FastAPI) -> None:
    """Mount the Vite-built React SPA under /app/, if it has been built.

    Serves hashed assets from frontend/dist/assets and falls back to
    index.html for any other /app/* path so client-side routes (and hard
    refreshes on deep links) resolve. No-ops when frontend/dist is absent
    (e.g. dev/test runs without `npm run build`), leaving the legacy
    server-rendered /dashboard as the UI.
    """
    spa_dist = _SPA_DIST
    spa_index = spa_dist / "index.html"
    if not spa_index.is_file():
        _logger.info("React SPA dist not found at %s — skipping /app mount", spa_dist)
        return

    # Hashed, content-addressed JS/CSS — safe to serve as immutable static.
    app.mount("/app/assets", StaticFiles(directory=spa_dist / "assets"), name="spa-assets")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str = "") -> FileResponse:  # noqa: D401
        if full_path:
            candidate = (spa_dist / full_path).resolve()
            if candidate.is_file() and spa_dist in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(spa_index, media_type="text/html")

    _logger.info("React SPA mounted at /app (dist=%s)", spa_dist)


class UserDataContextMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that routes each authenticated request to the
    requesting user's own data partition under DATA_FOLDER/users/{oid}/.

        Security model:
            - Any authenticated Entra user is routed to DATA_FOLDER/users/{oid}/,
                provisioned on first access.
            - API-key "admin" sessions are never mapped to an owner partition and
                cannot access tenant-scoped data endpoints.
    """

    async def dispatch(self, request: StarletteRequest, call_next):  # NOSONAR
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
            "/setup",
            "/architecture",
            "/privacy",
            "/terms",            "/og-image",            "/logged-out",
            "/login",
            "/why",
            "/app",              # React SPA shell + hashed assets (data APIs stay protected)
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
        version=_APP_VERSION,
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
    if settings.desktop_mode:
        from transport.http import desktop as desktop_routes
        from transport.http.routes import chat as chat_routes
        app.include_router(desktop_routes.router)
        app.include_router(chat_routes.router)  # embedded chat — desktop-only in v1
    app.include_router(jobs_routes.router)
    app.include_router(resumes_routes.router)
    app.include_router(context_routes.router)
    app.include_router(workflows_routes.router)
    app.include_router(personas_routes.router)
    app.include_router(dashboard_api_router)  # /api/dashboard/* JSON for the React SPA
    app.include_router(dashboard_router)

    @app.get("/", include_in_schema=False)
    async def _root_landing() -> HTMLResponse:
        return HTMLResponse(landing_html())

    @app.get("/why", include_in_schema=False)
    async def _why_page() -> HTMLResponse:
        return HTMLResponse(why_html())

    @app.get("/setup", include_in_schema=False)
    async def _setup_page() -> HTMLResponse:
        return HTMLResponse(setup_html())

    @app.get("/architecture", include_in_schema=False)
    async def _architecture_page() -> HTMLResponse:
        return HTMLResponse(architecture_html())

    @app.get("/privacy", include_in_schema=False)
    async def _privacy_page() -> HTMLResponse:
        return HTMLResponse(privacy_html())

    @app.get("/terms", include_in_schema=False)
    async def _terms_page() -> HTMLResponse:
        return HTMLResponse(terms_html())

    @app.get("/login", include_in_schema=False)
    async def _login_page(next: str = "/app") -> HTMLResponse:
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

    @app.get("/og-image.png", include_in_schema=False)
    async def og_image():
        """Open Graph image for LinkedIn / social previews (1200x627 PNG)."""
        return FileResponse(_static / "og-image.png", media_type=_PNG_MEDIA_TYPE)

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon_svg():
        return FileResponse(_static / "favicon.svg", media_type="image/svg+xml")

    @app.get("/favicon-32.png", include_in_schema=False)
    async def favicon_32():
        return FileResponse(_static / "favicon-32.png", media_type=_PNG_MEDIA_TYPE)

    @app.get("/favicon-16.png", include_in_schema=False)
    async def favicon_16():
        return FileResponse(_static / "favicon-16.png", media_type=_PNG_MEDIA_TYPE)

    @app.get("/apple-touch-icon{_:path}.png", include_in_schema=False)
    async def apple_touch_icon(_: str):
        """Catch all apple-touch-icon variants iOS requests (sized, precomposed, etc.)."""
        return FileResponse(_static / "apple-touch-icon.png", media_type=_PNG_MEDIA_TYPE)

    # ── React SPA (served under /app/, built by Vite to frontend/dist) ───────
    # Mounted before the MCP catch-all so /app/* resolves here. The dist
    # directory only exists after `npm run build` (CI/Docker build stage), so
    # _mount_spa() guards on its presence — dev/test runs without a build skip
    # it and the legacy server-rendered /dashboard remains the UI.
    _mount_spa(app)

    # ── MCP Streamable HTTP transport (optional, catch-all — must be last) ────
    # The FastMCP Starlette app registers its handler at the path /mcp
    # internally.  Mounting at "" (no prefix stripping) passes the full
    # request path through so /mcp matches.  Registered last so all FastAPI
    # routes above take priority; unmatched paths fall through to the MCP app.
    if mcp_starlette is not None:
        app.mount("", mcp_starlette)
        _logger.info("MCP Streamable HTTP transport mounted at /mcp")

    return app
