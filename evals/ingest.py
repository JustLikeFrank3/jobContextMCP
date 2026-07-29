"""Shared results ingest — persist eval payloads and mirror gauges.

Used by two producers with identical semantics: the HTTP ingest route
(``POST /api/evals/results``, results pushed from a CLI run elsewhere) and
the ``run_evals`` control-plane executor (suite executed server-side).
Both run inside a partition context, so the store lands in the right
tenant's data folder and the gauges reflect whoever produced results last
on this server instance.
"""
from __future__ import annotations

import time

from lib import metrics
from lib.io import _load_json, _save_json

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


def apply_results(payload: dict) -> tuple[str, int]:
    """Mirror *payload* into eval_* gauges; returns (kind, scored_count).

    Raises ValueError for payloads that are neither suite results nor a
    Layer 1 report.
    """
    if "rows" in payload:
        scored = _record_suite_gauges(payload)
        metrics.set_gauge("eval_last_run_timestamp_seconds", time.time(), kind="suite")
        return "suite", scored
    if "pass_rate" in payload:
        _record_layer1_gauges(payload)
        metrics.set_gauge("eval_last_run_timestamp_seconds", time.time(), kind="layer1")
        return "layer1", 0
    raise ValueError(
        "Unrecognized eval payload — expected suite results (rows) "
        "or a Layer 1 report (pass_rate)."
    )


def store_results(payload: dict) -> tuple[str, int]:
    """Apply gauges and persist *payload* into the partition's results store."""
    from lib import config  # noqa: PLC0415 — late bind: constants are re-pointed at runtime

    kind, scored = apply_results(payload)
    stored = _load_json(config.EVAL_RESULTS_FILE, {})
    stored[kind] = payload
    stored["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_json(config.EVAL_RESULTS_FILE, stored)
    metrics.inc("eval_pushes_total", kind=kind)
    return kind, scored


def restore_gauges() -> None:
    """Re-expose stored results as gauges after a restart (best-effort)."""
    from lib import config  # noqa: PLC0415

    stored = _load_json(config.EVAL_RESULTS_FILE, {})
    for payload in (stored.get("suite"), stored.get("layer1")):
        if isinstance(payload, dict):
            try:
                apply_results(payload)
            except ValueError:
                pass
