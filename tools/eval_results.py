"""Read-only eval results for MCP clients — the missing pull path.

The eval suite's stored payload was reachable only through the authenticated
HTTP API (``GET /api/evals/results``) and the kiosk wallboard page. An MCP
client asking "how did the last run go?" had no facade to call — which meant
an assistant with a live MCP connection could trigger a run
(``POST /api/evals/run`` exists) but never read its outcome without the
operator pasting JSON by hand (2026-08-18, mid-interview-prep). This module
closes that: same partition-scoped payload the wallboard renders, formatted
for a chat surface.

Read-only by design — the facade action can summarize and expose, never
mutate. Rendering favors the synopsis use case: entries with the volume
signal (``hallucination_flags``) next to the saturating rate, alert strings
verbatim, flagged claims quoted. ``raw=True`` returns the JSON payload for
machine consumers.
"""
from __future__ import annotations

import json

from lib import config
from lib.io import _load_json


def get_eval_results(raw: bool = False) -> str:
    """Latest stored eval-suite results — per-entry scores, alerts, and the exact flagged claims from the adversarial judge. Read-only. Set raw=true for the full JSON payload."""
    payload = _load_json(config.EVAL_RESULTS_FILE, {})
    if not isinstance(payload, dict) or not (payload.get("suite") or {}).get("rows"):
        return (
            "No stored eval run in this partition yet. Runs land here after "
            "the nightly suite or POST /api/evals/run completes."
        )
    if raw:
        return json.dumps(payload, indent=2, ensure_ascii=False)

    suite = payload.get("suite") or {}
    rows = suite.get("rows") or []
    detail = suite.get("detail") or {}
    lines = [
        "🧪 EVAL RUN DETAIL",
        f"judge: {suite.get('judge_model') or 'unknown'}"
        f" · N={suite.get('n_runs', '?')}"
        f" · started {suite.get('started_at') or '?'}"
        f" · stored {payload.get('updated_at') or '?'}",
        "",
        "ENTRIES (mean · accuracy · CoV% · flips% · flags)",
    ]
    for row in rows:
        gd = row.get("gd_id") or "?"
        if "mean" not in row:
            lines.append(f"  {gd}  ✗ errored: {row.get('error') or 'unknown'}")
            continue
        # hallucination_flags is absent from pre-2026-08-18 payloads; show a
        # dash rather than a fake zero (same doctrine as the ingest gauge).
        flags = (detail.get(gd) or {}).get("hallucination_flags")
        lines.append(
            f"  {gd} {row.get('role') or ''}: "
            f"{row.get('mean', '—')} · {row.get('accuracy', '—')} · "
            f"{row.get('cov_pct', '—')}% · {row.get('flip_rate_pct', '—')}% · "
            f"{'—' if flags is None else flags}"
        )

    lines.append("")
    lines.append("ALERTS")
    any_alert = False
    for row in rows:
        for alert in row.get("alerts") or []:
            any_alert = True
            lines.append(f"  ⚠ {row.get('gd_id') or '?'}: {alert}")
    if not any_alert:
        lines.append("  none — every entry inside thresholds")

    lines.append("")
    lines.append("FLAGGED CLAIMS (judge; distinct across runs)")
    any_claim = False
    for gd_id, agg in detail.items():
        for claim in (agg or {}).get("hallucinations") or []:
            any_claim = True
            lines.append(f"  {gd_id}: “{claim}”")
    if not any_claim:
        lines.append("  none flagged in the stored run")

    return "\n".join(lines)
