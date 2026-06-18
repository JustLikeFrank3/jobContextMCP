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
import os
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
from transport.http.routes import personas as personas_routes
from transport.http.routes import resumes as resumes_routes
from transport.http.routes import workflows as workflows_routes
from transport.http.routes.dashboard import router as dashboard_router
from transport.http.routes.dashboard.assets import banner_svg

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_logger = logging.getLogger(__name__)


class UserDataContextMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that routes each authenticated request to the
    requesting user's own data partition under DATA_FOLDER/users/{oid}/.

    Gated by the ENTRA_OWNER_OID env var:
      - Not set  → no-op (single-user / local dev mode, existing behaviour preserved).
      - Set       → ALL authenticated users, including the owner, are routed to
                   DATA_FOLDER/users/{oid}/, provisioned on first access.
                   ENTRA_OWNER_OID is retained for admin/dashboard privilege
                   checks but no longer controls filesystem routing.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        owner_oid = os.environ.get("ENTRA_OWNER_OID", "").strip()
        if not owner_oid:
            # Feature not yet configured — preserve existing behaviour.
            return await call_next(request)

        from transport.http.security import get_auth_provider
        from lib.user_context import set_data_folder, reset_data_folder
        from lib.user_provisioning import provision_user_data
        import lib.config as _cfg_module

        provider = get_auth_provider()
        authorization = request.headers.get("Authorization")
        session = request.cookies.get("jc_session")
        user = provider.authenticate_request(authorization, session)

        # Resolve the OID to route to: prefer the JWT claim, fall back to
        # ENTRA_OWNER_OID for API-key / admin sessions.
        oid: str | None = None
        if user and user.id and user.id != "admin":
            oid = user.id
        elif user and user.id == "admin":
            oid = owner_oid  # route API-key sessions to the owner's data dir

        if oid:
            data_dir = Path(str(_cfg_module.DATA_FOLDER)) / "users" / oid
            provision_user_data(data_dir)
            token = set_data_folder(data_dir)
            try:
                return await call_next(request)
            finally:
                reset_data_folder(token)

        return await call_next(request)


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

    # Per-user data isolation — no-op unless ENTRA_OWNER_OID is set.
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

    app.include_router(health_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(resumes_routes.router)
    app.include_router(context_routes.router)
    app.include_router(workflows_routes.router)
    app.include_router(personas_routes.router)
    app.include_router(dashboard_router)

    @app.get("/", include_in_schema=False)
    async def _root_login_entry() -> HTMLResponse:
        html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>jobContextMCP</title>
  <style>
        body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: #0b1220; color: #e6edf7;
           font-family: Inter, Arial, sans-serif; }
        .card { width: min(560px, 92vw); background: #111a2b; border: 1px solid #23324d;
            border-radius: 14px; padding: 24px; text-align: center; }
        .banner-wrap { width: 100%; max-width: 420px; margin: 0 auto 10px; }
        .banner-wrap svg { width: 100%; height: auto; display: block; }
    h1 { margin: 0 0 10px; font-size: 1.25rem; }
    p { margin: 0 0 16px; color: #9aa8bf; line-height: 1.45; }
    .btn { display: inline-block; text-decoration: none; font-weight: 700;
           color: #0b1220; background: #3FA8A8; border-radius: 10px;
           padding: 10px 14px; }
  </style>
</head>
<body>
  <main class=\"card\">
                <div class=\"banner-wrap\">__BANNER_SVG__</div>
        <h1>Secure Dashboard Access</h1>
    <p>Sign in to access the dashboard.</p>
    <a class=\"btn\" href=\"/dashboard/login\">Log in</a>
  </main>
</body>
</html>"""
        return HTMLResponse(html.replace("__BANNER_SVG__", banner_svg()))

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
