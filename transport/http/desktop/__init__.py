"""Desktop-mode runtime routes (loopback-only, single-user).

Mounted by create_app() only when DEPLOY_MODE=desktop.  The desktop shell
(Tauri/pywebview) uses these to manage the backend it spawned; the SPA's
Settings screen drives the rest.  One module per concern:

    runtime           POST /desktop/shutdown
    mcp_clients       GET  /desktop/mcp-clients, POST /desktop/mcp-connect
    ai_provider       GET/POST /desktop/ai-provider (BYOK)
    sync              GET /desktop/sync, POST /desktop/sync/config, /sync/run
    os_open           POST /desktop/open-file, /desktop/open-url
    import_workspace  POST /desktop/import-workspace

The public surface is unchanged from the pre-package desktop.py: import
``router`` and ``register_shutdown`` from ``transport.http.desktop``.
"""
from __future__ import annotations

from fastapi import APIRouter

from transport.http.desktop import (
    ai_provider,
    import_workspace,
    mcp_clients,
    os_open,
    runtime,
    sync,
)
from transport.http.desktop.import_workspace import _validated_member_path
from transport.http.desktop.mcp_clients import MCP_SERVER_NAME, _mcp_client_registry
from transport.http.desktop.runtime import register_shutdown

router = APIRouter(tags=["desktop"])
router.include_router(runtime.router)
router.include_router(mcp_clients.router)
router.include_router(ai_provider.router)
router.include_router(sync.router)
router.include_router(os_open.router)
router.include_router(import_workspace.router)

__all__ = [
    "MCP_SERVER_NAME",
    "_mcp_client_registry",
    "_validated_member_path",
    "register_shutdown",
    "router",
]
