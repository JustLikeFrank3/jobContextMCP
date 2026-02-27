from lib import config, honcho_client
from lib.io import _load_json, _save_json
from lib.helpers import _build_story_entry, _filter_stories, _format_story_list


def log_personal_story(
    story: str,
    tags: list[str],
    people: list[str] | None = None,
    title: str = "",
) -> str:
    """Save a personal STAR story to the context library. Tag it with relevant skills or themes (e.g. ['cloud_migration', 'leadership']). Optionally include people involved and a short title. Retrieved later via get_personal_context()."""
    people = people or []

    # Always write to JSON — source of truth and local backup
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    entry = _build_story_entry(data["stories"], story, tags, people, title)
    data["stories"].append(entry)
    _save_json(config.PERSONAL_CONTEXT_FILE, data)

    # Also write to Honcho when configured
    honcho_meta = {
        "id": entry["id"],
        "title": entry["title"],
        "tags": tags,
        "people": people,
    }
    honcho_content = f"[Story #{entry['id']}] {entry['title']}\n\n{story}"
    honcho_client.add_story(honcho_content, metadata=honcho_meta)

    return f"✓ Story logged (#{entry['id']}): {entry['title']}"


def get_personal_context(tag: str = "", person: str = "", query: str = "") -> str:
    """Retrieve stored personal stories, optionally filtered by tag or person's name.
    Pass a freeform `query` to ask Honcho a targeted question (overrides tag/person).
    When Honcho is configured, returns an AI-synthesised view of the relevant stories.
    Falls back to the full JSON list if Honcho is unavailable."""

    # Honcho path — synthesised, reranked response
    if honcho_client.is_available():
        if query:
            honcho_query = query
        else:
            parts = ["Retrieve and summarise the most relevant personal career stories"]
            if tag:
                parts.append(f"related to '{tag}'")
            if person:
                parts.append(f"involving '{person}'")
            if not tag and not person:
                parts.append("across all topics")
            honcho_query = " ".join(parts) + ". Include specific project names, metrics, and outcomes."
        result = honcho_client.query_context(honcho_query)
        if result:
            return result

    # JSON fallback (no Honcho key, or Honcho call failed)
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = _filter_stories(data.get("stories", []), tag, person)

    if not stories:
        qualifier = f" for tag '{tag}'" if tag else ""
        qualifier += f" for person '{person}'" if person else ""
        return f"No personal stories found{qualifier}."

    return _format_story_list(stories)


def register(mcp) -> None:
    mcp.tool()(log_personal_story)
    mcp.tool()(get_personal_context)
