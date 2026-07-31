"""Uvicorn entry point for the HTTP transport.

Usage:
    python -m transport.http.main

Reads HOST / PORT / ENABLE_REMOTE / API_KEY from the environment. See
transport/http/config.py for the full list.
"""

import logging

import uvicorn

import server as _server  # noqa: F401 — registers all MCP tools as a side-effect
from transport.http.app import create_app
from transport.http.config import get_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# httpx logs every request line at INFO with the full URL — for SerpAPI that
# is the api_key in a query param. Errors still surface via callers' logs.
logging.getLogger("httpx").setLevel(logging.WARNING)


app = create_app(mcp=_server.mcp)


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "transport.http.main:app",
        host=settings.bind_host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
