"""
ingest_anecdote — intent-level bundler.

One call logs a story to:
  - personal_context.json          (always)
  - tone_samples.json              (if tone_sample=True, story >= 40 words)

Also reports whether the story's tags match known STAR interview tags so the
caller knows it will surface in get_star_story_context() queries.
"""

from lib import config
from lib.io import _load_json, _save_json
from lib.helpers import _build_story_entry, _build_tone_sample_entry

# Tags that map to interview-relevant STAR categories in star.py
_STAR_TAGS: frozenset[str] = frozenset({
    "testing", "quality", "craftsmanship", "solo-developer", "cloud",
    "ai", "leadership", "modernization", "ford", "grandfather",
    "cloud_migration", "azure", "ai_adoption", "cross_team", "speak_up",
    "innovation", "product_idea", "iot", "cameras", "diagonal_slice",
    "testing_automation", "tdd", "ci_cd", "sla", "migration",
})


def ingest_anecdote(
    story: str,
    tags: list[str],
    title: str = "",
    people: list[str] | None = None,
    tone_sample: bool = True,
) -> str:
    """
    Log a personal story, work anecdote, or STAR narrative in one call.

    Always saves to the personal context library. If tone_sample=True (default)
    and the story is at least 40 words, also ingests it as a tone/voice sample.
    Reports which STAR interview tags were detected so you know the story will
    surface in get_star_story_context() queries.

    Args:
        story:       The narrative — raw, first-person, as much detail as useful.
        tags:        Relevant themes (e.g. ['leadership', 'azure', 'cloud_migration']).
        title:       Short label for the story. Auto-generated from tags if omitted.
        people:      Names of people involved (e.g. ['Pat McDevitt', 'Andrea Samo']).
        tone_sample: Whether to also ingest the story text as a voice/tone sample.
                     Skipped automatically if story is under 40 words.
    """
    people = people or []
    logged: list[str] = []

    # 1. Always log to personal context
    ctx_data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    entry = _build_story_entry(ctx_data["stories"], story, tags, people, title)
    ctx_data["stories"].append(entry)
    _save_json(config.PERSONAL_CONTEXT_FILE, ctx_data)
    logged.append(f"personal context (#{entry['id']}): {entry['title']}")

    # 2. Optionally ingest as tone sample
    word_count = len(story.split())
    tone_logged = False
    if tone_sample and word_count >= 40:
        tone_source = f"anecdote_{entry['id']}_{tags[0] if tags else 'story'}"
        tone_ctx = f"Story #{entry['id']}: {entry['title']}"
        tone_data = _load_json(config.TONE_FILE, {"samples": []})
        tone_entry = _build_tone_sample_entry(tone_data["samples"], story, tone_source, tone_ctx)
        tone_data["samples"].append(tone_entry)
        _save_json(config.TONE_FILE, tone_data)
        logged.append(f"tone profile (#{tone_entry['id']}, {word_count} words)")
        tone_logged = True
    elif tone_sample and word_count < 40:
        logged.append(f"tone profile skipped (only {word_count} words, min 40)")

    # 3. Detect STAR-relevant tags
    matched_star = sorted(set(t.lower() for t in tags) & _STAR_TAGS)

    lines = [f"✓ Anecdote ingested — {len(logged)} destination(s):"]
    for item in logged:
        lines.append(f"  • {item}")

    if matched_star:
        lines.append(f"\nSTAR tags detected: {', '.join(matched_star)}")
        lines.append("→ Will surface in get_star_story_context() for these tags.")
    else:
        lines.append("\nNo STAR interview tags matched.")
        lines.append("→ Add tags like 'leadership', 'cloud_migration', 'testing' to make it retrievable during interview prep.")

    if not tone_logged and tone_sample and word_count >= 40:
        pass  # already noted above
    elif not tone_sample:
        lines.append("\nTip: set tone_sample=True to also calibrate Frank's voice profile from this story.")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(ingest_anecdote)
