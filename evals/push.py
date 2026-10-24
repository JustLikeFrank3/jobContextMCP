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
import urllib.parse
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward evaluation data or bearer credentials to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "eval result redirects are not allowed", headers, fp
        )


def _results_url(url: str) -> str:
    """Validate an explicit HTTP(S) base URL before constructing the endpoint."""
    # urlsplit strips some controls; reject them before parsing so the checked
    # URL is the URL actually sent. Userinfo and query/fragment base URLs are
    # ambiguous here, and credentials belong in the explicit api_key argument.
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url) or "\\" in url:
        raise ValueError("server URL must not contain whitespace or control characters")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("server URL must be an absolute http:// or https:// URL")
    if parts.username is not None or parts.password is not None or "?" in url or "#" in url:
        raise ValueError("server URL must not contain userinfo, query, or fragment")
    # Accessing port validates its syntax and range before any request is made.
    _ = parts.port
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc, parts.path.rstrip("/") + "/api/evals/results", "", ""
    ))


def push_results(payload: dict, url: str, api_key: str = "", timeout: float = 10.0) -> dict:
    """POST *payload* to ``<url>/api/evals/results``; returns the response JSON.

    Only explicit HTTP(S) base URLs are accepted. Redirects are errors, including
    same-origin redirects: callers must supply the final server URL, and neither
    the payload nor its bearer credential may be forwarded elsewhere.
    Raises ValueError on an invalid URL and urllib errors on HTTP failure
    (callers surface those — a failed push must never look like a success).
    """
    if not url:
        raise ValueError(
            "no server URL — pass --push-url or set JOBCONTEXT_EVAL_URL "
            "(desktop sidecar: http://127.0.0.1:<port> from its startup log)"
        )
    request = urllib.request.Request(
        _results_url(url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
