"""Evals dashboard — the tenant triage loop as screens.

GET /dashboard/evals plus the small POST endpoints it drives. This is the
product surface for the loop the owner ran by hand in chat for a month:
author a golden set from your own applications, run the suite against your
own master, read the flagged claims, rule each one A/B/C/D, and let the D
rulings tell you what to document. Works identically in the web app and the
desktop app (the Tauri shell wraps these same dashboards).

Every payload-derived string rendered here is escaped: flagged claims are
LLM output and JD text is pasted by users — hostile markup, always.
"""
from __future__ import annotations

import html
import json

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from transport.http.auth import require_api_key
from .shared import html_page

_LOG = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _payload() -> dict:
    from lib import config  # noqa: PLC0415
    from lib.io import _load_json  # noqa: PLC0415

    data = _load_json(config.EVAL_RESULTS_FILE, {})
    return data if isinstance(data, dict) else {}


# ── POST endpoints the page drives ───────────────────────────────────────────

class RunBody(BaseModel):
    n: int = 5


@router.post("/evals/run")
async def evals_run(body: RunBody) -> JSONResponse:
    from evals import work as evals_work  # noqa: PLC0415
    from evals.tenant import load_tenant_golden  # noqa: PLC0415

    # The first error a new user hits must be a sentence, not a stack trace
    # (or worse, a silent errored run against someone else's file names).
    tenant_set = load_tenant_golden()
    if tenant_set is not None and not tenant_set:
        return JSONResponse({"error": "Your golden set is empty — add an entry below first."},
                            status_code=422)
    # The run confirmation names how many entries the SERVER will actually
    # run — a silently-short golden set must not score silently (a user who
    # believes they added five and lost two to a failed write should see
    # "running 3 entries" before the money is spent).
    if tenant_set is not None:
        entry_count = len(tenant_set)
    else:
        from evals.golden import load_golden, resolve_file  # noqa: PLC0415

        entry_count = sum(1 for e in load_golden() if resolve_file(e.jd_file))
        if not entry_count:
            return JSONResponse({"error": "No golden set yet — add 3–5 entries below before "
                                          "running. The suite needs your job descriptions."},
                                status_code=422)
    n = max(1, min(int(body.n), 10))
    work_id = evals_work.enqueue_run(n=n, origin="dashboard")
    return JSONResponse({"work_id": work_id, "n": n, "entries": entry_count})


class GoldenBody(BaseModel):
    company: str
    role: str
    jd_text: str
    entry_id: str = ""
    output_kind: str = "resume"


@router.post("/evals/golden")
async def evals_golden_upsert(body: GoldenBody) -> JSONResponse:
    from evals.tenant import upsert_golden_entry  # noqa: PLC0415

    try:
        row = upsert_golden_entry(
            company=body.company, role=body.role, jd_text=body.jd_text,
            entry_id=body.entry_id, output_kind=body.output_kind,
        )
    except ValueError as e:
        # Every rejected golden-set write leaves a server-side trace — the
        # 2026-08-24 report's first finding was that a dropped write had no
        # record anywhere.
        _LOG.warning("golden-set write rejected (company=%r, role=%r, jd_len=%d): %s",
                     body.company[:40], body.role[:40], len(body.jd_text), e)
        return JSONResponse({"error": str(e)}, status_code=422)
    _LOG.info("golden-set entry saved: %s (%s)", row["id"], row["company"])
    return JSONResponse({"entry": row})


class GoldenDeleteBody(BaseModel):
    entry_id: str


@router.post("/evals/golden/delete")
async def evals_golden_delete(body: GoldenDeleteBody) -> JSONResponse:
    from evals.tenant import delete_golden_entry  # noqa: PLC0415

    return JSONResponse({"deleted": delete_golden_entry(body.entry_id)})


class TriageBody(BaseModel):
    gd_id: str
    claim: str
    ruling: str = ""
    note: str = ""


@router.post("/evals/triage")
async def evals_triage(body: TriageBody) -> JSONResponse:
    from evals.tenant import save_ruling  # noqa: PLC0415

    try:
        record = save_ruling(body.gd_id, body.claim, body.ruling, body.note)
    except ValueError as e:
        _LOG.warning("triage ruling rejected (gd_id=%s, ruling=%r): %s", body.gd_id, body.ruling, e)
        return JSONResponse({"error": str(e)}, status_code=422)
    return JSONResponse({"stored": record})


class JudgeBody(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@router.post("/evals/judge")
async def evals_judge(body: JudgeBody) -> JSONResponse:
    from evals.tenant import judge_calibration_label, save_judge_prefs  # noqa: PLC0415

    try:
        prefs = save_judge_prefs(body.provider, body.model, body.api_key, body.base_url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    prefs["calibration"] = judge_calibration_label(prefs["model"])
    out = {"prefs": prefs}
    if prefs.get("key_plaintext_at_rest"):
        out["warning"] = ("key stored WITHOUT encryption — the server has no "
                         "APP_ENCRYPTION_KEY configured; it is in cleartext at rest")
    return JSONResponse(out)


@router.get("/evals/stamp")
async def evals_stamp() -> JSONResponse:
    return JSONResponse({"updated_at": _payload().get("updated_at") or ""})


@router.get("/evals/run/status")
async def evals_run_status() -> JSONResponse:
    """The latest run's work-item state — the poll target while a run is in
    flight. Polling the results stamp alone could never terminate on a FAILED
    run (a failure never stores results, so the stamp never changes and the
    page said "running" forever, or nothing at all after a reload)."""
    from evals import work as evals_work  # noqa: PLC0415

    return JSONResponse(evals_work.latest_run_status() or {})


@router.get("/evals/data")
async def evals_data() -> JSONResponse:
    """Everything the SPA's Evals screen needs, in one authenticated call.

    The React frontend is the product UI (web AND the desktop shell); the
    server-rendered page above serves the operational/LAN layer. Both drive
    the same POST endpoints — this endpoint is the SPA's read side.
    """
    from evals.tenant import (  # noqa: PLC0415
        JUDGE_CALIBRATION, JUDGE_UNCALIBRATED, TRIAGE_MEANINGS, claim_key,
        judge_calibration_label, list_tenant_entries, load_judge_prefs,
        load_triage, results_history,
    )

    payload = _payload()
    suite = payload.get("suite") or {}
    rows_in = suite.get("rows") or []
    detail = suite.get("detail") or {}
    triage = load_triage()

    rows = []
    for r in rows_in:
        agg = detail.get(r.get("gd_id")) or {}
        rows.append({
            "gd_id": r.get("gd_id"), "role": r.get("role"),
            "mean": r.get("mean"), "accuracy": r.get("accuracy"),
            "cov_pct": r.get("cov_pct"), "flip_rate_pct": r.get("flip_rate_pct"),
            "flags": agg.get("hallucination_flags"),
            "alerts": r.get("alerts") or [], "error": r.get("error") or "",
        })

    claims = []
    for gd_id, agg in detail.items():
        for claim in (agg or {}).get("hallucinations") or []:
            claims.append({"gd_id": gd_id, "claim": claim, "source": "judge"})
        for f in ((agg or {}).get("critic") or {}).get("findings") or []:
            text = str(f.get("claim") or "")
            if text:
                claims.append({"gd_id": gd_id, "claim": text,
                               "source": f"critic:{f.get('verdict')}"})
    for c in claims:
        key = claim_key(c["gd_id"], c["claim"])
        rec = triage.get(key) or {}
        c.update({"key": key, "ruling": rec.get("ruling", ""), "note": rec.get("note", "")})

    total_flags = sum(int((agg or {}).get("hallucination_flags") or 0) for agg in detail.values())
    means = [float(r.get("mean") or 0) for r in rows_in if "mean" in r]
    judge_model = str(suite.get("judge_model") or "")
    prefs = load_judge_prefs()
    # The default judge is whatever this DEPLOYMENT resolves for
    # task="eval_judge" — on the cloud that's the calibrated split; on a
    # BYOK desktop it's the user's own generation model judging its own
    # output. Resolve it and label it honestly instead of asserting
    # "calibrated" for a configuration this install may not have.
    from lib import config as config_mod  # noqa: PLC0415

    d_provider, d_model = config_mod._resolve_llm_settings(task="eval_judge")
    default_judge = {
        "provider": d_provider,
        "model": d_model,
        "calibration": judge_calibration_label(d_model),
    }
    prefs["calibration"] = (judge_calibration_label(prefs["model"]) if prefs["provider"]
                            else f"default judge for this install: {d_model} — "
                                 + judge_calibration_label(d_model))
    from evals import work as evals_work  # noqa: PLC0415

    return JSONResponse({
        "stamp": payload.get("updated_at") or "",
        "run": evals_work.latest_run_status(),
        "summary": {
            "mean": round(sum(means) / len(means), 3) if means else None,
            "total_flags": total_flags if rows_in else None,
            "judge_model": judge_model,
            "judge_calibration": judge_calibration_label(judge_model.split(",")[0].strip()),
            "n_runs": suite.get("n_runs"),
        },
        "rows": rows,
        "claims": claims,
        "golden": list_tenant_entries(),
        "judge": prefs,
        "default_judge": default_judge,
        "calibration_map": JUDGE_CALIBRATION,
        "calibration_default": JUDGE_UNCALIBRATED,
        "triage_meanings": TRIAGE_MEANINGS,
        "history": results_history(),
    })


# ── scoring visuals (inline SVG — kiosk visual language, dashboard palette) ──
#
# Same truthfulness rules as the Grafana boards: absent data renders as a gap,
# never a zero; the 4.0 pass line is drawn, not implied; flags color red the
# moment they exist. CSS vars keep the charts on the dashboard theme.

_DIM_LABELS = (
    ("keyword_coverage", "keyword"), ("relevance", "relevance"),
    ("accuracy", "accuracy"), ("impact_language", "impact"),
    ("ats_readiness", "ats"),
)


def _svg_trend(history: list[dict]) -> str:
    """Mean score (line, 1–5 left axis) + flags per run (bars) per stored suite.

    Flag bars are normalized to flags/N, never raw totals: a flag class that
    fires in 1 of 5 runs triples its raw count going N=1 → N=5 with zero real
    change, so a raw-total trend across mixed-N history would be the exact
    specificity failure this product flags in resumes. Each point's N renders
    in its tooltip; a run whose N is unknown shows its raw count, labeled.
    """
    if len(history) < 2:
        return ""
    w, h, pad = 820, 200, 34
    n = len(history)
    step = (w - 2 * pad) / max(n - 1, 1)
    y_score = lambda s: h - pad - (max(1.0, min(5.0, s)) - 1.0) / 4.0 * (h - 2 * pad)  # noqa: E731

    def per_run(r) -> "float | None":
        if r["flags"] is None:
            return None
        return r["flags"] / r["n_runs"] if r.get("n_runs") else float(r["flags"])

    max_rate = max((per_run(r) or 0) for r in history) or 1.0
    parts = [f"<svg viewBox='0 0 {w} {h}' style='width:100%;height:auto' role='img' "
             "aria-label='Mean score and hallucination flags per run'>"]
    pass_y = y_score(4.0)
    parts.append(f"<line x1='{pad}' y1='{pass_y:.1f}' x2='{w - pad}' y2='{pass_y:.1f}' "
                 "stroke='var(--ok)' stroke-dasharray='5 5' stroke-width='1' opacity='.7'/>")
    parts.append(f"<text x='{w - pad + 4}' y='{pass_y + 4:.1f}' fill='var(--ok)' font-size='11'>4.0</text>")
    bar_w = max(4.0, min(18.0, step * 0.4))
    for i, r in enumerate(history):
        x = pad + i * step
        rate = per_run(r)
        if rate is not None:  # absent stays absent — a gap, not a zero bar
            bh = (rate / max_rate) * (h - 2 * pad) * 0.85
            color = "var(--danger)" if r["flags"] else "var(--ok)"
            n_runs = r.get("n_runs")
            tip = (f"{r['started_at']}: {r['flags']} flags across N={n_runs} ({rate:.1f}/run)"
                   if n_runs else f"{r['started_at']}: {r['flags']} flags (N unknown — raw count)")
            parts.append(f"<rect x='{x - bar_w / 2:.1f}' y='{h - pad - bh:.1f}' width='{bar_w:.1f}' "
                         f"height='{max(bh, 2):.1f}' fill='{color}' opacity='.45'>"
                         f"<title>{_e(tip)}</title></rect>")
    points = " ".join(f"{pad + i * step:.1f},{y_score(r['mean']):.1f}" for i, r in enumerate(history))
    parts.append(f"<polyline points='{points}' fill='none' stroke='var(--accent)' stroke-width='2.5'/>")
    for i, r in enumerate(history):
        x, y = pad + i * step, y_score(r["mean"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3.5' fill='var(--accent)'>"
                     f"<title>{_e(r['started_at'])}: mean {r['mean']:.2f}</title></circle>")
    last = history[-1]
    parts.append(f"<text x='{pad + (n - 1) * step + 6:.1f}' y='{y_score(last['mean']) + 4:.1f}' "
                 f"fill='var(--text)' font-size='12' font-weight='700'>{last['mean']:.2f}</text>")
    parts.append(f"<text x='{pad}' y='16' fill='var(--muted)' font-size='11'>"
                 "mean score (line) · hallucination flags per run, normalized by N (bars)</text>")
    parts.append("</svg>")
    return ("<div class='card' style='padding:16px'>"
            "<div class='k'>Trend across stored runs</div>" + "".join(parts) + "</div>")


def _svg_dimensions(dims: dict) -> str:
    """Latest run's per-dimension means as bars against the 4.0 pass line."""
    rows = [(label, dims.get(key)) for key, label in _DIM_LABELS if dims.get(key) is not None]
    if not rows:
        return ""
    w, row_h, pad_l, pad_r = 820, 30, 90, 46
    h = len(rows) * row_h + 26
    scale = lambda s: pad_l + (max(1.0, min(5.0, s)) - 1.0) / 4.0 * (w - pad_l - pad_r)  # noqa: E731
    parts = [f"<svg viewBox='0 0 {w} {h}' style='width:100%;height:auto' role='img' "
             "aria-label='Per-dimension mean scores'>"]
    pass_x = scale(4.0)
    parts.append(f"<line x1='{pass_x:.1f}' y1='8' x2='{pass_x:.1f}' y2='{h - 8}' "
                 "stroke='var(--ok)' stroke-dasharray='5 5' stroke-width='1' opacity='.7'/>")
    for i, (label, val) in enumerate(rows):
        y = 18 + i * row_h
        good = val >= 4.0
        parts.append(f"<text x='{pad_l - 8}' y='{y + 13}' fill='var(--muted)' font-size='12' "
                     f"text-anchor='end'>{_e(label)}</text>")
        parts.append(f"<rect x='{pad_l}' y='{y}' width='{scale(val) - pad_l:.1f}' height='18' rx='4' "
                     f"fill='{'var(--ok)' if good else 'var(--accent)'}' opacity='{'0.9' if good else '0.75'}'>"
                     f"<title>{_e(label)}: {val:.2f}</title></rect>")
        parts.append(f"<text x='{scale(val) + 6:.1f}' y='{y + 13}' fill='var(--text)' "
                     f"font-size='12' font-weight='700'>{val:.2f}</text>")
    parts.append("</svg>")
    return ("<div class='card' style='padding:16px; margin-top:10px'>"
            "<div class='k'>Latest run — per dimension (pass line 4.0)</div>" + "".join(parts) + "</div>")


# ── the page ─────────────────────────────────────────────────────────────────

_EXTRA_CSS = """
  .lab-section { margin-bottom: 30px; }
  .entries-table { width: 100%; border-collapse: collapse; }
  .entries-table th, .entries-table td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line-soft); font-size: .9rem; }
  .entries-table th { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; }
  .num { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
  .flag-count { font-weight: 700; }
  .flag-count.ok { color: var(--ok); }
  .flag-count.bad { color: var(--danger); }
  .claim-card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; }
  .claim-card.ruled { border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
  .claim-head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; margin-bottom: 6px; }
  .gd-chip { font-family: 'JetBrains Mono', monospace; font-size: .72rem; color: var(--muted); background: var(--chip); border-radius: 5px; padding: 2px 7px; }
  .src-chip { font-size: .68rem; color: var(--faint); }
  .claim-text { color: var(--text-soft); font-size: .92rem; margin-bottom: 10px; }
  .rule-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .rule-btn { font-family: 'JetBrains Mono', monospace; font-weight: 700; border: 1px solid var(--line); background: var(--well); color: var(--muted); border-radius: 8px; padding: 6px 14px; cursor: pointer; }
  .rule-btn.sel-A { background: var(--danger); color: #fff; border-color: transparent; }
  .rule-btn.sel-B { background: var(--warn); color: #1a1200; border-color: transparent; }
  .rule-btn.sel-C { background: var(--ok); color: #03200f; border-color: transparent; }
  .rule-btn.sel-D { background: var(--accent); color: #062330; border-color: transparent; }
  .rule-note { flex: 1; min-width: 220px; background: var(--well); border: 1px solid var(--line); border-radius: 8px; color: var(--text); font-family: inherit; font-size: .85rem; padding: 7px 10px; }
  .legend-grid { display: grid; grid-template-columns: auto 1fr; gap: 5px 10px; font-size: .85rem; color: var(--muted); margin-bottom: 14px; }
  .legend-key { font-family: 'JetBrains Mono', monospace; font-weight: 700; text-align: center; border-radius: 5px; width: 1.6em; }
  .lk-A { background: var(--danger); color: #fff; } .lk-B { background: var(--warn); color: #1a1200; }
  .lk-C { background: var(--ok); color: #03200f; } .lk-D { background: var(--accent); color: #062330; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
  .form-grid input, .form-grid select, .jd-area, .judge-grid input, .judge-grid select {
    background: var(--well); border: 1px solid var(--line); border-radius: 8px; color: var(--text);
    font-family: inherit; font-size: .9rem; padding: 9px 12px; width: 100%;
  }
  .jd-area { min-height: 140px; resize: vertical; font-family: 'JetBrains Mono', monospace; font-size: .8rem; }
  .judge-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 10px; }
  .cal-label { font-size: .8rem; color: var(--muted); margin: 6px 0 12px; }
  .cal-label.good { color: var(--ok); } .cal-label.warn-c { color: var(--warn); }
  .status-line { font-size: .85rem; color: var(--muted); margin-left: 10px; }
  .del-btn { background: none; border: 1px solid var(--line); color: var(--muted); border-radius: 7px; padding: 4px 10px; cursor: pointer; font-size: .78rem; }
  .del-btn:hover { color: var(--danger); border-color: var(--danger); }
  .hint { color: var(--faint); font-size: .8rem; margin-top: 6px; }
"""


def _results_section(payload: dict, triage: dict) -> "tuple[str, str, list[dict]]":
    """(cards_html, entries_html, claims) — claims feed the triage section."""
    from evals.tenant import claim_key, judge_calibration_label  # noqa: PLC0415

    suite = payload.get("suite") or {}
    rows = suite.get("rows") or []
    detail = suite.get("detail") or {}
    if not rows:
        empty = ('<div class="empty">No eval run stored yet. Add golden entries below, '
                 'then hit <b>Run evals</b> — results land here when the run finishes.</div>')
        return "", empty, []

    total_flags = sum(int((agg or {}).get("hallucination_flags") or 0) for agg in detail.values())
    means = [float(r.get("mean") or 0) for r in rows if "mean" in r]
    overall = sum(means) / len(means) if means else 0.0
    judge_model = str(suite.get("judge_model") or "unknown")
    cal = judge_calibration_label(judge_model.split(",")[0].strip())
    cal_cls = "ok" if cal.startswith("calibrated") else "warn"
    flags_cls = "ok" if total_flags == 0 else "danger"
    cards = f"""<div class="cards">
      <div class="card"><div class="k">Stored</div><div class="v" style="font-size:1rem">{_e(payload.get("updated_at") or "?")}</div></div>
      <div class="card"><div class="k">Mean score</div><div class="v num">{overall:.2f}</div></div>
      <div class="card"><div class="k">Hallucination flags</div><div class="v num {flags_cls}">{total_flags}</div></div>
      <div class="card"><div class="k">Judge</div><div class="v" style="font-size:.95rem">{_e(judge_model)}</div>
        <div class="hint">{_e(cal)}</div></div>
    </div>"""

    body = ["<table class='entries-table'><tr><th>entry</th><th>mean</th><th>accuracy</th>"
            "<th>CoV%</th><th>flips%</th><th>flags</th><th>alerts</th></tr>"]
    for row in rows:
        gd = _e(row.get("gd_id") or "?")
        if "mean" not in row:
            body.append(f"<tr><td>{gd}</td><td colspan='6' style='color:var(--danger)'>"
                        f"errored: {_e(row.get('error') or 'unknown')}</td></tr>")
            continue
        agg = detail.get(row.get("gd_id")) or {}
        flags = int(agg.get("hallucination_flags") or 0)
        fcls = "ok" if flags == 0 else "bad"
        body.append(
            f"<tr><td>{gd} <span class='src-chip'>{_e(row.get('role') or '')}</span></td>"
            f"<td class='num'>{float(row.get('mean') or 0):.2f}</td>"
            f"<td class='num'>{_e(row.get('accuracy', '—'))}</td>"
            f"<td class='num'>{_e(row.get('cov_pct', '—'))}</td>"
            f"<td class='num'>{_e(row.get('flip_rate_pct', '—'))}</td>"
            f"<td class='num flag-count {fcls}'>{flags}</td>"
            f"<td class='num'>{len(row.get('alerts') or [])}</td></tr>"
        )
    body.append("</table>")

    claims: list[dict] = []
    for gd_id, agg in detail.items():
        for claim in (agg or {}).get("hallucinations") or []:
            claims.append({"gd_id": gd_id, "claim": claim, "source": "judge",
                           "key": claim_key(gd_id, claim)})
        critic = (agg or {}).get("critic") or {}
        for f in critic.get("findings") or []:
            text = str(f.get("claim") or "")
            if text:
                claims.append({"gd_id": gd_id, "claim": text,
                               "source": f"critic:{f.get('verdict')}",
                               "key": claim_key(gd_id, text)})
    for c in claims:
        rec = triage.get(c["key"]) or {}
        c["ruling"] = rec.get("ruling", "")
        c["note"] = rec.get("note", "")
    return cards, "".join(body), claims


def _triage_section(claims: list[dict], has_run: bool) -> str:
    from evals.tenant import TRIAGE_MEANINGS  # noqa: PLC0415

    legend = "".join(
        f"<span class='legend-key lk-{k}'>{k}</span><span>{_e(v)}</span>"
        for k, v in TRIAGE_MEANINGS.items()
    )
    if not claims:
        # Two DIFFERENT empty states: "no run yet" must never read as "you're
        # passing" — a clean run earns that sentence, an absent run doesn't.
        if not has_run:
            return (f"<div class='legend-grid'>{legend}</div>"
                    "<div class='empty'>No run yet, so nothing to triage. Flagged claims from "
                    "your first run land here — expect some.</div>")
        return (f"<div class='legend-grid'>{legend}</div>"
                "<div class='empty'>Nothing to triage — the stored run has no flagged claims. "
                "That is the goal state; keep it.</div>")
    ruled = sum(1 for c in claims if c["ruling"])
    cards = []
    for c in claims:
        sel = c["ruling"]
        btns = "".join(
            f"<button class='rule-btn{' sel-' + k if sel == k else ''}' data-r='{k}'>{k}</button>"
            for k in ("A", "B", "C", "D")
        )
        cards.append(
            f"<div class='claim-card{' ruled' if sel else ''}' data-key='{_e(c['key'])}' "
            f"data-gd='{_e(c['gd_id'])}'>"
            f"<div class='claim-head'><span class='gd-chip'>{_e(c['gd_id'])}</span>"
            f"<span class='src-chip'>{_e(c['source'])}</span></div>"
            f"<div class='claim-text'>“{_e(c['claim'])}”</div>"
            f"<div class='rule-row'>{btns}"
            f"<input class='rule-note' placeholder='Note — for a D, tell the story: it becomes the master edit' "
            f"value='{_e(c['note'])}'></div></div>"
        )
    claims_json = json.dumps(
        [{"key": c["key"], "gd_id": c["gd_id"], "claim": c["claim"]} for c in claims]
    ).replace("</", "<\\/")
    return (
        f"<div class='legend-grid'>{legend}</div>"
        f"<div class='hint' style='margin-bottom:10px'>{ruled}/{len(claims)} ruled. "
        "Rulings persist across runs: the same claim re-flagged later stays ruled. "
        "Every <b>D</b> is a to-do — document the fact in your master resume, and the flag "
        "converts to a citable strength on the next run.</div>"
        + "".join(cards)
        + f"<script>window.__claims = {claims_json};</script>"
    )


def _golden_section(entries: list[dict], using_fallback: bool) -> str:
    rows = ""
    if entries:
        body = ["<table class='entries-table'><tr><th>id</th><th>company</th><th>role</th>"
                "<th>kind</th><th></th></tr>"]
        for e in entries:
            body.append(
                f"<tr><td class='num'>{_e(e.get('id'))}</td><td>{_e(e.get('company'))}</td>"
                f"<td>{_e(e.get('role'))}</td><td>{_e(e.get('output_kind') or 'resume')}</td>"
                f"<td><button class='del-btn' data-del='{_e(e.get('id'))}'>remove</button></td></tr>"
            )
        body.append("</table>")
        rows = "".join(body)
    elif using_fallback:
        rows = ("<div class='hint'>This partition runs the built-in golden set until you add "
                "your own entries — add one below to switch to your set.</div>")
    else:
        rows = ("<div class='empty'>No golden entries yet. Pick 3–5 real job descriptions you "
                "care about — pasting the JD is all it takes. The suite generates against "
                "<i>your</i> master resume and judges the output.</div>")
    return rows + """
    <div class="form-grid" style="margin-top:14px">
      <input id="g-company" placeholder="Company">
      <input id="g-role" placeholder="Role title">
    </div>
    <textarea id="g-jd" class="jd-area" placeholder="Paste the full job description here"></textarea>
    <div style="display:flex; gap:10px; align-items:center; margin-top:10px">
      <select id="g-kind" style="width:auto"><option value="resume">resume</option>
        <option value="cover_letter">cover letter</option></select>
      <button class="btn-primary" id="g-add">Add entry</button>
      <span class="status-line" id="g-status"></span>
    </div>"""


def _judge_section(prefs: dict) -> str:
    from evals.tenant import JUDGE_CALIBRATION, JUDGE_UNCALIBRATED, judge_calibration_label  # noqa: PLC0415

    from lib import config as config_mod  # noqa: PLC0415

    provider = prefs.get("provider", "")
    model = prefs.get("model", "")
    _, d_model = config_mod._resolve_llm_settings(task="eval_judge")
    default_cal = f"default judge for this install: {d_model} — {judge_calibration_label(d_model)}"
    cal = judge_calibration_label(model) if provider else default_cal
    key_ph = "API key (stored, unchanged)" if prefs.get("has_key") else "API key"
    clear_warn = ""
    if prefs.get("key_plaintext_at_rest"):
        clear_warn = ("<div class='cal-label warn-c'>⚠ your key is stored WITHOUT encryption — "
                      "this server has no APP_ENCRYPTION_KEY configured. It is never shown or "
                      "sent back, but it sits in cleartext at rest; clear the provider to "
                      "remove it if that is not acceptable.</div>")
    cal_json = json.dumps({"map": JUDGE_CALIBRATION, "default": JUDGE_UNCALIBRATED,
                           "install_default": default_cal}).replace("</", "<\\/")
    opts = "".join(
        f"<option value='{v}'{' selected' if provider == v else ''}>{label}</option>"
        for v, label in (("", "Default judge for this install"), ("openai", "OpenAI (your key)"),
                         ("anthropic", "Anthropic (your key)"), ("ollama", "Ollama / local"))
    )
    return f"""
    <div class="hint" style="margin-bottom:10px">Judges are not interchangeable: scores are only
      comparable to the <i>same</i> judge's earlier runs. A cheaper judge is a fine drift signal
      for your own trend line — the calibration label tells you what has actually been measured.</div>
    <div class="judge-grid">
      <select id="j-provider">{opts}</select>
      <input id="j-model" placeholder="Model (blank = provider default)" value="{_e(model)}">
      <input id="j-key" type="password" placeholder="{_e(key_ph)}" autocomplete="off">
      <input id="j-base" placeholder="Base URL (Ollama only)" value="{_e(prefs.get('base_url', ''))}">
    </div>
    <div class="cal-label" id="j-cal">{_e(cal)}</div>
    {clear_warn}
    <button class="btn-primary" id="j-save">Save judge</button>
    <span class="status-line" id="j-status"></span>
    <script>window.__cal = {cal_json};</script>"""


_PAGE_JS = """
<script>
async function post(url, body) {
  const res = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify(body)});
  return res.json();
}

// triage
document.querySelectorAll('.claim-card').forEach(card => {
  const key = card.dataset.key;
  const meta = (window.__claims || []).find(c => c.key === key);
  if (!meta) return;
  const note = card.querySelector('.rule-note');
  const send = (ruling) => post('/dashboard/evals/triage',
    {gd_id: meta.gd_id, claim: meta.claim, ruling: ruling, note: note.value});
  card.querySelectorAll('.rule-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const r = btn.dataset.r;
      const already = btn.className.includes('sel-');
      card.querySelectorAll('.rule-btn').forEach(b => b.className = 'rule-btn');
      if (already) { await send(''); card.classList.remove('ruled'); return; }
      btn.classList.add('sel-' + r);
      card.classList.add('ruled');
      await send(r);
    });
  });
  note.addEventListener('change', () => {
    const sel = card.querySelector("[class*='sel-']");
    if (sel) send(sel.dataset.r);
  });
});

// golden set
const gAdd = document.getElementById('g-add');
if (gAdd) gAdd.addEventListener('click', async () => {
  const status = document.getElementById('g-status');
  status.textContent = 'saving…';
  const out = await post('/dashboard/evals/golden', {
    company: document.getElementById('g-company').value,
    role: document.getElementById('g-role').value,
    jd_text: document.getElementById('g-jd').value,
    output_kind: document.getElementById('g-kind').value,
  });
  if (out.error) { status.textContent = out.error; return; }
  window.location.reload();
});
document.querySelectorAll('[data-del]').forEach(btn => btn.addEventListener('click', async () => {
  await post('/dashboard/evals/golden/delete', {entry_id: btn.dataset.del});
  window.location.reload();
}));

// judge
const jModel = document.getElementById('j-model');
const jProv = document.getElementById('j-provider');
function refreshCal() {
  const el = document.getElementById('j-cal');
  if (!jProv.value) { el.textContent = window.__cal.install_default; return; }
  el.textContent = (window.__cal.map[jModel.value.trim()] || window.__cal.default);
}
if (jModel) { jModel.addEventListener('input', refreshCal); jProv.addEventListener('change', refreshCal); }
const jSave = document.getElementById('j-save');
if (jSave) jSave.addEventListener('click', async () => {
  const status = document.getElementById('j-status');
  status.textContent = 'saving…';
  const out = await post('/dashboard/evals/judge', {
    provider: jProv.value, model: jModel.value,
    api_key: document.getElementById('j-key').value,
    base_url: document.getElementById('j-base').value,
  });
  status.textContent = out.error ? out.error
    : (out.warning ? 'saved, but: ' + out.warning : 'saved — applies to your next run');
});

// run — poll the WORK ITEM, not the results stamp: a failed run never
// stores results, so a stamp poll would say "running" forever while the
// run was already dead (2026-08-24 vanished-run report).
function armRunPoll() {
  if (window.__runPoll) return;
  window.__runPoll = setInterval(async () => {
    try {
      const r = await (await fetch('/dashboard/evals/run/status')).json();
      if (r.status && r.status !== 'queued' && r.status !== 'running') {
        clearInterval(window.__runPoll); window.location.reload();
      }
    } catch (e) { /* transient — next tick retries */ }
  }, 60000);
}
const runBtn = document.getElementById('run-btn');
if (runBtn) runBtn.addEventListener('click', async () => {
  const status = document.getElementById('run-status');
  status.textContent = 'starting…';
  const out = await post('/dashboard/evals/run',
    {n: parseInt(document.getElementById('run-n').value, 10)});
  if (out.error) { status.textContent = out.error; return; }
  status.textContent = 'running ' + (out.entries ?? '?') + ' entries × N=' + out.n +
    ' (work #' + out.work_id +
    ') — a full run takes 1–3 hours; this page reloads itself when the run resolves';
  armRunPoll();
});
if (window.__run_inflight) armRunPoll();
</script>
"""


@router.get("/evals")
async def evals_page() -> HTMLResponse:
    from evals.tenant import (  # noqa: PLC0415
        list_tenant_entries, load_judge_prefs, load_triage, results_history,
    )

    from evals import work as evals_work  # noqa: PLC0415

    payload = _payload()
    triage = load_triage()
    cards, entries_html, claims = _results_section(payload, triage)
    tenant_entries = list_tenant_entries()
    history = results_history()
    visuals = ""
    if history:
        visuals = _svg_trend(history) + _svg_dimensions(history[-1].get("dimensions") or {})
    stamp = json.dumps(str(payload.get("updated_at") or ""))
    # A launched run always renders a state here — in flight, failed, or its
    # stored results above. Before this, the ONLY record of an in-flight or
    # failed run was ephemeral post-click JS state: a reload forgot a running
    # run, and a failed one looked identical to "never ran".
    run_state = evals_work.latest_run_status()
    run_inflight = bool(run_state and run_state["status"] in ("queued", "running"))
    if run_inflight:
        run_status_html = (
            f"running (work #{_e(run_state['work_id'])}, started "
            f"{_e(run_state['created_at'])} UTC) — a full run takes 1–3 hours; "
            "this page reloads itself when the run resolves")
    elif run_state and run_state["status"] in ("failed", "cancelled"):
        run_status_html = (
            f"<span style='color:var(--red, #e5484d)'>run #{_e(run_state['work_id'])} "
            f"{_e(run_state['status'])}: {_e(run_state['error'] or 'no error recorded')}</span>")
    else:
        run_status_html = ""
    body = f"""
    {cards}
    {visuals}
    <div class="lab-section">
      <div class="section-title">Latest run</div>
      {entries_html}
      <div style="display:flex; gap:10px; align-items:center; margin-top:12px">
        <select id="run-n" style="width:auto; background:var(--well); color:var(--text);
                border:1px solid var(--line); border-radius:8px; padding:8px 10px">
          <option value="1">N=1 (quick, ~$0.50)</option>
          <option value="3">N=3</option>
          <option value="5" selected>N=5 (full variance)</option>
        </select>
        <button class="btn-primary" id="run-btn">Run evals</button>
        <span class="status-line" id="run-status">{run_status_html}</span>
      </div>
      <div class="hint" style="margin-top:8px">First runs usually flag a lot — most of it
        points at gaps in your master resume, not at the generator. Triage with <b>D</b>,
        document the true facts, and the count drains on the next run.</div>
      <div class="hint">Cost scales with entries × N: on the default judge a 5-entry set at
        N=5 runs roughly $2.50–8. A cheaper judge (below) cuts this.</div>
    </div>
    <div class="lab-section">
      <div class="section-title">Triage flagged claims</div>
      {_triage_section(claims, has_run=bool((payload.get('suite') or {}).get('rows')))}
    </div>
    <div class="lab-section">
      <div class="section-title">Your golden set</div>
      {_golden_section(tenant_entries, using_fallback=bool((payload.get("suite") or {}).get("rows")) and not tenant_entries)}
    </div>
    <div class="lab-section">
      <div class="section-title">Judge</div>
      {_judge_section(load_judge_prefs())}
    </div>
    <script>window.__stamp = {stamp}; window.__run_inflight = {json.dumps(run_inflight)};</script>
    {_PAGE_JS}
    """
    return HTMLResponse(html_page(
        "Evals", "evals",
        "Does your generated resume tell the truth? Run the suite, triage what it flags, fix your ground truth.",
        _EXTRA_CSS, body,
    ))
