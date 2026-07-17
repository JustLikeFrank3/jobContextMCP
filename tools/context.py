from lib import config
from lib.io import _load_json, _save_json
from lib.helpers import _build_story_entry, _filter_stories, _format_story_list


def log_personal_story(
    story: str,
    tags: list[str],
    people: list[str] | None = None,
    title: str = "",
) -> str:
    """Save a personal STAR story to the context library. Tag it with relevant skills or themes (e.g. ['cloud_migration', 'leadership']). Optionally include people involved and a short title. Retrieved later via get_star_story_context()."""
    people = people or []
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    entry = _build_story_entry(data["stories"], story, tags, people, title)
    data["stories"].append(entry)
    _save_json(config.PERSONAL_CONTEXT_FILE, data)
    return f"✓ Story logged (#{entry['id']}): {entry['title']}"


def update_personal_story(
    story_id: int,
    story: str | None = None,
    tags: list[str] | None = None,
    people: list[str] | None = None,
    title: str | None = None,
) -> str:
    """Correct a personal story in place. A wrong fact caught after logging
    should be fixed here, not superseded by a second entry — a superseding
    story just leaves the wrong one sitting in the story library where it
    can still surface in generated documents.

    Only the fields you pass are changed; omit any you want to leave alone.
    """
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = data.get("stories", [])
    entry = next((s for s in stories if s.get("id") == story_id), None)
    if entry is None:
        return f"✗ No story found with id={story_id}."

    if story is not None:
        entry["story"] = story
    if tags is not None:
        entry["tags"] = [t.lower().strip() for t in tags]
    if people is not None:
        entry["people"] = list(people)
    if title is not None:
        entry["title"] = title

    _save_json(config.PERSONAL_CONTEXT_FILE, data)
    return f"✓ Story #{story_id} updated: {entry['title']}"


def delete_personal_story(story_id: int) -> str:
    """Remove a personal story from the library entirely (e.g. a duplicate,
    or one logged in error). For a story with a wrong fact, prefer
    update_personal_story() so the corrected version keeps its id and
    history instead of leaving a gap."""
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = data.get("stories", [])
    entry = next((s for s in stories if s.get("id") == story_id), None)
    if entry is None:
        return f"✗ No story found with id={story_id}."

    stories.remove(entry)
    _save_json(config.PERSONAL_CONTEXT_FILE, data)
    return f"✓ Story #{story_id} deleted: {entry.get('title', '')}"


def get_personal_context(tag: str = "", person: str = "") -> str:
    """Retrieve stored personal stories, optionally filtered by tag or person's name. Returns all stories if no filters provided."""
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = _filter_stories(data.get("stories", []), tag, person)

    if not stories:
        qualifier = f" for tag '{tag}'" if tag else ""
        qualifier += f" for person '{person}'" if person else ""
        return f"No personal stories found{qualifier}."

    return _format_story_list(stories)


def register(mcp) -> None:
    mcp.tool()(log_personal_story)
    mcp.tool()(update_personal_story)
    mcp.tool()(delete_personal_story)
    mcp.tool()(get_personal_context)
