"""
LinkedIn post tracking tool

Stores Frank's public LinkedIn posts with engagement metrics and audience data.
Posts also serve as tone samples — the voice used publicly is the same voice to
calibrate for outreach and cover letters.

Tools:
  log_linkedin_post      — add or update a post record
  update_post_metrics    — update engagement numbers on an existing post
  get_linkedin_posts     — retrieve/filter posts with metrics summary
"""

from lib import config
from lib.io import _load_json, _save_json, _now
from tools.tone import log_tone_sample as _log_tone_sample


def _next_id(posts: list[dict]) -> int:
    if not posts:
        return 1
    return max(p.get("id", 0) for p in posts) + 1


def _find_post(posts: list[dict], post_id: int | None = None, source: str = "") -> dict | None:
    if post_id is not None:
        return next((p for p in posts if p.get("id") == post_id), None)
    if source:
        sl = source.strip().lower()
        return next((p for p in posts if p.get("source", "").lower() == sl), None)
    return None


def log_linkedin_post(
    text: str,
    source: str,
    context: str = "",
    posted_date: str = "",
    url: str = "",
    hashtags: list[str] | None = None,
    links: list[str] | None = None,
    title: str = "",
    auto_log_tone: bool = True,
) -> str:
    """
    Add or update a LinkedIn post in the post database.

    Stores the full post text, metadata, and a blank metrics block ready for
    update_post_metrics(). Optionally ingests the post as a tone sample
    (default: True) so Frank's public voice calibrates future outreach drafts.

    Args:
        text:           Full post text.
        source:         Unique slug label (e.g. 'linkedin_post_mcp_v4').
        context:        What the post is about / why it matters.
        posted_date:    ISO date string (YYYY-MM-DD). Defaults to today.
        url:            LinkedIn post URL or short link.
        hashtags:       List of hashtags used (without #).
        links:          List of external URLs included in the post.
        title:          Short human-readable title for the post.
        auto_log_tone:  If True, also ingest post text as a tone sample.

    Returns:
        Confirmation string with post ID.
    """
    hashtags = hashtags or []
    links = links or []
    data = _load_json(config.LINKEDIN_POSTS_FILE, {"posts": []})
    posts = data.setdefault("posts", [])

    existing = _find_post(posts, source=source)
    if existing:
        existing["text"] = text or existing.get("text", "")
        existing["context"] = context or existing.get("context", "")
        if posted_date:
            existing["posted_date"] = posted_date
        if url:
            existing["url"] = url
        if hashtags:
            existing["hashtags"] = list(dict.fromkeys(existing.get("hashtags", []) + hashtags))
        if links:
            existing["links"] = list(dict.fromkeys(existing.get("links", []) + links))
        if title:
            existing["title"] = title
        existing["last_updated"] = _now()
        _save_json(config.LINKEDIN_POSTS_FILE, data)

        tone_note = ""
        if auto_log_tone and text.strip():
            _log_tone_sample(text=text.strip(), source=source, context=context)
            tone_note = " Tone sample updated."
        return f"✓ Updated existing post #{existing['id']}: {existing.get('title', source)}{tone_note}"

    entry = {
        "id": _next_id(posts),
        "timestamp": _now(),
        "posted_date": posted_date or _now()[:10],
        "source": source.strip(),
        "title": title.strip(),
        "text": text.strip(),
        "url": url.strip(),
        "hashtags": hashtags,
        "links": links,
        "context": context.strip(),
        "metrics": {
            "impressions": None,
            "members_reached": None,
            "reactions": None,
            "comments": None,
            "reposts": None,
            "saves": None,
            "link_clicks": None,
            "profile_views_from_post": None,
            "followers_gained": None,
            "last_checked": None,
        },
        "audience_highlights": {},
    }
    posts.append(entry)
    _save_json(config.LINKEDIN_POSTS_FILE, data)

    tone_note = ""
    if auto_log_tone and text.strip():
        _log_tone_sample(text=text.strip(), source=source, context=context)
        tone_note = " Tone sample auto-logged."

    return f"✓ LinkedIn post logged #{entry['id']}: {title or source}{tone_note}"


def update_post_metrics(
    post_id: int | None = None,
    source: str = "",
    impressions: int | None = None,
    members_reached: int | None = None,
    reactions: int | None = None,
    comments: int | None = None,
    reposts: int | None = None,
    saves: int | None = None,
    link_clicks: int | None = None,
    profile_views_from_post: int | None = None,
    followers_gained: int | None = None,
    audience_highlights: dict | None = None,
) -> str:
    """
    Update engagement metrics on an existing LinkedIn post.

    Identify the post by post_id (integer) or source slug. Only provided
    fields are updated — pass None to leave a metric unchanged.

    Args:
        post_id:                  Numeric ID of the post.
        source:                   Source slug (alternative to post_id).
        impressions:              Total impressions.
        members_reached:          Unique members reached.
        reactions:                Total reactions (likes, celebrates, etc.).
        comments:                 Comment count.
        reposts:                  Repost count.
        saves:                    Save count.
        link_clicks:              Clicks on links in the post.
        profile_views_from_post:  Profile views attributed to this post.
        followers_gained:         New followers from this post.
        audience_highlights:      Dict with top_job_title, top_location,
                                  top_industry, top_company, top_seniority.

    Returns:
        Confirmation string with updated metrics summary.
    """
    if post_id is None and not source:
        return "✗ Provide either post_id or source to identify the post."

    data = _load_json(config.LINKEDIN_POSTS_FILE, {"posts": []})
    posts = data.get("posts", [])
    post = _find_post(posts, post_id=post_id, source=source)

    if not post:
        ident = f"id={post_id}" if post_id is not None else f"source='{source}'"
        return f"✗ No post found with {ident}."

    m = post.setdefault("metrics", {})
    updates = {
        "impressions": impressions,
        "members_reached": members_reached,
        "reactions": reactions,
        "comments": comments,
        "reposts": reposts,
        "saves": saves,
        "link_clicks": link_clicks,
        "profile_views_from_post": profile_views_from_post,
        "followers_gained": followers_gained,
    }
    for key, val in updates.items():
        if val is not None:
            m[key] = val
    m["last_checked"] = _now()[:10]

    if audience_highlights:
        post["audience_highlights"] = {**post.get("audience_highlights", {}), **audience_highlights}

    _save_json(config.LINKEDIN_POSTS_FILE, data)

    summary_parts = [f"{k}={v}" for k, v in m.items() if v is not None and k != "last_checked"]
    return f"✓ Metrics updated for post #{post['id']} ({post.get('title', post.get('source', ''))}): {', '.join(summary_parts)}"


def get_linkedin_posts(
    source: str = "",
    hashtag: str = "",
    min_reactions: int = 0,
    include_text: bool = False,
) -> str:
    """
    Retrieve LinkedIn posts with metrics summary.

    Args:
        source:         Filter by source slug (partial match).
        hashtag:        Filter by hashtag (e.g. 'IoT', 'Python').
        min_reactions:  Only return posts with at least this many reactions.
        include_text:   If True, include full post text in output.

    Returns:
        Formatted summary of matching posts with metrics.
    """
    data = _load_json(config.LINKEDIN_POSTS_FILE, {"posts": []})
    posts = data.get("posts", [])

    if not posts:
        return "No LinkedIn posts logged yet. Use log_linkedin_post() to add posts."

    filtered = posts
    if source:
        sl = source.lower()
        filtered = [p for p in filtered if sl in p.get("source", "").lower()]
    if hashtag:
        hl = hashtag.lower().lstrip("#")
        filtered = [p for p in filtered if hl in [h.lower() for h in p.get("hashtags", [])]]
    if min_reactions:
        filtered = [p for p in filtered if ((p.get("metrics") or {}).get("reactions") or 0) >= min_reactions]

    if not filtered:
        return "No posts match the given filters."

    total_reactions = sum((p.get("metrics") or {}).get("reactions") or 0 for p in filtered)
    total_impressions = sum((p.get("metrics") or {}).get("impressions") or 0 for p in filtered)
    total_reposts = sum((p.get("metrics") or {}).get("reposts") or 0 for p in filtered)
    total_comments = sum((p.get("metrics") or {}).get("comments") or 0 for p in filtered)

    lines = [
        f"═══ LINKEDIN POSTS ({len(filtered)} posts) ═══",
        f"Aggregate: {total_reactions} reactions | {total_reposts} reposts | "
        f"{total_comments} comments | {total_impressions} impressions",
        "",
    ]

    for p in sorted(filtered, key=lambda x: x.get("posted_date", ""), reverse=True):
        m = p.get("metrics") or {}
        ah = p.get("audience_highlights") or {}
        label = p.get("title") or p.get("source", "")
        lines.append(f"── #{p['id']} | {p.get('posted_date', 'unknown date')} | {label} ──")
        if p.get("url"):
            lines.append(f"URL: {p['url']}")
        if p.get("context"):
            lines.append(f"Context: {p['context']}")

        metric_str = " | ".join(
            f"{k.replace('_', ' ')}={v}"
            for k, v in m.items()
            if v is not None and k != "last_checked"
        )
        if metric_str:
            lines.append(f"Metrics: {metric_str}")
        if m.get("last_checked"):
            lines.append(f"Last checked: {m['last_checked']}")
        if ah:
            lines.append(f"Audience: {', '.join(f'{k}={v}' for k, v in ah.items())}")
        if p.get("hashtags"):
            lines.append(f"Tags: #{' #'.join(p['hashtags'])}")
        if include_text and p.get("text"):
            lines.append(f"\n{p['text']}")
        lines.append("")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(log_linkedin_post)
    mcp.tool()(update_post_metrics)
    mcp.tool()(get_linkedin_posts)
