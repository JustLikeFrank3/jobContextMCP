"""Eval results ingest + server-side runs.

Ingest (``POST /api/evals/results``) bridges CLI eval runs to Grafana: the
payload persists in the caller's partition and mirrors into ``eval_*``
gauges on ``/metrics`` (shared logic in evals/ingest.py). ``POST
/api/evals/run`` instead executes the suite server-side through the
control plane (kind ``run_evals``) — where partition data and provider
credentials already live; poll the returned work id via ``GET /api/work``.

Gauges are in-process — a restart clears them until the stored results are
re-exposed at startup (evals.ingest.restore_gauges) or the next push/run.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from evals import work as evals_work  # noqa: F401 — import registers the run_evals kind
from evals.ingest import restore_gauges, store_results  # noqa: F401 — restore_gauges re-exported for app startup
from lib.io import _load_json
from transport.http.auth import require_authenticated_user
from transport.http.security import User

router = APIRouter(prefix="/api/evals", tags=["evals"])


@router.post("/results")
async def evals_ingest(
    payload: dict,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    try:
        kind, scored = store_results(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"stored": kind, "entries_scored": scored}


@router.get("/results")
async def evals_latest(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    from lib import config  # noqa: PLC0415 — late bind: constants are re-pointed at runtime

    return _load_json(config.EVAL_RESULTS_FILE, {})


@router.post("/run")
async def evals_run(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
    payload: "dict | None" = None,
) -> dict:
    """Run the golden suite server-side; returns the control-plane work id."""
    payload = payload or {}
    try:
        n = max(1, min(int(payload.get("n", 5)), 10))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail="n must be an integer 1-10") from e
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise HTTPException(status_code=422, detail="entries must be a list of GD ids")
    work_id = evals_work.enqueue_run(n=n, entries=[str(e) for e in entries])
    return {"work_id": work_id, "status_url": f"/api/work/{work_id}"}
