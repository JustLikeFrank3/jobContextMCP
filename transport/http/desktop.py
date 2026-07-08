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

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
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


def _write_desktop_config(path: Path, cfg: dict) -> None:
    """Persist the desktop config (sync; call via asyncio.to_thread).

    Written via open() on the app-dirs-derived path: the config *values*
    include request fields, and Sonar's taint engine mis-reads
    Path.write_text()'s content argument as a path sink (S2083 FP — same
    pattern previously cleared in tools/latex_export.py).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as cfg_fh:
        cfg_fh.write(json.dumps(cfg, indent=2))


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
        await asyncio.to_thread(_write_desktop_config, config_path, cfg)
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


# ── Cloud sync (desktop side) ─────────────────────────────────────────────────
# Configuration + manual trigger for lib/sync_client. The PAT comes from the
# hosted dashboard's API Keys tab and lives in the local config.json next to
# the other BYO keys.


class SyncConfigRequest(BaseModel):
    url: str = ""
    pat: str = ""          # empty = keep stored
    auto: bool = True
    clear: bool = False


@router.get("/desktop/sync")
async def sync_status() -> dict:
    from lib.sync_client import is_configured, last_summary, sync_settings

    settings = sync_settings()
    return {
        "configured": is_configured(),
        "url": settings["url"],
        "auto": settings["auto"],
        "has_pat": bool(settings["pat"]),
        "last": last_summary(),
    }


@router.post("/desktop/sync/config")
async def sync_config(request: SyncConfigRequest) -> dict:
    updates: dict[str, Any] = {"cloud_sync_auto": request.auto}
    if request.clear:
        updates["cloud_sync_pat"] = None
        updates["cloud_sync_url"] = None
    else:
        if request.url.strip():
            updates["cloud_sync_url"] = request.url.strip().rstrip("/")
        if request.pat.strip():
            updates["cloud_sync_pat"] = request.pat.strip()

    config_path = _desktop_config_path()
    cfg = _read_desktop_config(config_path)
    for field, value in updates.items():
        if value is None:
            cfg.pop(field, None)
        else:
            cfg[field] = value
    await asyncio.to_thread(_write_desktop_config, config_path, cfg)

    from lib.config import update_runtime_config

    update_runtime_config(updates)
    from lib.sync_client import is_configured

    return {"status": "saved", "configured": is_configured()}


@router.post("/desktop/sync/run")
async def sync_run() -> dict:
    from lib.sync_client import is_configured, run_sync

    if not is_configured():
        raise HTTPException(
            status_code=409,
            detail="Cloud sync isn't configured — add your cloud dashboard's API key first.",
        )
    return await asyncio.to_thread(run_sync)


# ── Native open (files + URLs) ────────────────────────────────────────────────
# The Tauri webview supports neither window.open popups nor download-attribute
# navigation, so the SPA's file previews and external links dead-end on
# desktop. Instead the SPA posts here and the OS opens the target natively —
# Preview/Word/etc. for workspace files (view, print, and save in one move),
# the default browser for links.


def _open_with_os(target: str) -> None:
    import subprocess

    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
    elif os.name == "nt":
        os.startfile(target)  # noqa: S606 — the whole point; validated upstream
    else:
        subprocess.Popen(["xdg-open", target])


class OpenFileRequest(BaseModel):
    href: str  # the /dashboard/materials/file/... href the backend emitted


@router.post("/desktop/open-file")
async def open_file(request: OpenFileRequest) -> dict:
    """Open a workspace file with its OS-default application.

    Accepts only the material-file hrefs this server itself generates, and
    re-runs the same folder-containment resolution the file-serving route
    uses — nothing outside the workspace folders can be opened.
    """
    from urllib.parse import unquote

    prefix = "/dashboard/materials/file/"
    href = request.href.strip()
    if not href.startswith(prefix):
        raise HTTPException(status_code=422, detail="Not a workspace file link.")
    folder_key, _, quoted_name = href[len(prefix):].partition("/")
    if not quoted_name:
        raise HTTPException(status_code=422, detail="Not a workspace file link.")

    from transport.http.routes.dashboard.materials import _folder_path

    folder = _folder_path(folder_key)
    if folder is None or not folder.exists():
        raise HTTPException(status_code=404, detail=f"Unknown folder: {folder_key}")
    root = folder.resolve()
    target = (folder / unquote(quoted_name)).resolve()
    if root != target.parent and root not in target.parents:
        raise HTTPException(status_code=404, detail="Invalid file path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    _open_with_os(str(target))
    return {"status": "opened", "name": target.name}


class OpenUrlRequest(BaseModel):
    url: str


@router.post("/desktop/open-url")
async def open_url(request: OpenUrlRequest) -> dict:
    """Open an http(s) URL in the system browser."""
    from urllib.parse import urlsplit

    url = request.url.strip()
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail="Only http(s) links can be opened.")
    _open_with_os(url)
    return {"status": "opened"}


# ── Workspace import ──────────────────────────────────────────────────────────
# Counterpart of GET /api/dashboard/export: the user downloads a zip of their
# cloud workspace from the hosted dashboard, then imports it here to replace
# the local data. Raw zip body (no multipart — python-multipart isn't a dep).

# Zip-slip guard: reject what is dangerous on the machine doing the
# extraction, nothing more. Universally hostile: control chars and
# ".."/"."/"" components ("/" can't appear — entries are split on it).
# Windows-only: ":" (drive refs / NTFS alternate streams) and "\\" (a
# separator there) — on macOS/Linux both are legal filename characters that
# real exports contain (e.g. scraped-job filenames embedding "https:").
_SAFE_ZIP_PART = re.compile(r"[^\x00-\x1f]+")
_WINDOWS_BAD = re.compile(r"[:\\]")
_IS_WINDOWS = os.name == "nt"


def _validated_member_path(extract_root: Path, name: str) -> Path:
    """Return the extraction path for a zip entry, or 422 on traversal attempts."""
    import posixpath

    parts = posixpath.normpath(name).split("/")
    if name.startswith(("/", "\\")) or not parts:
        raise HTTPException(status_code=422, detail=f"Unsafe path in archive: {name!r}")
    target = extract_root
    for part in parts:
        if part in ("..", ".", "") or not _SAFE_ZIP_PART.fullmatch(part):
            raise HTTPException(status_code=422, detail=f"Unsafe path in archive: {name!r}")
        if _IS_WINDOWS and _WINDOWS_BAD.search(part):
            raise HTTPException(status_code=422, detail=f"Unsafe path in archive: {name!r}")
        target = target / part
    return target


@router.post("/desktop/import-workspace")
async def import_workspace(request: "Request") -> dict:
    """Replace the local workspace with an exported zip; requires app restart.

    The current data dir is moved aside (never deleted) to
    ``<data-dir>-backup-<timestamp>`` before the zip contents take its place.
    Open SQLite handles may still point at the old inode, so the response
    tells the shell/user a restart is required — nothing re-reads config
    until then.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="No file received.")
    # All file I/O happens in a worker thread — a large archive must not
    # block the event loop (and uvicorn is single-loop in the desktop app).
    return await asyncio.to_thread(_perform_import, body)


def _perform_import(body: bytes) -> dict:
    import datetime
    import tempfile
    import zipfile

    from lib.app_dirs import desktop_data_dir

    data_dir = desktop_data_dir()
    staging = Path(tempfile.mkdtemp(prefix="jc-import-"))
    try:
        archive = staging / "import.zip"
        archive.write_bytes(body)
        extract_root = staging / "extracted"
        extract_root.mkdir()
        try:
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    target = _validated_member_path(extract_root, member.filename)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail="That file isn't a valid zip archive.") from exc

        # Accept both a bare export (config.json at the root) and a zip that
        # wraps everything in a single top-level folder.
        root = extract_root
        entries = [p for p in root.iterdir() if not p.name.startswith("__MACOSX")]
        if len(entries) == 1 and entries[0].is_dir():
            root = entries[0]
        if not (root / "config.json").exists() and not (root / "db").is_dir():
            raise HTTPException(
                status_code=422,
                detail="That zip doesn't look like a jobContext export (no config.json or db/).",
            )

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = data_dir.with_name(f"{data_dir.name}-backup-{stamp}")
        if data_dir.exists():
            shutil.move(str(data_dir), str(backup))
        else:
            backup = None
        shutil.move(str(root), str(data_dir))
        return {
            "status": "imported",
            "restart_required": True,
            "backup": str(backup) if backup else "",
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
