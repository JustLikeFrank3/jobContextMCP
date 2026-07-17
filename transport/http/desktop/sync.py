"""Cloud sync (desktop side).

Configuration + manual trigger for lib/sync_client.  The PAT comes from the
hosted dashboard's API Keys tab and lives in the local config.json next to
the other BYO keys.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from transport.http.desktop.config_store import (
    _desktop_config_path,
    _read_desktop_config,
    _write_desktop_config,
)

router = APIRouter(tags=["desktop"])


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
