"""Desktop-mode runtime routes (loopback-only, single-user).

Mounted by create_app() only when DEPLOY_MODE=desktop.  The desktop shell
(Tauri/pywebview) uses these to manage the backend it spawned:

    POST /desktop/shutdown    — stop the server gracefully.  Fallback for
        shells that can't signal the sidecar (and the #1 defence against
        orphaned backend processes holding the SQLite file).
    GET  /desktop/mcp-clients — detect installed MCP clients (Claude
        Desktop / VS Code / Cursor) and whether jobContext is registered.
    POST /desktop/mcp-connect — one-click connect: merge a jobContext stdio
        server entry into the chosen client's MCP config, pointing at this
        same binary with --mcp-stdio.

desktop_main.py registers a callback that flips uvicorn's ``should_exit``
flag; anything else (TestClient, stdio mode) simply has no callback and the
endpoint reports that instead of exiting the process.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["desktop"])

MCP_SERVER_NAME = "jobcontext"

_shutdown_callback: Callable[[], None] | None = None


def register_shutdown(callback: Callable[[], None] | None) -> None:
    """Register the callable that performs a graceful server shutdown."""
    global _shutdown_callback
    _shutdown_callback = callback


@router.post("/desktop/shutdown")
async def shutdown() -> dict:
    if _shutdown_callback is None:
        return {"status": "unavailable", "detail": "no shutdown handler registered"}
    _shutdown_callback()
    return {"status": "shutting-down"}


# ── One-click MCP client connect ──────────────────────────────────────────────

def _backend_stdio_command() -> tuple[str, list[str]]:
    """The (command, args) an MCP client should launch for stdio transport.

    Frozen (installed app): the sidecar binary itself with --mcp-stdio.
    Source checkout: the current Python interpreter running desktop_main.py.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp-stdio"]
    entry = Path(__file__).resolve().parents[2] / "desktop_main.py"
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


# ── AI provider settings (BYOK) ───────────────────────────────────────────────
# Desktop is single-user: the config lives at the app-data config.json
# (JOBCONTEXT_CONFIG). Saves persist there AND refresh the in-memory config
# so the next chat/generation call uses the new provider without a restart.

AI_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "key_field": "openai_api_key",
        "model_field": "openai_model",
        "default_model": "gpt-4o-mini",
        "key_prefix": "sk-",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "key_field": "anthropic_api_key",
        "model_field": "anthropic_model",
        "default_model": "claude-sonnet-5",
        "key_prefix": "sk-ant-",
    },
    "ollama": {
        "label": "Ollama (local)",
        "key_field": None,
        "model_field": "ollama_model",
        "default_model": "llama3.1:8b",
        "key_prefix": "",
    },
}


def _desktop_config_path() -> Path:
    env_path = os.environ.get("JOBCONTEXT_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    from lib.app_dirs import desktop_data_dir

    return desktop_data_dir() / "config.json"


def _read_desktop_config(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def _ollama_running() -> bool:
    import httpx

    from lib.config import get_config_value

    base = str(get_config_value("ollama_base_url", "http://localhost:11434/v1"))
    root = base.rsplit("/v1", 1)[0]
    try:
        return httpx.get(f"{root}/api/tags", timeout=0.8).status_code == 200
    except Exception:  # noqa: BLE001 — any failure just means "not detected"
        return False


class AiProviderRequest(BaseModel):
    provider: str
    api_key: str = ""    # empty = keep the existing stored key
    model: str = ""      # empty = keep existing / provider default
    clear_key: bool = False


@router.get("/desktop/ai-provider")
async def get_ai_provider() -> dict:
    """Current provider selection + per-provider readiness (keys never echoed)."""
    from lib.config import get_active_config, get_llm_client

    cfg = get_active_config()
    client, model = get_llm_client("chat")
    active = os.environ.get("LLM_PROVIDER", str(cfg.get("llm_provider", "openai"))).lower()
    providers = {}
    for provider_id, spec in AI_PROVIDERS.items():
        providers[provider_id] = {
            "label": spec["label"],
            "has_key": bool(str(cfg.get(spec["key_field"], "") or "").strip()) if spec["key_field"] else True,
            "model": str(cfg.get(spec["model_field"], "") or spec["default_model"]),
        }
    providers["ollama"]["running"] = _ollama_running()
    return {
        "provider": active,
        "model": model or "",
        "configured": client is not None,
        "providers": providers,
    }


@router.post("/desktop/ai-provider")
async def set_ai_provider(request: AiProviderRequest) -> dict:
    """Select a provider and optionally store its key/model.

    Writes the app-data config.json and refreshes the live config, so the
    change applies to the next request without restarting the app.
    """
    spec = AI_PROVIDERS.get(request.provider)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown provider {request.provider!r}; expected one of {sorted(AI_PROVIDERS)}")

    key = request.api_key.strip()
    if key and spec["key_prefix"] and not key.startswith(spec["key_prefix"]):
        raise HTTPException(
            status_code=422,
            detail=f"That doesn't look like a {spec['label']} key (should start with {spec['key_prefix']}…).",
        )

    updates: dict[str, Any] = {"llm_provider": request.provider}
    if spec["key_field"]:
        if request.clear_key:
            updates[spec["key_field"]] = None
        elif key:
            updates[spec["key_field"]] = key
    if request.model.strip():
        updates[spec["model_field"]] = request.model.strip()

    config_path = _desktop_config_path()
    cfg = _read_desktop_config(config_path)
    for field, value in updates.items():
        if value is None:
            cfg.pop(field, None)
        else:
            cfg[field] = value
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write {config_path}: {exc}") from exc

    from lib.config import get_llm_client, update_runtime_config

    update_runtime_config(updates)
    client, model = get_llm_client("chat")
    return {
        "status": "saved",
        "provider": request.provider,
        "model": model or "",
        "configured": client is not None,
    }


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
