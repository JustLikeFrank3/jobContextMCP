"""Read/write helpers for the desktop app-data config.json.

Desktop is single-user: the config lives at the app-data config.json
(JOBCONTEXT_CONFIG).  Used by the AI-provider and cloud-sync routes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


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
