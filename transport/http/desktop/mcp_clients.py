"""One-click MCP client connect.

GET  /desktop/mcp-clients — detect installed MCP clients (Claude Desktop /
    VS Code / Cursor) and whether jobContext is registered.
POST /desktop/mcp-connect — merge a jobContext stdio server entry into the
    chosen client's MCP config, pointing at this same binary with
    --mcp-stdio.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["desktop"])

MCP_SERVER_NAME = "jobcontext"


def _backend_stdio_command() -> tuple[str, list[str]]:
    """The (command, args) an MCP client should launch for stdio transport.

    Frozen (installed app): the sidecar binary itself with --mcp-stdio.
    Source checkout: the current Python interpreter running desktop_main.py.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp-stdio"]
    entry = Path(__file__).resolve().parents[3] / "desktop_main.py"
    return sys.executable, [str(entry), "--mcp-stdio"]


def _mcp_client_registry() -> dict[str, dict[str, Any]]:
    """Known MCP clients and where their user-level config lives on this OS.

    ``key`` is the top-level JSON key holding server entries; VS Code's
    user mcp.json uses ``servers`` (with an explicit ``type``), the others
    use the classic ``mcpServers`` shape.
    """
    home = Path.home()
    if sys.platform == "darwin":
        claude = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        vscode = home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", "").strip() or (home / "AppData" / "Roaming"))
        claude = appdata / "Claude" / "claude_desktop_config.json"
        vscode = appdata / "Code" / "User" / "mcp.json"
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or (home / ".config"))
        claude = config_home / "Claude" / "claude_desktop_config.json"
        vscode = config_home / "Code" / "User" / "mcp.json"
    return {
        "claude-desktop": {"label": "Claude Desktop", "path": claude, "key": "mcpServers", "typed": False},
        "vscode": {"label": "VS Code", "path": vscode, "key": "servers", "typed": True},
        "cursor": {"label": "Cursor", "path": home / ".cursor" / "mcp.json", "key": "mcpServers", "typed": False},
    }


def _server_entry(typed: bool) -> dict[str, Any]:
    command, args = _backend_stdio_command()
    entry: dict[str, Any] = {"command": command, "args": args}
    if typed:
        entry["type"] = "stdio"
    return entry


def _read_client_config(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


class McpConnectRequest(BaseModel):
    client: str


@router.get("/desktop/mcp-clients")
async def mcp_clients() -> dict:
    """Detect installed MCP clients and whether jobContext is already wired."""
    clients = []
    for client_id, spec in _mcp_client_registry().items():
        path: Path = spec["path"]
        config = _read_client_config(path)
        servers = config.get(spec["key"], {})
        clients.append({
            "id": client_id,
            "label": spec["label"],
            # Heuristic: the client's config dir exists → the app is installed.
            "installed": path.parent.is_dir(),
            "connected": isinstance(servers, dict) and MCP_SERVER_NAME in servers,
            "config_path": str(path),
        })
    return {"clients": clients}


@router.post("/desktop/mcp-connect")
async def mcp_connect(request: McpConnectRequest) -> dict:
    """Merge a jobContext stdio entry into the chosen client's MCP config.

    Preserves everything else in the file; backs the previous version up to
    ``<name>.bak`` before writing.
    """
    registry = _mcp_client_registry()
    spec = registry.get(request.client)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown client {request.client!r}; expected one of {sorted(registry)}")

    path: Path = spec["path"]
    config = _read_client_config(path)
    servers = config.get(spec["key"])
    if not isinstance(servers, dict):
        servers = {}
    servers[MCP_SERVER_NAME] = _server_entry(spec["typed"])
    config[spec["key"]] = servers

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.with_suffix(path.suffix + ".bak").write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write {path}: {exc}") from exc

    return {
        "status": "connected",
        "client": request.client,
        "config_path": str(path),
        "server_name": MCP_SERVER_NAME,
    }
