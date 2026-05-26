"""
GitHub stats tool — F1 feature track.

`get_github_stats(username)` pulls a lightweight public profile summary from
the GitHub REST API (`/users/{user}` + `/users/{user}/repos`) and returns a
formatted text block suitable for inclusion in cover letters, resumes, or
recruiter outreach.

Network and credentials:
    * Reads token from env `GITHUB_TOKEN` if set (raises rate limit to 5000/h);
      otherwise calls the unauthenticated public endpoint (60/h).
    * If env `JOBCONTEXTMCP_OFFLINE=1`, returns a deterministic offline stub
      without making any network call. Tests use this.
    * Network errors degrade gracefully to a "⚠ unable to fetch" message
      rather than raising.

The implementation uses urllib from the stdlib so no new dependency is added.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


_GITHUB_API = "https://api.github.com"


def _is_offline() -> bool:
    return os.environ.get("JOBCONTEXTMCP_OFFLINE", "").lower() in ("1", "true", "yes")


def _http_get_json(url: str, timeout: float = 5.0) -> Any:
    """Fetch JSON from a URL. Raises urllib.error.URLError on network problems."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "jobContextMCP-github-stats/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _offline_stub(username: str) -> dict[str, Any]:
    return {
        "profile": {
            "login": username,
            "name": "Offline Stub",
            "bio": "Offline mode active — set JOBCONTEXTMCP_OFFLINE=0 to fetch live.",
            "public_repos": 0,
            "followers": 0,
            "following": 0,
            "html_url": f"https://github.com/{username}",
        },
        "top_repos": [],
    }


def _fetch(username: str) -> dict[str, Any]:
    if _is_offline():
        return _offline_stub(username)
    try:
        profile = _http_get_json(f"{_GITHUB_API}/users/{username}")
        repos = _http_get_json(
            f"{_GITHUB_API}/users/{username}/repos?per_page=100&sort=updated"
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {
            "profile": None,
            "top_repos": [],
            "error": f"unable to fetch GitHub data for {username}: {exc}",
        }

    # Trim profile + repo fields to what we display.
    prof = {
        "login": profile.get("login"),
        "name": profile.get("name"),
        "bio": profile.get("bio"),
        "public_repos": profile.get("public_repos", 0),
        "followers": profile.get("followers", 0),
        "following": profile.get("following", 0),
        "html_url": profile.get("html_url"),
    }
    top = sorted(
        [r for r in repos if not r.get("fork")],
        key=lambda r: r.get("stargazers_count", 0),
        reverse=True,
    )[:5]
    top_repos = [
        {
            "name": r.get("name"),
            "description": r.get("description") or "",
            "language": r.get("language") or "",
            "stars": r.get("stargazers_count", 0),
            "url": r.get("html_url"),
        }
        for r in top
    ]
    return {"profile": prof, "top_repos": top_repos}


def get_github_stats(username: str) -> str:
    """Return a formatted GitHub public profile summary.

    Args:
        username: GitHub login (e.g. "JustLikeFrank3").

    Returns:
        Multi-line text block. Includes a "⚠" prefix line on fetch failure.
    """
    if not username or not username.strip():
        return "⚠ get_github_stats: username is required"
    username = username.strip()

    data = _fetch(username)
    if data.get("error"):
        return f"⚠ {data['error']}"

    prof = data["profile"] or {}
    lines = [
        f"# GitHub profile: @{prof.get('login', username)}",
        prof.get("name") or "(no display name)",
        prof.get("bio") or "(no bio)",
        "",
        f"Public repos: {prof.get('public_repos', 0)}    "
        f"Followers: {prof.get('followers', 0)}    "
        f"Following: {prof.get('following', 0)}",
        f"URL: {prof.get('html_url', f'https://github.com/{username}')}",
    ]
    repos = data.get("top_repos", [])
    if repos:
        lines.append("")
        lines.append("## Top non-fork repos (by stars, recently updated)")
        for r in repos:
            lang = f" [{r['language']}]" if r.get("language") else ""
            stars = f" ★{r['stars']}" if r.get("stars") else ""
            desc = f" — {r['description']}" if r.get("description") else ""
            lines.append(f"- {r['name']}{lang}{stars}{desc}")
            lines.append(f"  {r['url']}")
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_github_stats)
