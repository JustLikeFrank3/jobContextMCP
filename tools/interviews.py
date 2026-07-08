"""
Interview transcript / debrief tracking tool — v6

Stores structured records of recruiter screens, hiring manager calls, panels,
and onsite loops. Captures the things that JDs never tell you:
  * What landed in the room (specific moments, framings, jokes)
  * What didn't land (rough spots, recovered or not)
  * Verbatim quotes from interviewers (highest-signal context)
  * HM priorities surfaced on the call but absent from the JD
  * Process details, comp signals, follow-up commitments

Generators (fitment, resume, cover letter) automatically pull matching
interview context when company/role match a logged interview.

Tools:
  log_interview    — add or update an interview record
  get_interviews   — retrieve/filter interviews with structured summary
  get_interview_context  — pull all interviews for a company/role as a
                           context block ready to feed into resume / CL /
                           prep generation
"""

from lib import config
from lib.io import _load_json, _save_json, _now


# ── Constants ─────────────────────────────────────────────────────────────────

VALID_INTERVIEW_TYPES = {
    "recruiter_screen",
    "hiring_manager",
    "technical",
    "panel",
    "onsite_loop",
    "informational",
    "team_match",
    "behavioral",
    "system_design",
    "coding",
    "debrief",
}

VALID_FORMATS = {"phone", "video", "in_person", "async"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_id(interviews: list[dict]) -> int:
    if not interviews:
        return 1
    return max(i.get("id", 0) for i in interviews) + 1


def _as_str_list(value) -> list[str]:
    """Coerce a list-ish tool argument to a list of strings.

    LLM tool calls routinely pass a plain string where the schema says
    list[str]; ``list("Proceed as…")`` explodes it into characters (the Cox
    follow_up_commitments corruption). A string becomes a one-item list; an
    iterable is stringified item-wise; None is empty.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    try:
        return [str(v).strip() for v in value if str(v).strip()]
    except TypeError:
        return [str(value)]


def _find_interview(
    interviews: list[dict],
    interview_id: int | None = None,
    company: str = "",
    interview_date: str = "",
) -> dict | None:
    """Locate by id, or by (company + interview_date) composite key."""
    if interview_id is not None:
        return next((i for i in interviews if i.get("id") == interview_id), None)
    if company and interview_date:
        cl = company.strip().lower()
        dl = interview_date.strip()
        return next(
            (
                i
                for i in interviews
                if i.get("company", "").lower() == cl
                and i.get("interview_date", "").startswith(dl)
            ),
            None,
        )
    return None


def _normalize_quotes(quotes) -> list[dict]:
    """Accept either list[str] (treated as interviewer quotes) or
    list[dict] with {speaker, quote, context} keys. Return list[dict]."""
    if not quotes:
        return []
    if isinstance(quotes, str):
        quotes = [quotes]  # a bare string would iterate as characters
    normalized = []
    for q in quotes:
        if isinstance(q, str):
            normalized.append({"speaker": "interviewer", "quote": q, "context": ""})
        elif isinstance(q, dict):
            normalized.append({
                "speaker": (q.get("speaker") or "interviewer").strip(),
                "quote": (q.get("quote") or "").strip(),
                "context": (q.get("context") or "").strip(),
            })
    return [q for q in normalized if q["quote"]]


# ── Tools ─────────────────────────────────────────────────────────────────────

def log_interview(  # NOSONAR — 18 params are intentional: structured debrief schema for MCP tool contract
    company: str,
    role: str,
    interview_date: str,
    interview_type: str,
    interviewer: str = "",
    interviewer_role: str = "",
    duration_minutes: int | None = None,
    self_rating: int | None = None,
    interview_format: str = "video",
    what_landed: list[str] | None = None,
    what_didnt: list[str] | None = None,
    verbatim_quotes: list | None = None,
    surfaced_priorities: list[str] | None = None,
    process_details: str = "",
    comp_signals: str = "",
    follow_up_commitments: list[str] | None = None,
    tags: list[str] | None = None,
    notes: str = "",
) -> str:
    """
    Add or update a structured interview / call debrief record.

    If an interview already exists for the same company + interview_date,
    the existing record is updated (additive merge for list fields).

    Args:
        company:               Target company name.
        role:                  Specific role discussed.
        interview_date:        ISO date or datetime string (YYYY-MM-DD or YYYY-MM-DD HH:MM).
        interview_type:        One of: recruiter_screen, hiring_manager, technical,
                               panel, onsite_loop, informational, team_match,
                               behavioral, system_design, coding, debrief.
        interviewer:           Interviewer's name (empty for panels: list in notes).
        interviewer_role:      Interviewer's title / function.
        duration_minutes:      Length of the call in minutes.
        self_rating:           Self-rated performance, 1-10.
        interview_format:      phone, video, in_person, async. Defaults to video.
        what_landed:           List of specific moments / framings that worked.
        what_didnt:            List of rough spots, recovered or not.
        verbatim_quotes:       List of either strings (assumed interviewer) or
                               dicts {speaker, quote, context}.
        surfaced_priorities:   HM/team priorities surfaced on the call that are
                               NOT in the public JD — highest signal for
                               tailoring the next artifact.
        process_details:       Next steps, format of next round, scheduling info.
        comp_signals:          Any comp discussion (anchors, ranges, reactions).
        follow_up_commitments: Things you said you'd send / do after the call.
        tags:                  Free-form tags for retrieval.
        notes:                 Free-form long-form notes.

    Returns:
        Confirmation string with interview ID.
    """
    if interview_type not in VALID_INTERVIEW_TYPES:
        return (
            f"✗ Invalid interview_type '{interview_type}'. "
            f"Valid: {', '.join(sorted(VALID_INTERVIEW_TYPES))}"
        )
    if interview_format not in VALID_FORMATS:
        return (
            f"✗ Invalid interview_format '{interview_format}'. "
            f"Valid: {', '.join(sorted(VALID_FORMATS))}"
        )
    if self_rating is not None:
        try:
            self_rating = max(1, min(10, int(self_rating)))
        except (TypeError, ValueError):
            return "✗ self_rating must be an integer 1-10."

    what_landed = _as_str_list(what_landed)
    what_didnt = _as_str_list(what_didnt)
    surfaced_priorities = _as_str_list(surfaced_priorities)
    follow_up_commitments = _as_str_list(follow_up_commitments)
    tags = _as_str_list(tags)
    quotes = _normalize_quotes(verbatim_quotes)

    data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
    interviews = data.setdefault("interviews", [])

    existing = _find_interview(interviews, company=company, interview_date=interview_date)
    if existing:
        # Additive merge for list fields, replace for scalars.
        existing["role"] = role or existing.get("role", "")
        existing["interview_type"] = interview_type
        existing["interview_format"] = interview_format
        if interviewer:
            existing["interviewer"] = interviewer
        if interviewer_role:
            existing["interviewer_role"] = interviewer_role
        if duration_minutes is not None:
            existing["duration_minutes"] = duration_minutes
        if self_rating is not None:
            existing["self_rating"] = self_rating
        if process_details:
            existing["process_details"] = process_details
        if comp_signals:
            existing["comp_signals"] = comp_signals
        if notes:
            existing["notes"] = notes

        for field, addition in (
            ("what_landed", what_landed),
            ("what_didnt", what_didnt),
            ("surfaced_priorities", surfaced_priorities),
            ("follow_up_commitments", follow_up_commitments),
        ):
            if addition:
                merged = list(existing.get(field, []))
                for item in addition:
                    if item and item not in merged:
                        merged.append(item)
                existing[field] = merged

        if tags:
            existing["tags"] = list(dict.fromkeys(existing.get("tags", []) + tags))

        if quotes:
            existing_quotes = existing.get("verbatim_quotes", [])
            existing_keys = {(q.get("speaker"), q.get("quote")) for q in existing_quotes}
            for q in quotes:
                if (q["speaker"], q["quote"]) not in existing_keys:
                    existing_quotes.append(q)
            existing["verbatim_quotes"] = existing_quotes

        existing["last_updated"] = _now()
        _save_json(config.INTERVIEWS_FILE, data)
        return f"✓ Updated existing interview #{existing['id']}: {company} / {role} ({interview_date})"

    entry = {
        "id": _next_id(interviews),
        "timestamp": _now(),
        "company": company.strip(),
        "role": role.strip(),
        "interview_date": interview_date.strip(),
        "interview_type": interview_type,
        "interview_format": interview_format,
        "interviewer": interviewer.strip(),
        "interviewer_role": interviewer_role.strip(),
        "duration_minutes": duration_minutes,
        "self_rating": self_rating,
        "what_landed": what_landed,
        "what_didnt": what_didnt,
        "verbatim_quotes": quotes,
        "surfaced_priorities": surfaced_priorities,
        "process_details": process_details.strip(),
        "comp_signals": comp_signals.strip(),
        "follow_up_commitments": follow_up_commitments,
        "tags": [t.strip().lower() for t in tags if t.strip()],
        "notes": notes.strip(),
        "last_updated": _now(),
    }
    interviews.append(entry)
    _save_json(config.INTERVIEWS_FILE, data)
    return f"✓ Interview logged #{entry['id']}: {company} / {role} ({interview_date})"


def get_interviews(  # NOSONAR
    company: str = "",
    role: str = "",
    interviewer: str = "",
    interview_type: str = "",
    tag: str = "",
    since: str = "",
    include_full: bool = False,
) -> str:
    """
    Retrieve interview records with structured summary.

    Args:
        company:        Filter by company name (partial, case-insensitive).
        role:           Filter by role (partial, case-insensitive).
        interviewer:    Filter by interviewer name (partial, case-insensitive).
        interview_type: Exact match on interview_type.
        tag:            Filter by tag (exact, case-insensitive).
        since:          ISO date — only interviews on/after this date.
        include_full:   If True, include full quotes / landed / didn't lists
                        for each match. Default False = compact summary.

    Returns:
        Formatted text block of matching interviews.
    """
    data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
    interviews = data.get("interviews", [])

    if not interviews:
        return "No interviews logged yet. Use log_interview() to add a debrief."

    filtered = interviews
    if company:
        cl = company.lower()
        filtered = [i for i in filtered if cl in i.get("company", "").lower()]
    if role:
        rl = role.lower()
        filtered = [i for i in filtered if rl in i.get("role", "").lower()]
    if interviewer:
        il = interviewer.lower()
        filtered = [i for i in filtered if il in i.get("interviewer", "").lower()]
    if interview_type:
        filtered = [i for i in filtered if i.get("interview_type") == interview_type]
    if tag:
        tl = tag.lower()
        filtered = [i for i in filtered if tl in [t.lower() for t in i.get("tags", [])]]
    if since:
        filtered = [i for i in filtered if i.get("interview_date", "") >= since]

    if not filtered:
        return "No interviews match the given filters."

    filtered = sorted(filtered, key=lambda i: i.get("interview_date", ""), reverse=True)

    lines = [f"═══ INTERVIEWS ({len(filtered)} found) ═══", ""]
    for i in filtered:
        rating = f" | self-rated {i['self_rating']}/10" if i.get("self_rating") is not None else ""
        duration = f" | {i['duration_minutes']}min" if i.get("duration_minutes") else ""
        lines.append(
            f"#{i['id']} — {i.get('company', '?')} / {i.get('role', '?')}"
        )
        lines.append(
            f"  {i.get('interview_date', '?')} | {i.get('interview_type', '?')}"
            f"{duration}{rating}"
        )
        if i.get("interviewer"):
            ir = f" ({i['interviewer_role']})" if i.get("interviewer_role") else ""
            lines.append(f"  with: {i['interviewer']}{ir}")
        if include_full:
            if i.get("what_landed"):
                lines.append("  WHAT LANDED:")
                for item in i["what_landed"]:
                    lines.append(f"    • {item}")
            if i.get("what_didnt"):
                lines.append("  WHAT DIDN'T:")
                for item in i["what_didnt"]:
                    lines.append(f"    • {item}")
            if i.get("verbatim_quotes"):
                lines.append("  QUOTES:")
                for q in i["verbatim_quotes"]:
                    ctx = f" [{q['context']}]" if q.get("context") else ""
                    lines.append(f"    «{q['speaker']}»: \"{q['quote']}\"{ctx}")
            if i.get("surfaced_priorities"):
                lines.append("  PRIORITIES SURFACED (not in JD):")
                for p in i["surfaced_priorities"]:
                    lines.append(f"    • {p}")
            if i.get("process_details"):
                lines.append(f"  PROCESS: {i['process_details']}")
            if i.get("comp_signals"):
                lines.append(f"  COMP: {i['comp_signals']}")
            if i.get("follow_up_commitments"):
                lines.append("  FOLLOW-UP COMMITMENTS:")
                for c in i["follow_up_commitments"]:
                    lines.append(f"    • {c}")
            if i.get("notes"):
                lines.append(f"  NOTES: {i['notes']}")
        lines.append("")

    return "\n".join(lines)


def get_interview_context(company: str, role: str = "") -> str:  # NOSONAR
    """
    Pull all interview history for a company (optionally filtered by role) as
    a structured context block. Designed to be appended to fitment assessments,
    resume generation, and cover letter generation prompts so that prior
    in-room signal (verbatim quotes, surfaced HM priorities, what landed)
    feeds the next artifact.

    Returns an empty string if no matching interviews exist — safe to
    unconditionally append to generator context.

    Args:
        company: Target company (required, case-insensitive substring match).
        role:    Optional role filter (case-insensitive substring match).

    Returns:
        Formatted context block, or "" if no matches.
    """
    if not company:
        return ""

    data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
    interviews = data.get("interviews", [])
    if not interviews:
        return ""

    cl = company.lower()
    matches = [i for i in interviews if cl in i.get("company", "").lower()]
    if role:
        rl = role.lower()
        matches = [i for i in matches if rl in i.get("role", "").lower()]
    if not matches:
        return ""

    matches = sorted(matches, key=lambda i: i.get("interview_date", ""))

    lines = [
        f"──── PRIOR INTERVIEW CONTEXT ({company}) ────",
        "(Verbatim signal from in-room conversations — weight this heavily over",
        " the public JD when tailoring artifacts. These are what the recruiter or",
        " HM actually said matters.)",
        "",
    ]
    for i in matches:
        interviewer_role = i.get('interviewer_role')
        role_suffix = f" ({interviewer_role})" if interviewer_role else ""
        lines.append(
            f"▪ {i.get('interview_date', '?')} — {i.get('interview_type', '?')}"
            f" with {i.get('interviewer', 'unknown')}"
            f"{role_suffix}"
        )
        if i.get("self_rating") is not None:
            lines.append(f"  Self-rated: {i['self_rating']}/10")
        if i.get("surfaced_priorities"):
            lines.append("  HM priorities surfaced (NOT in public JD):")
            for p in i["surfaced_priorities"]:
                lines.append(f"    → {p}")
        if i.get("what_landed"):
            lines.append("  What landed in the room:")
            for item in i["what_landed"]:
                lines.append(f"    ✓ {item}")
        if i.get("what_didnt"):
            lines.append("  What was rough (avoid repeating):")
            for item in i["what_didnt"]:
                lines.append(f"    ✗ {item}")
        if i.get("verbatim_quotes"):
            lines.append("  Verbatim quotes:")
            for q in i["verbatim_quotes"]:
                ctx = f" [{q['context']}]" if q.get("context") else ""
                lines.append(f"    «{q['speaker']}»: \"{q['quote']}\"{ctx}")
        if i.get("comp_signals"):
            lines.append(f"  Comp signal: {i['comp_signals']}")
        if i.get("process_details"):
            lines.append(f"  Process detail: {i['process_details']}")
        if i.get("notes"):
            lines.append(f"  Notes: {i['notes']}")
        lines.append("")

    return "\n".join(lines)


def get_upcoming_interviews(days_ahead: int = 14) -> str:
    """Return interviews whose interview_date is on/after today, soonest first.

    Args:
        days_ahead: Window upper bound (days from today). Default 14.

    Returns:
        Formatted summary, or a friendly empty message.
    """
    import datetime as _dt

    data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
    interviews = data.get("interviews", [])
    if not interviews:
        return "No interviews logged yet."

    today = _dt.date.today()
    upper = today + _dt.timedelta(days=max(0, days_ahead))

    def _parse(d: str):
        try:
            return _dt.date.fromisoformat((d or "")[:10])
        except Exception:
            return None

    upcoming = []
    for i in interviews:
        d = _parse(i.get("interview_date", ""))
        if d is None:
            continue
        if today <= d <= upper:
            upcoming.append((d, i))

    if not upcoming:
        return f"No interviews scheduled in the next {days_ahead} days."

    upcoming.sort(key=lambda t: t[0])
    lines = [f"# Upcoming interviews (next {days_ahead} days, {len(upcoming)} total)"]
    for d, i in upcoming:
        days_out = (d - today).days
        when = "today" if days_out == 0 else f"in {days_out}d"
        lines.append(
            f"- {d.isoformat()} ({when}): {i.get('company','?')} / {i.get('role','?')}"
            f" — {i.get('interview_type','?')}"
            + (f" with {i['interviewer']}" if i.get("interviewer") else "")
        )
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(log_interview)
    mcp.tool()(get_interviews)
    mcp.tool()(get_interview_context)
    mcp.tool()(get_upcoming_interviews)
