"""FastAPI HTTP + SSE transport for jobContextMCP.

Layout:
    config.py    Environment configuration (host, port, API key, remote bind).
    auth.py      Bearer-token API key dependency.
    models.py    Pydantic request/response models.
    sse.py       Helper to convert a sync service callback into an SSE stream.
    app.py       FastAPI app factory.
    main.py      Uvicorn entry point: `python -m transport.http.main`.
    routes/      One module per resource group.

Usage:
    HOST=127.0.0.1 PORT=8000 API_KEY=secret python -m transport.http.main

By default the server binds to 127.0.0.1 only. Set ENABLE_REMOTE=true to bind
to 0.0.0.0 for Tailscale / LAN use.
"""

from transport.http.app import create_app

__all__ = ["create_app"]
