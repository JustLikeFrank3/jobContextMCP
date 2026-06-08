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


# ── closed / waiting token sets (used for filtering) ──────────────────────────

# Statuses that mean the opportunity is over — excluded from all digest sections
_CLOSED_TOKENS = frozenset({
    "rejected", "withdrew", "closed", "declined", "passed",
    "role filled", "no suitable role", "abandoned",
})

# Statuses that mean "ball is in their court"
_WAITING_TOKENS = frozenset({
    "applied", "phone screen", "technical screen", "take-home",
    "onsite", "final round", "offer", "interviewing",
    "referral submitted", "background check", "pre-application",
    "interested",
})

# Event types worth surfacing as recent progress
_PROGRESS_EVENT_TYPES = frozenset({
    "applied", "phone_screen", "technical_screen", "take_home", "onsite",
    "offer", "referral_submitted", "recruiter_contact", "hiring_manager_contact",
    "outreach_sent", "recruiter_reengaged", "meeting_scheduled", "reply_sent",
    "referral_path_confirmed", "referral_confirmed",
})

_PROGRESS_LABELS = {
    "applied": "Applied",
    "phone_screen": "Phone screen",
    "technical_screen": "Technical screen",
    "take_home": "Take-home sent",
    "onsite": "Onsite",
    "offer": "Offer received",
    "referral_submitted": "Referral submitted",
    "recruiter_contact": "Recruiter contact",
    "hiring_manager_contact": "HM contact",
    "outreach_sent": "Outreach sent",
    "recruiter_reengaged": "Recruiter re-engaged",
    "meeting_scheduled": "Meeting scheduled",
    "reply_sent": "Reply sent",
    "referral_path_confirmed": "Referral confirmed",
    "referral_confirmed": "Referral confirmed",
}


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


def _load_queue() -> list[dict]:
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    return data.get("jobs", [])


def _load_rejections() -> list[dict]:
    data = _load_json(config.REJECTIONS_FILE, {"rejections": []})
    return data.get("rejections", [])


def _load_people() -> list[dict]:
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    return data.get("people", [])


def _load_health() -> list[dict]:
    data = _load_json(config.HEALTH_LOG_FILE, {"entries": []})
    return data.get("entries", [])


def _is_closed(app: dict) -> bool:
    """Return True if the app status matches any closed/archived token."""
    status = app.get("status", "").lower()
    return any(token in status for token in _CLOSED_TOKENS)


def _is_waiting(app: dict) -> bool:
    """Return True if the app is in a state where the ball is in their court."""
    status = app.get("status", "").lower()
    return any(token in status for token in _WAITING_TOKENS)


def _short_note(text: str, max_len: int = 70) -> str:
    """Return the first sentence of a notes string, capped at max_len chars."""
    if not text:
        return ""
    first = text.strip().split(".")[0].split("\n")[0]
    if len(first) <= max_len:
        return first
    return first[:max_len].rstrip() + "..."


# ── get_daily_digest ───────────────────────────────────────────────────────────

def get_daily_digest() -> str:
    """
    Return a morning briefing for the job search day.

    Sections:
    - PIPELINE       total active / in-flight counts
    - ACTION         overdue follow-ups + unsent drafted messages
    - WAITING        applied/in-process apps (ball in their court)
    - NEEDS REVIEW   stale apps (14+ days, not waiting) — up to 5
    - RECENT         positive signals from app event logs (last 7 days)
    - FOCUS          top 3 priorities derived from above
    - WELLBEING      nudge suppressed if check-in logged within 3 days

    Filtering:
    - Closed/archived statuses excluded from all sections.
    - Apps inactive 60+ days with no next_steps silently dropped.

    Returns:
        Formatted daily digest string.
    """
    today = datetime.date.today()
    days_label = today.strftime("%A, %B %d, %Y")
    week_ago_iso = (today - datetime.timedelta(days=7)).isoformat()

    apps = _load_apps()
    rejections = _load_rejections()
    people = _load_people()
    health_entries = _load_health()
    queue_jobs = _load_queue()

    # ── Filter: drop closed and long-dormant with nothing pending ─────────────
    active = [
        a for a in apps
        if not _is_closed(a)
        and not (
            _days_since(a.get("last_updated", "")) >= 60
            and not a.get("next_steps")
        )
    ]

    lines = [
        "╔══════════════════════════════════════╗",
        f"║  DAILY DIGEST  —  {days_label}",
        "╚══════════════════════════════════════╝",
        "",
    ]

    # ── PIPELINE snapshot ─────────────────────────────────────────────────────
    waiting = [a for a in active if _is_waiting(a)]
    closed_count = sum(1 for a in apps if _is_closed(a))
    lines.append(f"  PIPELINE: {len(active)} active  /  {len(waiting)} in flight  /  {closed_count} closed")
    lines.append("")

    # ── NEEDS DECISION: jobs in queue awaiting apply/dismiss ──────────────────
    undecided = [j for j in queue_jobs if j.get("status") in ("pending", "evaluated")]
    if undecided:
        lines.append("  NEEDS DECISION  (apply or dismiss):")
        for j in undecided:
            status_label = j.get("status", "?").upper()
            score = f"  score: {j['fitment_score']}" if j.get("fitment_score") else ""
            lines.append(f"    [{status_label}] {j['company']} — {j['role']}{score}")
        lines.append("")

    # ── ACTION: overdue follow-ups ────────────────────────────────────────────
    overdue = _check_overdue_followups(active)
    if overdue:
        lines.append("  ACTION  —  FOLLOW-UPS DUE:")
        for reminder in overdue:
            # Trim verbose next_steps text; keep [LABEL] Company — Role only
            trimmed = reminder[:reminder.index(":")] if ":" in reminder else reminder[:100]
            lines.append(trimmed)
        lines.append("")

    # ── ACTION: drafted messages not yet sent ─────────────────────────────────
    drafted_unsent = [
        p for p in people
        if p.get("outreach_status", "").lower() == "drafted"
    ]
    if drafted_unsent:
        lines.append("  ACTION  —  DRAFTED BUT NOT SENT:")
        for p in drafted_unsent:
            lines.append(f"    {p['name']}  ({p.get('company', '?')})")
        lines.append("")

    # ── WAITING on others ─────────────────────────────────────────────────────
    if waiting:
        lines.append("  WAITING ON OTHERS:")
        for a in sorted(waiting, key=lambda x: x.get("last_updated", ""), reverse=True):
            age = _days_since(a.get("last_updated", ""))
            status = a.get("status", "?").split("—")[0].strip()[:35]
            lines.append(f"    {a['company']} — {a['role']}  ({status}, {age}d)")
        lines.append("")

    # ── NEEDS REVIEW: stale non-waiting apps (replaces old "stale" dump) ──────
    overdue_companies = {
        r.split("]")[-1].split("—")[0].strip()
        for r in overdue if "]" in r
    }
    needs_review = [
        a for a in active
        if not _is_waiting(a)
        and _days_since(a.get("last_updated", "")) >= 14
        and a.get("company", "") not in overdue_companies
    ]
    needs_review.sort(key=lambda x: _days_since(x.get("last_updated", "")), reverse=True)
    if needs_review:
        lines.append("  NEEDS REVIEW  (follow up / archive / re-engage):")
        for a in needs_review[:5]:
            age = _days_since(a.get("last_updated", ""))
            lines.append(f"    {a['company']} — {a['role']}  ({age}d)")
        lines.append("")

    # ── RECENT PROGRESS (last 7 days from event logs) ─────────────────────────
    progress_items = []
    for app in apps:
        for ev in app.get("events", []):
            if ev.get("type") in _PROGRESS_EVENT_TYPES and ev.get("date", "") >= week_ago_iso:
                label = _PROGRESS_LABELS.get(ev["type"], ev["type"].replace("_", " "))
                note = _short_note(ev.get("notes", ""), 60)
                summary = note if note else label
                progress_items.append((ev["date"], app["company"], summary))
    progress_items.sort(key=lambda x: x[0], reverse=True)
    if progress_items:
        lines.append("  RECENT PROGRESS:")
        for _, company, summary in progress_items[:5]:
            lines.append(f"    {company} — {summary}")
        lines.append("")

    # ── TOTALS ────────────────────────────────────────────────────────────────
    total_rejections = len(rejections)
    lines.append(f"  TOTALS: {len(apps)} apps tracked  /  {total_rejections} rejection{'s' if total_rejections != 1 else ''} logged")
    lines.append("")

    # ── TODAY'S FOCUS (top 3 priorities) ──────────────────────────────────────
    priorities = []
    if overdue:
        company = overdue[0].split("]")[-1].split("—")[0].strip() if "]" in overdue[0] else "overdue item"
        priorities.append(f"Follow up: {company}")
    if drafted_unsent:
        priorities.append(f"Send message to {drafted_unsent[0]['name']}")
    if needs_review and len(priorities) < 3:
        top = needs_review[0]
        priorities.append(f"Review: {top['company']} — {top['role']}")
    if undecided and len(priorities) < 3:
        top = undecided[0]
        verb = "Apply to" if top.get("status") == "evaluated" else "Evaluate"
        priorities.append(f"{verb}: {top['company']} — {top['role']}")
    if not priorities:
        if waiting:
            priorities.append(f"Check on {waiting[0]['company']} — {waiting[0]['role']}")
        priorities.append("Apply to 2-3 new roles")
        priorities.append("Log a check-in after the session")

    lines.append("  TODAY'S FOCUS:")
    for i, p in enumerate(priorities[:3], 1):
        lines.append(f"    {i}. {p}")
    lines.append("")

    # ── WELLBEING nudge — only if no check-in in the last 3 days ─────────────
    three_days_ago = (today - datetime.timedelta(days=3)).isoformat()
    recent_checkin = any(e.get("date", "") >= three_days_ago for e in health_entries)
    if not recent_checkin:
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

    # ── Applications ─────────────────────────────────────────────────────────
    new_apps = [
        a for a in apps
        if a.get("applied_date", a.get("last_updated", ""))[:10] >= week_ago_iso
    ]
    updated_apps = [
        a for a in apps
        if a.get("last_updated", "")[:10] >= week_ago_iso and a not in new_apps
    ]
    lines.append("  APPLICATIONS")
    lines.append(f"  New this week:     {len(new_apps)}")
    lines.append(f"  Updated this week: {len(updated_apps)}")
    if new_apps:
        for a in new_apps:
            lines.append(f"    + {a['company']} — {a['role']} ({a.get('status', '?')})")
    lines.append("")

    # ── Rejections ────────────────────────────────────────────────────────────
    week_rejects = [r for r in rejections if r.get("date", "") >= week_ago_iso]
    lines.append(f"  REJECTIONS THIS WEEK: {len(week_rejects)}")
    if week_rejects:
        stage_counts = Counter(r.get("stage", "unknown") for r in week_rejects)
        for stage, cnt in sorted(stage_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {stage}: {cnt}")
    lines.append("")

    # ── Contacts ──────────────────────────────────────────────────────────────
    new_contacts = [
        p for p in people
        if p.get("added_at", p.get("last_updated", ""))[:10] >= week_ago_iso
    ]
    lines.append(f"  CONTACTS ADDED: {len(new_contacts)}")
    for p in new_contacts:
        lines.append(f"    + {p['name']} ({p.get('company', '?')}, {p.get('relationship', '?')})")
    lines.append("")

    # ── Mental health trend ───────────────────────────────────────────────────
    week_entries = [e for e in health_entries if e.get("date", "") >= week_ago_iso]
    lines.append(f"  MENTAL HEALTH ({len(week_entries)} check-in{'s' if len(week_entries) != 1 else ''} this week)")
    if week_entries:
        avg_energy = sum(e.get("energy", 5) for e in week_entries) / len(week_entries)
        mood_counts = Counter(e.get("mood", "?") for e in week_entries)
        productive_days = sum(1 for e in week_entries if e.get("productive"))
        lines.append(f"  Avg energy: {avg_energy:.1f}/10")
        lines.append(f"  Productive days: {productive_days}/{len(week_entries)}")
        top_moods = mood_counts.most_common(3)
        lines.append(f"  Mood distribution: {', '.join(f'{m} ({c}x)' for m, c in top_moods)}")
        if avg_energy <= 4:
            lines.append("  Low-energy week. Be gentle with yourself.")
        elif avg_energy >= 7:
            lines.append("  High-energy week. Ride the momentum.")
    else:
        lines.append("  No check-ins logged this week.")
    lines.append("")

    # ── Pipeline snapshot ─────────────────────────────────────────────────────
    pipeline_active = [a for a in apps if not _is_closed(a)]
    status_counts = Counter(a.get("status", "unknown") for a in pipeline_active)
    lines.append(f"  PIPELINE SNAPSHOT ({len(pipeline_active)} active)")
    for status, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
        lines.append(f"    {status}: {cnt}")
    lines.append("")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_daily_digest)
    mcp.tool()(weekly_summary)
