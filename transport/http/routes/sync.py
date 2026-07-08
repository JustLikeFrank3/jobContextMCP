"""Sync transport: the cloud half of desktop ⇄ cloud bidirectional sync.

Mounted on every deployment (auth-gated); on the hosted product a desktop
app authenticates with a personal access token (API Keys tab), which
UserDataContextMiddleware resolves to the owner's partition — so every
handler below already runs against the right user's DB and workspace.

Row sync is a cursor exchange over lib.sync (see its module docs); file
sync moves whole documents by relative path, validated with the same
component rules the workspace-import endpoint uses.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from transport.http.auth import require_authenticated_user
from transport.http.security import User

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _user_root() -> Path:
    from transport.http.routes.dashboard.api import _active_user_root

    return _active_user_root()


class ChangesRequest(BaseModel):
    since_id: int = 0
    limit: int = 500


@router.post("/changes")
async def sync_changes(
    request: ChangesRequest,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    """Journal entries after the caller's cursor, with row snapshots."""
    from lib.db import get_connection
    from lib.sync import export_changes

    with get_connection() as con:
        return export_changes(con, request.since_id, limit=max(1, min(request.limit, 1000)))


class ApplyRequest(BaseModel):
    changes: list[dict]


@router.post("/apply")
async def sync_apply(
    request: ApplyRequest,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    """Apply a peer's change batch into this partition (LWW/dedupe/remap)."""
    from lib.db import get_connection
    from lib.sync import apply_changes

    if len(request.changes) > 2000:
        raise HTTPException(status_code=422, detail="Batch too large.")
    with get_connection() as con:
        return apply_changes(con, request.changes)


@router.post("/files/manifest")
async def sync_files_manifest(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    from lib.sync import file_manifest

    return {"manifest": file_manifest(_user_root())}


class FileRef(BaseModel):
    rel: str


def _resolve_rel(rel: str) -> Path:
    """Resolve a sync-relative path inside the user root (traversal-proof)."""
    from transport.http.desktop import _validated_member_path

    root = _user_root().resolve()
    return _validated_member_path(root, rel)


@router.post("/files/get")
async def sync_files_get(
    request: FileRef,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    target = _resolve_rel(request.rel)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    stat = target.stat()
    return {
        "rel": request.rel,
        "mtime": stat.st_mtime,
        "content_b64": base64.b64encode(target.read_bytes()).decode("ascii"),
    }


class FilePut(BaseModel):
    rel: str
    content_b64: str
    mtime: float = 0.0


@router.post("/files/put")
async def sync_files_put(
    request: FilePut,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    target = _resolve_rel(request.rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(request.content_b64))
    if request.mtime:
        os.utime(target, (request.mtime, request.mtime))
    return {"status": "stored", "rel": request.rel}
