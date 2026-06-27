"""
People / contacts tracking tool — v1

Stores background context on people Frank mentions during his job search:
former coworkers, recruiters, hiring managers, referrals, contacts.

Tools:
  log_person   — add or update a person in the database
  get_people   — retrieve/search the people database
"""

from lib import config
from lib.io import _load_json, _save_json, _now
from tools.tone import log_tone_sample as _log_tone_sample


def _next_id(people: list[dict]) -> int:
    if not people:
        return 1
    return max(p.get("id", 0) for p in people) + 1


def _find_person(people: list[dict], name: str) -> dict | None:
    """Case-insensitive name match."""
    nl = name.strip().lower()
    return next((p for p in people if p.get("name", "").lower() == nl), None)


def log_person(  # NOSONAR
    name: str,
    relationship: str,
    company: str,
    context: str,
    tags: list[str] | None = None,
    contact_info: str = "",
    outreach_status: str = "none",
    notes: str = "",
    sent_message: str = "",
) -> str:
    """
    Add or update a person in the contacts database.

    Call this any time a new person is mentioned with background info — former coworkers,
    recruiters, hiring managers, referrals, or anyone worth remembering.

    Args:
        name:            Full name of the person.
        relationship:    How the candidate knows them (e.g. 'former coworker', 'recruiter',
                         'hiring manager', 'referral contact', 'friend').
        company:         Current or last known company.
        context:         Background info — who they are, how the candidate knows them,
                         anything relevant about them.
        tags:            Searchable tags (e.g. ['gm', 'ai', 'java', 'recruiter']).
        contact_info:    LinkedIn URL, email, phone, etc. Optional.
        outreach_status: One of: 'none', 'drafted', 'sent', 'responded'. Default 'none'.
        notes:           Running notes about the relationship or interactions.
        sent_message:    The actual text of a message the candidate sent to this person.
                         When provided, automatically ingests it as a tone sample.

    Returns:
        Confirmation string with the person's name and assigned ID.
    """
    _VALID_STATUSES = ("none", "drafted", "sent", "responded")
    if outreach_status not in _VALID_STATUSES:
        return f"✗ Invalid outreach_status '{outreach_status}'. Must be one of: {', '.join(_VALID_STATUSES)}"
    tags = tags or []
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    people = data.setdefault("people", [])

    existing = _find_person(people, name)
    if existing:
        # Update in place — merge rather than overwrite
        existing["relationship"] = relationship or existing.get("relationship", "")
        existing["company"] = company or existing.get("company", "")
        existing["context"] = context or existing.get("context", "")
        if tags:
            merged = list(dict.fromkeys(existing.get("tags", []) + tags))
            existing["tags"] = merged
        if contact_info:
            existing["contact_info"] = contact_info
        if outreach_status and outreach_status != "none":
            existing["outreach_status"] = outreach_status
        if notes:
            existing["notes"] = (existing.get("notes", "") + "\n" + notes).strip()
        existing["last_updated"] = _now()
        _save_json(config.PEOPLE_FILE, data)

        tone_note = ""
        if sent_message.strip():
            source = f"outreach_{name.lower().replace(' ', '_')}"
            _log_tone_sample(
                text=sent_message.strip(),
                source=source,
                context=f"Message sent to {name} ({relationship} at {company}).",
            )
            tone_note = " Tone sample auto-logged."

        return f"✓ Updated existing person #{existing['id']}: {existing['name']} ({existing['company']}){tone_note}"

    entry = {
        "id": _next_id(people),
        "timestamp": _now(),
        "name": name.strip(),
        "relationship": relationship.strip(),
        "company": company.strip(),
        "context": context.strip(),
        "tags": tags,
        "contact_info": contact_info.strip(),
        "outreach_status": outreach_status,
        "notes": notes.strip(),
    }
    people.append(entry)
    _save_json(config.PEOPLE_FILE, data)

    tone_note = ""
    if sent_message.strip():
        source = f"outreach_{name.lower().replace(' ', '_')}"
        _log_tone_sample(
            text=sent_message.strip(),
            source=source,
            context=f"Message sent to {name} ({relationship} at {company}).",
        )
        tone_note = " Tone sample auto-logged."

    return f"✓ Person logged (#{entry['id']}): {entry['name']} — {entry['relationship']} at {entry['company']}{tone_note}"


def _format_person_full(p: dict) -> str:
    """Format a single person record with all fields."""
    lines = [
        f"#{p['id']} — {p['name']}",
        f"   Relationship:    {p.get('relationship', '—')}",
        f"   Company:         {p.get('company', '—')}",
        f"   Outreach status: {p.get('outreach_status', 'none')}",
        f"   Tags:            {', '.join(p.get('tags', [])) or '—'}",
        f"   Context:         {p.get('context', '—')}",
    ]
    if p.get("contact_info"):
        lines.append(f"   Contact info:    {p['contact_info']}")
    if p.get("notes"):
        lines.append(f"   Notes:           {p['notes']}")
    lines.append(f"   Added:           {p.get('timestamp', '—')}")
    if p.get("last_updated"):
        lines.append(f"   Last updated:    {p['last_updated']}")
    return "\n".join(lines)


def _format_person_slim(p: dict) -> str:
    """Format a single person record with essential fields only (no notes/context)."""
    lines = [
        f"#{p['id']} — {p['name']}",
        f"   Company:         {p.get('company', '—')}",
        f"   Relationship:    {p.get('relationship', '—')}",
        f"   Outreach status: {p.get('outreach_status', 'none')}",
        f"   Tags:            {', '.join(p.get('tags', [])) or '—'}",
    ]
    if p.get("last_updated"):
        lines.append(f"   Last updated:    {p['last_updated']}")
    return "\n".join(lines)


def get_person(name: str) -> str:
    """
    Look up a single person by name (case-insensitive partial match).

    Returns the full record if exactly one match is found.
    If multiple people match, lists them so you can be more specific.
    Use this instead of get_people() when you only need one person — much
    cheaper on tokens.

    Args:
        name: Full or partial name to search for.

    Returns:
        Full person record, disambiguation list, or not-found message.
    """
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    people = data.get("people", [])

    matches = [p for p in people if name.lower() in p.get("name", "").lower()]

    if not matches:
        return f"No person found matching '{name}'."

    if len(matches) > 1:
        names = ", ".join(f"#{p['id']} {p['name']}" for p in matches)
        return f"Multiple matches for '{name}': {names}. Use a more specific name."

    return _format_person_full(matches[0])


def get_people(
    name: str = "",
    company: str = "",
    tag: str = "",
    outreach_status: str = "",
    slim: bool = False,
) -> str:
    """
    Retrieve people from the contacts database, optionally filtered by name,
    company, tag, or outreach status. Returns all people if no filters given.

    Args:
        name:            Partial name filter (case-insensitive).
        company:         Partial company filter (case-insensitive).
        tag:             Tag filter (exact match, case-insensitive).
        outreach_status: Filter by outreach status.
        slim:            If True, return only name/company/relationship/status/tags
                         with no notes or context. Much cheaper on tokens when you
                         just need to scan the list.
    """
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    people = data.get("people", [])

    if name:
        people = [p for p in people if name.lower() in p.get("name", "").lower()]
    if company:
        people = [p for p in people if company.lower() in p.get("company", "").lower()]
    if tag:
        people = [p for p in people if tag.lower() in [t.lower() for t in p.get("tags", [])]]
    if outreach_status:
        people = [p for p in people if p.get("outreach_status", "").lower() == outreach_status.lower()]

    if not people:
        return "No people found matching those filters."

    fmt = _format_person_slim if slim else _format_person_full
    mode_label = " [slim]" if slim else ""
    lines = [f"═══ PEOPLE DATABASE ({len(people)} result{'s' if len(people) != 1 else ''}){mode_label} ═══", ""]
    for p in people:
        lines.append(fmt(p))
        lines.append("")

    return "\n".join(lines).rstrip()


def lookup_person_context(name: str) -> str:
    """Internal helper — returns a compact person summary for injection into other tool contexts."""
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    person = _find_person(data.get("people", []), name)
    if not person:
        return ""
    parts = [
        f"Known contact: {person['name']} ({person.get('relationship', '?')} at {person.get('company', '?')})",
        f"Background: {person.get('context', '')}",
    ]
    if person.get("notes"):
        parts.append(f"Notes: {person['notes']}")
    if person.get("outreach_status") and person["outreach_status"] != "none":
        parts.append(f"Prior outreach: {person['outreach_status']}")
    return "\n".join(parts)


def get_referral_chains(target_company: str) -> str:  # NOSONAR
    """Find contacts who could potentially refer the candidate to a target company.

    A "referral chain" is any person whose company matches `target_company`
    (case-insensitive substring) and whose `outreach_status` is not already
    "responded". Output is grouped by strength signal:
      * direct  — person currently at the target company
      * adjacent — person whose tags mention the company name or whose
                   context mentions it

    Args:
        target_company: Company name to find referral paths into.

    Returns:
        Formatted text block. Empty-friendly message when no matches.
    """
    if not target_company or not target_company.strip():
        return "⚠ get_referral_chains: target_company is required"
    needle = target_company.strip().lower()

    data = _load_json(config.PEOPLE_FILE, {"people": []})
    people = data.get("people", [])
    if not people:
        return "No contacts logged yet. Use log_person() to start building the network."

    direct: list[dict] = []
    adjacent: list[dict] = []
    for p in people:
        company = (p.get("company") or "").lower()
        tags = [t.lower() for t in p.get("tags", [])]
        context = (p.get("context") or "").lower()
        notes = (p.get("notes") or "").lower()

        if needle and needle in company:
            direct.append(p)
        elif needle and (needle in " ".join(tags) or needle in context or needle in notes):
            adjacent.append(p)

    if not direct and not adjacent:
        return f"No referral paths found for {target_company!r}."

    lines = [f"# Referral chains for {target_company}"]

    def _fmt(p: dict) -> str:
        status = p.get("outreach_status", "none")
        contact = f" — {p['contact_info']}" if p.get("contact_info") else ""
        return (
            f"- {p.get('name','?')} ({p.get('relationship','?')} @ {p.get('company','?')})"
            f" [outreach: {status}]{contact}"
        )

    if direct:
        lines.append("")
        lines.append(f"## Direct ({len(direct)} at target company)")
        for p in direct:
            lines.append(_fmt(p))
    if adjacent:
        lines.append("")
        lines.append(f"## Adjacent ({len(adjacent)} mention the company)")
        for p in adjacent:
            lines.append(_fmt(p))
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(log_person)
    mcp.tool()(get_people)
    mcp.tool()(get_person)
    mcp.tool()(get_referral_chains)
