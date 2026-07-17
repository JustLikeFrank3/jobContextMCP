"""Graceful shutdown of the desktop backend.

POST /desktop/shutdown is the fallback for shells that can't signal the
sidecar (and the #1 defence against orphaned backend processes holding the
SQLite file).  desktop_main.py registers a callback that flips uvicorn's
``should_exit`` flag; anything else (TestClient, stdio mode) simply has no
callback and the endpoint reports that instead of exiting the process.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter

router = APIRouter(tags=["desktop"])

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
