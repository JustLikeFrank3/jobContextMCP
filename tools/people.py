"""
People / contacts tracking tool — v1

Stores background context on people Frank mentions during his job search:
former coworkers, recruiters, hiring managers, referrals, contacts.

Tools:
  log_person   — add or update a person in the database
  get_people   — retrieve/search the people database
"""

from lib import config, honcho_client
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


def _sync_person_to_honcho(person: dict) -> None:
    """Write/update a person record in the Honcho people session."""
    if not honcho_client.is_available():
        return
    content = (
        f"[Contact #{person['id']}] {person['name']}\n"
        f"Relationship: {person.get('relationship', '')}\n"
        f"Company: {person.get('company', '')}\n"
        f"Background: {person.get('context', '')}\n"
    )
    if person.get("tags"):
        content += f"Tags: {', '.join(person['tags'])}\n"
    if person.get("notes"):
        content += f"Notes: {person['notes']}\n"
    if person.get("outreach_status") and person["outreach_status"] != "none":
        content += f"Outreach status: {person['outreach_status']}\n"
    honcho_client.add_person(
        content,
        metadata={"id": person["id"], "name": person["name"], "company": person.get("company", "")},
    )


def log_person(
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
        relationship:    How Frank knows them (e.g. 'former coworker', 'recruiter',
                         'hiring manager', 'referral contact', 'friend').
        company:         Current or last known company.
        context:         Background info — who they are, how Frank knows them,
                         anything relevant about them.
        tags:            Searchable tags (e.g. ['gm', 'ai', 'java', 'recruiter']).
        contact_info:    LinkedIn URL, email, phone, etc. Optional.
        outreach_status: One of: 'none', 'drafted', 'sent', 'responded'. Default 'none'.
        notes:           Running notes about the relationship or interactions.
        sent_message:    The actual text of a message Frank sent to this person.
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

        _sync_person_to_honcho(existing)
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

    _sync_person_to_honcho(entry)
    return f"✓ Person logged (#{entry['id']}): {entry['name']} — {entry['relationship']} at {entry['company']}{tone_note}"


def get_people(
    name: str = "",
    company: str = "",
    tag: str = "",
    outreach_status: str = "",
) -> str:
    """
    Retrieve people from the contacts database, optionally filtered by name,
    company, tag, or outreach status. Returns all people if no filters given.
    When searching by name only, returns an AI-synthesised relationship summary
    if Honcho is available.
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

    # For a single-name lookup with no other filters, use Honcho synthesis
    if name and not company and not tag and not outreach_status and len(people) == 1:
        if honcho_client.is_available():
            query = (
                f"What do I know about {people[0]['name']}? "
                "Summarise our relationship, their background, any relevant context "
                "for outreach or conversation, and any notes from prior interactions."
            )
            result = honcho_client.query_context(query)
            if result:
                return f"═══ {people[0]['name'].upper()} (Honcho synthesis) ═══\n\n{result}"

    # JSON structured output for multi-result or filtered queries
    lines = [f"═══ PEOPLE DATABASE ({len(people)} result{'s' if len(people) != 1 else ''}) ═══", ""]
    for p in people:
        lines.append(f"#{p['id']} — {p['name']}")
        lines.append(f"   Relationship:    {p.get('relationship', '—')}")
        lines.append(f"   Company:         {p.get('company', '—')}")
        lines.append(f"   Outreach status: {p.get('outreach_status', 'none')}")
        lines.append(f"   Tags:            {', '.join(p.get('tags', [])) or '—'}")
        lines.append(f"   Context:         {p.get('context', '—')}")
        if p.get("contact_info"):
            lines.append(f"   Contact info:    {p['contact_info']}")
        if p.get("notes"):
            lines.append(f"   Notes:           {p['notes']}")
        lines.append(f"   Added:           {p.get('timestamp', '—')}")
        if p.get("last_updated"):
            lines.append(f"   Last updated:    {p['last_updated']}")
        lines.append("")

    return "\n".join(lines).rstrip()


def lookup_person_context(name: str) -> str:
    """Internal helper — returns a compact person summary for injection into other tool contexts."""
    # Try Honcho first for richer synthesis
    if honcho_client.is_available():
        query = (
            f"Give a brief, factual summary of {name}: who they are, how Frank knows them, "
            "their current role, and anything relevant for a job search interaction."
        )
        result = honcho_client.query_context(query)
        if result:
            return result

    # JSON fallback
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


def register(mcp) -> None:
    mcp.tool()(log_person)
    mcp.tool()(get_people)
