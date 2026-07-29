"""Push eval results to a running jobContext server.

POSTs a suite (or Layer 1) results payload to ``/api/evals/results`` so the
server persists it and exposes ``eval_*`` gauges on ``/metrics`` — from
there the existing Prometheus scrape (workstation exporter or AKS pod
annotations) carries the numbers to Grafana and the wallboard.

stdlib urllib on purpose: this must work from the frozen desktop sidecar
environment and from bare CI, with no extra dependencies.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def push_results(payload: dict, url: str, api_key: str = "", timeout: float = 10.0) -> dict:
    """POST *payload* to ``<url>/api/evals/results``; returns the response JSON.

    Raises ValueError on a missing URL and urllib errors on HTTP failure
    (callers surface those — a failed push must never look like a success).
    """
    if not url:
        raise ValueError(
            "no server URL — pass --push-url or set JOBCONTEXT_EVAL_URL "
            "(desktop sidecar: http://127.0.0.1:<port> from its startup log)"
        )
    request = urllib.request.Request(  # noqa: S310 — caller-supplied http(s) URL
        url.rstrip("/") + "/api/evals/results",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))
