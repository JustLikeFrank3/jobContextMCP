"""Eval results ingest — the bridge from local eval runs to Grafana.

The eval suite runs as a CLI wherever the workspace lives; the server is
what Prometheus scrapes. ``python -m evals push`` (or ``suite --push``)
POSTs the results here; we persist them in the user's data partition and
mirror the headline numbers into ``eval_*`` gauges on ``/metrics``. From
there the existing scrape paths take over: the workstation exporter
(:9105) for the desktop sidecar → Pi wallboard, pod annotations for AKS.

Gauges are in-process — a restart clears them until the stored results are
re-exposed on the next startup (see ``restore_gauges``).
"""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lib import metrics
from lib.io import _load_json, _save_json
from transport.http.auth import require_authenticated_user
from transport.http.security import User

router = APIRouter(prefix="/api/evals", tags=["evals"])

# dashboard_row key → judge dimension label
_DIMENSIONS = {
    "keyword": "keyword_coverage",
    "relevance": "relevance",
    "accuracy": "accuracy",
    "impact": "impact_language",
    "ats": "ats_readiness",
}


def _record_suite_gauges(payload: dict) -> int:
    detail = payload.get("detail") or {}
    scored = 0
    for row in payload.get("rows", []):
        gd_id = str(row.get("gd_id", ""))
        if not gd_id or "mean" not in row:
            continue  # entry errored before any run completed
        scored += 1
        metrics.set_gauge("eval_mean_score", float(row["mean"]), gd_id=gd_id)
        metrics.set_gauge("eval_cov_pct", float(row.get("cov_pct", 0)), gd_id=gd_id)
        metrics.set_gauge(
            "eval_verdict_flip_rate_pct", float(row.get("flip_rate_pct", 0)), gd_id=gd_id
        )
        metrics.set_gauge(
            "eval_alert_count", float(len(row.get("alerts", []))), gd_id=gd_id
        )
        for key, dimension in _DIMENSIONS.items():
            if key in row:
                metrics.set_gauge(
                    "eval_dimension_score", float(row[key]),
                    gd_id=gd_id, dimension=dimension,
                )
        rate = (detail.get(gd_id) or {}).get("hallucination_rate_pct")
        if rate is not None:
            metrics.set_gauge("eval_hallucination_rate_pct", float(rate), gd_id=gd_id)
    return scored


def _record_layer1_gauges(payload: dict) -> None:
    metrics.set_gauge("eval_layer1_pass_rate_pct", float(payload["pass_rate"]) * 100)
    if "smoke_pass_rate" in payload:
        metrics.set_gauge(
            "eval_layer1_smoke_pass_rate_pct", float(payload["smoke_pass_rate"]) * 100
        )


def _apply(payload: dict) -> tuple[str, int]:
    """Record gauges for *payload*; returns (kind, scored_entry_count)."""
    if "rows" in payload:
        scored = _record_suite_gauges(payload)
        metrics.set_gauge("eval_last_run_timestamp_seconds", time.time(), kind="suite")
        return "suite", scored
    if "pass_rate" in payload:
        _record_layer1_gauges(payload)
        metrics.set_gauge("eval_last_run_timestamp_seconds", time.time(), kind="layer1")
        return "layer1", 0
    raise HTTPException(
        status_code=422,
        detail="Unrecognized eval payload — expected suite results (rows) "
               "or a Layer 1 report (pass_rate).",
    )


@router.post("/results")
async def evals_ingest(
    payload: dict,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    from lib import config  # noqa: PLC0415 — late bind: constants are re-pointed at runtime

    kind, scored = _apply(payload)
    stored = _load_json(config.EVAL_RESULTS_FILE, {})
    stored[kind] = payload
    stored["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_json(config.EVAL_RESULTS_FILE, stored)
    metrics.inc("eval_pushes_total", kind=kind)
    return {"stored": kind, "entries_scored": scored}


@router.get("/results")
async def evals_latest(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    from lib import config  # noqa: PLC0415

    return _load_json(config.EVAL_RESULTS_FILE, {})


def restore_gauges() -> None:
    """Re-expose stored results as gauges after a restart (best-effort).

    Called at app startup for the owner partition only — per-tenant results
    reload when that tenant next pushes.
    """
    from lib import config  # noqa: PLC0415

    stored = _load_json(config.EVAL_RESULTS_FILE, {})
    for payload in (stored.get("suite"), stored.get("layer1")):
        if isinstance(payload, dict):
            try:
                _apply(payload)
            except HTTPException:
                pass
