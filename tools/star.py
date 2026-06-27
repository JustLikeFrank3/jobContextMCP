from lib import config
from lib.io import _load_json


# Metrics are loaded per-user from personal_context.json at runtime.
# This dict is intentionally empty — do not add hardcoded data here.
_STAR_METRICS: dict[str, list[str]] = {}

_STAR_RELATED: dict[str, list[str]] = {
    "testing": ["quality", "craftsmanship", "solo-developer"],
    "quality": ["testing", "craftsmanship", "solo-developer"],
    "craftsmanship": ["quality", "testing", "ford"],
    "cloud": ["solo-developer", "modernization"],
    "ai": ["leadership"],
    "solo-developer": ["testing", "quality", "modernization"],
    "leadership": ["ai"],
    "modernization": ["cloud", "solo-developer"],
    "ford": ["craftsmanship", "quality"],
    "grandfather": ["ford", "craftsmanship", "quality"],
}

# Company framing is loaded per-user from personal_context.json at runtime.
# This dict is intentionally empty — do not add hardcoded data here.
_COMPANY_FRAMING: dict[str, dict[str, str]] = {}


def get_star_story_context(
    tag: str,
    company: str = "",
    role_type: str = "",
) -> str:
    """Retrieve STAR stories matching a tag (e.g. 'ai_adoption', 'cloud_migration', 'testing', 'leadership'). Optionally filter by company or role_type for targeted framing. Returns primary stories, related stories from connected tags, derived metric bullets, and company-specific framing hints."""
    tag_lower = tag.lower().strip()

    story_data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    all_stories = story_data.get("stories", [])
    # Read per-user metrics and framing from the data file — never from the
    # hardcoded module constants which contain the owner's personal data.
    star_metrics: dict = story_data.get("star_metrics", {})
    company_framing: dict = story_data.get("company_framing", {})

    related = _STAR_RELATED.get(tag_lower, [])
    search_tags = {tag_lower} | set(related)

    seen_ids: set = set()
    primary_stories, related_stories = [], []
    for s in all_stories:
        story_tags = set(s.get("tags", []))
        if s["id"] in seen_ids:
            continue
        if tag_lower in story_tags:
            primary_stories.append(s)
            seen_ids.add(s["id"])
        elif story_tags & search_tags:
            related_stories.append(s)
            seen_ids.add(s["id"])

    metrics: list[str] = []
    for t in [tag_lower] + related:
        for m in star_metrics.get(t, []):
            if m not in metrics:
                metrics.append(m)

    company_lower = company.lower().strip()
    framing = None
    for key in company_framing:
        if key in company_lower:
            framing = company_framing[key]
            break

    header = f"tag='{tag}'"
    if company:
        header += f" | company='{company}'"
    if role_type:
        header += f" | role='{role_type}'"
    lines = [f"═══ STAR STORY CONTEXT: {header} ═══", ""]

    if primary_stories:
        lines.append(f"── PRIMARY STORIES ({len(primary_stories)} direct match) ──")
        for s in primary_stories:
            lines += [
                f"\n▪ #{s['id']} — {s['title']}",
                f"  Tags: {', '.join(s.get('tags', []))}",
                f"  {s['story']}",
                "",
            ]

    if related_stories:
        lines.append(f"── RELATED STORIES ({len(related_stories)} via related tags) ──")
        for s in related_stories:
            lines += [
                f"\n▪ #{s['id']} — {s['title']}",
                f"  Tags: {', '.join(s.get('tags', []))}",
                f"  {s['story']}",
                "",
            ]

    if not primary_stories and not related_stories:
        lines.append("No personal stories found for this tag or related tags.")
        lines.append("Log stories with log_personal_story() to enrich future STAR answers.")
        lines.append("")

    if metrics:
        lines.append("── RESUME METRICS TO WEAVE IN ──")
        for m in metrics:
            lines.append(f"  • {m}")
        lines.append("")

    if framing:
        lines.append(f"── {company.upper()} FRAMING HINTS ──")
        for k, v in framing.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    lines += [
        "── STAR STRUCTURE ──",
        "  Situation: Set the scene — team size, stack, constraints, stakes",
        "  Task:      What you owned and why it mattered",
        "  Action:    Specific decisions — what you built, how you tested, trade-offs made",
        "  Result:    Metrics first, then narrative payoff",
        "",
        "Use the personal stories for humanity. Use the metrics for credibility.",
        "The story is what makes it memorable. The numbers are what makes it land.",
    ]

    return "\n".join(lines)


def get_all_star_context() -> str:
    """Dump the full STAR context: all personal stories, all metric bullets by category, and all company framing hints. Used at session boot to load the complete interview prep picture."""
    story_data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    all_stories = story_data.get("stories", [])
    # Read per-user metrics and framing from the data file — never from the
    # hardcoded module constants which contain the owner's personal data.
    star_metrics: dict = story_data.get("star_metrics", {})
    company_framing: dict = story_data.get("company_framing", {})

    lines = ["═══ STAR CONTEXT (full boot dump) ═══", ""]

    # All personal stories
    if all_stories:
        lines.append(f"── PERSONAL STORIES ({len(all_stories)} total) ──")
        for s in all_stories:
            lines += [
                f"\n▪ #{s['id']} — {s['title']}",
                f"  Tags:   {', '.join(s.get('tags', []))}",
                f"  People: {', '.join(s.get('people', []))}",
                f"  {s['story']}",
                "",
            ]
    else:
        lines.append("No personal stories logged yet.")
        lines.append("")

    # All STAR metrics by category
    if star_metrics:
        lines.append("── RESUME METRICS BY CATEGORY ──")
        for category, bullets in star_metrics.items():
            lines.append(f"\n  [{category}]")
            for b in bullets:
                lines.append(f"    • {b}")
        lines.append("")
    else:
        lines.append("── RESUME METRICS BY CATEGORY ──")
        lines.append("  No metrics logged yet. Add star_metrics to your personal_context.json.")
        lines.append("")

    # All company framing hints
    if company_framing:
        lines.append("── COMPANY FRAMING HINTS ──")
        for company, framing in company_framing.items():
            lines.append(f"\n  [{company.upper()}]")
            for k, v in framing.items():
                lines.append(f"    {k}: {v}")
        lines.append("")
    else:
        lines.append("── COMPANY FRAMING HINTS ──")
        lines.append("  No company framing logged yet.")
        lines.append("")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_star_story_context)
    mcp.tool()(get_all_star_context)
