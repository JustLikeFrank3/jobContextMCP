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


@router.get("/stats")
async def work_stats(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    """Aggregates over the caller's work: counts, durations, recent failures.
    Everything here is a GROUP BY over work_items — the control plane doubles
    as its own telemetry source."""
    from lib.db import get_connection

    work._ensure_schema()
    with get_connection() as con:
        by_kind_status = [
            dict(r)
            for r in con.execute(
                "SELECT kind, status, COUNT(*) AS count, "
                "ROUND(AVG((julianday(finished_at) - julianday(started_at)) * 86400.0), 2) "
                "  AS avg_seconds "
                "FROM work_items GROUP BY kind, status ORDER BY kind, status"
            ).fetchall()
        ]
        recent_failures = [
            dict(r)
            for r in con.execute(
                "SELECT id, kind, finished_at, "
                "substr(COALESCE(error, ''), 1, 200) AS error_head "
                "FROM work_items WHERE status = 'failed' "
                "ORDER BY id DESC LIMIT 5"
            ).fetchall()
        ]
    return {"by_kind_status": by_kind_status, "recent_failures": recent_failures}


@router.get("/{item_id}")
async def work_get(
    item_id: int,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    item = work.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such work item.")
    return item
