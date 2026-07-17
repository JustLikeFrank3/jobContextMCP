"""Workspace import.

Counterpart of GET /api/dashboard/export: the user downloads a zip of their
cloud workspace from the hosted dashboard, then imports it here to replace
the local data. Raw zip body (no multipart — python-multipart isn't a dep).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["desktop"])

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
    import asyncio

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
