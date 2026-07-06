"""jobContext Desktop entrypoint.

Runs the server in single-user, local-first desktop mode:

  - All mutable state lives in the per-OS app-data dir (lib/app_dirs.py);
    nothing is written next to the executable.
  - SQLite is the sole datastore (SQLITE_ONLY=1), auth middleware is off
    (no API key ⇒ local admin), bind is loopback-only.
  - ``--port 0`` (the default) binds an OS-assigned free port and prints
    ``JOBCONTEXT_PORT=<port>`` to stdout so the desktop shell (Tauri /
    pywebview) can discover it, then poll /healthz and open the webview.
  - Graceful shutdown via SIGINT/SIGTERM (uvicorn's own handlers) or
    POST /desktop/shutdown (transport/http/desktop.py).
  - ``--mcp-stdio`` runs the stdio MCP transport against the same desktop
    data dir instead of the HTTP server — this is what "Connect to Claude
    Desktop" points MCP clients at.

This module is the PyInstaller entrypoint for the desktop sidecar binary.
Environment must be finalised BEFORE importing server/lib modules: several
of them (lib.config, lib.io) read env and config at import time.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

from lib.app_dirs import desktop_data_dir


def _apply_desktop_env(app_dir: Path) -> None:
    """Set the desktop-profile environment. Must run before server imports."""
    os.environ["DEPLOY_MODE"] = "desktop"
    os.environ.setdefault("USE_SQLITE", "1")   # SQLite reads
    os.environ.setdefault("SQLITE_ONLY", "1")  # no JSON dual-writes
    os.environ.setdefault("JOBCONTEXT_CONFIG", str(app_dir / "config.json"))
    # Desktop is never remote and never multi-tenant.
    for var in ("ENABLE_REMOTE", "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID"):
        os.environ.pop(var, None)


def bootstrap(app_dir: Path) -> Path:
    """First-run (and upgrade-safe) bootstrap of the desktop app-data dir.

    Reuses the AKS guest auto-provisioning path: workspace tree, starter
    config.json, placeholder master resume, and a schema-complete SQLite DB.
    Then ensures the config carries absolute desktop paths so lib.config
    resolves everything inside app_dir.  Idempotent.

    Returns the path to the desktop config.json.
    """
    from lib.user_provisioning import provision_user_data

    provision_user_data(app_dir)

    config_path = app_dir / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}

    desktop_defaults = {
        "data_folder": str(app_dir),
        "resume_folder": str(app_dir / "workspace"),
        "leetcode_folder": str(app_dir / "workspace" / "leetcode"),
    }
    changed = False
    for key, value in desktop_defaults.items():
        if cfg.get(key) != value:
            cfg[key] = value
            changed = True
    if changed:
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return config_path


def _selftest(app_dir: Path) -> int:
    """Headless diagnostics for frozen builds (CI smoke test on all OSes).

    Verifies the packaging-risk hotspots: config resolution, SQLite schema,
    tool registration (exercises tiktoken/langgraph/etc. hidden imports),
    bundled document templates, and a real WeasyPrint PDF render (native
    Pango/Cairo libs). Prints one line per check; exit 0 = all passed.
    """
    import tempfile

    failures = 0

    def check(name: str, fn) -> None:
        nonlocal failures
        try:
            detail = fn()
            print(f"PASS {name}{f' ({detail})' if detail else ''}", flush=True)
        except Exception as exc:  # noqa: BLE001 — report every failure, keep going
            failures += 1
            print(f"FAIL {name}: {exc!r}", flush=True)

    def _config() -> str:
        import lib.config as cfg
        assert Path(str(cfg.DATA_FOLDER)) == app_dir, f"DATA_FOLDER={cfg.DATA_FOLDER}"
        return str(cfg.DATA_FOLDER)

    def _sqlite() -> str:
        from lib.db import get_connection
        with get_connection() as con:
            tables = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        assert tables > 0, "no tables"
        return f"{tables} tables"

    def _tools() -> str:
        import server as _server
        count = len(_server._TOOL_MODULES)
        assert count > 20, f"only {count} tool modules"
        return f"{count} tool modules"

    def _templates() -> str:
        from lib.template_loader import list_templates
        names = list_templates()
        assert names, "no templates found"
        return f"{len(names)} templates"

    def _pdf() -> str:
        import weasyprint
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "selftest.pdf"
            weasyprint.HTML(string="<h1>jobContext selftest</h1>").write_pdf(str(out))
            size = out.stat().st_size
        assert size > 500, f"suspicious PDF size {size}"
        return f"{size} bytes"

    check("config", _config)
    check("sqlite", _sqlite)
    check("tools", _tools)
    check("templates", _templates)
    check("pdf", _pdf)

    print(f"SELFTEST {'PASS' if failures == 0 else f'FAIL ({failures})'}", flush=True)
    return 0 if failures == 0 else 1


def _bind_socket(port: int) -> socket.socket:
    """Bind a loopback TCP socket; port 0 lets the OS pick a free port.

    The bound socket is handed to uvicorn directly, so there is no
    close-then-rebind race between discovering the port and serving on it.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(128)
    return sock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobcontext-desktop",
        description="jobContext local backend (desktop mode)",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "0") or "0"),
        help="Port to bind on 127.0.0.1 (default 0 = OS-assigned; printed as JOBCONTEXT_PORT=<port>)",
    )
    parser.add_argument(
        "--data-dir", default="",
        help="Override the app-data directory (default: per-OS location, e.g. ~/Library/Application Support/jobContext)",
    )
    parser.add_argument(
        "--mcp-stdio", action="store_true",
        help="Run the stdio MCP transport (for Claude Desktop / VS Code / Cursor) instead of the HTTP server",
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="Run packaging diagnostics (config, SQLite, tools, templates, PDF render) and exit",
    )
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["JOBCONTEXT_DATA_DIR"] = args.data_dir
    app_dir = desktop_data_dir()
    app_dir.mkdir(parents=True, exist_ok=True)

    _apply_desktop_env(app_dir)
    bootstrap(app_dir)

    if args.selftest:
        return _selftest(app_dir)

    if args.mcp_stdio:
        # stdout belongs to the MCP protocol here — no port banner.
        import server as _server
        _server.mcp.run()
        return 0

    import uvicorn

    import server as _server  # registers all MCP tools at import time
    from transport.http import desktop as desktop_runtime
    from transport.http.app import create_app

    app = create_app(mcp=_server.mcp)

    sock = _bind_socket(args.port)
    port = sock.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    desktop_runtime.register_shutdown(lambda: setattr(server, "should_exit", True))

    # The shell parses this line to find the backend; keep the format stable.
    print(f"JOBCONTEXT_PORT={port}", flush=True)

    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
