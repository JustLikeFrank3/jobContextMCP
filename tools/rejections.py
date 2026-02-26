"""
Rejection tracking tool — v4

Stores structured rejection data so Frank can spot patterns:
which companies, stages, and reasons are showing up repeatedly.

Tools:
  log_rejection   — record a rejection with company, role, stage, and optional reason
  get_rejections  — retrieve rejections with optional filtering and pattern summary
"""

import datetime
from lib import config
from lib.io import _load_json, _save_json, _now


_STAGE_ORDER = [
    "applied",
    "phone screen",
    "technical screen",
    "take-home",
    "onsite",
    "final round",
    "offer",
    "unknown",
]


def _next_id(rejections: list[dict]) -> int:
    if not rejections:
        return 1
    return max(r.get("id", 0) for r in rejections) + 1


def log_rejection(
    company: str,
    role: str,
    stage: str,
    reason: str = "",
    notes: str = "",
    date: str = "",
) -> str:
    """
    Log a rejection from a job application.

    Records the company, role, interview stage reached, optional stated reason,
    and any additional notes. Stored in data/rejections.json for pattern analysis.

    Args:
        company:  Company name (e.g. 'FanDuel').
        role:     Role title as applied (e.g. 'Senior Software Engineer').
        stage:    Stage reached before rejection: 'applied', 'phone screen',
                  'technical screen', 'take-home', 'onsite', 'final round', 'unknown'.
        reason:   Stated or inferred reason if known (e.g. 'overqualified',
                  'not enough X experience', 'ghosted').
        notes:    Any additional context worth remembering.
        date:     ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Confirmation string with rejection ID.
    """
    data = _load_json(config.REJECTIONS_FILE, {"rejections": []})
    rejections: list = data.setdefault("rejections", [])

    entry = {
        "id": _next_id(rejections),
        "company": company.strip(),
        "role": role.strip(),
        "stage": stage.strip().lower(),
        "reason": reason.strip(),
        "notes": notes.strip(),
        "date": date.strip() or datetime.date.today().isoformat(),
        "logged_at": _now(),
    }
    rejections.append(entry)
    _save_json(config.REJECTIONS_FILE, data)

    stage_label = stage or "unknown stage"
    return f"✓ Rejection logged: {company} — {role} (stage: {stage_label}, id: {entry['id']})"


def get_rejections(
    company: str = "",
    stage: str = "",
    since: str = "",
    include_pattern_analysis: bool = True,
) -> str:
    """
    Retrieve logged rejections with optional filters and pattern analysis.

    Args:
        company:                 Filter by company name (partial match, case-insensitive).
        stage:                   Filter by stage reached.
        since:                   ISO date string — only show rejections on or after this date.
        include_pattern_analysis: If True, append a brief pattern summary at the end.

    Returns:
        Formatted rejection log with optional pattern summary.
    """
    data = _load_json(config.REJECTIONS_FILE, {"rejections": []})
    rejections: list = data.get("rejections", [])

    if not rejections:
        return "No rejections logged yet."

    # Apply filters
    filtered = rejections
    if company:
        cl = company.strip().lower()
        filtered = [r for r in filtered if cl in r.get("company", "").lower()]
    if stage:
        sl = stage.strip().lower()
        filtered = [r for r in filtered if r.get("stage", "") == sl]
    if since:
        filtered = [r for r in filtered if r.get("date", "") >= since]

    if not filtered:
        return "No rejections match the specified filters."

    lines = [
        f"═══ REJECTIONS ({len(filtered)} total) ═══",
        "",
    ]
    for r in sorted(filtered, key=lambda x: x.get("date", ""), reverse=True):
        lines.append(f"■ {r['company']} — {r['role']}")
        lines.append(f"  Date:   {r.get('date', '—')}")
        lines.append(f"  Stage:  {r.get('stage', '—')}")
        if r.get("reason"):
            lines.append(f"  Reason: {r['reason']}")
        if r.get("notes"):
            lines.append(f"  Notes:  {r['notes']}")
        lines.append("")

    if include_pattern_analysis and len(filtered) >= 2:
        lines += _build_pattern_summary(filtered)

    return "\n".join(lines)


def _build_pattern_summary(rejections: list[dict]) -> list[str]:
    """Generate a short pattern analysis from rejection data."""
    from collections import Counter

    stage_counts = Counter(r.get("stage", "unknown") for r in rejections)
    company_counts = Counter(r.get("company", "?") for r in rejections)
    reason_counts = Counter(
        r["reason"] for r in rejections if r.get("reason")
    )

    lines = ["── PATTERN ANALYSIS ──", ""]

    # Stage breakdown
    lines.append("Rejections by stage:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
        bar = "▓" * count
        lines.append(f"  {stage:<20} {bar} ({count})")
    lines.append("")

    # Companies with multiple rejections
    multi = {c: n for c, n in company_counts.items() if n > 1}
    if multi:
        lines.append("Companies with multiple rejections:")
        for company, count in sorted(multi.items(), key=lambda x: -x[1]):
            lines.append(f"  {company}: {count} rejections")
        lines.append("")

    # Reason breakdown
    if reason_counts:
        lines.append("Stated/inferred reasons:")
        for reason, count in reason_counts.most_common(5):
            lines.append(f"  '{reason}' — {count}x")
        lines.append("")

    # Furthest stage reached
    all_stages = [r.get("stage", "unknown") for r in rejections]
    stage_index = {s: i for i, s in enumerate(_STAGE_ORDER)}
    furthest = max(all_stages, key=lambda s: stage_index.get(s, 0))
    lines.append(f"Furthest stage reached: {furthest}")

    # Early-funnel flag
    early = [r for r in rejections if r.get("stage", "") in ("applied", "phone screen", "unknown")]
    if len(early) / len(rejections) > 0.6:
        lines.append(
            "⚠  >60% rejections before technical screen — resume/ATS filtering may be the bottleneck."
        )

    return lines


def register(mcp) -> None:
    mcp.tool()(log_rejection)
    mcp.tool()(get_rejections)
