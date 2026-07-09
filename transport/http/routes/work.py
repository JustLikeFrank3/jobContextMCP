"""Work-item status API — the read side of the control plane (lib/work.py).

  GET /api/work           — recent work items for the caller's partition
  GET /api/work/{id}      — one item: status, error, artifacts, timings

Auth matches the rest of the tenant API; the partition middleware scopes
every read to the caller's own rows.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lib import work
from transport.http.auth import require_authenticated_user
from transport.http.security import User

router = APIRouter(prefix="/api/work", tags=["work"])


@router.get("")
async def work_list(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
    status: str = "",
    limit: int = 50,
) -> dict:
    return {"items": work.list_items(status=status, limit=limit)}


@router.get("/{item_id}")
async def work_get(
    item_id: int,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    item = work.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such work item.")
    return item
