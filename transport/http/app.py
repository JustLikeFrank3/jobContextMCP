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
from fastapi.responses import FileResponse

from transport.http.config import get_settings
from transport.http.routes import context as context_routes
from transport.http.routes import health as health_routes
from transport.http.routes import jobs as jobs_routes
from transport.http.routes import personas as personas_routes
from transport.http.routes import resumes as resumes_routes
from transport.http.routes import workflows as workflows_routes
from transport.http.routes.dashboard import router as dashboard_router

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_logger = logging.getLogger(__name__)


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

    # ── MCP Streamable HTTP transport (optional) ─────────────────────────────
    # The FastMCP Starlette app registers its handler at the path /mcp
    # internally.  Mounting at "" (no prefix stripping) passes the full
    # request path through so /mcp matches.  All FastAPI routes registered
    # above take priority; this acts as a catch-all only for unmatched paths.
    if mcp_starlette is not None:
        app.mount("", mcp_starlette)
        _logger.info("MCP Streamable HTTP transport mounted at /mcp")

    # ── Static icon routes (suppress browser-auto 404s) ──────────────────────
    _static = Path(__file__).parent / "static"
    _PNG = "image/png"

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(_static / "favicon.ico", media_type=_PNG)

    @app.get("/apple-touch-icon{_:path}.png", include_in_schema=False)
    async def apple_touch_icon(_: str):
        """Catch all apple-touch-icon variants iOS requests (sized, precomposed, etc.)."""
        return FileResponse(_static / "apple-touch-icon.png", media_type=_PNG)

    return app
