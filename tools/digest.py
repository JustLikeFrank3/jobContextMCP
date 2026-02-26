"""
Daily digest and weekly summary tools — v4

get_daily_digest()   — morning briefing: overdue follow-ups, stale apps,
                        pending actions, rejection count, health nudge.
weekly_summary()     — 7-day aggregate: apps, screens, rejections,
                        contacts added, mental health trend.
"""

import datetime
from collections import Counter

from lib import config
from lib.io import _load_json, _now
from tools.health import get_daily_checkin_nudge
from tools.job_hunt import _extract_followup_date, _check_overdue_followups


# ── helpers ────────────────────────────────────────────────────────────────────

def _days_since(iso_date: str) -> int:
    """Return calendar days since an ISO date string. Returns 999 on parse error."""
    try:
        d = datetime.date.fromisoformat(iso_date[:10])
        return (datetime.date.today() - d).days
    except Exception:
        return 999


def _load_apps() -> list[dict]:
    data = _load_json(config.STATUS_FILE, {"applications": []})
    return data.get("applications", [])


def _load_rejections() -> list[dict]:
    data = _load_json(config.REJECTIONS_FILE, {"rejections": []})
    return data.get("rejections", [])


def _load_people() -> list[dict]:
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    return data.get("people", [])


def _load_health() -> list[dict]:
    data = _load_json(config.HEALTH_LOG_FILE, {"entries": []})
    return data.get("entries", [])


# ── get_daily_digest ───────────────────────────────────────────────────────────

def get_daily_digest() -> str:
    """
    Return a morning briefing for Frank's job search day.

    Includes:
    - Today's date and pipeline count
    - Overdue or due-today follow-up actions
    - Stale applications (no update in 7+ days and status not closed)
    - Recent rejections (last 7 days)
    - Contacts awaiting outreach (drafted but not sent)
    - Mental health check-in nudge if not yet logged today
    - 3 focus priorities for the day

    Returns:
        Formatted daily digest string.
    """
    today = datetime.date.today()
    today_iso = today.isoformat()
    days_label = today.strftime("%A, %B %d, %Y")

    apps = _load_apps()
    rejections = _load_rejections()
    people = _load_people()

    lines = [
        "╔══════════════════════════════════════╗",
        f"║  DAILY DIGEST  —  {days_label}",
        "╚══════════════════════════════════════╝",
        "",
    ]

    # ── Pipeline snapshot ────────────────────────────────────────────────────
    active_statuses = {"applied", "phone screen", "technical screen", "take-home", "onsite", "final round", "offer", "interviewing"}
    active = [a for a in apps if a.get("status", "").lower() not in ("rejected", "withdrew", "closed", "declined")]
    lines.append(f"📋  PIPELINE: {len(active)} active application{'s' if len(active) != 1 else ''} / {len(apps)} total")
    lines.append("")

    # ── Overdue / due-today follow-ups ───────────────────────────────────────
    overdue = _check_overdue_followups(apps)
    if overdue:
        lines.append("⚠  FOLLOW-UPS DUE:")
        lines.extend(overdue)
        lines.append("")

    # ── Stale applications (7+ days, not closed) ─────────────────────────────
    stale = [
        a for a in active
        if _days_since(a.get("last_updated", "")) >= 7
    ]
    if stale:
        lines.append("🕐  STALE APPLICATIONS (7+ days since update):")
        for a in sorted(stale, key=lambda x: _days_since(x.get("last_updated", "")), reverse=True):
            age = _days_since(a.get("last_updated", ""))
            lines.append(f"  {a['company']} — {a['role']} ({age} days)")
        lines.append("")

    # ── Recent rejections ────────────────────────────────────────────────────
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    recent_rejections = [r for r in rejections if r.get("date", "") >= week_ago]
    if recent_rejections:
        lines.append(f"❌  REJECTIONS THIS WEEK ({len(recent_rejections)}):")
        for r in recent_rejections:
            lines.append(f"  {r['company']} — {r['role']} (stage: {r.get('stage', '?')})")
        lines.append("")

    # ── Contacts with drafts not yet sent ────────────────────────────────────
    drafted_unsent = [
        p for p in people
        if p.get("outreach_status", "").lower() == "drafted"
    ]
    if drafted_unsent:
        lines.append("📝  DRAFTED BUT NOT SENT:")
        for p in drafted_unsent:
            lines.append(f"  {p['name']} ({p.get('company', '?')})")
        lines.append("")

    # ── Applications needing action (next_steps set but no overdue date) ─────
    action_needed = [
        a for a in active
        if a.get("next_steps") and a not in stale
    ]
    if action_needed:
        lines.append("📌  PENDING NEXT STEPS:")
        for a in action_needed[:5]:  # Cap at 5 to avoid noise
            lines.append(f"  {a['company']} — {a.get('next_steps', '')[:100]}")
        lines.append("")

    # ── Totals summary ───────────────────────────────────────────────────────
    total_rejections = len(rejections)
    lines.append(f"📊  TOTALS: {len(apps)} apps tracked · {total_rejections} rejection{'s' if total_rejections != 1 else ''} logged")
    lines.append("")

    # ── 3 focus priorities ───────────────────────────────────────────────────
    priorities = []
    if overdue:
        priorities.append(f"Follow up on {overdue[0].split('—')[0].strip().lstrip('[').split(']')[-1].strip() if overdue else 'overdue item'}")
    if stale:
        priorities.append(f"Nudge {stale[0]['company']} — {stale[0]['role']}")
    if drafted_unsent:
        priorities.append(f"Send drafted message to {drafted_unsent[0]['name']}")
    if not priorities:
        if active:
            priorities.append("Review active pipeline for any needed follow-ups")
        priorities.append("Apply to 2-3 new roles")
        priorities.append("Log a check-in after the session")

    lines.append("🎯  TODAY'S FOCUS:")
    for i, p in enumerate(priorities[:3], 1):
        lines.append(f"  {i}. {p}")
    lines.append("")

    # ── Health nudge (last) ───────────────────────────────────────────────────
    nudge = get_daily_checkin_nudge()
    if nudge:
        lines.append(nudge)

    return "\n".join(lines)


# ── weekly_summary ─────────────────────────────────────────────────────────────

def weekly_summary() -> str:
    """
    Return a 7-day aggregate summary of job search activity.

    Covers:
    - Applications added or advanced this week
    - Screens / interviews scheduled or completed
    - Rejections logged this week with stage breakdown
    - New contacts added
    - Mental health trend (average energy, mood distribution)

    Returns:
        Formatted weekly summary string.
    """
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    week_ago_iso = week_ago.isoformat()

    apps = _load_apps()
    rejections = _load_rejections()
    people = _load_people()
    health_entries = _load_health()

    lines = [
        "╔══════════════════════════════════════╗",
        f"║  WEEKLY SUMMARY  —  week of {week_ago.strftime('%b %d')}",
        "╚══════════════════════════════════════╝",
        "",
    ]

    # ── Applications ────────────────────────────────────────────────────────
    new_apps = [
        a for a in apps
        if a.get("applied_date", a.get("last_updated", ""))[:10] >= week_ago_iso
    ]
    updated_apps = [
        a for a in apps
        if a.get("last_updated", "")[:10] >= week_ago_iso and a not in new_apps
    ]
    lines.append(f"📋  APPLICATIONS")
    lines.append(f"  New this week:     {len(new_apps)}")
    lines.append(f"  Updated this week: {len(updated_apps)}")
    if new_apps:
        for a in new_apps:
            lines.append(f"    + {a['company']} — {a['role']} ({a.get('status', '?')})")
    lines.append("")

    # ── Rejections ───────────────────────────────────────────────────────────
    week_rejects = [r for r in rejections if r.get("date", "") >= week_ago_iso]
    lines.append(f"❌  REJECTIONS THIS WEEK: {len(week_rejects)}")
    if week_rejects:
        stage_counts = Counter(r.get("stage", "unknown") for r in week_rejects)
        for stage, cnt in sorted(stage_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {stage}: {cnt}")
    lines.append("")

    # ── Contacts ─────────────────────────────────────────────────────────────
    new_contacts = [
        p for p in people
        if p.get("added_at", p.get("last_updated", ""))[:10] >= week_ago_iso
    ]
    lines.append(f"👥  CONTACTS ADDED: {len(new_contacts)}")
    for p in new_contacts:
        lines.append(f"  + {p['name']} ({p.get('company', '?')}, {p.get('relationship', '?')})")
    lines.append("")

    # ── Mental health trend ──────────────────────────────────────────────────
    week_entries = [e for e in health_entries if e.get("date", "") >= week_ago_iso]
    lines.append(f"🧠  MENTAL HEALTH ({len(week_entries)} check-in{'s' if len(week_entries) != 1 else ''} this week)")
    if week_entries:
        avg_energy = sum(e.get("energy", 5) for e in week_entries) / len(week_entries)
        mood_counts = Counter(e.get("mood", "?") for e in week_entries)
        productive_days = sum(1 for e in week_entries if e.get("productive"))
        lines.append(f"  Avg energy: {avg_energy:.1f}/10")
        lines.append(f"  Productive days: {productive_days}/{len(week_entries)}")
        top_moods = mood_counts.most_common(3)
        lines.append(f"  Mood distribution: {', '.join(f'{m} ({c}x)' for m, c in top_moods)}")

        if avg_energy <= 4:
            lines.append("  ⚠  Low-energy week. Be gentle with yourself.")
        elif avg_energy >= 7:
            lines.append("  ✓  High-energy week. Ride the momentum.")
    else:
        lines.append("  No check-ins logged this week.")
    lines.append("")

    # ── Pipeline snapshot ────────────────────────────────────────────────────
    active = [a for a in apps if a.get("status", "").lower() not in ("rejected", "withdrew", "closed", "declined")]
    status_counts = Counter(a.get("status", "unknown") for a in active)
    lines.append(f"📊  PIPELINE SNAPSHOT ({len(active)} active)")
    for status, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {status}: {cnt}")
    lines.append("")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_daily_digest)
    mcp.tool()(weekly_summary)
