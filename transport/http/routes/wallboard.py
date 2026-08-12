"""Kiosk-local eval detail page — GET /wallboard/evals.

The wallboard's Grafana panels show aggregates; the *detail* behind them
(alert strings, per-entry scores, the exact flagged hallucination claims)
lives in the owner's cloud partition, served by an authenticated JSON API.
Tapping that from the kiosk touchscreen yields a 401 or a wall of JSON —
neither is a wallboard experience. This route is the human-readable version:
the Pi's app fetches the payload server-side with an operator-provisioned
PAT and renders plain HTML sized for a touchscreen.

Security model, stated plainly:

- The route is **disabled unless BOTH** ``WALLBOARD_EVALS_URL`` and
  ``WALLBOARD_EVALS_PAT`` are set — it answers 404 everywhere those are
  absent, which is every deployment except a LAN box whose operator
  explicitly configured the pair (the Pi, via ``.env.pi`` →
  ``jcmcp-pi-app-secrets``). Cloud and desktop never set them.
- When enabled, the page is **deliberately unauthenticated** (the path is a
  public prefix): the viewer is whoever stands at the kiosk. That trades
  LAN-wide readability of eval detail — which includes flagged-claim text
  naming real employers — for a login-free wall display. The operator makes
  that trade by setting the env pair; this module never makes it for them.
- The PAT is used in an outbound Authorization header only. It is never
  rendered, never logged, and error pages show upstream status, not headers.

Fetches are cached for ``_CACHE_TTL_SECONDS`` so a kiosk refresh loop or a
curious phone can't turn one page into a request storm against the cloud.
"""
from __future__ import annotations

import html
import logging
import os
import threading
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/wallboard", tags=["wallboard"])

_CACHE_TTL_SECONDS = 60.0
# key -> (monotonic_ts, payload). Guarded by _CACHE_LOCK; the payloads are
# small (KBs) and there are exactly two keys, so no eviction is needed.
_CACHE: "dict[str, tuple[float, dict]]" = {}
_CACHE_LOCK = threading.Lock()

_DIMENSIONS = ("keyword", "relevance", "accuracy", "impact", "ats")


def _settings() -> "tuple[str, str]":
    url = str(os.environ.get("WALLBOARD_EVALS_URL", "") or "").strip().rstrip("/")
    pat = str(os.environ.get("WALLBOARD_EVALS_PAT", "") or "").strip()
    return url, pat


def _fetch(path: str) -> dict:
    """GET an authenticated cloud endpoint, with a short shared cache."""
    base, pat = _settings()
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(path)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]

    import httpx  # noqa: PLC0415 — keep app startup free of transport imports

    resp = httpx.get(
        f"{base}{path}",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/json"},
        timeout=10.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"unexpected payload shape from {path}")
    with _CACHE_LOCK:
        _CACHE[path] = (time.monotonic(), data)
    return data


def _e(value: Any) -> str:
    """Escape ANY payload-derived text. The flagged claims are LLM output and
    the alert strings interpolate document text — treat all of it as hostile
    markup, always."""
    return html.escape(str(value), quote=True)


_CSS = """
body { background:#111217; color:#d8d9df; font-family: system-ui, sans-serif;
       margin:0; padding:1.2rem 1.6rem; font-size:1.15rem; }
h1 { font-size:1.6rem; margin:0 0 .2rem; } h2 { font-size:1.25rem; margin:1.4rem 0 .5rem; color:#8ab4f8; }
.meta { color:#9aa0a6; margin-bottom:1rem; }
table { border-collapse:collapse; width:100%; margin:.4rem 0 1rem; }
th, td { text-align:left; padding:.45rem .7rem; border-bottom:1px solid #2a2c33; }
th { color:#9aa0a6; font-weight:600; font-size:.95rem; }
.pass { color:#5bb974; font-weight:700; } .fail { color:#f28b82; font-weight:700; }
.alert { color:#fdd663; margin:.15rem 0; }
.claim { color:#f28b82; margin:.3rem 0 .3rem 1rem; font-style:italic; }
.clean { color:#5bb974; }
.err { background:#3c1e1e; border:1px solid #f28b82; padding:1rem; border-radius:8px; }
.num { font-variant-numeric: tabular-nums; }
"""


def _render_error(reason: str) -> str:
    return (
        f"<style>{_CSS}</style><h1>\U0001F9EA Eval detail</h1>"
        f"<div class='err'><b>Couldn't fetch from the cloud:</b> {_e(reason)}"
        "<br>The wallboard gauges are unaffected; this page just couldn't "
        "load the run detail. It retries on refresh.</div>"
    )


def _render(evals: dict, work: "dict | None") -> str:  # noqa: PLR0912 — one page, one pass
    suite = evals.get("suite") or {}
    rows = suite.get("rows") or []
    detail = suite.get("detail") or {}
    parts = [f"<style>{_CSS}</style>"]
    parts.append("<h1>\U0001F9EA Eval run detail</h1>")
    parts.append(
        f"<div class='meta'>judge: <b>{_e(suite.get('judge_model') or 'unknown')}</b>"
        f" &nbsp;·&nbsp; N={_e(suite.get('n_runs', '?'))}"
        f" &nbsp;·&nbsp; stored {_e(evals.get('updated_at') or 'unknown')}</div>"
    )

    parts.append("<h2>Entries</h2><table><tr><th>entry</th><th>mean</th>"
                 "<th>acc</th><th>CoV%</th><th>flips%</th><th>alerts</th></tr>")
    for row in rows:
        gd = _e(row.get("gd_id") or "?")
        if "mean" not in row:
            parts.append(f"<tr><td>{gd}</td><td colspan='5' class='fail'>"
                         f"errored: {_e(row.get('error') or 'unknown')}</td></tr>")
            continue
        mean = float(row.get("mean") or 0)
        cls = "pass" if mean >= 4.0 else "fail"
        parts.append(
            f"<tr><td>{gd} <span class='meta'>{_e(row.get('role') or '')}</span></td>"
            f"<td class='num {cls}'>{mean:.2f}</td>"
            f"<td class='num'>{_e(row.get('accuracy', '—'))}</td>"
            f"<td class='num'>{_e(row.get('cov_pct', '—'))}</td>"
            f"<td class='num'>{_e(row.get('flip_rate_pct', '—'))}</td>"
            f"<td class='num'>{len(row.get('alerts') or [])}</td></tr>"
        )
    parts.append("</table>")

    parts.append("<h2>Alerts</h2>")
    any_alert = False
    for row in rows:
        for alert in row.get("alerts") or []:
            any_alert = True
            parts.append(f"<div class='alert'>⚠ {_e(row.get('gd_id') or '?')}: {_e(alert)}</div>")
    if not any_alert:
        parts.append("<div class='clean'>none — every entry inside thresholds</div>")

    parts.append("<h2>Flagged claims (judge)</h2>")
    any_claim = False
    for gd_id, agg in (detail or {}).items():
        for claim in (agg or {}).get("hallucinations") or []:
            any_claim = True
            parts.append(f"<div class='claim'>{_e(gd_id)}: “{_e(claim)}”</div>")
    if not any_claim:
        parts.append("<div class='clean'>none flagged in the stored run</div>")

    if work:
        parts.append("<h2>Work stats (tokens by kind)</h2><table>"
                     "<tr><th>kind</th><th>calls</th><th>prompt</th><th>completion</th></tr>")
        for row in work.get("tokens_by_kind") or []:
            parts.append(
                f"<tr><td>{_e(row.get('kind'))}</td>"
                f"<td class='num'>{_e(row.get('llm_calls'))}</td>"
                f"<td class='num'>{_e(row.get('tokens_prompt'))}</td>"
                f"<td class='num'>{_e(row.get('tokens_completion'))}</td></tr>"
            )
        parts.append("</table>")
        quota = work.get("quota") or {}
        if quota.get("daily_token_quota"):
            state = "fail" if quota.get("exceeded") else "pass"
            parts.append(
                f"<div class='meta'>quota: <span class='{state}'>"
                f"{_e(quota.get('tokens_used_today'))} / {_e(quota.get('daily_token_quota'))}"
                "</span> tokens today (UTC)</div>"
            )
        else:
            parts.append("<div class='meta'>no daily quota configured</div>")
    return "".join(parts)


@router.get("/evals")
def wallboard_evals() -> HTMLResponse:
    base, pat = _settings()
    if not (base and pat):
        # Unconfigured = the route does not exist. 404, not 403: nothing
        # should reveal that a proxy COULD be here.
        return HTMLResponse("Not Found", status_code=404)
    try:
        evals = _fetch("/api/evals/results")
    except Exception as exc:  # noqa: BLE001 — render the failure, never a traceback
        _LOG.warning("wallboard evals fetch failed: %s", type(exc).__name__)
        return HTMLResponse(_render_error(f"{type(exc).__name__}: {exc}"), status_code=502)
    work: "dict | None" = None
    try:
        work = _fetch("/api/work/stats")
    except Exception as exc:  # noqa: BLE001 — evals still render without work stats
        _LOG.warning("wallboard work-stats fetch failed: %s", type(exc).__name__)
    return HTMLResponse(_render(evals, work))
