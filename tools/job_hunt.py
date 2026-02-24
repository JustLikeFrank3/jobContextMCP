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
        existing.update(
            role=role,
            status=status,
            next_steps=next_steps,
            contact=contact,
            notes=notes,
            last_updated=_now(),
        )
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
                applied_date=_now(),
                last_updated=_now(),
            )
        )
        action = "Added"

    data["last_updated"] = _now()
    _save_json(config.STATUS_FILE, data)
    return f"✓ {action}: {company} — {role} ({status})"


def register(mcp) -> None:
    mcp.tool()(get_job_hunt_status)
    mcp.tool()(update_application)
