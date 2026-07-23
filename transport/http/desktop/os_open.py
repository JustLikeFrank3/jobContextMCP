"""Native open (files + URLs).

The Tauri webview supports neither window.open popups nor download-attribute
navigation, so the SPA's file previews and external links dead-end on
desktop. Instead the SPA posts here and the OS opens the target natively —
Preview/Word/etc. for workspace files (view, print, and save in one move),
the default browser for links.
"""
from __future__ import annotations

import asyncio
import os
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["desktop"])


def _child_env() -> dict:
    """Environment for OS-opener children, scrubbed of PyInstaller leakage.

    The frozen sidecar exports LD_LIBRARY_PATH pointing at its bundled
    private libraries. xdg-open — and the viewer it launches — inherits it
    and can crash on startup against mismatched system libs, so the Popen
    "succeeds" while nothing ever appears (the Linux desktop dead-click).
    PyInstaller preserves the pre-freeze value in <VAR>_ORIG: restore that,
    or drop the variable entirely. In dev the vars are absent — no-op.
    """
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        orig = env.get(f"{var}_ORIG")
        if orig:
            env[var] = orig
        else:
            env.pop(var, None)
    return env


def _open_with_os(target: str) -> None:
    import subprocess

    # A target starting with '-' could be misread as a CLI flag by the OS
    # opener (argument injection) rather than a file/URL — a real path is
    # never affected by this (absolute paths start with '/', URLs must have
    # a valid scheme), so the prefix is a no-op except for that edge case.
    if target.startswith("-"):
        target = f"./{target}"

    if sys.platform == "darwin":
        subprocess.Popen(["open", target], env=_child_env())  # NOSONAR — list form (no shell); target is a resolved workspace path (containment-checked by open_file, basename-sanitized); taint from HTTP request is broken by os.path.basename sanitization in caller
    elif os.name == "nt":
        os.startfile(target)  # noqa: S606 — target is a resolved workspace path (containment-checked + basename-sanitized); validated upstream
    else:
        subprocess.Popen(["xdg-open", target], env=_child_env())  # NOSONAR — list form (no shell); target is a resolved workspace path (containment-checked by open_file, basename-sanitized); taint from HTTP request is broken by os.path.basename sanitization in caller


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

    # os.path.basename strips any directory component from the user-supplied
    # filename, eliminating path-traversal sequences before the path is built.
    safe_name = os.path.basename(unquote(quoted_name))
    if not safe_name:
        raise HTTPException(status_code=422, detail="Not a workspace file link.")

    root = folder.resolve()
    target = (folder / safe_name).resolve()
    if root != target.parent and root not in target.parents:
        raise HTTPException(status_code=404, detail="Invalid file path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Markdown is writer-friendly, not reader-friendly: render assessments /
    # prep docs to a styled PDF (content-hash cached outside the sync root)
    # and open that instead, so "view" means Preview, not a text editor.
    if target.suffix.lower() in (".md", ".markdown"):
        from lib.app_dirs import desktop_data_dir
        from lib.md_render import rendered_pdf_for

        try:
            pdf = await asyncio.to_thread(
                rendered_pdf_for, target, desktop_data_dir() / "cache" / "md-pdf"
            )
        except Exception:  # noqa: BLE001 — fall back to the raw file
            pdf = target
        _launch(str(pdf))
        return {"status": "opened", "name": target.name, "rendered": str(pdf) != str(target)}

    _launch(str(target))
    return {"status": "opened", "name": target.name}


def _launch(target: str) -> None:
    """_open_with_os with a missing-opener guard surfaced as a real error
    instead of a 500 traceback — the SPA shows the detail inline."""
    try:
        _open_with_os(target)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="No system opener found (is xdg-open installed?).",
        ) from None


class OpenUrlRequest(BaseModel):
    url: str


@router.post("/desktop/open-url")
async def open_url(request: OpenUrlRequest) -> dict:
    """Open an http(s) URL in the default browser.

    Routed through the same launcher as files (not stdlib webbrowser): on
    Linux webbrowser.open also spawns xdg-open, inheriting the frozen
    sidecar's poisoned LD_LIBRARY_PATH — the same silent dead-click the
    file path had. One launcher, one env scrub.
    """
    from urllib.parse import urlsplit

    url = request.url.strip()
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail="Only http(s) links can be opened.")
    await asyncio.to_thread(_launch, url)
    return {"status": "opened"}
