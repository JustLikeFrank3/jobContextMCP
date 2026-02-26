import re
from datetime import date

from lib import config
from lib.io import _load_json, _save_json, _now
from tools.health import get_daily_checkin_nudge

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(
    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*~?\s*(\d{1,2})\b',
    re.IGNORECASE,
)


def _extract_followup_date(text: str) -> date | None:
    """Parse the first recognisable month+day from a next_steps string."""
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1).lower()[:3])
    if month is None:
        return None
    day = int(m.group(2))
    today = date.today()
    year = today.year
    # If the parsed month is already past this year, assume next year
    if month < today.month:
        year += 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _check_overdue_followups(apps: list) -> list[str]:
    """Return reminder lines for any application whose next_steps mentions a date <= today."""
    today = date.today()
    reminders = []
    for app in apps:
        next_steps = app.get("next_steps", "")
        if not next_steps:
            continue
        due = _extract_followup_date(next_steps)
        if due and due <= today:
            label = "TODAY" if due == today else f"OVERDUE since {due.strftime('%b %d')}"
            summary = next_steps[:120].rstrip(".")
            reminders.append(f"  [{label}] {app['company']} — {app['role']}: {summary}")
    return reminders


def get_job_hunt_status() -> str:
    """Return the current job application pipeline: all tracked companies, roles, statuses, next steps, and contacts. Also nudges a daily mental health check-in if none has been logged today."""
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps = data.get("applications", [])
    nudge = get_daily_checkin_nudge()

    if not apps:
        base = "No applications tracked yet. Use update_application() to add one."
        return f"{base}\n\n{nudge}" if nudge else base

    lines = [
        "═══ JOB HUNT STATUS ═══",
        f"Last updated: {data.get('last_updated', 'unknown')}",
        "",
    ]
    for app in apps:
        lines.append(f"■ {app['company']} — {app['role']}")
        lines.append(f"  Status:       {app['status']}")
        lines.append(f"  Last update:  {app.get('last_updated', '—')}")
        if app.get("next_steps"):
            lines.append(f"  Next steps:   {app['next_steps']}")
        if app.get("contact"):
            lines.append(f"  Contact:      {app['contact']}")
        if app.get("notes"):
            lines.append(f"  Notes:        {app['notes']}")
        lines.append("")

    overdue = _check_overdue_followups(apps)
    if overdue:
        lines += ["⚠ FOLLOW-UP ACTIONS DUE:"] + overdue + [""]

    if nudge:
        lines += ["", nudge]

    return "\n".join(lines)


def update_application(
    company: str,
    role: str,
    status: str,
    next_steps: str = "",
    contact: str = "",
    notes: str = "",
) -> str:
    """Add or update a job application in the pipeline tracker. Pass company, role, and current status (e.g. 'applied', 'phone screen', 'offer'). Optionally include next_steps, contact name, and free-form notes."""
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps: list = data.setdefault("applications", [])

    existing = next(
        (
            a
            for a in apps
            if a["company"].lower() == company.lower()
            and a["role"].lower() == role.lower()
        ),
        None,
    )
    if existing is None:
        existing = next((a for a in apps if a["company"].lower() == company.lower()), None)

    if existing:
        existing["role"] = role
        existing["status"] = status
        if next_steps:
            existing["next_steps"] = next_steps
        if contact:
            existing["contact"] = contact
        # Append to notes instead of clobbering — prefix new note with timestamp
        if notes:
            old_notes = existing.get("notes", "")
            if old_notes:
                existing["notes"] = f"{old_notes}\n[{_now()}] {notes}"
            else:
                existing["notes"] = notes
        existing["last_updated"] = _now()
        action = "Updated"
    else:
        apps.append(
            dict(
                company=company,
                role=role,
                status=status,
                next_steps=next_steps,
                contact=contact,
                notes=notes,
                events=[],
                applied_date=_now(),
                last_updated=_now(),
            )
        )
        action = "Added"

    data["last_updated"] = _now()
    _save_json(config.STATUS_FILE, data)
    return f"✓ {action}: {company} — {role} ({status})"


def log_application_event(
    company: str,
    role: str,
    event_type: str,
    notes: str = "",
) -> str:
    """
    Append an event to a tracked application's event log.

    Use this to record milestones without overwriting existing data.
    The event log is append-only — nothing is ever removed or replaced.

    Args:
        company:    Company name (must match an existing application).
        role:       Role title (used to disambiguate if multiple roles at same company).
        event_type: One of: 'applied', 'phone_screen', 'technical_screen', 'take_home',
                    'onsite', 'offer', 'rejected', 'withdrew', 'follow_up', 'note',
                    'referral_submitted', 'recruiter_contact', 'hiring_manager_contact'.
        notes:      Free-form detail about what happened.

    Returns:
        Confirmation string with the appended event.
    """
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps: list = data.setdefault("applications", [])

    existing = next(
        (a for a in apps if a["company"].lower() == company.lower()
         and a["role"].lower() == role.lower()),
        None,
    )
    if existing is None:
        existing = next((a for a in apps if a["company"].lower() == company.lower()), None)

    if existing is None:
        return (
            f"No application found for {company}. "
            "Use update_application() to add it first."
        )

    event = {
        "type": event_type.strip().lower(),
        "notes": notes.strip(),
        "date": _now(),
    }
    existing.setdefault("events", []).append(event)
    existing["last_updated"] = _now()
    data["last_updated"] = _now()
    _save_json(config.STATUS_FILE, data)

    return f"✓ Event logged: {company} — {role} [{event_type}] {notes[:80] if notes else ''}"


def register(mcp) -> None:
    mcp.tool()(get_job_hunt_status)
    mcp.tool()(update_application)
    mcp.tool()(log_application_event)
