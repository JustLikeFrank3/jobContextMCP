"""Desktop deployment helpers: mode detection, app-data dir, frozen resources.

The desktop distribution (Tauri shell + PyInstaller sidecar) runs the server
in single-user, local-first mode.  Installed apps live in read-only locations,
so all mutable state must go to the per-OS app-data directory:

    macOS    ~/Library/Application Support/jobContext
    Windows  %APPDATA%\\jobContext
    Linux    ~/.local/share/jobContext  (XDG_DATA_HOME respected)

Nothing in this module imports config or server code — it must be safe to
call before environment variables are finalised by desktop_main.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "jobContext"


def is_desktop_mode() -> bool:
    """True when running as the desktop app (DEPLOY_MODE=desktop)."""
    return os.environ.get("DEPLOY_MODE", "").strip().lower() == "desktop"


def desktop_data_dir() -> Path:
    """Return the per-OS app-data directory for the desktop app.

    JOBCONTEXT_DATA_DIR overrides the platform default (tests, portable
    installs, power users).  The directory is not created here — bootstrap
    owns that.
    """
    override = os.environ.get("JOBCONTEXT_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    try:
        from platformdirs import user_data_dir
        # roaming=True → %APPDATA% (not %LOCALAPPDATA%) on Windows.
        return Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
    except ImportError:
        pass

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else home / ".local" / "share"
    return base / APP_NAME


def resource_root() -> Path:
    """Root directory for bundled read-only resources.

    Resolves templates/, tools.json, and the built React SPA both from a
    source checkout and from inside a PyInstaller bundle (sys._MEIPASS points
    at the extraction/_internal dir where --add-data files land).
    """
    frozen = getattr(sys, "_MEIPASS", "")
    if frozen:
        return Path(frozen)
    return Path(__file__).resolve().parent.parent
